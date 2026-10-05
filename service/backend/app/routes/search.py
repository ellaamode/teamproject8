"""통합검색.

한국어는 PostgreSQL 기본 전문검색(형태소 분리 없음)으로는 잘 안 잡혀서, pg_trgm 인덱스 + 부분일치로 찾는다.
점수 = 본문 포함 단어 비율×3 + 제목 포함 단어 비율×2 + (검색어와 제목이 비슷한 정도)
검색어가 '여전법 제2조' 처럼 조문 표기면 인용 엔진으로 해석해 그 조문을 결과 맨 위에 '바로가기'로 준다.
"""
import re
from datetime import date
from functools import lru_cache

from fastapi import APIRouter, Query

from batch.linker import Resolver

from ..db import q

router = APIRouter(tags=["검색"])
KINDS = ("법령해석", "비조치의견", "행정지도", "입법예고", "규정변경예고", "현장건의")


@lru_cache(maxsize=1)
def _has_trgm() -> bool:
    return bool(q("SELECT 1 FROM pg_extension WHERE extname='pg_trgm'"))


@lru_cache(maxsize=1)
def _resolver() -> Resolver:
    laws = {r["slug"]: {"name": r["name"], "kind": r["kind"], "parent": r["parent_slug"], "aliases": r["aliases"]}
            for r in q("SELECT slug, name, kind, parent_slug, aliases FROM laws")}
    arts: dict = {}
    for r in q("SELECT law_slug, no FROM articles"):
        arts.setdefault(r["law_slug"], set()).add(r["no"])
    return Resolver(laws, arts)


def _like(w: str) -> str:
    return "%" + w.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"


def _snippet(text: str, words: list[str], width: int = 70) -> str:
    t = re.sub(r"\s+", " ", text or "")
    pos = min((t.find(w) for w in words if w in t), default=-1)
    if pos < 0:
        return t[:width * 2]
    s = max(0, pos - width)
    return ("…" if s else "") + t[s:pos + width] + ("…" if pos + width < len(t) else "")


@router.get("/search", summary="통합검색 (문서 + 조문 바로가기 + 유형별 개수)")
def search(q_: str = Query("", alias="q", max_length=100),
           kinds: list[str] = Query([]), orgs: list[str] = Query([]), laws: list[str] = Query([]),
           from_: date | None = Query(None, alias="from"), to: date | None = None,
           sort: str = Query("relevance", pattern="^(relevance|date)$"),
           limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    words = [w for w in q_.split() if len(w) >= 1][:6]

    # 1) 조문 표기 해석 → 바로가기
    jump = None
    if re.search(r"\d+\s*조", q_):
        res = _resolver().resolve([q_])
        if res.links:
            l = res.links[0]
            jump = q("""SELECT a.key, a.label, a.title, l.name AS law_name FROM articles a
                        JOIN laws l ON l.slug=a.law_slug WHERE a.key=%s""", (l.key,))
            jump = jump[0] if jump else None

    # 2) 문서 검색. 필터는 (조건, 값) 쌍으로 모아 두고, 유형별 개수를 셀 때는 '유형' 필터만 빼고 재사용한다.
    score, sargs = "0", []
    text_filter: list[tuple[str, list]] = []
    if words:
        score = "(" + " + ".join(["(d.search_text ILIKE %s)::int*3 + (d.title ILIKE %s)::int*2"] * len(words)) + \
                f")::float / {len(words)}" + (" + similarity(d.title, %s)" if _has_trgm() else "")
        for w in words:
            sargs += [_like(w), _like(w)]
        if _has_trgm():
            sargs.append(q_)
        # 조문 제목이 검색어와 맞으면 그 조문에 연결된 문서도 결과에 포함 (예: '선불충전금' → 제25조의2 연결 문서)
        text_filter.append(("(" + " OR ".join(["d.search_text ILIKE %s"] * len(words)) +
                            " OR d.id IN (SELECT l.doc_id FROM article_links l JOIN articles a ON a.key=l.article_key WHERE " +
                            " AND ".join(["a.title ILIKE %s"] * len(words)) + "))",
                            [_like(w) for w in words] * 2))
    other: list[tuple[str, list]] = []
    if orgs:
        other.append(("d.org = ANY(%s)", [orgs]))
    if laws:
        other.append(("EXISTS (SELECT 1 FROM article_links l JOIN articles a ON a.key=l.article_key "
                      "JOIN laws w ON w.slug=a.law_slug WHERE l.doc_id=d.id AND coalesce(w.parent_slug,w.slug) = ANY(%s))",
                      [laws]))
    if from_:
        other.append(("d.published_on >= %s", [from_]))
    if to:
        other.append(("d.published_on <= %s", [to]))
    kind_filter = [("d.kind = ANY(%s)", [kinds])] if kinds else []

    def build(parts):
        return " AND ".join(["TRUE"] + [c for c, _ in parts]), [v for _, vs in parts for v in vs]

    where, args = build(text_filter + other + kind_filter)
    order = "d.published_on DESC" if sort == "date" or not words else "score DESC, d.published_on DESC"
    rows = q(f"""SELECT d.id, d.kind, d.title, d.org, d.dept, d.published_on, d.stage, d.valid_to,
                        d.search_text, {score} AS score, count(*) OVER () AS total
                 FROM documents d WHERE {where}
                 ORDER BY {order} LIMIT %s OFFSET %s""", tuple(sargs + args + [limit, offset]))
    total = rows[0]["total"] if rows else 0
    ids = [r["id"] for r in rows]
    arts = {}
    if ids:
        for r in q("""SELECT l.doc_id, a.key, a.label, a.title, w.name AS law_name, w.kind AS law_kind
                      FROM article_links l JOIN articles a ON a.key=l.article_key JOIN laws w ON w.slug=a.law_slug
                      WHERE l.doc_id = ANY(%s) ORDER BY w.kind, a.sort_key""", (ids,)):
            lst = arts.setdefault(r.pop("doc_id"), [])
            if all(x["key"] != r["key"] for x in lst):
                lst.append(r)
    items = []
    for r in rows:
        r["snippet"] = _snippet(r.pop("search_text"), words)
        r["articles"] = arts.get(r["id"], [])[:4]
        r.pop("total")
        items.append(r)

    # 3) 유형별 개수 (필터 칩 숫자) — 유형 필터를 뺀 같은 조건으로 센다
    fwhere, fargs = build(text_filter + other)
    facets = {r["kind"]: r["n"] for r in q(f"SELECT d.kind, count(*) AS n FROM documents d WHERE {fwhere} GROUP BY d.kind",
                                           tuple(fargs))}

    # 4) 조문 자체 검색 (제목·본문)
    art_hits = []
    if words:
        art_hits = q(f"""SELECT a.key, a.label, a.title, l.name AS law_name, l.kind AS law_kind,
                                coalesce(s.total,0) AS linked
                         FROM articles a JOIN laws l ON l.slug=a.law_slug
                         LEFT JOIN article_stats s ON s.article_key=a.key
                         WHERE {' AND '.join(['a.title ILIKE %s'] * len(words))}
                         ORDER BY coalesce(s.total,0) DESC, l.kind, a.sort_key LIMIT 5""",
                     tuple(_like(w) for w in words))
    return {"query": q_, "jump": jump, "total": total, "facets": facets, "articles": art_hits, "items": items}
