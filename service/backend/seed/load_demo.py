"""데모 데이터를 '실제 배치와 같은 경로'로 적재한다.

  python -m seed.load_demo            # DATABASE_URL 필요 (스키마 적용 포함)

실제 조문(seed/demo_laws.json)은 raw_payloads 에 원천 응답처럼 넣고 parse → link → derive 를 그대로 돌린다.
즉 데모가 동작한다는 것은 파이프라인이 동작한다는 뜻이다. 예시 문서만 수집 단계를 건너뛰고 바로 넣는다.
"""
import json
import pathlib
import sys
from datetime import date

from batch import pipeline, store
from batch.config import DEMO_SLUGS, LAW_BY_SLUG, SETTINGS

HERE = pathlib.Path(__file__).parent
SQL = HERE.parent / "sql" / "001_schema.sql"


def main(today: date | None = None):
    if not SETTINGS.database_url:
        sys.exit("DATABASE_URL 이 필요합니다")
    conn = store.connect(SETTINGS.database_url)
    conn.autocommit = True
    conn.execute(SQL.read_text(encoding="utf-8"))
    conn.autocommit = False

    for slug in DEMO_SLUGS:
        store.upsert_law(conn, LAW_BY_SLUG[slug])
    for law in json.loads((HERE / "demo_laws.json").read_text(encoding="utf-8"))["laws"]:
        spec = LAW_BY_SLUG[law["meta"]["slug"]]
        store.save_raw(conn, spec.source, f"{spec.slug}:{law['meta']['seq']}", 200, json.dumps(law, ensure_ascii=False))
    conn.commit()
    pipeline.parse(conn)

    docs = json.loads((HERE / "demo_documents.json").read_text(encoding="utf-8"))["documents"]
    for d in docs:
        d.setdefault("source_url", "https://better.fsc.go.kr/fsc_new/replyCase/TotalReplyList.do?stNo=11&muNo=117&muGpNo=75")
        d.setdefault("source_name", "예시 데이터 (실제 회신 아님)")
        for k in ("dept", "question", "answer", "reason", "body", "valid_from", "valid_to", "stage"):
            d.setdefault(k, None)
        store.upsert_document(conn, d)
    conn.commit()
    pipeline.link(conn, relink_all=True)
    pipeline.derive(conn, today=today)
    c = conn.execute("""SELECT (SELECT count(*) FROM articles) a, (SELECT count(*) FROM article_versions) v,
                               (SELECT count(*) FROM delegations) dl, (SELECT count(*) FROM documents) d,
                               (SELECT count(*) FROM article_links) l, (SELECT count(*) FROM change_events) e,
                               (SELECT count(*) FROM unresolved_mentions) u""").fetchone()
    print(f"조문 {c['a']} · 본문버전 {c['v']} · 위임 {c['dl']} · 문서 {c['d']} · 링크 {c['l']} · 이벤트 {c['e']} · 미해결 {c['u']}")
    conn.close()


if __name__ == "__main__":
    main()
