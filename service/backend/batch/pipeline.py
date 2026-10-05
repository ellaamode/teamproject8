"""배치 4단계. 각 단계는 독립 실행·재실행 가능하다.

  fetch  : 원천 → raw_payloads        (바뀐 것만, 원본 그대로)
  parse  : raw → laws/articles/documents (정규화, 버전 관리)
  link   : documents → article_links     (인용 연결 엔진)
  derive : → change_events, article_stats (변화 피드·집계)

규칙(인용 정규식, 별칭)을 고치면 fetch 없이 `link --all` → `derive` 만 다시 돌리면 된다.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from . import store
from .config import DEPT_HINTS, LAW_BY_SLUG, SETTINGS, TARGET_LAWS
from .lawtext import lines_from_payload, split_articles
from .normalize import substance
from .linker import Resolver
from .sources import fscportal, lawgo

DOC_SOURCES = ("fsc.lawreq", "fsc.opinion", "fsc.pastreq", "fsc.guidance")
LAW_SOURCES = ("lawgo.law", "lawgo.admrul")


# ---------------------------------------------------------------- fetch
def fetch(conn, sources=("fsc", "lawgo")):
    if "fsc" in sources:
        with store.run(conn, "fetch", "fsc.reply") as s:
            s.update(fscportal.fetch_replies(conn))
        with store.run(conn, "fetch", "fsc.guidance") as s:
            s.update(fscportal.fetch_guidance(conn))
    if "lawgo" in sources:
        # 정식 경로는 법제처 Open API(OC 키). 키가 없으면 국가법령정보센터 웹페이지 수집(크롤링)으로 대체
        api_ok = False
        if SETTINGS.law_oc:
            with store.run(conn, "fetch", "lawgo") as s:
                s.update(lawgo.fetch_laws(conn))
                api_ok = s.get("errors", 0) < s.get("checked", 0)       # 전부 실패(키 오류·장애)면 웹 수집으로 대체
        if not api_ok:
            from .sources import lawweb
            with store.run(conn, "fetch", "lawweb") as s:
                s.update(lawweb.fetch_laws_web(conn))


# ---------------------------------------------------------------- parse
def parse(conn):
    # 대상 법령은 본문을 받기 전에도 등록해 둔다 → 인용 엔진이 '여전법'을 대상 밖 법령으로 오판하지 않게
    for spec in TARGET_LAWS:
        store.upsert_law(conn, spec)
    removed = prune_laws(conn)
    conn.commit()
    with store.run(conn, "parse", "laws") as s:
        s.update({"articles_new": 0, "articles_changed": 0, "pending": 0, "pruned": removed})
        for src in LAW_SOURCES:
            for row in store.unparsed(conn, src):
                if _parse_law(conn, src, row, s) is not False:
                    store.mark_parsed(conn, src, row["source_key"], row["content_hash"])
    with store.run(conn, "parse", "delegations") as s:
        s["thdcmp"] = thdcmp_delegations(conn)
        s["delegations"] = text_delegations(conn)
    with store.run(conn, "parse", "documents") as s:
        s.update({"new": 0, "changed": 0, "same": 0})
        for src in DOC_SOURCES:
            for row in store.unparsed(conn, src):
                try:
                    doc = fscportal.PARSERS[src](src, row["source_key"], row["payload"])
                    s[store.upsert_document(conn, doc)] += 1
                    store.mark_parsed(conn, src, row["source_key"], row["content_hash"])
                except Exception:
                    s["errors"] += 1


def prune_laws(conn) -> list[str]:
    """대상 범위에서 빠진 법령을 DB 에서 정리한다(조문·연결·이벤트). 원본(raw_payloads)은 남겨 두므로
    나중에 다시 대상에 넣으면 재수집 없이 parse 만으로 복원된다."""
    gone = [r["slug"] for r in conn.execute("SELECT slug FROM laws WHERE NOT (slug = ANY(%s))",
                                             ([s.slug for s in TARGET_LAWS],)).fetchall()]
    if gone:
        conn.execute("UPDATE documents SET primary_law = NULL WHERE primary_law = ANY(%s)", (gone,))
        conn.execute("""DELETE FROM change_events WHERE law_slug = ANY(%s)
                        OR article_key IN (SELECT key FROM articles WHERE law_slug = ANY(%s))""", (gone, gone))
        conn.execute("DELETE FROM laws WHERE slug = ANY(%s)", (gone,))     # articles·versions·links·delegations 는 CASCADE
        conn.execute("UPDATE raw_payloads SET parsed_at = NULL WHERE source IN ('lawgo.law','lawgo.admrul') "
                     "AND split_part(source_key, ':', 1) = ANY(%s)", (gone,))
    return gone


def _parse_law(conn, src, row, s):
    p = json.loads(row["payload"])
    meta = p["meta"]
    spec = LAW_BY_SLUG.get(meta["slug"])
    if spec is None:                       # 대상 밖 법령의 원본 → 건너뜀 (원본은 보존, 미처리 상태 유지)
        s["skipped_out_of_scope"] = s.get("skipped_out_of_scope", 0) + 1
        return False
    if meta.get("via") == "web" and conn.execute(
            """SELECT 1 FROM raw_payloads WHERE source=%s AND source_key LIKE %s
               AND payload LIKE '%%"via": "api"%%' LIMIT 1""", (src, f"{spec.slug}:%")).fetchone():
        s["web_superseded"] = s.get("web_superseded", 0) + 1     # 같은 법령의 Open API 본이 있으면 웹 수집본은 쓰지 않는다
        return None
    base_eff = _ymd(meta.get("effective")) or date.today()
    future_copy = meta.get("version") == "시행예정"          # Open API: 시행예정 법령 본문 전체(바뀐 조문은 일부뿐)
    # 웹 수집 → Open API 로 처음 바꾸는 날: 달라진 조문은 대부분 '수집 방식' 차이(웹 수집 오류 교정 포함)라 개정 알림을 내지 않는다
    switching = meta.get("via") == "api" and not conn.execute(
        """SELECT 1 FROM raw_payloads WHERE source=%s AND source_key LIKE %s AND parsed_at IS NOT NULL
           AND payload LIKE '%%"via": "api"%%' LIMIT 1""", (src, f"{spec.slug}:%")).fetchone()
    store.upsert_law(conn, spec, current_seq=meta["seq"] if meta.get("version") == "현행" else None,
                     promulgated_on=_ymd(meta.get("promulgated")),
                     effective_on=base_eff if meta.get("version") == "현행" else None)
    for a in split_articles(lines_from_payload(json.dumps(p["body"], ensure_ascii=False))):
        eff = a.pending_from or base_eff
        if future_copy:
            # 그날 시행되는 본문 중 '그 전 버전과 내용이 다른 조문'만 시행예정 버전으로 저장
            prior = conn.execute("""SELECT body FROM article_versions WHERE article_key=%s AND effective_from < %s
                                    ORDER BY effective_from DESC LIMIT 1""", (f"{spec.slug}:{a.no}", eff)).fetchone()
            if prior and substance(prior["body"]) == substance(a.body):
                continue
            a.pending_from = eff
        had = conn.execute("SELECT count(*) AS n FROM article_versions WHERE article_key=%s",
                           (f"{spec.slug}:{a.no}",)).fetchone()["n"]
        res = store.upsert_article_version(conn, spec.slug, a.no, title=a.title, chapter=a.chapter,
                                           body=a.body, effective_from=eff, source_seq=meta["seq"])
        if res == "same":
            continue
        s["articles_new" if res == "new" else "articles_changed"] += 1
        key = f"{spec.slug}:{a.no}"
        if a.pending_from:
            s["pending"] += 1
            store.add_event(conn, f"art_pending:{key}:{eff}", eff, "조문_시행예정",
                            f"{spec.name} {a.label}({a.title}) {eff:%Y.%m.%d} 시행 예정",
                            law_slug=spec.slug, article_key=key)
        elif had and switching:
            s["source_switch_fixed"] = s.get("source_switch_fixed", 0) + 1
        elif had:                                   # 첫 적재가 아니라 '바뀐' 경우만 개정 이벤트
            store.add_event(conn, f"art_changed:{key}:{eff}", eff, "조문_개정",
                            f"{spec.name} {a.label}({a.title}) 개정", law_slug=spec.slug, article_key=key)


def thdcmp_delegations(conn) -> int:
    """법제처 3단비교(공식 위임조문)로 법률 → 시행령·시행규칙 위임 관계를 다시 만든다. 법률마다 가장 최근 응답을 쓴다."""
    n = 0
    for spec in (x for x in TARGET_LAWS if x.kind == "법률"):
        row = conn.execute("""SELECT payload FROM raw_payloads WHERE source='lawgo.thdcmp' AND source_key LIKE %s
                              ORDER BY fetched_at DESC LIMIT 1""", (f"{spec.slug}:%",)).fetchone()
        if not row:
            continue
        try:
            pairs = lawgo.delegation_pairs(spec.slug, row["payload"])
        except ValueError:                              # JSON 이 아닌 오류 응답
            continue
        conn.execute("DELETE FROM delegations WHERE origin='thdcmp' AND from_key LIKE %s", (f"{spec.slug}:%",))
        have = {r["key"] for r in conn.execute("SELECT key FROM articles WHERE key = ANY(%s)",
                                               ([k for p in pairs for k in p],)).fetchall()}
        for src, dst in pairs:
            if src in have and dst in have:             # 본문을 받은 조문끼리만 (시행규칙이 없는 법률 등)
                store.upsert_delegation(conn, src, dst, origin="thdcmp")
                n += 1
    conn.execute("UPDATE raw_payloads SET parsed_at=now() WHERE source='lawgo.thdcmp' AND parsed_at IS NULL")
    return n


def text_delegations(conn) -> int:
    """시행령·감독규정 조문이 본문에서 '법 제N조', '영 제N조'를 인용하면 → 상위 조문에서 이 조문으로 위임된 것으로 본다.
    법제처 3단비교(thdCmp)를 받으면 그 결과가 우선이고, 이것은 키 발급 전·누락 보완용이다."""
    R = build_resolver(conn)
    n = 0
    conn.execute("DELETE FROM delegations WHERE origin='text'")   # 본문 추정분만 다시 계산
    # 3단비교가 있는 법률의 시행령·시행규칙은 공식 자료만 쓴다 (본문 추정은 정의 조항 인용까지 위임으로 잡는 잡음이 큼)
    official = {r["slug"] for r in conn.execute("""SELECT DISTINCT split_part(from_key, ':', 1) AS slug
                                                   FROM delegations WHERE origin='thdcmp'""").fetchall()}
    rows = conn.execute("""SELECT a.key, a.law_slug, l.kind, l.parent_slug, v.body FROM articles a
                           JOIN laws l ON l.slug=a.law_slug
                           JOIN LATERAL (SELECT body FROM article_versions WHERE article_key=a.key
                                         AND effective_from <= current_date ORDER BY effective_from DESC LIMIT 1) v ON true
                           WHERE l.kind IN ('시행령','시행규칙','감독규정','고시','시행세칙')""").fetchall()
    for r in rows:
        if r["kind"] in ("시행령", "시행규칙") and r["parent_slug"] in official:
            continue
        res = R.resolve([r["body"]], hint_law=r["law_slug"])
        uppers = {l.key for l in res.links
                  if LEVEL.get(R.laws[l.slug]["kind"], 9) < LEVEL.get(r["kind"], 9)
                  and R._root(l.slug) == R._root(r["law_slug"])}
        # '업무의 위탁'·'과태료' 처럼 상위 조문을 한꺼번에 나열하는 조문은 위임이 아니라 목록이다 → 제외
        if len(uppers) > MAX_UPPER_REFS:
            continue
        for key in uppers:
            store.upsert_delegation(conn, key, r["key"])
            n += 1
    return n


MAX_UPPER_REFS = 4
LEVEL = {"법률": 0, "시행령": 1, "시행규칙": 2, "감독규정": 3, "고시": 3, "시행세칙": 4}


def _ymd(v) -> date | None:
    if not v:
        return None
    v = str(v).replace("-", "").replace(".", "")[:8]
    return date(int(v[:4]), int(v[4:6]), int(v[6:8])) if len(v) == 8 and v.isdigit() else None


# ---------------------------------------------------------------- link
def build_resolver(conn) -> Resolver:
    laws = {r["slug"]: {"name": r["name"], "kind": r["kind"], "parent": r["parent_slug"], "aliases": r["aliases"]}
            for r in conn.execute("SELECT slug, name, kind, parent_slug, aliases FROM laws").fetchall()}
    arts: dict[str, set] = {}
    for r in conn.execute("SELECT law_slug, no FROM articles").fetchall():
        arts.setdefault(r["law_slug"], set()).add(r["no"])
    # 본문을 아직 못 받은 법령은 검증하지 않는다(조문 목록이 비어 있으면 모두 '없음'이 되므로)
    return Resolver(laws, {k: v for k, v in arts.items() if v})


def link(conn, relink_all: bool = False):
    with store.run(conn, "link", "documents") as s:
        last = conn.execute("""SELECT max(started_at) AS t FROM pipeline_runs
                               WHERE stage='link' AND status IN ('ok','partial')""").fetchone()["t"]
        q = "SELECT id, title, question, answer, reason, body, dept FROM documents"
        rows = conn.execute(q).fetchall() if relink_all or not last else \
            conn.execute(q + " WHERE changed_at >= %s", (last,)).fetchall()
        R = build_resolver(conn)
        s.update({"docs": 0, "links": 0, "unresolved": 0, "no_citation": 0})
        for d in rows:
            res = R.resolve([d["title"], d["question"], d["answer"], d["reason"], d["body"]],
                            fallback_law=DEPT_HINTS.get(d["dept"] or ""))
            store.replace_links(conn, d["id"], res, res.primary_law)
            s["docs"] += 1
            s["links"] += len(res.links)
            s["unresolved"] += len(res.unresolved)
            s["no_citation"] += 0 if res.links else 1


# ---------------------------------------------------------------- derive
def derive(conn, today: date | None = None):
    today = today or date.today()
    soon = today + timedelta(days=SETTINGS.expiring_days)
    with store.run(conn, "derive", "events") as s:
        n = 0
        # 새 해석·비조치의견 → 이벤트 (주 법령은 link 단계 결과)
        for d in conn.execute("""SELECT id, kind, title, published_on, primary_law FROM documents
                                 WHERE kind IN ('법령해석','비조치의견') AND published_on IS NOT NULL""").fetchall():
            kind = "해석_신규" if d["kind"] == "법령해석" else "비조치_신규"
            n += store.add_event(conn, f"doc_new:{d['id']}", d["published_on"], kind, d["title"],
                                 law_slug=d["primary_law"], doc_id=d["id"])
        # 행정지도: 예고 / 시행 / 만료임박 / 만료
        for g in conn.execute("""SELECT id, title, stage, valid_from, valid_to, primary_law FROM documents
                                 WHERE kind='행정지도'""").fetchall():
            if g["stage"] == "예고" and g["valid_from"]:
                n += store.add_event(conn, f"gd_notice:{g['id']}", g["valid_from"], "행정지도_예고", g["title"],
                                     law_slug=g["primary_law"], doc_id=g["id"])
            if g["stage"] == "시행" and g["valid_from"] and g["valid_from"] <= today:
                n += store.add_event(conn, f"gd_start:{g['id']}", g["valid_from"], "행정지도_시행", g["title"],
                                     law_slug=g["primary_law"], doc_id=g["id"])
            if g["stage"] == "시행" and g["valid_to"]:
                if today <= g["valid_to"] <= soon:
                    n += store.add_event(conn, f"gd_expiring:{g['id']}:{g['valid_to']}", today, "행정지도_만료임박",
                                         f"{g['title']} — {g['valid_to']:%Y.%m.%d} 존속기간 만료",
                                         law_slug=g["primary_law"], doc_id=g["id"])
                elif g["valid_to"] < today:
                    n += store.add_event(conn, f"gd_expired:{g['id']}:{g['valid_to']}", g["valid_to"], "행정지도_만료",
                                         g["title"], law_slug=g["primary_law"], doc_id=g["id"])
        # 입법예고·규정변경예고: 시작 / 의견제출 마감 7일 전
        for p in conn.execute("""SELECT id, title, valid_from, valid_to, primary_law FROM documents
                                 WHERE kind IN ('입법예고','규정변경예고') AND valid_from IS NOT NULL""").fetchall():
            n += store.add_event(conn, f"notice_start:{p['id']}", p["valid_from"], "입법예고_시작", p["title"],
                                 law_slug=p["primary_law"], doc_id=p["id"])
            if p["valid_to"] and today <= p["valid_to"] <= today + timedelta(days=7):
                n += store.add_event(conn, f"notice_due:{p['id']}", today, "입법예고_마감임박",
                                     f"{p['title']} — {p['valid_to']:%m.%d} 의견제출 마감",
                                     law_slug=p["primary_law"], doc_id=p["id"])
        s["events_new"] = n
        # 원천별 수집 현황 요약 — 조회 API 계정(api_reader)은 원본 표(raw_payloads)를 못 읽으므로 실행 기록에 남겨 둔다
        s["sources"] = {r["source"]: {"n": r["n"], "last": r["last"].isoformat(), "api": r["api"]}
                        for r in conn.execute("""
            SELECT source,
                   count(DISTINCT CASE WHEN source LIKE 'lawgo.%%' THEN split_part(source_key, ':', 1)
                                       ELSE source_key END) AS n,
                   max(fetched_at) AS last,
                   count(*) FILTER (WHERE payload LIKE '%%"via": "api"%%') AS api
            FROM raw_payloads
            WHERE source NOT IN ('lawgo.law', 'lawgo.admrul') OR split_part(source_key, ':', 1) IN (SELECT slug FROM laws)
            GROUP BY source""").fetchall()}
        store.refresh_stats(conn)
