"""금융규제·법령해석포털 (better.fsc.go.kr) 수집기.

실측한 구조 (2026-10 기준)
  회신사례 목록  POST /fsc_new/replyCase/selectReplyCaseTotalReplyList.do   DataTables JSON
                 {recordsTotal: 12088, data:[{dataIdx, pastreqType, title, replyRegDate}]}
  회신사례 상세  POST /fsc_new/replyCase/{LawreqDetail|OpinionDetail|PastReqDetail}.do  HTML
                 표(th/td): 처리구분·소관부서·회신일·첨부파일·질의요지·회답·이유  ← '관련 법령' 칸은 없음
  행정지도 목록  POST /fsc_new/status/adminMap/select{Opertn|Prvntc}List.do     JSON
                 {postNo, title, dpNm(소관부서), addFild1(관리번호), eventStartDate~eventEndDate(존속·예고기간)}

이용 조건: 포털 저작권정책상 원문 변경 금지·출처 명시 의무 → 원문은 고치지 않고 저장하며 화면에 항상 출처 링크를 단다.
공식 API가 아니므로 하루 1회, 새 글만 받는다(증분). 첫 적재는 BACKFILL_LIMIT 으로 나눠서 진행한다.
"""
from __future__ import annotations

import json
import re

from .. import store
from ..config import SETTINGS
from ..http import PoliteClient
from ..normalize import html_to_text

BASE = "https://better.fsc.go.kr/fsc_new"
LIST_REFERER = f"{BASE}/replyCase/TotalReplyList.do?stNo=11&muNo=117&muGpNo=75"

# pastreqType → (상세 경로, 번호 파라미터, documents.kind, 원천 키 접두어)
REPLY_KINDS = {
    "법령해석":             ("replyCase/LawreqDetail.do",   "lawreqIdx",  "법령해석",  "fsc.lawreq"),
    "비조치의견서":         ("replyCase/OpinionDetail.do",  "opinionIdx", "비조치의견", "fsc.opinion"),
    "법령해석(2014이전)":   ("replyCase/PastReqDetail.do",  "pastreqIdx", "법령해석",  "fsc.pastreq"),
    "비조치의견서(2014이전)": ("replyCase/PastReqDetail.do", "pastreqIdx", "비조치의견", "fsc.pastreq"),
}
GUIDANCE_LISTS = {"시행": ("status/adminMap/selectOpertnList.do", 145, "OpertnDetail.do"),
                  "예고": ("status/adminMap/selectPrvntcList.do", 144, "PrvntcDetail.do")}


def detail_url(path: str, param: str, idx) -> str:
    """사용자에게 보여줄 원문 링크. 포털 상세는 POST 전용이라 목록 화면 + 번호로 안내한다."""
    return f"{BASE}/{path}?stNo=11&muNo=117&{param}={idx}&actCd=R"


# ---------------------------------------------------------------- fetch
def fetch_replies(conn, client: PoliteClient | None = None, page_size: int = 50) -> dict:
    """두 단계로 받는다.
    1) 머리: 최신순 목록을 넘기다 한 페이지가 전부 이미 받은 글이면 멈춤 → 매일 새 글
    2) 꼬리: 첫 적재가 덜 끝났으면 이미 받은 개수 지점부터 이어서 BACKFILL_LIMIT 건 더 받음
       (목록은 최신순이라, 지금까지 받은 N건 = 앞쪽 N건. 새 글로 밀린 만큼은 한 페이지 겹쳐 읽어 메움)"""
    client = client or PoliteClient()
    stats = {"listed": 0, "new": 0, "skipped": 0, "errors": 0, "backfill_from": None}
    budget = SETTINGS.backfill_limit or 10**9

    def page(start: int) -> list[dict]:
        r = client.request("POST", f"{BASE}/replyCase/selectReplyCaseTotalReplyList.do", expect="json",
                           referer=LIST_REFERER, data={"draw": 1, "start": start, "length": page_size})
        stats["total"] = max(stats.get("total") or 0, r.json().get("recordsTotal") or 0)   # 빈 마지막 페이지가 0 으로 덮지 않게
        return r.json().get("data", [])

    def take(rows) -> int:
        fresh = 0
        for row in rows:
            if stats["new"] >= budget:                     # 하루 할당량을 넘기지 않는다
                break
            stats["listed"] += 1
            kind = REPLY_KINDS.get(row["pastreqType"])
            if not kind:                                   # 현장건의 과제 등 범위 밖
                stats["skipped"] += 1
                continue
            path, param, _, src = kind
            key = str(row["dataIdx"])
            if conn.execute("SELECT 1 FROM raw_payloads WHERE source=%s AND source_key=%s LIMIT 1",
                            (src, key)).fetchone():
                continue
            fresh += 1
            try:
                d = client.request("POST", f"{BASE}/{path}", expect="html:질의요지", referer=LIST_REFERER,
                                   data={"muNo": 117, "stNo": 11, param: row["dataIdx"], "actCd": "R"})
                payload = json.dumps({"list": row, "html": content_tables(d.text)}, ensure_ascii=False)
                if store.save_raw(conn, src, key, d.status_code, payload):
                    stats["new"] += 1
                conn.commit()
            except Exception:
                stats["errors"] += 1
        return fresh

    # 1) 머리
    start = 0
    while stats["new"] < budget:
        rows = page(start)
        if not rows or take(rows) == 0:
            break
        start += page_size
    # 2) 꼬리 (첫 적재 이어받기)
    # 범위 밖 유형(현장건의)은 저장하지 않으므로 '개수 비교'로는 끝을 알 수 없다 → 끝까지 간 기록을 남겨 둔다
    done = conn.execute("""SELECT 1 FROM pipeline_runs WHERE stage='fetch' AND source='fsc.reply'
                           AND status IN ('ok','partial') AND (stats->>'backfill_done')::boolean LIMIT 1""").fetchone()
    stats["backfill_done"] = bool(done)
    if not done:
        known = conn.execute("""SELECT count(DISTINCT source_key) AS n FROM raw_payloads
                                WHERE source IN ('fsc.lawreq','fsc.opinion','fsc.pastreq')""").fetchone()["n"]
        start = max(0, known - page_size)
        stats["backfill_from"] = start
        while stats["new"] < budget:
            rows = page(start)
            if not rows:
                stats["backfill_done"] = True              # 목록 끝까지 도달 → 이후로는 머리만
                break
            take(rows)
            start += page_size
    return stats


def fetch_guidance(conn, client: PoliteClient | None = None) -> dict:
    client = client or PoliteClient()
    stats = {"listed": 0, "new": 0, "errors": 0}
    for stage, (path, mu, _) in GUIDANCE_LISTS.items():
        r = client.request("POST", f"{BASE}/{path}?actCd=R", expect="json",
                           data={"draw": 1, "start": 0, "length": 200, "muNo": mu})
        for row in r.json().get("data", []):
            stats["listed"] += 1
            row["_stage"] = stage
            payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if store.save_raw(conn, "fsc.guidance", f"{stage}:{row['postNo']}", 200, payload):
                stats["new"] += 1
    conn.commit()
    return stats


def content_tables(page: str) -> str:
    """상세 페이지(약 40KB, 대부분 메뉴·레이아웃)에서 회신 내용이 든 표만 남긴다(보통 수 KB).
    12,000건 전체 페이지를 그대로 두면 약 480MB로 Supabase 무료 한도(500MB)를 넘는다."""
    tables = re.findall(r"<table\b.*?</table>", page, re.S | re.I)
    keep = [t for t in tables if any(k in t for k in ("질의요지", "처리구분", "소관부서", "회신일"))]
    return "\n".join(keep) or page


# ---------------------------------------------------------------- parse
_CELL = r"<th[^>]*>\s*{label}\s*</th>\s*<td[^>]*>(.*?)</td>"


def _cell(html: str, label: str) -> str:
    m = re.search(_CELL.format(label=label), html, re.S)
    return html_to_text(m.group(1)) if m else ""


def normalize_dept(raw: str | None) -> str | None:
    """'금융위원회,자본시장정책관,자산운용과,금융감독원' → '자산운용과' (가장 구체적인 부서).
    실측: 소관부서 칸에 기관·국·과가 쉼표로 이어 붙어 있는 경우가 많다."""
    if not raw:
        return None
    parts = [p.strip() for p in re.split(r"[,/·]", raw) if p.strip()]
    specific = [p for p in parts if p not in ("금융위원회", "금융감독원")]
    if not specific:
        return parts[0] if parts else None
    for suffix in ("과", "팀", "실", "국", "관", "단"):
        cand = [p for p in specific if p.endswith(suffix)]
        if cand:
            return cand[-1]
    return specific[-1]


def parse_reply(source: str, key: str, payload: str) -> dict:
    p = json.loads(payload)
    row, h = p["list"], p["html"]
    path, param, kind, _ = REPLY_KINDS[row["pastreqType"]]
    # 회신일 → 목록 등록일 → 첨부파일명 앞의 YYMMDD(예: 230106_회신.hwp) 순. 끝내 없으면 날짜 미상(None)
    date_ = _cell(h, "회신일") or row.get("replyRegDate")
    if not date_:
        m = re.match(r"(\d{2})(\d{2})(\d{2})_", _cell(h, "첨부파일"))
        date_ = f"20{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None
    return {
        "id": f"{source}:{key}", "kind": kind, "org": "금융위원회",
        "dept": normalize_dept(_cell(h, "소관부서")), "title": row["title"].strip(),
        "question": _cell(h, "질의요지") or None, "answer": _cell(h, "회답") or None,
        "reason": _cell(h, "이유") or None, "body": None,
        "published_on": date_[:10] if date_ else None, "valid_from": None, "valid_to": None, "stage": None,
        "source_url": detail_url(path, param, row["dataIdx"]), "source_name": "금융규제·법령해석포털",
    }


def parse_guidance(source: str, key: str, payload: str) -> dict:
    row = json.loads(payload)
    stage = row["_stage"]
    _, mu, detail = GUIDANCE_LISTS[stage]
    return {
        "id": f"fsc.guidance:{row['postNo']}", "kind": "행정지도", "org": row.get("rootDpNm") or "금융위원회",
        "dept": row.get("dpNm"), "title": row["title"].strip(), "question": None, "answer": None,
        "reason": None, "body": f"관리번호 {row.get('addFild1') or '-'}",
        "published_on": (row.get("regDate") or row.get("eventStartDate") or "").replace(".", "-")[:10],
        "valid_from": row.get("eventStartDate") or None, "valid_to": row.get("eventEndDate") or None,
        "stage": stage,
        "source_url": f"{BASE}/status/adminMap/{detail}?stNo=11&muNo={mu}&postNo={row['postNo']}&actCd=R",
        "source_name": "금융규제·법령해석포털",
    }


PARSERS = {"fsc.lawreq": parse_reply, "fsc.opinion": parse_reply, "fsc.pastreq": parse_reply,
           "fsc.guidance": parse_guidance}
