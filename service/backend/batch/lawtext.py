"""법령·행정규칙 본문 → 조문 목록.

법제처 응답(JSON/XML)이든 웹페이지 HTML이든 '평문 줄 목록'으로 바꾼 뒤 같은 규칙으로 자른다.
응답 필드 이름이 바뀌어도 본문 표기 규칙(제N조(제목) …)은 안 바뀌므로 이쪽이 더 튼튼하다.

실측(국가법령정보센터, 전자금융거래법 2026-10-02 시행본): 한 문서 안에 현행 조문과
'[시행일: 2026. 12. 17.]' 꼬리표가 붙은 시행예정 조문이 함께 들어 있다 → 버전으로 분리 저장.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date

from .normalize import article_no, html_to_text, sort_key

ART = re.compile(r"^(제\d+(?:-\d+)?조(?:의\d+)?)\s*\(([^)]*)\)\s*(.*)$")
CHAPTER = re.compile(r"^제\d+(?:-\d+)?장\s+\S")
SECTION = re.compile(r"^제\d+(?:-\d+)?(?:편|절|관)\s+\S")
PENDING = re.compile(r"\[시행일\s*:\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\][^\n]*$")
ADDENDA = re.compile(r"^부\s*칙")


@dataclass
class ArticleText:
    no: str
    label: str
    title: str
    chapter: str
    body: str
    pending_from: date | None      # 시행예정 버전이면 시행일


def lines_from_json(obj) -> list[str]:
    """JSON 트리의 문자열 값을 문서 순서대로 평탄화한다(조문내용·항내용·호내용·목내용 등)."""
    out: list[str] = []

    def walk(x):
        if isinstance(x, str):
            out.extend(s for s in (ln.strip() for ln in x.split("\n")) if s)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, dict):
            for k, v in x.items():
                if "부칙" not in str(k):          # 부칙은 같은 조문 번호(제1조…)를 다시 써서 본문을 덮어쓴다
                    walk(v)
    walk(obj)
    return out


def _aslist(x) -> list:
    return x if isinstance(x, list) else [x] if x else []


def _texts(x) -> list[str]:
    """문자열 또는 (중첩) 문자열 목록 → 비어 있지 않은 줄 목록"""
    if isinstance(x, str):
        x = re.sub(r"<img[^>]*>", "", x)          # 수식 이미지 태그 (외국환거래법 시행령 제21조의4 등) — 본문 아님
        return [s for s in (ln.strip() for ln in x.split("\n")) if s]
    return [s for v in _aslist(x) for s in _texts(v)]


def lines_from_law_json(law: dict, today: date | None = None) -> list[str]:
    """법제처 lawService(target=law) 응답의 '법령' 객체 → 웹페이지 수집과 같은 줄 형식.

    실측(2026-10, 전자금융거래법): 조문.조문단위[] 에 조문여부='전문'(장·절 제목)과 '조문'이 섞여 있고,
    본문은 조문내용(첫 줄) → 항[].항내용 → 호[].호내용 → 목[].목내용 으로 나뉜다. 항이 하나뿐이면 항이 dict.
    조문시행일자가 오늘 이후인 조문은 '[시행일: …]' 꼬리표를 붙여 시행예정 버전으로 넘긴다."""
    today = today or date.today()
    out: list[str] = []
    for u in _aslist((law.get("조문") or {}).get("조문단위")):
        head = _texts(u.get("조문내용"))
        if u.get("조문여부") == "전문":                      # 장·절 제목
            out.extend(head)
            continue
        lines = list(head)
        for h in _aslist(u.get("항")):
            p = [_circled(x) for x in _texts(h.get("항내용"))]
            if p and len(lines) == 1 and ART.match(lines[0]) and not ART.match(lines[0]).group(3):
                lines[0] = f"{lines[0]} {p.pop(0)}"           # '제18조(제목)' + 첫 항 → 웹 표기처럼 한 줄
            lines += p
            for ho in _aslist(h.get("호")):
                lines += _texts(ho.get("호내용"))
                for mok in _aslist(ho.get("목")):
                    lines += _texts(mok.get("목내용"))
        out.extend(lines)
        eff = str(u.get("조문시행일자") or "")
        if len(eff) == 8 and eff.isdigit() and date(int(eff[:4]), int(eff[4:6]), int(eff[6:])) > today and head:
            label = ART.match(re.sub(r"\s+", " ", head[0]))
            out.append(f"[시행일: {int(eff[:4])}. {int(eff[4:6])}. {int(eff[6:])}.] {label.group(1) if label else ''}")
    return out


def _circled(line: str) -> str:
    """항 번호 16 이상은 API 가 '<16>'으로 준다 → 웹 표기·인용 규칙과 같게 ⑯ (21~35 는 ㉑~㉟)"""
    m = re.match(r"<(\d{1,2})>\s*", line)
    if not m or not 1 <= int(m.group(1)) <= 35:
        return line
    n = int(m.group(1))
    return (chr(0x2460 + n - 1) if n <= 20 else chr(0x3251 + n - 21)) + " " + line[m.end():]


_MOK = "가나다라마바사아자차카타파하"
_ITEM = re.compile(r"(\d{1,2})((?:의\d+)?)\.\s+|([가-하])\.\s+")


def split_items(line: str) -> list[str]:
    """행정규칙 응답은 항·호·목이 한 문자열에 붙어 온다('…다음과 같다.1. "전산실"이라…2. …').
    ①② 앞, 그리고 번호가 '이어지는' 호(1.→2.→2의2.→3.)·목(가.→나.) 앞에서만 줄을 나눈다.
    날짜(2013. 12. 3.)·조문 인용(제2조제1호)은 번호가 이어지지 않거나 앞 글자로 걸러진다."""
    out = []
    line = re.sub(r"<(1[6-9]|2\d|3[0-5])>(?=\s)", lambda m: _circled(m.group(0)).strip(), line)   # <16> → ⑯
    for para in re.sub(r"(?<=\S)\s*(?<!제)([①-⑳㉑-㉟])", r"\n\1", line).split("\n"):
        cuts, last_no, last_mok = [], 0, None
        for m in _ITEM.finditer(para):
            i = m.start()
            before = para[max(0, i - 5):i]
            if m.group(1):
                n = int(m.group(1))
                if i and (para[i - 1].isdigit() or para[i - 1] == "제" or re.search(r"\d\.\s*$", before)):
                    continue                                   # 2013. 12. / 제1. / 12. (날짜·소수)
                if n == last_no + 1 or (m.group(2) and n == last_no and last_no):
                    if i:
                        cuts.append(i)
                    last_no, last_mok = n, None
            elif last_no and m.group(3) == _MOK[0 if last_mok is None else min(_MOK.index(last_mok) + 1, 13)]:
                if i and para[i - 1] not in " (":              # '가.'가 문장 중간 단어가 아닌 경우만
                    cuts.append(i)
                last_mok = m.group(3)
        prev = 0
        for c in cuts + [len(para)]:
            if para[prev:c].strip():
                out.append(para[prev:c].strip())
            prev = c
    return out


_HEAD = re.compile(r"제(\d+)(?:-\d+)?(편|장|절|관)\s|제(\d+(?:-\d+)?)조(의\d+)? ?\([^()]{1,60}\)(?=\s|[①-⑳<\[]|삭제|제\d)")
_NEXT_HEAD = re.compile(r"(?:<[^>]{0,40}>|[^.\n<]){1,120}?제\d+(?:-\d+)?(?:조(?:의\d+)? ?\(|편\s|장\s|절\s|관\s)")
_LEVELS = ("편", "장", "절", "관")


def split_headings(text: str) -> list[str]:
    """조문·장 제목이 구분자 없이 이어 붙은 문자열을 자른다 (실측: 금융투자업규정 등 '제1-1조' 체계 행정규칙은
    본문 전체가 문자열 하나 — '…정함을 목적으로 한다.<개정 2013. 9. 17.>제1-2조(용어의 정의) 이 규정에서…').
    인용과 구별: 조문은 '제1-3조(제목)' 바로 뒤가 공백·①·<개정·삭제이고(인용은 '(제목)에 따른') 번호가 앞 조문보다 커야 한다.
    편·장·절은 번호가 하나씩 늘고, 바로 앞이 문장 끝(. > ] ))·'삭제'·윗단계 제목일 때만 자른다."""
    cuts, last_art, last_lv, after_heading = [], (0,), dict.fromkeys(_LEVELS, 0), False
    for m in _HEAD.finditer(text):
        i = m.start()
        if m.group(2):                                         # 편·장·절·관
            n, lv = int(m.group(1)), m.group(2)
            prev = text[:i].rstrip()
            boundary = i == 0 or after_heading or prev.endswith((".", ">", "]", ")", "삭제"))
            # 제목 바로 뒤에 다음 조문·하위 단계 제목이 오면(마침표 없이) 인용이 아니라 제목이다
            if (n == last_lv[lv] + 1 and boundary) or _NEXT_HEAD.match(text, m.end()):
                if i:
                    cuts.append(i)
                last_lv[lv] = n
                for low in _LEVELS[_LEVELS.index(lv) + 1:]:
                    last_lv[low] = 0
                after_heading = True
            continue
        sk = sort_key(article_no(f"제{m.group(3)}조{m.group(4) or ''}"))
        if sk > last_art:
            if i:
                cuts.append(i)
            last_art = sk
        after_heading = False
    return [text[a:b].strip() for a, b in zip([0] + cuts, cuts + [len(text)]) if text[a:b].strip()]


def lines_from_admrul_json(svc: dict) -> list[str]:
    """법제처 lawService(target=admrul) 응답의 'AdmRulService' 객체 → 줄 형식.
    실측 두 형태: ① 조문내용[] 에 조문(또는 장 제목) 하나가 문자열 하나 (전자금융감독규정 등)
                ② 조문내용 이 본문 전체 문자열 하나 ('제1-1조' 체계: 금융투자업규정·외국환거래규정·각 시행세칙)
    별표·부칙·첨부파일은 본문이 아니므로 제외."""
    out: list[str] = []
    body = svc.get("조문내용")
    chunks = split_headings(body) if isinstance(body, str) else _texts(body)   # ② 형태만 잘라야 한다(①은 이미 조문별)
    for s in chunks:
        parts = split_items(s)
        head = ART.match(parts[0]) if parts else None
        if head and not head.group(3) and len(parts) > 1:           # '제5조(제목)' + '① …' → 한 줄 (웹 표기와 같게)
            parts[:2] = [f"{parts[0]} {parts[1]}"]
        out.extend(parts)
    return out


def lines_from_payload(payload: str) -> list[str]:
    s = payload.lstrip()
    if s.startswith("{") or s.startswith("["):
        obj = json.loads(s)
        if isinstance(obj, dict) and isinstance(obj.get("법령"), dict):          # Open API: 법령 본문
            return lines_from_law_json(obj["법령"])
        if isinstance(obj, dict) and isinstance(obj.get("AdmRulService"), dict):  # Open API: 행정규칙 본문
            return lines_from_admrul_json(obj["AdmRulService"])
        return lines_from_json(obj)                                              # 웹 수집분({"lines": [...]})
    return [ln for ln in html_to_text(s).split("\n") if ln.strip()]


def split_articles(lines: list[str]) -> list[ArticleText]:
    arts: list[dict] = []
    chapter, cur, started, high = "", None, False, (0,)
    for ln in lines:
        ln = re.sub(r"\s+", " ", ln).strip()
        if started and ADDENDA.match(ln):
            break                                      # 부칙 이후는 본문이 아님
        if 'src="' in ln or "href=" in ln or "조문목록" in ln:
            continue                                   # 웹페이지 HTML 찌꺼기
        if CHAPTER.match(ln):
            chapter, cur, started = ln, None, True
            continue
        if SECTION.match(ln):
            cur = None
            continue
        m = ART.match(ln)
        if m:
            sk = sort_key(article_no(m.group(1)))
            if started and sk < high:
                break                                  # 번호가 뒤로 감(제51조 → 제1조) = 부칙 시작
            started, high = True, max(high, sk)
            cur = {"label": m.group(1), "title": m.group(2).strip(), "chapter": chapter, "body": ln}
            arts.append(cur)
        elif cur and re.match(r"^[①-⑳]?\s*\((시행일|적용례|경과조치)\)", ln):
            break                                      # 조문 번호 없는 부칙 (①(시행일) 이 영은…)
        elif cur and not ln.startswith(cur["body"][:20]):
            cur["body"] += "\n" + ln
    out = []
    for a in arts:
        pending = None
        if pm := PENDING.search(a["body"]):
            pending = date(int(pm.group(1)), int(pm.group(2)), int(pm.group(3)))
            a["body"] = a["body"][: pm.start()].rstrip()
        out.append(ArticleText(article_no(a["label"]), a["label"], a["title"], a["chapter"], a["body"], pending))
    return out
