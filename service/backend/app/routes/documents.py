from fastapi import APIRouter, HTTPException

from ..db import one, q

router = APIRouter(tags=["문서"])


@router.get("/documents/{doc_id}", summary="문서 원문 + 인용 조문(근거 표현) + 같은 조문을 다룬 다른 문서")
def document(doc_id: str):
    d = one("""SELECT id, kind, org, dept, title, question, answer, reason, body, published_on,
                      valid_from, valid_to, stage, source_url, source_name, primary_law
               FROM documents WHERE id=%s""", (doc_id,))
    if not d:
        raise HTTPException(404, f"문서 {doc_id}를 찾을 수 없습니다")
    links = q("""SELECT a.key, a.label, a.title, w.slug AS law_slug, w.name AS law_name, w.kind AS law_kind,
                        l.paragraph, l.item, l.method, l.confidence, l.evidence, l.reviewed
                 FROM article_links l JOIN articles a ON a.key=l.article_key JOIN laws w ON w.slug=a.law_slug
                 WHERE l.doc_id=%s ORDER BY w.kind, a.sort_key, l.paragraph""", (doc_id,))
    # 연관 문서: 같은 조문을 많이 공유할수록 위로
    related = q("""SELECT d.id, d.kind, d.title, d.published_on, count(*) AS shared,
                          array_agg(DISTINCT a.label) AS via
                   FROM article_links mine
                   JOIN article_links other ON other.article_key = mine.article_key AND other.doc_id <> mine.doc_id
                   JOIN documents d ON d.id = other.doc_id
                   JOIN articles a ON a.key = mine.article_key
                   WHERE mine.doc_id=%s
                   GROUP BY d.id ORDER BY count(*) DESC, d.published_on DESC LIMIT 6""", (doc_id,))
    return {**d, "links": links, "related": related}
