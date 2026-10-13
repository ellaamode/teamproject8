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

원칙: 잘못 연결하느니 연결하지 않는다. 애매하면 짐작하지 않고 보류(unresolved)한다.
  - '법·동법·제N조' 바로 앞 문맥이 대상 밖 법령이면 그 법령의 조문으로 보고 보류 (unknown_law)
  - 앞 문맥에 서로 다른 법령이 둘 이상이라 '동법·같은 조'가 무엇인지 알 수 없으면 보류 (ambiguous)
  - '구 「…」', '…시행되기 전의 것' 처럼 개정 전 법령을 가리키면 보류 (old_version)
  - 별지·서식·별표·부칙 번호는 조문이 아니므로 제외
  - 원문에 '제4조(주요주주의 범위)' 처럼 제목이 있으면 우리 조문 제목과 한 번 더 대조, 다르면 보류 (title_mismatch)
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
# 법령명처럼 끝나지만 특정 법령이 아닌 일반명 (언급 위치로 기록하지 않음)
GENERIC_NAMES = {"동법", "이법", "본법", "같은법", "동시행령", "같은시행령", "동규정", "이규정", "본규정", "같은규정", "위규정",
                 "감독규정", "관련규정", "해당규정", "관계규정", "세부규정", "시행세칙", "동시행세칙", "감독규정시행세칙",
                 "업무시행세칙", "감독업무시행세칙", "관련법", "관계법", "해당법", "현행법", "개정법", "관련법률", "해당법률"}
NOT_LAW_ENDINGS = ("방법", "위법", "불법", "적법", "편법", "합법", "입법", "해법", "용법", "수법", "기법", "비법", "공법", "사법", "문법")
# 두 글자 법령명 (낫표 없이 '상법 제438조' 처럼 쓰임)
SHORT_LAWS = {"상법", "민법", "형법", "세법"}
# 개정 전 법령을 가리키는 표현: 구「보험업법 시행령」, (… 시행되기 전의 것)
OLD_VERSION = re.compile(r"(?:^|[^가-힣])구\s?[「\[]|시행되기\s?전의\s?것\)?\s*$|개정되기\s?전의\s?것\)?\s*$")
# 조문 번호 뒤 괄호 속 제목: '제4조(주요주주의 범위)'
TITLE_AFTER = re.compile(r"^\s?\(([가-힣ㆍ·,\s]{2,40})\)")
NEAR = 200          # '법·동법·제N조'가 따르는 앞 문맥의 범위(글자)


@dataclass
class Link:
    slug: str
    no: str
    paragraph: int
    item: str
    method: str
    evidence: str
    confidence: float = 0.0
    title_hint: str = ""        # 원문에서 조문 번호 바로 뒤 괄호에 적힌 제목 (대조용)

    @property
    def key(self) -> str:
        return f"{self.slug}:{self.no}"


@dataclass
class Result:
    links: list[Link] = field(default_factory=list)
    unresolved: list[tuple[str, str]] = field(default_factory=list)   # (raw_text, reason)
    primary_law: str | None = None


class Resolver:
    def __init__(self, laws: dict, articles: dict[str, set] | None = None, titles: dict[str, str] | None = None):
        """laws: slug → {'name','kind','parent','aliases'}; articles: slug → {'25의2', ...} (검증용);
        titles: 'slug:no' → 조문 제목 (원문 괄호 제목과 대조용)."""
        self.laws = laws
        self.articles = articles or {}
        self.titles = titles or {}
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

    def _near_verdict(self, ctx: dict, nearest_only: bool = False) -> str | None:
        """조문 표기 앞 NEAR 글자 안의 법령 언급을 보고, 보류해야 하면 그 이유 표식을 돌려준다.
        - 가장 가까운 언급이 대상 밖 법령 → 그 법령 이름 ('특정금융거래보고법은 …(법 제4조)')
        - (nearest_only 가 아니면) 서로 다른 법령이 둘 이상 → '§amb' ('기술이전법 …, 자본시장법 …, 동법 제4조')"""
        near = ctx.get("near") or []
        if not near:
            return None
        _, slug, name = max(near, key=lambda x: x[0])
        if slug is None:
            return name
        if nearest_only:
            return None
        roots = {self._root(s) if s else n for _, s, n in near}
        return "§amb" if len(roots) >= 2 else None

    def _resolve_suffix(self, words: list[str], local: dict):
        """띄어쓴 단어열의 '뒤쪽 가장 긴' 부분이 법령명인지 본다. ('이 경우 여전법' → 여전법)"""
        for i in range(len(words)):
            name, method = self._lookup_name("".join(words[i:]), local)
            if name:
                return name, method, " ".join(words[i:])
        return None, "", None

    def _law_before(self, prefix: str, ctx: dict):
        """조문 표기 바로 앞(prefix 끝)에 붙은 법령 표현을 해석. → (slug|None, method, matched, unknown_raw)"""
        p = re.sub(r"\(이하[^)]*\)\s*$", "", prefix.rstrip()).rstrip().rstrip("'\"’”‘“").rstrip()   # '…법률 시행령' 제109조
        # 개정 전 법령: 구「보험업법 시행령」(… 시행되기 전의 것) 제15조 → 지금 조문과 내용이 다를 수 있어 보류
        if (re.search(r"(?:시행|개정)되기\s?전의\s?것\)$", p) or re.search(r"(?:^|[^가-힣])구\s?[「\[][^」\]]{2,60}[」\]]$", p)
                or re.search(r"(?:^|\s)구\s[가-힣]{2,30}(?:법|시행령|규정)$", p)):
            return None, "", "", "§old"
        child = None
        m = re.search(r"\s?(시행령|시행규칙)$", p)
        if m and not re.search(r"(같은|동|이)\s?(법\s?)?시행령$", p):
            child, p = m.group(1), re.sub(r"\(이하[^)]*\)\s*$", "", p[: m.start()].rstrip()).rstrip()

        if m2 := re.search(r"[「\[]([^」\]]{2,60})[」\]]$", p):
            slug, method = self._lookup_name(m2.group(1), ctx["local"])
            if not slug:
                return None, "", m2.group(0), m2.group(1)
            return self._child(slug, child), ("explicit" if method == "explicit" else method), m2.group(0), None

        if m2 := re.search(r"(?:같은|동)\s?(?:법\s?)?(시행령|영)$|(?:같은\s?법|동\s?법)$|(?:같은|동|이)\s?규정$", p):
            # 직전에 인용한 법령이 '대상 밖 법령'이면 '같은 법'도 그 법령이다 → 아는 법령으로 끌어오지 않는다
            if ctx.get("last_unknown"):
                return None, "", m2.group(0), ctx["last_unknown"]
            # 바로 앞 문맥에 서로 다른 법령이 둘 이상이면 '동법'이 어느 쪽인지 알 수 없다 → 보류
            if ambiguous := self._near_verdict(ctx):
                return None, "", m2.group(0), ambiguous
        if m2 := re.search(r"(?:같은|동)\s?(?:법\s?)?(시행령|영)$", p):
            return self._child(ctx["last"] or ctx["primary"], "시행령"), "same_law", m2.group(0), None
        if m2 := re.search(r"(?:같은\s?법|동\s?법)$", p):
            # '동법'은 법률을 가리킨다 (직전 인용이 시행령이어도 '동법 제6조'는 법률 제6조)
            return self._child(self._root(ctx["last"]), child), "same_law", m2.group(0), None
        if m2 := re.search(r"(?:이|본)\s?법$", p):
            return self._child(self._root(ctx["primary"]), child), "this_law", m2.group(0), None
        if m2 := re.search(r"(?:같은|동|이)\s?규정$", p):
            return ctx["last"] or ctx["primary"], "same_law", m2.group(0), None

        words = re.findall(r"[가-힣A-Za-z·]+", p[-80:])
        if words and re.search(r"[가-힣A-Za-z·]$", p):
            slug, method, matched = self._resolve_suffix(words, ctx["local"])
            if slug:
                return self._child(slug, child), method, matched, None
            # 문서가 대상 밖 법령에 붙인 약칭 ('증발공 규정 제5-21조') → 그 법령의 조문
            for i in range(len(words)):
                if (alias := "".join(words[i:])) in ctx.get("unknown_alias", {}):
                    return None, "", " ".join(words[i:]), ctx["unknown_alias"][alias]
            last = words[-1]
            if last in SHORT_LAWS:                           # '상법 제438조'
                return None, "", last, last
            # 모법·하위규정을 가리키는 단독 표현 ('법·영·규정·세칙'): 바로 앞 문맥이 대상 밖 법령이거나
            # 서로 다른 법령이 섞여 있으면 어느 법령인지 알 수 없으므로 보류
            if last in ("법", "영", "시행령", "감독규정", "규정", "세칙", "시행세칙", "규칙", "시행규칙") \
                    and (verdict := self._near_verdict(ctx, nearest_only=True)):
                return None, "", last, verdict
            base = ctx["primary"] or max((x for x in ctx.get("near") or [] if x[1]), default=(0, None, ""))[1]
            if last == "법" and (len(words) == 1 or not LAWISH.search(words[-2])):
                return self._child(self._root(base), child), "parent_ref", "법", None
            if last in ("영", "시행령") and len(words) >= 1:
                return self._child(base, "시행령"), "parent_ref", last, None
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
        local, unknown_alias = self._collect_definitions(texts)
        # 1차: 명시적 표현만으로 주 법령 추정
        first = self._scan(texts, local, unknown_alias, primary=hint_law, allow_implicit=False)
        primary = hint_law or self._guess_primary(first) or (fallback_law if fallback_law in self.laws else None)
        # 2차: '이 법'·'법'·단독 '제N조'까지 해석
        res = self._scan(texts, local, unknown_alias, primary=primary, allow_implicit=True)
        res.primary_law = primary
        return self._validate(res)

    def _collect_definitions(self, texts: list[str]) -> tuple[dict, dict]:
        """문서 안 약칭 정의 '(이하 ‘…’)'. 아는 법령은 local, 대상 밖 법령은 unknown_alias 로 따로 모은다."""
        local, unknown_alias = {}, {}
        for t in texts:
            for m in DEFINE.finditer(t):
                name = m.group("b") or m.group("n") or ""
                slug, _ = self._lookup_name(name, {})
                if not slug and m.group("n"):
                    slug, _, _ = self._resolve_suffix(name.split(), {})
                if slug:
                    local[despace(m.group("alias"))] = self._child(slug, m.group("ch"))
                elif LAWISH.search(despace(name)) and len(despace(name)) >= 4:
                    unknown_alias[despace(m.group("alias"))] = name
        return local, unknown_alias

    def _guess_primary(self, res: Result) -> str | None:
        if not res.links:
            return None
        c = Counter(self._root(l.slug) for l in res.links)
        return c.most_common(1)[0][0]

    def _scan(self, texts, local, unknown_alias, primary, allow_implicit) -> Result:
        res = Result()
        for t in texts:
            ctx = {"local": local, "unknown_alias": unknown_alias, "primary": primary, "last": None, "last_unknown": None}
            prev_end, prev_link, prev_unknown = -1, None, None
            unknown_at: list[int] = []      # 보류한(대상 밖) 조문 표기 위치 — '같은 조'가 그쪽을 가리키는지 볼 때 씀
            # 문장에 낫표·대괄호·큰따옴표로 언급된 법령명 위치 (조문 번호가 바로 붙지 않은 언급까지)
            mentions = []
            for mm in re.finditer(r"[「\[\"“]([^」\]\"”]{2,60})[」\]\"”]", t):
                ms, _ = self._lookup_name(mm.group(1), local)
                if ms or LAWISH.search(despace(mm.group(1))):
                    mentions.append((mm.end(), ms, mm.group(1)))
            # 낫표 없이 쓴 법령명 언급도 위치 기록 ('방법·위법' 같은 흔한 말과 '감독규정' 같은 일반명은 제외)
            for mm in re.finditer(r"(?<![가-힣])([가-힣]{1,20}(?:법|법률|시행령|규정|세칙))(?![가-힣])"
                                  r"|(?<![가-힣])([가-힣]{2,20}(?:법|법률))(?=(?:은|는|이|가|을|를|의|에|과|와|상|에서|으로)(?![가-힣]))", t):
                w = mm.group(1) or mm.group(2)
                if (w in COMMON_WORDS or w in GENERIC_NAMES or w.endswith(NOT_LAW_ENDINGS)
                        or w.startswith(("동법", "이법", "같은법", "본법"))):
                    continue
                ms, _ = self._lookup_name(w, local)
                if ms or w in SHORT_LAWS or len(w) >= 3 and w.endswith(("법", "법률")) or len(w) >= 5:
                    mentions.append((mm.end(1) if mm.group(1) else mm.end(2), ms, w))
            mentions.sort()
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
                    ctx["near"] = [x for x in mentions if start - NEAR <= x[0] <= start]
                    slug, method, matched, unknown = self._law_before(prefix, ctx)

                has_je = bool(m.group("je"))
                # 법령 조문이 아닌 '제N조': 부칙, 별표 속 항목, 정관·약관·규약·내규·지침
                # 별지·서식·별첨 번호도 조문이 아니다 ('금융투자업규정 별지 제16조 … 신청서')
                if re.search(r"(부칙\s*(\([^)]*\))?|별표\s*\d+(의\d+)?|별지|별첨|서식|양식|정관|약관|규약|내규|지침|가이드라인|협약|계약서)\s*$", prefix):
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
                    unknown_at.append(m.end())
                    reason = {"§old": "old_version", "§amb": "ambiguous"}.get(unknown, "unknown_law")
                    shown = (matched or "") if unknown.startswith("§") else unknown
                    res.unresolved.append((f"{shown} {m.group(0)}".strip(), reason))
                    ctx["last"], ctx["last_unknown"], ctx["unknown_at"] = None, unknown, m.end()
                    prev_end, prev_link, prev_unknown = m.end(), None, unknown
                    continue
                prev_unknown = None
                if not slug:
                    if not has_je or not allow_implicit or not primary:
                        prev_end, prev_link = m.end(), None
                        continue
                    # 근처에 법령 언급이 없는 단독 '제N조'를 주 법령으로 짐작하기 전에 한 번 더 확인:
                    # 앞쪽(400자)에 대상 밖 법령이 언급돼 있으면 그 법령일 수 있으므로 보류
                    if any(ms is None and 0 <= start - pos < 400 for pos, ms, _ in mentions):
                        res.unresolved.append((m.group(0), "ambiguous"))
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
                th = TITLE_AFTER.match(t[m.end():])
                link = Link(slug, no, para, item, method, ev.strip(), CONFIDENCE[method],
                            th.group(1).strip() if th and not re.search(r"이하|참조|참고", th.group(1)) else "")
                res.links.append(link)
                ctx["last"], ctx["last_unknown"] = slug, None
                prev_end, prev_link = m.end(), link

            # 조문 번호 없이 '같은 조 제6호'만 쓴 경우
            for sm in SAME_ARTICLE.finditer(t):
                if not (sm.group("para") or sm.group("item")):
                    continue
                before = [l for l in res.links if l.evidence and t.find(l.evidence) != -1 and t.find(l.evidence) < sm.start()]
                # 바로 앞에 서로 다른 조문이 둘 이상 나왔으면 '같은 조'가 어느 쪽인지 알 수 없다 → 보류
                recent = {(l.slug, l.no) for l in before if sm.start() - t.find(l.evidence) < NEAR}
                last_known = max((t.find(l.evidence) for l in before), default=-1)
                # 가장 가까운 앞 조문이 대상 밖 법령이면 '같은 조'도 그 법령 ('「전자서명법」 제2조제4호 … 같은 조제7호')
                if len(recent) >= 2 or any(last_known < u <= sm.start() for u in unknown_at):
                    res.unresolved.append((sm.group(0), "ambiguous"))
                    continue
                if before:
                    b = before[-1]
                    res.links.append(Link(b.slug, b.no, int(sm.group("para") or 0), sm.group("item") or "",
                                          "same_law", sm.group(0), CONFIDENCE["same_law"]))
        return res

    def _validate(self, res: Result) -> Result:
        # 원문 괄호 제목과 우리 조문 제목이 다르면 다른 법령의 같은 번호일 가능성이 크다 → 그 조문 연결은 모두 보류
        plain = lambda x: re.sub(r"[^가-힣A-Za-z0-9]", "", x or "")
        mismatch = {l.key for l in res.links if l.title_hint and self.titles.get(l.key)
                    and plain(l.title_hint) not in plain(self.titles[l.key]) and plain(self.titles[l.key]) not in plain(l.title_hint)}
        best: dict[tuple, Link] = {}
        for l in res.links:
            if l.key in mismatch:
                res.unresolved.append((l.evidence, "title_mismatch"))
                continue
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
