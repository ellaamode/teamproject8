"""수집한 원본(raw_payloads)을 파일로 옮겨, 다른 DB(예: Supabase)에서 다시 가공한다.

  python -m tools.raw_transfer dump  ../../_data/raw.jsonl.gz      # 로컬 DB → 파일
  python -m tools.raw_transfer load  ../../_data/raw.jsonl.gz      # 파일 → DATABASE_URL 의 DB, 이어서 parse·link·derive

원천 사이트를 다시 수 시간 긁지 않아도 되고, 원본이 같으므로 가공 결과도 같다(파이프라인이 멱등).
주의: 파일에는 포털 회신 원문이 들어 있다 → 공개 저장소(GitHub)에 올리지 말 것 (.gitignore 의 _data/).
"""
import gzip
import json
import sys

from batch import pipeline, store
from batch.config import SETTINGS, TARGET_LAWS


def dump(path: str):
    conn = store.connect(SETTINGS.database_url)
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in conn.execute("SELECT source, source_key, content_hash, fetched_at, http_status, payload FROM raw_payloads ORDER BY fetched_at"):
            r["fetched_at"] = r["fetched_at"].isoformat()
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    print(f"원본 {n}건 → {path}")


def load(path: str):
    conn = store.connect(SETTINGS.database_url)
    for spec in TARGET_LAWS:
        store.upsert_law(conn, spec)
    n = 0
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            conn.execute("""INSERT INTO raw_payloads (source, source_key, content_hash, fetched_at, http_status, payload)
                            VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                         (r["source"], r["source_key"], r["content_hash"], r["fetched_at"], r["http_status"], r["payload"]))
            n += 1
            if n % 1000 == 0:
                conn.commit()
                print(f"  {n}건…")
    conn.commit()
    print(f"원본 {n}건 적재 → parse · link · derive")
    pipeline.parse(conn)
    pipeline.link(conn, relink_all=True)
    pipeline.derive(conn)
    print("완료")


if __name__ == "__main__":
    {"dump": dump, "load": load}[sys.argv[1]](sys.argv[2])
