"""수집 윤리 장치: 개인정보 가리기, 403·429 를 받으면 그 사이트 수집을 멈추기 (수업 5주차 워크북 기준)."""
import pytest

from batch import http
from batch.normalize import redact_pii, strip_personal


def test_redact_phone_and_official_names():
    # 실측 문장 형태 (회신 본문 29건에서 관찰)
    s = "금융위원회 보험과 윤상기 사무관(02-2156-9832) 또는 송동식 주무관(02-2156-9836)에게 문의"
    assert redact_pii(s) == "금융위원회 보험과 ○○○ 사무관(연락처 생략) 또는 ○○○ 주무관(연락처 생략)에게 문의"
    assert redact_pii("공정시장과(02-2100-2685)로") == "공정시장과(연락처 생략)로"            # 부서명은 그대로
    assert redact_pii("나이스평가정보 1588-2486, 메일 a.b@fsc.go.kr") == "나이스평가정보 연락처 생략, 메일 이메일 생략"
    # 날짜·고시번호·일반 명사는 건드리지 않는다
    for keep in ("<개정 2013. 12. 3.>", "고시 제2026-29호", "담당 사무관에게", "제2-1조의4"):
        assert redact_pii(keep) == keep


def test_strip_personal_keys():
    row = {"title": "행정지도", "dpNm": "은행과", "regId": "u123", "regNm": "홍길동",
           "기본": {"담당자명": "홍길동", "전화번호": "02-0000-0000", "소관부처명": "금융위원회"}}
    assert strip_personal(row) == {"title": "행정지도", "dpNm": "은행과", "기본": {"소관부처명": "금융위원회"}}


class _Resp:
    def __init__(self, code):
        self.status_code, self.text = code, "{}"

    def raise_for_status(self):
        pass


@pytest.mark.parametrize("code", [403, 429])
def test_403_429_stop_the_whole_host(monkeypatch, code):
    http.BLOCKED.clear()
    calls = []
    client = http.PoliteClient(min_interval=0)
    monkeypatch.setattr(client.s, "request", lambda *a, **k: calls.append(1) or _Resp(code))
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    with pytest.raises(http.SourceBlocked):
        client.request("GET", "https://better.fsc.go.kr/a", expect="json")
    assert len(calls) == 1                                  # 재시도하지 않는다
    other = http.PoliteClient(min_interval=0)               # 다른 수집기도 같은 호스트에는 요청하지 않는다
    monkeypatch.setattr(other.s, "request", lambda *a, **k: calls.append(1) or _Resp(200))
    with pytest.raises(http.SourceBlocked):
        other.request("GET", "https://better.fsc.go.kr/b", expect="json")
    assert len(calls) == 1
    http.BLOCKED.clear()


def test_redact_edge_cases_from_real_data():
    assert redact_pii("보험과 윤상기 사무관(2156-9834)에게") == "보험과 ○○○ 사무관(연락처 생략)에게"
    assert redact_pii("금융위원회 보험과 송동식 주무관입니다.") == "금융위원회 보험과 ○○○ 주무관입니다."
    assert redact_pii("보험과 송동식주무관입니다") == "보험과 ○○○주무관입니다"
    for keep in ("일반사무관리회사에 위탁", "주무관청(중소기업청)의 승인", "사무관리사간 전산시스템", "(2013-2015) 기간"):
        assert redact_pii(keep) == keep
