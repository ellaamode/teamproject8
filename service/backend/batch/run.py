"""배치 실행기.

  python -m batch.run all                 # 매일: fetch → parse → link → derive
  python -m batch.run fetch --source fsc  # 포털만 수집
  python -m batch.run link --all          # 인용 규칙을 고친 뒤 전체 재연결 (원천 재수집 없음)
  python -m batch.run derive

GitHub Actions(.github/workflows/collect.yml)가 매일 06:00 KST 에 'all' 을 실행한다.
한 단계가 실패해도 다음 단계는 이미 저장된 데이터로 계속 진행한다(부분 실패 허용).
"""
import argparse
import sys

from . import pipeline, store
from .config import SETTINGS


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["all", "fetch", "parse", "link", "derive"])
    ap.add_argument("--source", choices=["fsc", "lawgo", "all"], default="all")
    ap.add_argument("--all", action="store_true", help="link: 모든 문서를 다시 연결")
    a = ap.parse_args(argv)
    if not SETTINGS.database_url:
        print("DATABASE_URL 이 필요합니다", file=sys.stderr)
        return 2
    conn = store.connect(SETTINGS.database_url)
    sources = ("fsc", "lawgo") if a.source == "all" else (a.source,)
    failed = []
    steps = {
        "fetch": lambda: pipeline.fetch(conn, sources),
        "parse": lambda: pipeline.parse(conn),
        "link": lambda: pipeline.link(conn, relink_all=a.all),
        "derive": lambda: pipeline.derive(conn),
    }
    for name in (["fetch", "parse", "link", "derive"] if a.stage == "all" else [a.stage]):
        try:
            steps[name]()
            print(f"[{name}] ok")
        except Exception as e:                    # 기록은 store.run 이 남긴다
            failed.append(name)
            print(f"[{name}] 실패: {e}", file=sys.stderr)
    conn.close()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
