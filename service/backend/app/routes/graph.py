"""조문 연결 그래프: 한 조문을 중심으로 '점(조문·문서)'과 '선(위임·인용)'을 돌려준다.

화면은 이 응답을 그대로 그림으로 그린다. 그림의 내용은 전부 DB 데이터이므로 손으로 그린 그림처럼 틀릴 수 없다.
  - 위임: 중심 조문의 위·아래로 최대 2단계 (법률 → 시행령 → 감독규정)
  - 인용: 중심 조문을 인용한 문서를 유형별 최신 per_kind 건, 나머지는 more 에 개수만
  - 그 문서가 그래프 안의 다른 조문(예: 시행령)도 인용했다면 그 선도 함께 준다
"""
from fastapi import APIRouter, HTTPException, Query

from ..db import one, q

router = APIRouter(tags=["조문"])
TIER = {"법률": 0, "시행령": 1, "시행규칙": 1, "감독규정": 2, "고시": 2, "시행세칙": 3}   # 그림의 가로줄


def _articles(keys) -> dict:
    if not keys:
        return {}
    rows = q("""SELECT a.key, a.label, a.title, l.slug AS law_slug, l.name AS law_name, l.kind AS law_kind
                FROM articles a JOIN laws l ON l.slug=a.law_slug WHERE a.key = ANY(%s)""", (list(keys),))
    return {r["key"]: r for r in rows}


def _delegations(keys: set, direction: str) -> list[dict]:
    col, other = ("from_key", "to_key") if direction == "down" else ("to_key", "from_key")
    return q(f"SELECT from_key, to_key, origin FROM delegations WHERE {col} = ANY(%s)", (list(keys),)) if keys else []


@router.get("/articles/{key}/graph", summary="조문 연결 그래프 (위임 관계 + 인용 문서) — 그림용 점·선 목록")
def article_graph(key: str, depth: int = Query(2, ge=1, le=2, description="위임 관계를 몇 단계까지 따라갈지"),
                  per_kind: int = Query(3, ge=1, le=10, description="문서 유형별로 그릴 최대 건수")):
    if not one("SELECT 1 FROM articles WHERE key=%s", (key,)):
        raise HTTPException(404, f"조문 {key}을 찾을 수 없습니다")

    # 1) 위임 관계: 중심에서 위·아래로 depth 단계
    edges, seen = [], {key}
    frontier_down, frontier_up = {key}, {key}
    for _ in range(depth):
        down = _delegations(frontier_down, "down")
        up = _delegations(frontier_up, "up")
        frontier_down = {d["to_key"] for d in down} - seen
        frontier_up = {d["from_key"] for d in up} - seen
        for d in down + up:
            e = {"from": d["from_key"], "to": d["to_key"], "type": "delegation", "origin": d["origin"]}
            if e not in edges:
                edges.append(e)
        seen |= frontier_down | frontier_up
    arts = _articles(seen)

    # 2) 중심 조문을 인용한 문서: 유형별 최신 per_kind 건
    docs = q("""SELECT * FROM (
                  SELECT d.id, d.kind, d.title, d.org, d.published_on, d.stage, d.valid_to,
                         row_number() OVER (PARTITION BY d.kind ORDER BY d.published_on DESC) AS rn,
                         count(*) OVER (PARTITION BY d.kind) AS kind_total
                  FROM documents d WHERE d.id IN (SELECT doc_id FROM article_links WHERE article_key=%s)) t
                WHERE rn <= %s ORDER BY kind, published_on DESC""", (key, per_kind))
    more = {d["kind"]: d["kind_total"] - per_kind for d in docs if d["kind_total"] > per_kind}

    # 3) 그 문서들이 그래프 안 조문을 인용한 선 (중심 + 위임 조문)
    if docs:
        for l in q("""SELECT doc_id, article_key, max(confidence) AS confidence, min(method) AS method
                      FROM article_links WHERE doc_id = ANY(%s) AND article_key = ANY(%s)
                      GROUP BY doc_id, article_key""", ([d["id"] for d in docs], list(seen))):
            edges.append({"from": l["doc_id"], "to": l["article_key"], "type": "citation",
                          "method": l["method"], "confidence": l["confidence"]})

    nodes = [{"id": k, "type": "article", "center": k == key, "tier": TIER.get(a["law_kind"], 1),
              "label": a["label"], "title": a["title"], "law_name": a["law_name"], "law_kind": a["law_kind"]}
             for k, a in arts.items()]
    nodes += [{"id": d["id"], "type": "document", "kind": d["kind"], "title": d["title"], "org": d["org"],
               "published_on": d["published_on"], "stage": d["stage"], "valid_to": d["valid_to"]} for d in docs]
    return {"center": key, "nodes": nodes, "edges": edges, "more": more,
            "note": "위임 관계 origin: thdcmp=법제처 3단비교, text=하위 규정 본문의 '법 제N조' 인용으로 추정"}
