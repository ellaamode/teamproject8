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
