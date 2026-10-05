from fastapi import APIRouter, HTTPException

from ..db import one, q

router = APIRouter(tags=["조문"])


@router.get("/articles/{key}", summary="조문 카드: 현행·시행예정 본문, 위임 관계, 연결 자료, 최근 변화")
def article(key: str):
    a = one("""SELECT a.key, a.no, a.label, a.title, a.chapter, a.is_deleted,
                      l.slug AS law_slug, l.name AS law_name, l.kind AS law_kind, l.parent_slug AS law_parent
               FROM articles a JOIN laws l ON l.slug = a.law_slug WHERE a.key=%s""", (key,))
    if not a:
        raise HTTPException(404, f"조문 {key}을 찾을 수 없습니다")
    versions = q("""SELECT effective_from, effective_to, title, body FROM article_versions
                    WHERE article_key=%s ORDER BY effective_from""", (key,))
    # 시행예정으로만 존재하는 신설 조문은 current 가 없다(현행 조문처럼 보여주면 안 됨)
    current = next((v for v in reversed(versions) if v["effective_from"] <= _today()), None)
    pending = next((v for v in versions if v["effective_from"] > _today()), None)
    # 위임: thdCmp 결과가 있으면 그것을, 없으면 본문 인용(시행령이 '법 제N조'를 인용)으로 보완
    down = q("""SELECT d.to_key AS key, t.label, t.title, l.name AS law_name, l.kind AS law_kind, d.origin
                FROM delegations d JOIN articles t ON t.key=d.to_key JOIN laws l ON l.slug=t.law_slug
                WHERE d.from_key=%s ORDER BY l.kind, t.sort_key""", (key,))
    up = q("""SELECT d.from_key AS key, f.label, f.title, l.name AS law_name, l.kind AS law_kind
              FROM delegations d JOIN articles f ON f.key=d.from_key JOIN laws l ON l.slug=f.law_slug
              WHERE d.to_key=%s""", (key,))
    docs = q("""SELECT d.id, d.kind, d.title, d.org, d.dept, d.published_on, d.stage, d.valid_from, d.valid_to,
                       max(l.confidence) AS confidence,
                       array_agg(DISTINCT l.evidence) AS evidence,
                       array_agg(DISTINCT CASE WHEN l.paragraph>0 THEN l.paragraph END) FILTER (WHERE l.paragraph>0) AS paragraphs
                FROM article_links l JOIN documents d ON d.id=l.doc_id
                WHERE l.article_key=%s
                GROUP BY d.id ORDER BY d.published_on DESC""", (key,))
    stats = one("SELECT total, interp, noaction, guidance, notice, latest_on FROM article_stats WHERE article_key=%s",
                (key,)) or {"total": 0, "interp": 0, "noaction": 0, "guidance": 0, "notice": 0, "latest_on": None}
    events = q("""SELECT e.occurred_on, e.kind, e.title, e.doc_id FROM change_events e
                  WHERE e.article_key=%s OR e.doc_id IN (SELECT doc_id FROM article_links WHERE article_key=%s)
                  ORDER BY e.occurred_on DESC LIMIT 10""", (key, key))
    neighbors = q("""SELECT key, label, title FROM articles WHERE law_slug=%s AND sort_key IN (
                       (SELECT max(sort_key) FROM articles WHERE law_slug=%s AND sort_key < (SELECT sort_key FROM articles WHERE key=%s)),
                       (SELECT min(sort_key) FROM articles WHERE law_slug=%s AND sort_key > (SELECT sort_key FROM articles WHERE key=%s)))
                     ORDER BY sort_key""", (a["law_slug"], a["law_slug"], key, a["law_slug"], key))
    return {**a, "current": current, "pending": pending,
            "history": [{"effective_from": v["effective_from"], "effective_to": v["effective_to"]} for v in versions],
            "delegates_to": down, "delegated_from": up, "stats": stats, "documents": docs,
            "events": events, "neighbors": neighbors}


def _today():
    from datetime import date
    return date.today()
