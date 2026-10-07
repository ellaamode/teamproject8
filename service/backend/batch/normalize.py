"""텍스트 정규화.

원천 HTML은 `제 <span>2</span> 조`처럼 태그와 공백으로 조문 번호가 쪼개져 있다(포털 실측).
정규화하지 않으면 인용 추출이 통째로 실패하므로, 파싱 직후 반드시 이 단계를 거친다.
원문 표시용 본문은 공백만 정리하고, 인용 추출용 사본만 더 강하게 압축한다.
"""
import hashlib
import html
import re

_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"<\s*(br|/p|/div|/li|/tr|/h\d)\b[^>]*>", re.I)
_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)


def html_to_text(fragment: str) -> str:
    """HTML 조각 → 줄바꿈을 살린 평문. 원문 표시용."""
    t = _SCRIPT.sub("", fragment or "")
    t = _BLOCK.sub("\n", t)
    t = html.unescape(_TAG.sub("", t)).replace("\xa0", " ").replace("​", "")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in t.split("\n")]
    return "\n".join(ln for ln in lines if ln)


# 실측: 실제 회신은 반각 낫표 ｢｣(U+FF62/FF63)를 자주 쓴다 → 「」 로 통일하지 않으면 법령명 인식이 통째로 빠진다
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "『": "「", "』": "」", "｢": "「", "｣": "」", "ㆍ": "·"})


def for_citation(text: str) -> str:
    """인용 추출용 정규화. 의미는 같고 표기만 통일한다."""
    t = (text or "").translate(_QUOTES)
    t = re.sub(r"[  -​  　﻿]", " ", t)    # 실측: 특수 공백이 섞여 들어옴
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"「\s+", "「", t)
    t = re.sub(r"\s+」", "」", t)
    # 제 2 조 의 4 / 제 1 항 / 제 3 호  →  제2조의4 / 제1항 / 제3호
    t = re.sub(r"제\s+(\d)", r"제\1", t)
    t = re.sub(r"(\d)\s+(조|항|호|목)(?![가-힣])", r"\1\2", t)
    t = re.sub(r"(\d)\s+(조|항|호)", r"\1\2", t)
    t = re.sub(r"조\s+의\s*(\d)", r"조의\1", t)
    t = re.sub(r"(\d)\s*-\s*(\d+)\s*조", r"\1-\2조", t)
    t = re.sub(r"\(\s+", "(", t)
    t = re.sub(r"\s+\)", ")", t)
    return t


# ---------------------------------------------------------------- 조문 번호
_LABEL = re.compile(r"제?\s*(\d+)(?:-(\d+))?\s*조(?:\s*의\s*(\d+))?")


def article_no(label: str) -> str:
    """'제25조의2' → '25의2', '제4-20조' → '4-20', '제23조' → '23'."""
    m = _LABEL.search(label or "")
    if not m:
        raise ValueError(f"조문 번호를 읽을 수 없음: {label!r}")
    main, hyphen, sub = m.groups()
    no = main + (f"-{hyphen}" if hyphen else "")
    return no + (f"의{sub}" if sub else "")


def article_label(no: str) -> str:
    """'25의2' → '제25조의2', '4-20' → '제4-20조'."""
    base, _, sub = no.partition("의")
    return f"제{base}조" + (f"의{sub}" if sub else "")


def sort_key(no: str) -> tuple:
    """목차 정렬: 4-20 < 4-21 < 5, 25 < 25의2 < 26."""
    base, _, sub = no.partition("의")
    parts = [int(p) for p in base.split("-")]
    return (*parts, *([0] * (2 - len(parts))), int(sub or 0))


# ---------------------------------------------------------------- 개인정보 가리기 (수집 단계에서 적용)
# 실측(회신 6,174건): 본문 29건에 '○○과(02-2156-9431)', '보험과 ○○○ 사무관(02-…)'처럼 연락처·담당 공무원 실명이 있다.
# 회신의 법적 내용과 무관하므로 저장·표시하지 않는다. 부서명(공정시장과 등)은 그대로 둔다.
_PHONE = re.compile(r"(?<![\d.])(?:0\d{1,2}[)-]\s?\d{3,4}-\d{4}|1[568]\d{2}-\d{4})(?!\d)"
                    # 지역번호 없는 '(2156-9834)' — 괄호 안 + 앞자리가 연도(19xx·20xx)가 아닐 때만
                    r"|(?<=\()(?!(?:19|20)\d\d-)\d{3,4}-\d{4}(?=\))")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_RANKS = "사무관|주무관|서기관|연구관|행정관|조사관|검사역|조사역|전문관"
# 직급 뒤에는 조사·괄호만 허용 — '일반사무관리회사', '주무관청' 같은 법률 용어는 건드리지 않는다
_NAME_RANK = re.compile(rf"(?<![가-힣])([가-힣]{{2,4}})(?=\s?(?:{_RANKS})(?:입니다|에게|께|님|이|은|는|과|와|[\s(),.]|$))")
_NOT_NAME = {"담당", "소관", "해당", "관련", "주무", "행정", "선임", "수석", "책임", "전문", "일반", "담당자"}
# 원천 응답(JSON)에서 통째로 빼는 칸: 포털 행정지도 목록의 등록자 ID·이름, 법제처 행정규칙의 담당자·전화번호
PERSONAL_KEYS = {"regId", "regNm", "담당자명", "담당자", "전화번호", "부서연락처", "담당자연락처"}


def redact_pii(text: str | None) -> str | None:
    """전화번호 → '연락처 생략', 이메일 → '이메일 생략', '홍길동 사무관' → '○○○ 사무관' (예: '보험과(연락처 생략)')"""
    if not text:
        return text
    text = _PHONE.sub("연락처 생략", text)
    text = _EMAIL.sub("이메일 생략", text)
    return _NAME_RANK.sub(lambda m: m.group(1) if m.group(1) in _NOT_NAME else "○○○", text)


def strip_personal(obj):
    """JSON 객체에서 PERSONAL_KEYS 칸을 재귀적으로 지운다."""
    if isinstance(obj, dict):
        return {k: strip_personal(v) for k, v in obj.items() if k not in PERSONAL_KEYS}
    if isinstance(obj, list):
        return [strip_personal(v) for v in obj]
    return obj


def substance(body: str | None) -> str:
    """조문의 '내용'만 남긴 비교용 문자열: 공백·줄바꿈, <개정 …>·[본조신설 …] 같은 연혁 표기, 따옴표 모양을 무시한다.
    출처(웹 수집 ↔ Open API)마다 표기가 달라 생기는 가짜 '개정'을 막는다."""
    s = re.sub(r"<[^>]*>|\[[^\]]*\]", "", body or "")
    return re.sub(r"\s+", "", s).translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"}))


def content_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def despace(s: str) -> str:
    return re.sub(r"\s+", "", s or "")
