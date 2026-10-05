from fastapi import APIRouter, HTTPException

from ..db import one, q

router = APIRouter(tags=["법령"])


@router.get("/laws", summary="대상 법령 목록 (법률·시행령·감독규정 묶음)")
def laws():
    rows = q("""SELECT l.slug, l.name, l.kind, l.parent_slug AS parent, l.sectors, l.effective_on,
                       count(DISTINCT a.key) AS articles,
                       coalesce(sum(s.total), 0)::int AS linked_docs
                FROM laws l LEFT JOIN articles a ON a.law_slug = l.slug
                LEFT JOIN article_stats s ON s.article_key = a.key
                GROUP BY l.slug HAVING count(DISTINCT a.key) > 0  -- 본문 적재 전 법령은 숨김
                ORDER BY coalesce(l.parent_slug, l.slug), array_position(ARRAY['법률','시행령','시행규칙','감독규정','고시','시행세칙'], l.kind)""")
    return rows


@router.get("/laws/{slug}/toc", summary="법령 목차 + 조문별 연결 자료 수")
def toc(slug: str):
    law = one("SELECT slug, name, kind, parent_slug AS parent, effective_on, sectors FROM laws WHERE slug=%s", (slug,))
    if not law:
        raise HTTPException(404, f"법령 {slug}을 찾을 수 없습니다")
    family_root = law["parent"] or slug
    family = q("""SELECT slug, name, kind FROM laws WHERE slug=%s OR parent_slug=%s
                  ORDER BY array_position(ARRAY['법률','시행령','시행규칙','감독규정','고시','시행세칙'], kind)""", (family_root, family_root))
    arts = q("""SELECT a.key, a.no, a.label, a.title, a.chapter, a.is_deleted,
                       coalesce(s.total,0) AS total, coalesce(s.interp,0) AS interp,
                       coalesce(s.noaction,0) AS noaction, coalesce(s.guidance,0) AS guidance,
                       coalesce(s.notice,0) AS notice,
                       EXISTS (SELECT 1 FROM article_versions v WHERE v.article_key=a.key
                               AND v.effective_from > current_date) AS pending
                FROM articles a LEFT JOIN article_stats s ON s.article_key = a.key
                WHERE a.law_slug=%s ORDER BY a.sort_key""", (slug,))
    chapters: list[dict] = []
    for a in arts:
        name = a.pop("chapter") or ""
        if not chapters or chapters[-1]["name"] != name:
            chapters.append({"name": name, "articles": []})
        chapters[-1]["articles"].append(a)
    return {"law": law, "family": family, "chapters": chapters}
