"""국가법령정보센터 웹페이지 수집기 (Open API 키 발급 전 대체 경로 · 크롤링).

법제처 Open API(OC 키)가 정식 경로이고, 이 모듈은 키가 없을 때 같은 법령 본문을 웹페이지에서 받는다.
  - law.go.kr/robots.txt 는 전체 허용(Allow: /)
  - 법령·고시 조문은 저작권법 제7조상 보호받지 않는 저작물
  - 법령 1건당 요청 2회(위치 확인 + 본문), 1.5초 간격 → 대상 32건 전체 약 2분

실측한 구조 (2026-10)
  /법령/{법령명}       → iframe lsInfoP.do?lsiSeq={법령일련번호}&efYd={시행일}
  /행정규칙/{규칙명}   → iframe admRulInfoP.do?admRulSeq={행정규칙일련번호}
  본문: GET lsInfoR.do?lsiSeq=…  /  POST admRulLsInfoR.do (admRulSeq)  → HTML, 현행·시행예정 조문 함께
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote

from .. import store
from ..config import TARGET_LAWS
from ..http import PoliteClient, SourceBlocked
from ..lawtext import lines_from_payload, split_articles

BASE = "https://www.law.go.kr"


def _locate(client, spec) -> tuple[str, str | None]:
    kind_path = "행정규칙" if spec.source == "lawgo.admrul" else "법령"
    r = client.request("GET", f"{BASE}/{quote(kind_path)}/{quote(spec.name.replace(' ', ''))}", expect="html:<",
                       referer=BASE + "/")
    if spec.source == "lawgo.admrul":
        m = re.search(r"admRulSeq=(\d+)", r.text)
        return (m.group(1), None) if m else (None, None)
    m = re.search(r"lsiSeq=(\d+)", r.text)
    ef = re.search(r"efYd=(\d{8})", r.text)
    return (m.group(1) if m else None), (ef.group(1) if ef else None)


def fetch_laws_web(conn, client: PoliteClient | None = None, slugs: list[str] | None = None) -> dict:
    client = client or PoliteClient()
    stats = {"fetched": 0, "unchanged": 0, "not_found": [], "errors": 0}
    for spec in TARGET_LAWS:
        if slugs and spec.slug not in slugs:
            continue
        try:
            seq, efyd = _locate(client, spec)
            if not seq:
                stats["not_found"].append(spec.name)
                continue
            key = f"{spec.slug}:{seq}"
            if conn.execute("SELECT 1 FROM raw_payloads WHERE source=%s AND source_key=%s LIMIT 1",
                            (spec.source, key)).fetchone():
                stats["unchanged"] += 1
                continue
            if spec.source == "lawgo.admrul":
                page = f"{BASE}/LSW/admRulInfoP.do?admRulSeq={seq}"
                r = client.request("POST", f"{BASE}/LSW/admRulLsInfoR.do", expect="html:조(", referer=page,
                                   data={"admRulSeq": seq, "chrClsCd": "010201"})
            else:
                page = f"{BASE}/LSW/lsInfoP.do?lsiSeq={seq}"
                r = client.request("GET", f"{BASE}/LSW/lsInfoR.do", expect="html:조(", referer=page,
                                   params={"lsiSeq": seq, "efYd": efyd or "", "efYn": "Y", "chrClsCd": "010202",
                                           "nwJoYnInfo": "Y", "ancYnChk": "0", "netPrivateYn": "N"})
            html = r.text
            eff = re.search(r"\[시행\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\]", html)
            effective = f"{eff.group(1)}{int(eff.group(2)):02d}{int(eff.group(3)):02d}" if eff else efyd
            # 원문 HTML 대신 조문 줄만 저장 (용량 절약). 시행예정 꼬리표는 보존
            arts = split_articles(lines_from_payload(html))
            lines, ch = [], None
            for a in arts:
                if a.chapter and a.chapter != ch:
                    lines.append(a.chapter)
                    ch = a.chapter
                lines.extend(a.body.split("\n"))
                if a.pending_from:
                    lines.append(f"[시행일: {a.pending_from.year}. {a.pending_from.month}. {a.pending_from.day}.] {a.label}")
            payload = {"meta": {"slug": spec.slug, "seq": seq, "version": "현행", "effective": effective,
                                "promulgated": None, "source_url": page, "via": "web"},
                       "body": {"lines": lines}}
            store.save_raw(conn, spec.source, key, r.status_code, json.dumps(payload, ensure_ascii=False))
            conn.commit()
            stats["fetched"] += 1
        except SourceBlocked:
            conn.rollback()
            raise                                                   # 403·429: 수집을 멈춘다
        except Exception as e:
            conn.rollback()
            stats["errors"] += 1
            stats.setdefault("error_samples", []).append(f"{spec.name}: {str(e)[:120]}")
    return stats
