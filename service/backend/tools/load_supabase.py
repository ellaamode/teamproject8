"""수집해 둔 원본 파일(_data/raw.jsonl.gz)을 Supabase 로 옮기고 가공까지 한 번에 실행한다.

  python -m tools.load_supabase

연결 주소는 화면에 보이지 않게 입력받는다(파일·기록에 남지 않음). postgres 계정의 Session pooler 주소를 쓴다.
"""
import getpass
import os
import pathlib

url = getpass.getpass("Supabase 연결 주소 붙여넣기 (입력해도 화면에 안 보입니다) → ").strip()
if not url.startswith("postgresql://"):
    raise SystemExit("주소가 postgresql:// 로 시작해야 합니다. Supabase > Connect > Session pooler 주소를 복사하세요.")
os.environ["DATABASE_URL"] = url

from tools import raw_transfer  # noqa: E402  (주소를 넣은 뒤에 불러와야 설정에 반영된다)

path = pathlib.Path(__file__).resolve().parents[3] / "_data" / "raw.jsonl.gz"
print(f"원본 파일: {path}\n적재와 가공에 30분~1시간 걸릴 수 있습니다. 창을 닫지 마세요.")
raw_transfer.load(str(path))
