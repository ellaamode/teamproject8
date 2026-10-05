"""법제처 Open API 수집기를 '로컬 시험 DB'에 한 번 실제로 돌려 본다 (Supabase 는 건드리지 않음).

  python -m tools.lawgo_trial

OC 값은 화면에 보이지 않게 입력받고 어디에도 저장하지 않는다. 결과 요약만 화면에 찍는다.
"""
import getpass
import os

oc = getpass.getpass("법제처 OC 값 입력 (화면에 안 보입니다) → ").strip()
if not oc:
    raise SystemExit("OC 값이 비어 있습니다.")
os.environ["LAW_GO_KR_OC"] = oc
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:@127.0.0.1:58876/postgres")   # 로컬 시험 DB

from batch import store  # noqa: E402  (키를 넣은 뒤에 불러와야 설정에 반영된다)
from batch.sources import lawgo  # noqa: E402

conn = store.connect(os.environ["DATABASE_URL"])
print("법령 21건 + 3단비교를 받습니다 (2~4분)…")
stats = lawgo.fetch_laws(conn)
for k, v in stats.items():
    print(f"  {k}: {str(v).replace(oc, '<OC>')}")
print("\n끝났습니다. 채팅에 '시험 수집 끝'이라고 알려 주세요. (OC 값은 저장되지 않았습니다)")
