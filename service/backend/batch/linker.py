"""인용 연결 엔진: 문서 본문에서 '어느 법령의 몇 조'를 찾아 조문 키로 바꾼다.

회신사례에는 '관련 법령' 항목이 없어서(포털 실측) 본문 표기에 의존해야 한다. 실제로 쓰이는 표기:

  「여신전문금융업법」 제2조제3호            정식 명칭 + 낫표          → explicit
  여신전문금융업법(이하 '여전법') 제2조       문서 안에서 약칭을 정의     → 이후 '여전법 제5조' 는 defined
  자본시장법 제180조                         널리 쓰는 약칭             → abbr
  같은 법 제5조 / 동법 시행령 제13조의2       직전에 인용한 법령         → same_law
  이 법 제12조                               문서의 주 법령             → this_law
  법 제25조의2 / 영 제13조 / 감독규정 제56조  시행령·규정 문맥의 모법·하위규정 → parent_ref
  통신사기피해환급법 2조의4 1항               '제' 없이 쓴 제목형 표기     → title
  제23조 및 제18조                            앞 인용의 법령을 이어받음
  같은 조 제6호                              직전 조문을 이어받음

처리 순서: (1) 문서 안 약칭 정의 수집 → (2) 조문 표기마다 바로 앞의 법령 표현을 해석
→ (3) 주 법령 추정 후 '이 법'·'법'·단독 '제N조'를 다시 해석 → (4) 실제 존재하는 조문인지 검증.
검증에 실패하거나 대상 밖 법령이면 버리지 않고 unresolved 로 남겨 사람이 별칭 사전을 보강한다.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .normalize import despace, for_citation

CONFIDENCE = {
    "explicit": 0.98, "defined": 0.93, "abbr": 0.92, "same_law": 0.88,
    "this_law": 0.80, "parent_ref": 0.78, "title": 0.72, "inferred": 0.55,
}

# 조문 표기: 제25조의2 제1항 제3호 / 제4-20조 / 2조의4 1항(제 생략) / 제8조 제1항 제1의2호
ARTICLE = re.compile(
    r"(?P<je>제)?(?P<main>\d{1,3})(?:-(?P<hyph>\d{1,3}))?조(?:의(?P<sub>\d{1,2}))?"
    r"(?:\s?제?(?P<para>\d{1,2})항)?"
    r"(?:\s?제?(?P<item>\d{1,2}(?:의\d{1,2})?)호)?"
)
SAME_ARTICLE = re.compile(r"(?:같은|동)\s?조\s?(?:제?(?P<para>\d{1,2})항)?\s?(?:제?(?P<item>\d{1,2}(?:의\d{1,2})?)호)?")
CONNECTOR = re.compile(r"^\s*(?:,|및|와|과|또는|·|내지|부터|이나|나|그리고)\s*$")
# 바로 앞 문맥을 끊는 경계 (문장·글머리표)
BOUNDARY = re.compile(r"[\n□ㅇ☐○●▶■◦※]|다\.\s|\.\s(?=[가-힣])")
DEFINE = re.compile(
    r"(?:「(?P<b>[^」]{2,60})」|(?P<n>[가-힣A-Za-z· ]{2,60}?))\s*(?P<ch>시행령|시행규칙)?\s*"
    r"\(\s*이하\s*['\"]?(?P<alias>[^'\")]{1,25}?)['\"]?\s*(?:이?라\s*한다|라\s*함|이라\s*함)?\s*\)"
)
# '…법'으로 끝나지만 법령명이 아닌 흔한 말
COMMON_WORDS = {"방법", "위법", "불법", "적법", "편법", "합법", "입법", "사법", "해법", "용법", "수법", "문법", "기법", "비법",
                "공법", "헌법", "본법", "현행법", "개정법", "특별법", "관련법", "해당법", "상위법", "하위법", "관계법", "처리방법",
                "지급방법", "산정방법", "관리방법", "운용방법", "계산방법", "결제방법", "조치방법", "제공방법", "평가방법"}
LAWISH = re.compile(r"(법률|법|시행령|시행규칙|규정|세칙|규칙|고시|지침|기준|가이드라인)$")


@dataclass
class Link:
    slug: str
    no: str
    paragraph: int
    item: str
    method: str
    evidence: str
    confidence: float = 0.0

    @property
    def key(self) -> str:
        return f"{self.slug}:{self.no}"


@dataclass
class Result:
    links: list[Link] = field(default_factory=list)
    unresolved: list[tuple[str, str]] = field(default_factory=list)   # (raw_text, reason)
    primary_law: str | None = None


class Resolver:
    def __init__(self, laws: dict, articles: dict[str, set] | None = None):
        """laws: slug → {'name','kind','parent','aliases'}; articles: slug → {'25의2', ...} (검증용)."""
        self.laws = laws
        self.articles = articles or {}
        self.lexicon: dict[str, tuple[str, str]] = {}          # despaced name → (slug, method)
        for slug, l in laws.items():
            self.lexicon[despace(l["name"])] = (slug, "explicit")
            for a in l.get("aliases", ()):
                self.lexicon.setdefault(despace(a), (slug, "abbr"))
        self.children: dict[tuple[str, str], str] = {}         # (parent, kind) → slug
        for slug, l in laws.items():
            if l.get("parent"):
                self.children[(l["parent"], l["kind"])] = slug

    # ------------------------------------------------------------ 법령 표현 해석
    def _child(self, slug: str | None, kind: str | None) -> str | None:
        if not slug or not kind:
            return slug
        base = self.laws[slug].get("parent") or slug          # 시행령의 시행령 → 법률의 시행령
        return self.children.get((base, kind))

    def _root(self, slug: str | None) -> str | None:
        return (self.laws[slug].get("parent") or slug) if slug else None

    def _lookup_name(self, name: str, local: dict) -> tuple[str | None, str]:
        key = despace(name)
        if key in local:
            return local[key], "defined"
        if key in self.lexicon:
            return self.lexicon[key]
        return None, ""

    def _resolve_suffix(self, words: list[str], local: dict):
        """띄어쓴 단어열의 '뒤쪽 가장 긴' 부분이 법령명인지 본다. ('이 경우 여전법' → 여전법)"""
        for i in range(len(words)):
            name, method = self._lookup_name("".join(words[i:]), local)
            if name:
                return name, method, " ".join(words[i:])
        return None, "", None

    def _law_before(self, prefix: str, ctx: dict):
        """조문 표기 바로 앞(prefix 끝)에 붙은 법령 표현을 해석. → (slug|None, method, matched, unknown_raw)"""
        p = re.sub(r"\(이하[^)]*\)\s*$", "", prefix.rstrip()).rstrip()
        child = None
        m = re.search(r"\s?(시행령|시행규칙)$", p)
        if m and not re.search(r"(같은|동|이)\s?(법\s?)?시행령$", p):
            child, p = m.group(1), p[: m.start()].rstrip()

        if m2 := re.search(r"[「\[]([^」\]]{2,60})[」\]]$", p):
            slug, method = self._lookup_name(m2.group(1), ctx["local"])
            if not slug:
                return None, "", m2.group(0), m2.group(1)
            return self._child(slug, child), ("explicit" if method == "explicit" else method), m2.group(0), None

        if m2 := re.search(r"(?:같은|동)\s?(?:법\s?)?(시행령|영)$|(?:같은\s?법|동법)$|(?:같은|동|이)\s?규정$", p):
            # 직전에 인용한 법령이 '대상 밖 법령'이면 '같은 법'도 그 법령이다 → 아는 법령으로 끌어오지 않는다
            if ctx.get("last_unknown"):
                return None, "", m2.group(0), ctx["last_unknown"]
        if m2 := re.search(r"(?:같은|동)\s?(?:법\s?)?(시행령|영)$", p):
            return self._child(ctx["last"] or ctx["primary"], "시행령"), "same_law", m2.group(0), None
        if m2 := re.search(r"(?:같은\s?법|동법)$", p):
            return self._child(ctx["last"], child), "same_law", m2.group(0), None
        if m2 := re.search(r"(?:이|본)\s?법$", p):
            return self._child(self._root(ctx["primary"]), child), "this_law", m2.group(0), None
        if m2 := re.search(r"(?:같은|동|이)\s?규정$", p):
            return ctx["last"] or ctx["primary"], "same_law", m2.group(0), None

        words = re.findall(r"[가-힣A-Za-z·]+", p[-80:])
        if words and re.search(r"[가-힣A-Za-z·]$", p):
            slug, method, matched = self._resolve_suffix(words, ctx["local"])
            if slug:
                return self._child(slug, child), method, matched, None
            last = words[-1]
            # 모법·하위규정을 가리키는 단독 표현 (시행령·감독규정 문맥에서 흔함)
            if last == "법" and (len(words) == 1 or not LAWISH.search(words[-2])):
                return self._child(self._root(ctx["primary"]), child), "parent_ref", "법", None
            if last in ("영", "시행령") and len(words) >= 1:
                return self._child(ctx["primary"], "시행령"), "parent_ref", last, None
            if last in ("감독규정", "규정"):
                return (self._child(ctx["primary"], "감독규정") or self._child(ctx["primary"], "고시")), "parent_ref", last, None
            if last in ("세칙", "시행세칙", "감독규정시행세칙", "감독업무시행세칙", "업무시행세칙"):
                return self._child(ctx["primary"], "시행세칙"), "parent_ref", last, None
            if last in ("규칙", "시행규칙"):
                return self._child(ctx["primary"], "시행규칙"), "parent_ref", last, None
            if (LAWISH.search(last) and len(last) >= 3) or (last == "법률" and len(words) >= 2):
                return None, "", last, last                  # 대상 밖 법령 (예: 통신사기피해환급법)
        if child:                                            # 법령명 없이 '시행령 제N조'
            return self._child(ctx["primary"], child), "parent_ref", child, None
        return None, "", "", None

    # ------------------------------------------------------------ 메인
    def resolve(self, segments: list[str], hint_law: str | None = None, fallback_law: str | None = None) -> Result:
        """segments: [제목, 질의요지, 회답, 이유 ...] 순서.
        hint_law: 확실히 아는 주 법령(예: 시행령 본문의 자기 법령).
        fallback_law: 본문에 법령명이 하나도 없을 때만 쓰는 약한 단서(예: 소관부서)."""
        texts = [for_citation(s) for s in segments if s]
        local = self._collect_definitions(texts)
        # 1차: 명시적 표현만으로 주 법령 추정
        first = self._scan(texts, local, primary=hint_law, allow_implicit=False)
        primary = hint_law or self._guess_primary(first) or (fallback_law if fallback_law in self.laws else None)
        # 2차: '이 법'·'법'·단독 '제N조'까지 해석
        res = self._scan(texts, local, primary=primary, allow_implicit=True)
        res.primary_law = primary
        return self._validate(res)

    def _collect_definitions(self, texts: list[str]) -> dict:
        local = {}
        for t in texts:
            for m in DEFINE.finditer(t):
                name = m.group("b") or m.group("n") or ""
                slug, _ = self._lookup_name(name, {})
                if not slug and m.group("n"):
                    slug, _, _ = self._resolve_suffix(name.split(), {})
                if slug:
                    local[despace(m.group("alias"))] = self._child(slug, m.group("ch"))
        return local

    def _guess_primary(self, res: Result) -> str | None:
        if not res.links:
            return None
        c = Counter(self._root(l.slug) for l in res.links)
        return c.most_common(1)[0][0]

    def _scan(self, texts, local, primary, allow_implicit) -> Result:
        res = Result()
        for t in texts:
            ctx = {"local": local, "primary": primary, "last": None, "last_unknown": None}
            prev_end, prev_link, prev_unknown = -1, None, None
            # 문장에 낫표·대괄호로 언급된 법령명 위치 (조문 번호가 바로 붙지 않은 언급까지)
            mentions = []
            for mm in re.finditer(r"[「\[]([^」\]]{2,60})[」\]]", t):
                ms, _ = self._lookup_name(mm.group(1), local)
                if ms or LAWISH.search(despace(mm.group(1))):
                    mentions.append((mm.end(), ms, mm.group(1)))
            # 낫표 없이 쓴 법령명 언급도 위치 기록 ('방법·위법' 같은 흔한 말은 제외)
            for mm in re.finditer(r"(?<![가-힣])([가-힣]{2,20}(?:법|법률|시행령|감독규정))(?![가-힣])", t):
                w = mm.group(1)
                if w in COMMON_WORDS or w.endswith(("동법", "이법", "같은법")):
                    continue
                ms, _ = self._lookup_name(w, local)
                if ms or len(w) >= 4:
                    mentions.append((mm.end(), ms, w))
            for m in ARTICLE.finditer(t):
                start = m.start()
                prefix = t[max(0, start - 90): start]
                cut = max((b.end() for b in BOUNDARY.finditer(prefix)), default=0)
                prefix = prefix[cut:]
                no = m.group("main") + (f"-{m.group('hyph')}" if m.group("hyph") else "") + \
                    (f"의{m.group('sub')}" if m.group("sub") else "")
                para = int(m.group("para") or 0)
                item = m.group("item") or ""

                # (a) '같은 조'
                if (sm := re.search(r"(?:같은|동)\s?조\s?$", prefix)) and prev_link:
                    no = prev_link.no
                # (b) 앞 조문과 접속어로 이어짐 → 같은 법령
                gap = t[prev_end:start] if prev_end >= 0 else None
                if prev_link and gap is not None and CONNECTOR.match(gap):
                    slug, method, matched, unknown = prev_link.slug, prev_link.method, "", None
                elif prev_unknown and gap is not None and CONNECTOR.match(gap):
                    slug, method, matched, unknown = None, "", "", prev_unknown    # '대상 밖 법 제5조 및 제8조'
                else:
                    slug, method, matched, unknown = self._law_before(prefix, ctx)

                has_je = bool(m.group("je"))
                # 법령 조문이 아닌 '제N조': 부칙, 별표 속 항목, 정관·약관·규약·내규·지침
                if re.search(r"(부칙\s*(\([^)]*\))?|별표\s*\d+(의\d+)?|정관|약관|규약|내규|지침|가이드라인|협약|계약서)\s*$", prefix):                 # '부칙 제2조' 는 본칙 조문이 아니다
                    prev_end, prev_link = m.end(), None
                    continue
                if not slug and not unknown:
                    # 단독 '제N조' 는 200자 안에서 가장 가까이 언급된 법령을 따른다 ('「건축법」은 …(제2조)' → 건축법)
                    near = [x for x in mentions if x[0] <= start and start - x[0] < 200]
                    if ctx.get("last_unknown") and start - ctx.get("unknown_at", -10**9) < 200:
                        near.append((ctx["unknown_at"], None, ctx["last_unknown"]))
                    if near:
                        _, ms, name = max(near, key=lambda x: x[0])
                        if ms:
                            slug, method = ms, "inferred"
                        else:
                            unknown = name
                if unknown:
                    res.unresolved.append((f"{unknown} {m.group(0)}", "unknown_law"))
                    ctx["last"], ctx["last_unknown"], ctx["unknown_at"] = None, unknown, m.end()
                    prev_end, prev_link, prev_unknown = m.end(), None, unknown
                    continue
                prev_unknown = None
                if not slug:
                    if not has_je or not allow_implicit or not primary:
                        prev_end, prev_link = m.end(), None
                        continue
                    slug, method = primary, "inferred"
                if not has_je and method not in ("explicit", "abbr", "defined", "same_law"):
                    prev_end, prev_link = m.end(), None
                    continue
                if not has_je:
                    method = "title"
                if method in ("this_law", "parent_ref", "inferred") and not allow_implicit:
                    prev_end, prev_link = m.end(), None
                    continue

                # '제7-36조' 같은 하이픈 번호는 감독규정·세칙에만 쓰인다 → 법률·시행령으로 잡혔으면 하위 규정으로 옮김
                if m.group("hyph") and self.laws[slug]["kind"] in ("법률", "시행령", "시행규칙"):
                    reg = self._child(slug, "감독규정") or self._child(slug, "고시")
                    if not reg:
                        prev_end, prev_link = m.end(), None
                        continue
                    slug = reg

                ev = (matched + " " if matched else "") + m.group(0)
                link = Link(slug, no, para, item, method, ev.strip(), CONFIDENCE[method])
                res.links.append(link)
                ctx["last"], ctx["last_unknown"] = slug, None
                prev_end, prev_link = m.end(), link

            # 조문 번호 없이 '같은 조 제6호'만 쓴 경우
            for sm in SAME_ARTICLE.finditer(t):
                if not (sm.group("para") or sm.group("item")):
                    continue
                before = [l for l in res.links if l.evidence and t.find(l.evidence) != -1 and t.find(l.evidence) < sm.start()]
                if before:
                    b = before[-1]
                    res.links.append(Link(b.slug, b.no, int(sm.group("para") or 0), sm.group("item") or "",
                                          "same_law", sm.group(0), CONFIDENCE["same_law"]))
        return res

    def _validate(self, res: Result) -> Result:
        best: dict[tuple, Link] = {}
        for l in res.links:
            known = self.articles.get(l.slug)
            if known is not None and l.no not in known:
                res.unresolved.append((l.evidence, "unknown_article"))
                continue
            k = (l.slug, l.no, l.paragraph, l.item)
            if k not in best or best[k].confidence < l.confidence:
                best[k] = l
        res.links = list(best.values())
        res.unresolved = list(dict.fromkeys(res.unresolved))
        return res
