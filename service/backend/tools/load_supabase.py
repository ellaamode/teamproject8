"""수집해 둔 원본 파일(_data/raw.jsonl.gz)을 Supabase 로 옮기고 가공까지 한 번에 실행한다.

  python -m tools.load_supabase

연결 주소는 화면에 보이지 않게 입력받는다(파일·기록에 남지 않음). postgres 계정의 Session pooler 주소를 쓴다.
"""
import getpass
import os
import pathlib

url = getpass.getpass("Supabase 연결 주소 전체 붙여넣기 — 마우스 오른쪽 클릭 1번 후 Enter (화면에 안 보입니다) → ")
url = url.strip().strip('"').strip("'")
if not url.startswith("postgresql://"):
    # 비밀번호가 화면에 남지 않도록 내용 대신 '무엇이 왔는지'만 알려 준다
    if "\x16" in url or not url:
        hint = "아무것도 붙여넣어지지 않았습니다. Ctrl+V 대신 창 안에서 마우스 오른쪽 클릭으로 붙여넣으세요."
    elif "@" not in url:
        hint = (f"붙여넣은 글자가 {len(url)}자이고 '@'가 없습니다 — 비밀번호만 붙여넣은 것 같습니다. "
                "'postgresql://postgres.…:비밀번호@…pooler.supabase.com:5432/postgres' 한 줄 전체를 붙여넣으세요.")
    elif url.startswith("postgresql+psycopg://"):
        hint = "앞머리의 '+psycopg'를 지우세요. 이 프로젝트는 'postgresql://' 그대로 씁니다."
    else:
        hint = "주소 맨 앞 'postgresql://' 부분이 빠졌습니다. Supabase > Connect > Session pooler 주소를 처음부터 끝까지 복사하세요."
    raise SystemExit("[다시 해 주세요] " + hint)
if "[" in url or "]" in url:
    raise SystemExit("[다시 해 주세요] 주소에 '[YOUR-PASSWORD]' 같은 대괄호가 남아 있습니다. 대괄호까지 지우고 비밀번호만 넣으세요.")
os.environ["DATABASE_URL"] = url

from tools import raw_transfer  # noqa: E402  (주소를 넣은 뒤에 불러와야 설정에 반영된다)

path = pathlib.Path(__file__).resolve().parents[3] / "_data" / "raw.jsonl.gz"
print(f"원본 파일: {path}\n적재와 가공에 30분~1시간 걸릴 수 있습니다. 창을 닫지 마세요.")
raw_transfer.load(str(path))
