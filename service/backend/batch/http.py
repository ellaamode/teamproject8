"""원천 서버에 예의 바르게 요청하는 공통 HTTP 클라이언트.

실측·조사로 확인한 함정을 한곳에서 처리한다.
  - 법제처 DRF는 Referer/User-Agent가 없으면 OC 키가 맞아도 '사용자 정보 검증 실패'로 거부한다.
  - 클라우드 IP에서는 데이터 대신 JS 리다이렉트(안티봇) 페이지가, 점검 중에는 200 + 빈 본문/HTML이 온다.
    → 상태코드만 믿지 않고 '기대한 형식인지'를 검사해, 아니면 재시도 후 실패로 기록한다.
  - 같은 호스트에는 최소 간격(기본 1.5초)을 지킨다.
  - 원천이 403(차단)·429(요청 과다)로 답하면 재시도하지 않고 그 사이트 수집을 이번 실행에서 즉시 멈춘다
    (수업 5주차 크롤링 윤리: "403·429가 오면 수집을 멈추고 원인을 확인한다"). 실행 기록에 실패로 남는다.
"""
from __future__ import annotations

import json
import time
from urllib.parse import urlparse

import requests

from .config import SETTINGS


class FetchError(RuntimeError):
    pass


class SourceBlocked(FetchError):
    """원천이 403·429로 거부 → 이번 실행에서 그 호스트로는 더 요청하지 않는다."""


BLOCKED: dict[str, str] = {}      # 호스트 → 거부 사유 (실행 단위, 모든 수집기가 공유)


class PoliteClient:
    def __init__(self, min_interval: float | None = None, retries: int = 3):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": f"Mozilla/5.0 (compatible; FinRegLookup/1.0; KAIST class project; {SETTINGS.contact})",
            "Accept-Language": "ko-KR,ko;q=0.9",
        })
        self.min_interval = SETTINGS.min_interval if min_interval is None else min_interval
        self.retries = retries
        self._last: dict[str, float] = {}

    def _wait(self, host: str):
        gap = time.monotonic() - self._last.get(host, 0)
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last[host] = time.monotonic()

    def request(self, method: str, url: str, *, expect: str, referer: str | None = None, **kw) -> requests.Response:
        """expect: 'json' | 'xml' | 'html:<반드시 포함될 문자열>'"""
        host = urlparse(url).netloc
        if host in BLOCKED:
            raise SourceBlocked(f"{host} 수집 중단 상태 ({BLOCKED[host]}) — 요청하지 않음")
        headers = kw.pop("headers", {})
        headers.setdefault("Referer", referer or f"https://{host}/")
        last_err = None
        for attempt in range(1, self.retries + 1):
            self._wait(host)
            try:
                r = self.s.request(method, url, headers=headers, timeout=30, **kw)
                if r.status_code in (403, 429):
                    BLOCKED[host] = f"HTTP {r.status_code}"
                    raise SourceBlocked(f"{host} 이(가) HTTP {r.status_code} 로 거부 — 수집 중단, 원인 확인 필요")
                if r.status_code >= 500:
                    raise FetchError(f"HTTP {r.status_code}")
                r.raise_for_status()
                self._check(r, expect)
                return r
            except SourceBlocked:
                raise                             # 재시도하지 않는다
            except (requests.RequestException, FetchError) as e:
                last_err = e
                time.sleep(2 ** attempt)          # 2, 4, 8초 지수 백오프
        raise FetchError(f"{method} {url} 실패 ({self.retries}회): {last_err}")

    @staticmethod
    def _check(r: requests.Response, expect: str):
        body = r.text.strip()
        if not body:
            raise FetchError("빈 본문 (원천 점검 중일 가능성)")
        if "location.assign" in body[:2000] and "<html" in body[:200].lower():
            raise FetchError("안티봇 리다이렉트 페이지 (등록 IP·헤더 확인 필요)")
        if expect == "json":
            try:
                json.loads(body)
            except ValueError as e:
                raise FetchError(f"JSON 아님: {body[:80]!r}") from e
        elif expect == "xml":
            if not body.startswith("<?xml") and not body.startswith("<"):
                raise FetchError("XML 아님")
            if "사용자 정보 검증에 실패" in body or "검증에 실패" in body:
                raise FetchError("법제처 인증 실패: OC 키·Referer·등록 IP 확인")
        elif expect.startswith("html:"):
            marker = expect[5:]
            if marker not in body:
                raise FetchError(f"기대한 HTML 구조('{marker}')가 없음 — 원천 화면이 바뀌었을 수 있음")
