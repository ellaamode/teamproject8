"""인용 연결 엔진 테스트. 문장은 금융규제·법령해석포털 회신사례에서 실제로 관찰한 표기 형태를 따른다."""
import pytest

from batch.config import PHASE2_LAWS, TARGET_LAWS
from batch.linker import Resolver

# 인용 엔진 자체는 범위와 무관하므로 2단계 후보까지 넣은 등록부로 시험한다(약칭·정의어 규칙 검증용)
LAWS = {s.slug: {"name": s.name, "kind": s.kind, "parent": s.parent, "aliases": s.aliases}
        for s in TARGET_LAWS + PHASE2_LAWS}
ARTS = {
    "efta": {"2", "21", "23", "25의2", "25의3", "28", "35의2", "36의2"},
    "efta-ed": {"13의2", "13의3", "13의6", "15"},
    "efta-reg": {"56의2", "56의8"},
    "yjb": {"2", "19", "20"},
    "yjb-ed": {"6의7"},
    "fscma": {"180", "71"},
}


@pytest.fixture(scope="module")
def r():
    return Resolver(LAWS, ARTS)


def keys(res):
    return sorted((l.key, l.paragraph, l.item, l.method) for l in res.links)


def test_explicit_bracket_and_continuation(r):
    res = r.resolve(["「전자금융거래법」 제25조의2 및 제28조제2항제3호에 따르면"])
    assert keys(res) == [("efta:25의2", 0, "", "explicit"), ("efta:28", 2, "3", "explicit")]


def test_defined_alias_then_reuse(r):
    # 실측: '여신전문금융업법(이하 ‘여전법’) 제2조제3호' → 이후 '여전법 제2조제5호 가목'
    reason = ("□ 여신전문금융업법(이하 ‘여전법’) 제2조제3호에서는 신용카드를 정의하고 있으며\n"
              "ㅇ 여전법 제2조제5호 가목 및 나목에 따라 신용카드가맹점이란")
    res = r.resolve([reason])
    got = keys(res)
    assert ("yjb:2", 0, "3", "explicit") in got
    assert ("yjb:2", 0, "5", "abbr") in got or ("yjb:2", 0, "5", "defined") in got


def test_html_split_tokens_are_normalized(r):
    # 실측: 상세 HTML에서 '제 2 조' 처럼 태그 사이 공백으로 쪼개져 들어온다
    res = r.resolve(["「 여신전문금융업법 」 제 2 조 제 3 호"])
    assert keys(res) == [("yjb:2", 0, "3", "explicit")]


def test_common_abbreviation(r):
    res = r.resolve(["자본시장법 제180조제1항의 공매도 제한 적용 여부"])
    assert keys(res) == [("fscma:180", 1, "", "abbr")]


def test_same_law_enforcement_decree(r):
    res = r.resolve(["「전자금융거래법」 제25조의2제1항 및 같은 법 시행령 제13조의2에 따라"])
    assert ("efta-ed:13의2", 0, "", "same_law") in keys(res)


def test_parent_ref_in_decree_context(r):
    # 시행령·감독규정 문맥의 '법 제N조' 는 모법을 가리킨다
    res = r.resolve(["법 제25조의2제1항에 따른 별도관리 금액은 시행령 제13조의2에서 정한다"], hint_law="efta-ed")
    got = keys(res)
    assert ("efta:25의2", 1, "", "parent_ref") in got
    assert ("efta-ed:13의2", 0, "", "parent_ref") in got


def test_this_law_uses_primary(r):
    res = r.resolve(["「전자금융거래법」 제28조에 따른 등록 요건", "이 법 제36조의2의 행위규칙"])
    assert ("efta:36의2", 0, "", "this_law") in keys(res)
    assert res.primary_law == "efta"


def test_title_form_without_je(r):
    res = r.resolve(["전자금융거래법 25조의2 1항 관련 질의"])
    assert keys(res) == [("efta:25의2", 1, "", "title")]


def test_unknown_law_is_kept_for_review(r):
    # 실측: '통신사기피해환급법 2조의4 1항' — 대상 법령 목록 밖
    res = r.resolve(["본인확인조치(통신사기피해환급법 2조의4 1항 본문) 이행여부"])
    assert res.links == []
    assert any(reason == "unknown_law" for _, reason in res.unresolved)


def test_nonexistent_article_is_flagged(r):
    res = r.resolve(["「전자금융거래법」 제999조"])
    assert res.links == []
    assert ("「전자금융거래법」 제999조", "unknown_article") in res.unresolved


def test_money_is_not_an_article(r):
    res = r.resolve(["선불충전금 잔액이 5조 원을 넘는 경우 「전자금융거래법」 제25조의2"])
    assert keys(res) == [("efta:25의2", 0, "", "explicit")]


def test_supervisory_regulation_by_name(r):
    res = r.resolve(["전자금융감독규정 제56조의2에 따른 선불충전금 정보의 관리"])
    assert keys(res) == [("efta-reg:56의2", 0, "", "explicit")]


def test_other_law_in_brackets_does_not_leak(r):
    # 「은행법」에 따른 은행 — 조문 없이 법령명만 → 링크 없음, 다음 조문은 앞 법령을 따르지 않는다
    res = r.resolve(["「은행법」에 따른 은행은 「전자금융거래법」 제28조제2항의 등록 대상이 아니다"])
    assert keys(res) == [("efta:28", 2, "", "explicit")]


def test_hyphen_number_goes_to_regulation(r):
    # 실측 오류 수정: '제7-36조의2' 는 금융투자업규정 조문이지 자본시장법 조문이 아니다
    res = Resolver(LAWS).resolve(["금융투자업규정 제7-36조의2제2항", "같은 규정 제7-36조의2"], hint_law="fscma")
    assert {l.slug for l in res.links} == {"fscma-reg"}


def test_department_hint_only_when_no_law_named(r):
    # 실측: '법 제25조의2', '영 제13조의6' 만 쓴 비조치의견서 → 소관부서(전자금융과) 단서로 주 법령 추정
    text = ["법 제25조의2제1항의 별도관리 의무는 영 제13조의6에서 관리 기준을 정하고 있다"]
    assert {l.key for l in r.resolve(text, fallback_law="efta").links} == {"efta:25의2", "efta-ed:13의6"}
    assert r.resolve(text).links == []                              # 단서가 없으면 추측하지 않는다
    named = r.resolve(["「여신전문금융업법」 제2조"], fallback_law="efta")
    assert {l.slug for l in named.links} == {"yjb"}                 # 법령명이 있으면 단서는 무시


def test_same_law_after_unknown_law_stays_unknown(r):
    # 실측 오류 수정: 대상 밖 법령 뒤의 '동법 제8조'·'및 제8조'가 전자금융거래법 제8조로 잘못 연결되던 문제
    text = ["「전자금융거래법」 제2조의 정의와 별개로, 통신사기피해환급법 제5조제1항 및 제8조, 동법 시행령 제2조의3을 본다"]
    res = r.resolve(text, fallback_law="efta")
    assert {l.key for l in res.links} == {"efta:2"}
    raw = " ".join(u for u, _ in res.unresolved)
    assert "제8조" in raw and "제2조의3" in raw


def test_halfwidth_corner_brackets(r):
    # 실측: 실제 회신은 반각 낫표 ｢｣ 를 자주 쓴다 (U+FF62/FF63)
    res = Resolver(LAWS).resolve(["｢보험업법 시행령｣ 제59조제3항제13호는", "｢전자금융감독규정｣제13조 제1항 제6호에서"])
    assert {l.key for l in res.links} == {"ins-ed:59", "efta-reg:13"}


def test_unlisted_rules_are_not_guessed(r):
    # 실측: '운영규칙 제4조', ｢상호저축은행업감독규정｣ 제29조 가 문서의 주 법령으로 잘못 추정되던 문제
    text = ["「신용정보의 이용 및 보호에 관한 법률」 제2조에 따라",
            "□ 「법령해석 및 비조치의견서 업무처리에 관한 운영규칙」 제4조(비조치의견서)",
            "□ 법령해석 및 비조치의견서 업무처리에 관한 운영규칙 제4조 제2호",
            "□｢상호저축은행업감독규정｣ 제29조제1항제3호의2는"]
    res = Resolver(LAWS).resolve(text)
    # 상호저축은행업감독규정은 2차 보강으로 대상 법령이 되어 정상 연결된다. 운영규칙은 여전히 대상 밖
    assert {l.key for l in res.links} == {"credit:2", "sb-reg:29"}
    assert sum(1 for u, _ in res.unresolved if "운영규칙" in u) >= 2


def test_real_world_guess_traps(r):
    # 실측 오탐 3종: 부칙 조문, 대괄호 법령명, 대상 밖 법령 뒤의 괄호 속 단독 조문
    text = ["「여신전문금융업법」 제2조에 따라 부가서비스는 제외한다.",
            "ㅇ 또한, 여신전문금융업법 시행령 개정시 부칙 제2조에서는 별표를 정하였다.",
            "* [공정거래법 시행령] 제4조(기업집단의 범위)에 따라",
            "□ 「건축법」은 건축을 정의하고 있고(제2조 제1항 제8호), 이는 여전법과 무관하다"]
    res = Resolver(LAWS).resolve(text)
    assert {l.key for l in res.links} == {"yjb:2"}
    assert {l.paragraph for l in res.links} == {0}


def test_unbracketed_and_long_out_of_scope_names(r):
    text = ["「자본시장과 금융투자업에 관한 법률」 제9조에 따라",
            "□ 자산유동화법 개정법률 부칙 제3조는 \"제8조제1항의 개정규정\"을 정한다",
            "* 전자금융거래법 시행령 부칙(대통령령 제34887호) 제3조",
            "□ 금융위원회의 설치 등에 관한 법률 제38조 제9호는 다른 법을 정한다",
            "□ 지배구조법\u3000제10조제1항에서는"]
    res = Resolver(LAWS).resolve(text)
    assert {l.key for l in res.links} == {"fscma:9", "gov:10"}
    assert next(l for l in res.links if l.key == "gov:10").method == "abbr"


def test_non_statute_articles_are_skipped(r):
    text = ["「여신전문금융업법」 제2조 및 여신전문금융업법 시행령 제7조의3 및 별표 1의3 제2조바목2호",
            "신협법 제31조제1항 단서 및 신협 표준정관 제53조 제2항에 위반하는지"]
    keys = {l.key for l in Resolver(LAWS).resolve(text).links}
    assert keys == {"yjb:2", "yjb-ed:7의3", "cu:31"}


def test_phase1_scope_marks_other_laws_unknown():
    # 1단계 등록부(5개 법률 + 하위법령)만 쓰면 여전법 인용은 연결하지 않고 '대상 밖 법령'으로 남긴다
    scope = {s.slug: {"name": s.name, "kind": s.kind, "parent": s.parent, "aliases": s.aliases} for s in TARGET_LAWS}
    res = Resolver(scope).resolve(["「여신전문금융업법」 제2조 및 「외국환거래규정」 제7-2조, 「보험업법」 제97조에 따라"])
    assert {l.key for l in res.links} >= {"ins:97"}
    assert not any(l.slug == "yjb" for l in res.links)
    assert any(reason == "unknown_law" for _, reason in res.unresolved)


def test_detail_rules_and_fx_notice():
    scope = {s.slug: {"name": s.name, "kind": s.kind, "parent": s.parent, "aliases": s.aliases} for s in TARGET_LAWS}
    arts = {"bank-det": {"43"}, "ins-det": {"7-13"}, "fx-reg": {"7-2"}, "ins": {"97"}, "fx": {"18"}}
    R = Resolver(scope, arts)
    # 실측: 공식 이름(은행업감독업무시행세칙)과 다르게 '은행업감독규정시행세칙'으로 쓴다
    assert {l.key for l in R.resolve(["은행업감독규정시행세칙 제43조 제1항 제4호"]).links} == {"bank-det:43"}
    # 보험업법 문맥에서 '감독업무시행세칙 제7-13조' → 보험업감독업무시행세칙
    assert "ins-det:7-13" in {l.key for l in R.resolve(["「보험업법」 제97조 및 감독업무시행세칙 제7-13조"]).links}
    # 외국환거래법 문맥의 하이픈 번호는 감독규정이 아니라 고시(외국환거래규정)로
    assert "fx-reg:7-2" in {l.key for l in R.resolve(["「외국환거래법」 제18조 및 같은 법 제7-2조"]).links}
