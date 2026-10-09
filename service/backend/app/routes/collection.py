"""외부 원천 수집 현황 API.

이 서비스의 외부 연결(법제처 Open API·금융위 포털 크롤링)은 수집 프로그램(GitHub Actions)이 맡고,
조회 API는 그 결과를 DB에서 읽기만 한다. 이 API는 "언제, 어디서, 무엇을, 몇 건 받아 왔는지"를 보여 준다.
"""
from fastapi import APIRouter, Query

from ..db import q
from .analysis import source_summary

router = APIRouter(tags=["수집 현황"])

RUNNER = {"tool": "GitHub Actions", "workflow": ".github/workflows/collect.yml", "trigger": "수동 실행 (Run workflow 버튼)",
          "url": "https://github.com/ellaamode/teamproject8/actions/workflows/collect.yml",
          "steps": ["수집 (외부 원천에서 받아 원문 보관)", "정리 (조문·문서로 나눔)", "연결 (본문의 조문 인용 찾기)", "변화 기록"]}
STAGE = {"fetch": "수집", "parse": "정리", "link": "연결", "derive": "변화 기록"}
# 실행 기록의 source 이름 → 원천 (법제처는 Open API가 막히면 웹페이지 수집으로 대신한다)
RUN_SOURCES = {"lawgo": ("lawgo", "lawweb"), "fsc.reply": ("fsc.reply",), "fsc.guidance": ("fsc.guidance",)}


def _run(r: dict) -> dict:
    stats = {k: v for k, v in (r["stats"] or {}).items() if k != "sources"}   # 원천별 요약은 sources 에 따로 보여 줌
    return {"stage": STAGE.get(r["stage"], r["stage"]), "source": r["source"], "status": r["status"],
            "started_at": r["started_at"], "finished_at": r["finished_at"], "stats": stats, "error": r["error"]}


@router.get("/collection", summary="외부 원천별 수집 현황 (법제처 Open API · 금융위 포털 크롤링)")
def collection(limit: int = Query(20, ge=1, le=100, description="최근 실행 기록 개수")):
    sources = source_summary()
    for s in sources:
        last = q("""SELECT stage, source, status, started_at, finished_at, stats, error FROM pipeline_runs
                    WHERE stage='fetch' AND source = ANY(%s) ORDER BY started_at DESC LIMIT 1""",
                 (list(RUN_SOURCES.get(s["key"], (s["key"],))),))
        s["last_run"] = _run(last[0]) if last else None
    runs = q("""SELECT stage, source, status, started_at, finished_at, stats, error FROM pipeline_runs
                ORDER BY started_at DESC LIMIT %s""", (limit,))
    return {"runner": RUNNER, "sources": sources, "recent_runs": [_run(r) for r in runs]}
