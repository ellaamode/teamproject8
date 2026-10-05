"""변화 피드와 행정지도 현황.

관심 조문 모니터링은 로그인 없이 동작한다: 브라우저가 저장해 둔 관심 조문 키 목록을 articles= 로 보내면
그 조문에 직접 걸린 이벤트 + 그 조문을 인용한 문서의 이벤트를 돌려준다. 서버에 사용자 정보를 남기지 않는다.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Query

from ..db import q

router = APIRouter(tags=["변화"])


@router.get("/feed", summary="변화 피드 (새 해석·비조치, 조문 개정·시행예정, 행정지도 시행·만료)")
def feed(days: int = Query(90, ge=1, le=730),
         laws: list[str] = Query([], description="법률 slug (하위 시행령·감독규정 포함)"),
         articles: list[str] = Query([], description="관심 조문 키 (예: efta:25의2)"),
         kinds: list[str] = Query([]), limit: int = Query(50, ge=1, le=200)):
    since = date.today() - timedelta(days=days)
    where, args = ["e.occurred_on >= %s"], [since]
    if laws:
        where.append("""(coalesce(w.parent_slug, w.slug) = ANY(%s) OR e.doc_id IN (
                           SELECT l.doc_id FROM article_links l JOIN articles a ON a.key=l.article_key
                           JOIN laws x ON x.slug=a.law_slug WHERE coalesce(x.parent_slug,x.slug) = ANY(%s)))""")
        args += [laws, laws]
    if articles:
        where.append("(e.article_key = ANY(%s) OR e.doc_id IN (SELECT doc_id FROM article_links WHERE article_key = ANY(%s)))")
        args += [articles, articles]
    if kinds:
        where.append("e.kind = ANY(%s)")
        args.append(kinds)
    rows = q(f"""SELECT e.id, e.occurred_on, e.kind, e.title, e.doc_id, e.article_key, e.law_slug,
                        w.name AS law_name, a.label AS article_label, d.kind AS doc_kind, d.org
                 FROM change_events e
                 LEFT JOIN laws w ON w.slug = e.law_slug
                 LEFT JOIN articles a ON a.key = e.article_key
                 LEFT JOIN documents d ON d.id = e.doc_id
                 WHERE {' AND '.join(where)}
                 ORDER BY e.occurred_on DESC, e.id DESC LIMIT %s""", tuple(args + [limit]))
    # 이벤트가 문서에 걸린 경우, 그 문서가 인용한 조문 라벨을 붙여 준다(피드에서 '어느 조문 얘기인지' 보이게)
    ids = [r["doc_id"] for r in rows if r["doc_id"]]
    cites: dict = {}
    if ids:
        for r in q("""SELECT l.doc_id, a.key, a.label, w.name AS law_name FROM article_links l
                      JOIN articles a ON a.key=l.article_key JOIN laws w ON w.slug=a.law_slug
                      WHERE l.doc_id = ANY(%s) ORDER BY w.kind, a.sort_key""", (ids,)):
            lst = cites.setdefault(r.pop("doc_id"), [])
            if all(x["key"] != r["key"] for x in lst):
                lst.append(r)
    for r in rows:
        linked = cites.get(r["doc_id"], [])
        r["articles"] = linked[:3]
        # 브라우저가 관심 조문으로 다시 거를 수 있도록 관련 조문 키 전체를 함께 준다
        r["article_keys"] = sorted({x["key"] for x in linked} | ({r["article_key"]} if r["article_key"] else set()))
    summary = {r["kind"]: r["n"] for r in q(
        f"""SELECT e.kind, count(*) AS n FROM change_events e LEFT JOIN laws w ON w.slug = e.law_slug
             WHERE {' AND '.join(where)} GROUP BY e.kind""", tuple(args))}
    return {"since": since, "summary": summary, "items": rows}


@router.get("/guidance", summary="행정지도 현황 (시행중·만료임박·예고)")
def guidance(status: str = Query("active", pattern="^(active|expiring|notice|all)$"), within: int = 60):
    today = date.today()
    base = """SELECT id, title, org, dept, stage, valid_from, valid_to, source_url,
                     (valid_to - current_date) AS days_left
              FROM documents WHERE kind='행정지도'"""
    if status == "active":
        rows = q(base + " AND stage='시행' AND (valid_to IS NULL OR valid_to >= current_date) ORDER BY valid_to NULLS LAST")
    elif status == "expiring":
        rows = q(base + " AND stage='시행' AND valid_to BETWEEN current_date AND current_date + %s ORDER BY valid_to",
                 (within,))
    elif status == "notice":
        rows = q(base + " AND stage='예고' ORDER BY valid_from DESC")
    else:
        rows = q(base + " ORDER BY published_on DESC")
    return {"today": today, "status": status, "items": rows}
