from fastapi import APIRouter

from ..db import q

router = APIRouter(tags=["상태"])


@router.get("/health", summary="서버·DB 상태와 데이터 기준 시각")
def health():
    runs = q("""SELECT DISTINCT ON (stage, source) stage, source, status, finished_at, stats
                FROM pipeline_runs WHERE finished_at IS NOT NULL
                ORDER BY stage, source, started_at DESC""")
    counts = q("""SELECT (SELECT count(*) FROM documents) AS documents,
                         (SELECT count(*) FROM articles)  AS articles,
                         (SELECT count(*) FROM article_links) AS links,
                         (SELECT count(*) FROM laws) AS laws""")[0]
    last = max((r["finished_at"] for r in runs), default=None)
    return {"status": "ok", "data_as_of": last, "counts": counts, "runs": runs}
