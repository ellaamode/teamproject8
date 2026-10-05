"""DB 쓰기 계층. 배치의 모든 쓰기는 여기를 거친다(자연키 UPSERT → 재실행해도 결과 동일)."""
from __future__ import annotations

import contextlib
import json
from datetime import date

import psycopg
from psycopg.rows import dict_row

from .normalize import article_label, content_hash, sort_key, substance


def connect(dsn: str) -> psycopg.Connection:
    # prepare_threshold=None: Supabase 커넥션 풀러(트랜잭션 모드)와 호환
    return psycopg.connect(dsn, row_factory=dict_row, prepare_threshold=None, autocommit=False)


# ---------------------------------------------------------------- 실행 기록
@contextlib.contextmanager
def run(conn, stage: str, source: str):
    """with run(conn, 'fetch', 'fsc.reply') as stats: stats['new'] += 1"""
    rid = conn.execute("INSERT INTO pipeline_runs (stage, source) VALUES (%s, %s) RETURNING id",
                       (stage, source)).fetchone()["id"]
    conn.commit()
    stats: dict = {"errors": 0}
    try:
        yield stats
        conn.commit()
        status = "partial" if stats["errors"] else "ok"
        conn.execute("UPDATE pipeline_runs SET finished_at=now(), status=%s, stats=%s WHERE id=%s",
                     (status, json.dumps(stats, ensure_ascii=False), rid))
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.execute("UPDATE pipeline_runs SET finished_at=now(), status='failed', stats=%s, error=%s WHERE id=%s",
                     (json.dumps(stats, ensure_ascii=False), str(e)[:2000], rid))
        conn.commit()
        raise


# ---------------------------------------------------------------- 1. 원본
def save_raw(conn, source: str, key: str, status: int, payload: str) -> bool:
    """같은 내용이 이미 있으면 False (= 변경 없음). 증분 수집의 핵심."""
    h = content_hash(payload)
    cur = conn.execute(
        # clock_timestamp: 한 트랜잭션 안에서 저장한 원본(현행 본·시행예정 본)도 받은 순서대로 시각이 달라야 parse 순서가 지켜진다
        "INSERT INTO raw_payloads (source, source_key, content_hash, fetched_at, http_status, payload) "
        "VALUES (%s,%s,%s,clock_timestamp(),%s,%s) ON CONFLICT DO NOTHING", (source, key, h, status, payload))
    return cur.rowcount == 1


def unparsed(conn, source: str):
    return conn.execute(
        "SELECT source_key, content_hash, payload FROM raw_payloads "
        "WHERE source=%s AND parsed_at IS NULL "
        # 같은 시각이면 현행 본을 시행예정 본보다 먼저 (시행예정 본은 '그 전 버전'과 비교해 바뀐 조문만 저장하므로)
        # 시행예정 본이 여러 개면 시행일 순서로 (키 끝 ':YYYYMMDD')
        "ORDER BY fetched_at, (payload LIKE '%%\"version\": \"시행예정\"%%'), split_part(source_key, ':', 3), source_key",
        (source,)).fetchall()


def mark_parsed(conn, source: str, key: str, h: str):
    conn.execute("UPDATE raw_payloads SET parsed_at=now() WHERE source=%s AND source_key=%s AND content_hash=%s",
                 (source, key, h))


# ---------------------------------------------------------------- 2. 법령 구조
def upsert_law(conn, spec, *, source_id=None, current_seq=None, promulgated_on=None, effective_on=None):
    conn.execute("""
        INSERT INTO laws (slug, name, kind, parent_slug, source, source_id, sectors, aliases,
                          current_seq, promulgated_on, effective_on, synced_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
        ON CONFLICT (slug) DO UPDATE SET
          name=EXCLUDED.name, kind=EXCLUDED.kind, parent_slug=EXCLUDED.parent_slug,
          sectors=EXCLUDED.sectors, aliases=EXCLUDED.aliases,
          source_id=COALESCE(EXCLUDED.source_id, laws.source_id),
          current_seq=COALESCE(EXCLUDED.current_seq, laws.current_seq),
          promulgated_on=COALESCE(EXCLUDED.promulgated_on, laws.promulgated_on),
          effective_on=COALESCE(EXCLUDED.effective_on, laws.effective_on), synced_at=now()""",
        (spec.slug, spec.name, spec.kind, spec.parent, spec.source, source_id, list(spec.sectors),
         list(spec.aliases), current_seq, promulgated_on, effective_on))


def upsert_article_version(conn, law_slug: str, no: str, *, title: str | None, chapter: str | None,
                           body: str, effective_from: date, source_seq: str | None) -> str:
    """조문 정체성 + 본문 버전 저장. 반환: 'new' | 'changed' | 'same'"""
    key = f"{law_slug}:{no}"
    is_deleted = body.strip().endswith("삭제") or "삭제 <" in body[:40]
    conn.execute("""
        INSERT INTO articles (key, law_slug, no, label, title, chapter, sort_key, is_deleted)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (key) DO UPDATE SET title=EXCLUDED.title, chapter=EXCLUDED.chapter,
                                        sort_key=EXCLUDED.sort_key, is_deleted=EXCLUDED.is_deleted""",
        (key, law_slug, no, article_label(no), title, chapter, _flat_sort(no), is_deleted))
    h = content_hash(body)
    prev = conn.execute("SELECT body_hash, body FROM article_versions WHERE article_key=%s AND effective_from=%s",
                        (key, effective_from)).fetchone()
    if prev and prev["body_hash"] == h:
        return "same"
    if prev and substance(prev["body"]) == substance(body):
        # 줄바꿈·띄어쓰기·<개정 …> 표기만 다르면 개정이 아니다 (예: 웹 수집 → Open API 전환). 표기만 새것으로 교체
        conn.execute("UPDATE article_versions SET body=%s, body_hash=%s, title=%s, source_seq=%s "
                     "WHERE article_key=%s AND effective_from=%s", (body, h, title, source_seq, key, effective_from))
        return "same"
    conn.execute("""
        INSERT INTO article_versions (article_key, effective_from, title, body, body_hash, source_seq)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (article_key, effective_from) DO UPDATE
          SET title=EXCLUDED.title, body=EXCLUDED.body, body_hash=EXCLUDED.body_hash, source_seq=EXCLUDED.source_seq""",
        (key, effective_from, title, body, h, source_seq))
    # 버전 구간 다시 계산: 각 버전의 effective_to = 다음 버전 시행 전날
    conn.execute("""
        UPDATE article_versions v SET effective_to = n.next_from - 1
        FROM (SELECT effective_from, lead(effective_from) OVER (ORDER BY effective_from) AS next_from
              FROM article_versions WHERE article_key=%s) n
        WHERE v.article_key=%s AND v.effective_from=n.effective_from""", (key, key))
    return "changed" if prev else "new"


def _flat_sort(no: str) -> int:
    a, b, c = sort_key(no)
    return a * 1_000_000 + b * 1_000 + c


def upsert_delegation(conn, from_key: str, to_key: str, kind: str = "위임", origin: str = "text"):
    conn.execute("INSERT INTO delegations (from_key, to_key, kind, origin) VALUES (%s,%s,%s,%s) "
                 "ON CONFLICT (from_key, to_key) DO UPDATE SET origin = CASE WHEN delegations.origin='thdcmp' "
                 "THEN 'thdcmp' ELSE EXCLUDED.origin END", (from_key, to_key, kind, origin))


# ---------------------------------------------------------------- 3. 문서
DOC_COLS = ("id", "kind", "org", "dept", "title", "question", "answer", "reason", "body", "published_on",
            "valid_from", "valid_to", "stage", "source_url", "source_name")


def upsert_document(conn, doc: dict) -> str:
    """반환: 'new' | 'changed' | 'same'. 내용 해시가 같으면 아무것도 쓰지 않는다."""
    h = content_hash(*(str(doc.get(c) or "") for c in DOC_COLS))
    prev = conn.execute("SELECT content_hash FROM documents WHERE id=%s", (doc["id"],)).fetchone()
    if prev and prev["content_hash"] == h:
        return "same"
    cols = ", ".join(DOC_COLS) + ", content_hash"
    ph = ", ".join(["%s"] * (len(DOC_COLS) + 1))
    upd = ", ".join(f"{c}=EXCLUDED.{c}" for c in DOC_COLS[1:]) + ", content_hash=EXCLUDED.content_hash, changed_at=now()"
    conn.execute(f"INSERT INTO documents ({cols}) VALUES ({ph}) ON CONFLICT (id) DO UPDATE SET {upd}",
                 [doc.get(c) for c in DOC_COLS] + [h])
    return "changed" if prev else "new"


# ---------------------------------------------------------------- 4. 연결
def replace_links(conn, doc_id: str, result, primary_law: str | None):
    """문서 하나의 링크를 통째로 교체(규칙이 바뀌어도 재실행만 하면 최신 결과로 맞춰진다).
    사람이 검수한(reviewed) 링크는 보존한다."""
    conn.execute("DELETE FROM article_links WHERE doc_id=%s AND NOT reviewed", (doc_id,))
    conn.execute("DELETE FROM unresolved_mentions WHERE doc_id=%s", (doc_id,))
    for l in result.links:
        conn.execute("""
            INSERT INTO article_links (doc_id, article_key, paragraph, item, method, confidence, evidence)
            SELECT %s,%s,%s,%s,%s,%s,%s WHERE EXISTS (SELECT 1 FROM articles WHERE key=%s)
            ON CONFLICT DO NOTHING""",
            (doc_id, l.key, l.paragraph, l.item, l.method, l.confidence, l.evidence[:300], l.key))
    # 대상 법령이지만 아직 본문을 못 받은 조문 → 버리지 않고 기록 (본문 적재 후 link --all 로 연결됨)
    loaded = {r["key"] for r in conn.execute("SELECT key FROM articles WHERE key = ANY(%s)",
                                             ([l.key for l in result.links],)).fetchall()}
    for l in result.links:
        if l.key not in loaded:
            conn.execute("INSERT INTO unresolved_mentions VALUES (%s,%s,'article_not_loaded') ON CONFLICT DO NOTHING",
                         (doc_id, l.evidence[:300]))
    for raw, reason in result.unresolved:
        conn.execute("INSERT INTO unresolved_mentions VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                     (doc_id, raw[:300], reason))
    conn.execute("UPDATE documents SET primary_law=%s WHERE id=%s", (primary_law, doc_id))


# ---------------------------------------------------------------- 5. 이벤트
def add_event(conn, dedupe_key: str, occurred_on, kind: str, title: str, *,
              law_slug=None, article_key=None, doc_id=None) -> bool:
    cur = conn.execute("""
        INSERT INTO change_events (dedupe_key, occurred_on, kind, law_slug, article_key, doc_id, title)
        VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (dedupe_key) DO NOTHING""",
        (dedupe_key, occurred_on, kind, law_slug, article_key, doc_id, title))
    return cur.rowcount == 1


def refresh_stats(conn):
    # 세이브포인트 안에서 시도: 실패해도 같은 트랜잭션의 앞선 쓰기(이벤트 등)를 되돌리지 않는다
    try:
        with conn.transaction():
            conn.execute("SELECT refresh_article_stats()")          # 운영: 002_roles.sql 의 위임 함수
    except psycopg.errors.UndefinedFunction:
        with conn.transaction():
            conn.execute("REFRESH MATERIALIZED VIEW article_stats")  # 로컬: 소유자 계정
