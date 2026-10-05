"""법제처 Open API 실제 응답 견본을 받아 _data/lawgo_samples/ 에 저장한다 (수집 코드를 실제 응답에 맞추기 위한 1회용).

  python -m tools.lawgo_probe

OC 값은 화면에 보이지 않게 입력받고, 저장 파일과 화면 출력에서는 지운다(파일에 남지 않음).
_data/ 는 .gitignore 대상이라 GitHub 에 올라가지 않는다.
"""
import getpass
import json
import pathlib
import re
import time

import requests

BASE = "https://www.law.go.kr/DRF"
OUT = pathlib.Path(__file__).resolve().parents[3] / "_data" / "lawgo_samples"

oc = getpass.getpass("법제처 OC 값 입력 (화면에 안 보입니다) → ").strip()
if not oc:
    raise SystemExit("OC 값이 비어 있습니다.")
OUT.mkdir(parents=True, exist_ok=True)

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; FinRegLookup/1.0; KAIST class project)",
                  "Referer": "https://www.law.go.kr/"})


def hide(text: str) -> str:
    return text.replace(oc, "<OC>")


def call(name: str, path: str, **params) -> str:
    """호출 → 응답 원문 저장. 반환값은 응답 본문(OC 제거)."""
    time.sleep(1.0)
    try:
        r = s.get(f"{BASE}/{path}", params={"OC": oc, "type": "JSON", **params}, timeout=60)
        body, status = hide(r.text), r.status_code
    except Exception as e:                                   # 네트워크 오류도 기록
        body, status = hide(f"[요청 실패] {type(e).__name__}: {e}"), 0
    meta = {"name": name, "path": path, "params": params, "status": status}
    (OUT / f"{name}.json").write_text(json.dumps(meta, ensure_ascii=False) + "\n" + body, encoding="utf-8")
    ok = status == 200 and body.lstrip().startswith(("{", "["))
    print(f"{'OK ' if ok else '확인'} {name:<22} HTTP {status}  {len(body):>9,}자  {body[:80]!r}")
    return body


def first(body: str, field: str) -> str | None:
    m = re.search(rf'"{field}"\s*:\s*"?(\d+)', body)
    return m.group(1) if m else None


# 1) 법률: 검색 → 본문 → 3단비교(위임조문·인용조문)
b = call("01_law_search", "lawSearch.do", target="law", query="전자금융거래법", display=5)
mst = first(b, "법령일련번호")
if mst:
    call("02_law_body", "lawService.do", target="law", MST=mst)
    call("03_thdcmp_delegate", "lawService.do", target="thdCmp", MST=mst, knd=2)
    call("04_thdcmp_cite", "lawService.do", target="thdCmp", MST=mst, knd=1)
# 2) 시행예정 법령 검색 (자본시장법은 시행예정 조문이 있음)
call("05_eflaw_pending", "lawSearch.do", target="eflaw", query="자본시장과 금융투자업에 관한 법률", nw=2, display=5)
# 3) 행정규칙: 감독규정 검색 → 본문, 고시(외국환거래규정)·시행세칙 검색
b = call("06_admrul_search", "lawSearch.do", target="admrul", query="전자금융감독규정", display=5)
seq = first(b, "행정규칙일련번호")
if seq:
    call("07_admrul_body", "lawService.do", target="admrul", ID=seq)
call("08_admrul_notice", "lawSearch.do", target="admrul", query="외국환거래규정", display=5)
call("09_admrul_detail", "lawSearch.do", target="admrul", query="전자금융감독규정시행세칙", display=5)

# 4) 시행일 기준 본문 확인 (2차): 같은 MST 라도 efYd 를 주면 그날 시행 중인 본문만 오는지
def rows(body: str) -> list[dict]:
    try:
        node = json.loads(body).get("LawSearch", {}).get("law", [])
    except Exception:
        return []
    return node if isinstance(node, list) else [node]


if mst:
    cur = next((r for r in rows(call("10_law_eff_search", "lawSearch.do", target="law", query="전자금융거래법"))
                if r.get("법령명한글") == "전자금융거래법"), {})
    efyd = cur.get("시행일자", "")
    call("11_law_body_efyd", "lawService.do", target="law", MST=mst, efYd=efyd)
    call("12_eflaw_body_efyd", "lawService.do", target="eflaw", MST=mst, efYd=efyd)
    pend = [r for r in rows(call("13_eflaw_pending_efta", "lawSearch.do", target="eflaw", query="전자금융거래법",
                                 nw=2, display=10)) if r.get("법령명한글") == "전자금융거래법"]
    if pend:
        call("14_eflaw_pending_body", "lawService.do", target="eflaw", MST=pend[0]["법령일련번호"],
             efYd=pend[0]["시행일자"])

print(f"\n저장 위치: {OUT}\n끝났습니다. 채팅에 '견본 받음'이라고 알려 주세요. (OC 값은 파일에 남지 않았습니다)")
