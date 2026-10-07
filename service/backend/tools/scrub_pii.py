"""이미 수집해 둔 데이터에서 개인정보를 지운다 (1회용, 여러 번 실행해도 결과 같음).

  python -m tools.scrub_pii            # DATABASE_URL 이 없으면 연결 주소를 화면에 안 보이게 입력받는다

  - 포털 회신 원본: 본문 표의 전화번호·이메일·담당 공무원 실명 가리기, 목록 행의 개인 칸 제거
  - 포털 행정지도 원본: 등록자 ID·이름(regId·regNm) 제거
  - 법제처 원본: 행정규칙 담당자명·전화번호 칸 제거
  이후 포털 문서를 다시 가공(parse)·연결(link)해 화면에 쓰이는 documents 도 바뀐다.
"""
import getpass
import json
import os

if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = getpass.getpass("DB 연결 주소 (화면에 안 보입니다) → ").strip()

from batch import pipeline, store  # noqa: E402
from batch.config import SETTINGS  # noqa: E402
from batch.normalize import content_hash, redact_pii, strip_personal  # noqa: E402

REPLY = ("fsc.lawreq", "fsc.opinion", "fsc.pastreq")


def clean(source: str, payload: str) -> str:
    d = json.loads(payload)
    if source in REPLY:
        d = {**d, "list": strip_personal(d["list"]), "html": redact_pii(d["html"])}
        return json.dumps(d, ensure_ascii=False)
    if source == "fsc.guidance":
        return json.dumps(strip_personal(d), ensure_ascii=False, sort_keys=True)
    if d.get("meta", {}).get("via") == "api":                      # 법제처 Open API 본문
        return json.dumps({**d, "body": strip_personal(d["body"])}, ensure_ascii=False)
    return payload


def main():
    conn = store.connect(SETTINGS.database_url)
    changed = {}
    rows = conn.execute("""SELECT source, source_key, content_hash, payload FROM raw_payloads
                           WHERE source IN ('fsc.lawreq','fsc.opinion','fsc.pastreq','fsc.guidance',
                                            'lawgo.law','lawgo.admrul')""").fetchall()
    for r in rows:
        new = clean(r["source"], r["payload"])
        if new == r["payload"]:
            continue
        h = content_hash(new)
        dup = conn.execute("SELECT 1 FROM raw_payloads WHERE source=%s AND source_key=%s AND content_hash=%s",
                           (r["source"], r["source_key"], h)).fetchone()
        if dup:                                                      # 같은 내용(정리본)이 이미 있으면 원래 행만 지운다
            conn.execute("DELETE FROM raw_payloads WHERE source=%s AND source_key=%s AND content_hash=%s",
                         (r["source"], r["source_key"], r["content_hash"]))
        else:
            conn.execute("""UPDATE raw_payloads SET payload=%s, content_hash=%s,
                              parsed_at = CASE WHEN source LIKE 'fsc.%%' THEN NULL ELSE parsed_at END
                            WHERE source=%s AND source_key=%s AND content_hash=%s""",
                         (new, h, r["source"], r["source_key"], r["content_hash"]))
        changed[r["source"]] = changed.get(r["source"], 0) + 1
    conn.commit()
    print("원본 정리:", changed or "바뀐 것 없음")
    pipeline.parse(conn)          # 정리된 포털 원본 → documents 갱신
    pipeline.link(conn)           # 바뀐 문서만 다시 연결
    pipeline.derive(conn)
    left = conn.execute(r"""SELECT count(*) AS n FROM documents
                            WHERE concat_ws(' ', question, answer, reason, body) ~ '0\d{1,2}[)-]\s?\d{3,4}-\d{4}'""").fetchone()["n"]
    print("완료. 전화번호가 남은 문서:", left)


if __name__ == "__main__":
    main()
