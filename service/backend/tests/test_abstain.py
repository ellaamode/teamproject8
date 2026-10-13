"""'잘못 연결하느니 연결하지 않는다' 회귀 테스트.

2026-10 정확도 측정(무작위 100개, 정확도 87%)에서 틀렸던 13건을 실제 회신 문장 그대로 옮겨,
이제는 연결하지 않거나(보류) 올바른 조문으로 연결하는지 확인한다. 맞았던 연결은 계속 연결돼야 한다.
"""
import pytest

from batch.config import TARGET_LAWS
from batch.linker import Resolver

LAWS = {s.slug: {"name": s.name, "kind": s.kind, "parent": s.parent, "aliases": s.aliases} for s in TARGET_LAWS}
TITLES = {"fscma-ed:4": "기업어음증권의 요건", "ins:129": "보험요율 산출의 원칙", "fscma:42": "금융투자업자의 업무위탁"}


@pytest.fixture(scope="module")
def r():
    return Resolver(LAWS, {}, TITLES)


def keys(res):
    return {(l.key, l.paragraph) for l in res.links}


def linked(res):
    return {l.key for l in res.links}


# ---------------------------------------------------------------- 보류해야 하는 경우 (예전에 틀린 연결)
def test_same_article_with_two_candidates_is_held(r):
    # '같은 조'가 시행령 제58조인지 법 제123조인지 모름 → 보류 (예전: 보험업법 제123조 제4항)
    res = r.resolve(["□「보험업법 시행령」 제58조제2항에서는 보험회사는 「보험업법」 제123조에 따른 재무건전성 기준을 "
                     "충족시키기 위한 경우에만 자금을 차입할 수 있다고 규정하고 있고, 같은 조 제4항에서는 세부 사항을 "
                     "정하여 고시할 수 있도록 규정하고 있습니다."])
    assert ("ins:123", 4) not in keys(res)


def test_alias_of_out_of_scope_regulation_is_held(r):
    # 증권의 발행 및 공시 등에 관한 규정 → 금융투자업규정이 아님 (예전: 금융투자업규정 제5-21조)
    res = r.resolve(["「증권의 발행 및 공시 등에 관한 규정」(이하 ‘증발공 규정’) 제5-21조 제3항의 주식 비율 산정시 "
                     "증발공 규정 제5-21조 제3항의 보유 주식 비율"], hint_law="fscma")
    assert "fscma-reg:5-21" not in linked(res)


def test_law_ref_after_out_of_scope_law_is_held(r):
    # '법 제4조'의 법은 특정금융거래보고법 (예전: 자본시장법 제4조)
    res = r.resolve(["자본시장법 제42조에 따른 업무위탁 관련 질의",
                     "ㅇ 특정금융거래보고법은 금융회사등 ( 법 제 2 조제 1 호 ) 에 의심거래보고 의무를 부과 ( 법 제 4 조 ) 하면서"])
    assert not {"fscma:2", "fscma:4"} & linked(res)


def test_dongbeop_means_the_act_not_the_decree(r):
    # '동법 제6조제6항'은 투자자문업 정의(법률) (예전: 시행령 제6조)
    res = r.resolve(["ㅇ 자본시장법 시행령 제7조제4항에 해당하지 않으므로, 이를 영위하기 위해 투자자문업 등록이 필요함을 "
                     "알려드립니다.(동법 제6조제6항 및 제17조)"])
    assert "fscma-ed:6" not in linked(res)
    assert ("fscma:6", 6) in keys(res)


def test_dong_beop_with_space_after_other_law_is_held(r):
    # '동 법'은 기업구조조정 촉진법 (예전: 자본시장법 제19조)
    res = r.resolve(["자본시장법 시행령 제103조 제1호의 특정금전신탁계약에 의해서 회사채를 매입한 신탁업자는 "
                     "기업구조조정 촉진법 상 해당 기업에 신용공여를 한 채권금융기관으로 보며, 동 법 제19조 제4항의 확약서를"])
    assert "fscma:19" not in linked(res)


def test_form_number_is_not_an_article(r):
    # '별지 제16조'는 서식 번호 (예전: 자본시장법 제16조)
    res = r.resolve(["자본시장법 시행령 제277조는 등록신청서에 물적 설비에 관한 사항을 기재하도록 하며, "
                     "금융투자업 규정 별지 제 16 조 일반사무관리회사 등록 신청서 상에 물적 시설에 관한 사항"])
    assert "fscma:16" not in linked(res)


def test_quoted_other_regulation_is_held(r):
    # "금융기관의해외진출에관한규정"제7조 (예전: 은행법 제7조)
    res = r.resolve(["역외금융투자회사 등에 대한 해외직접투자 관련 절차 개선",
                     "\"금융기관의해외진출에관한규정\"제7조에 동일 내용 반영하였습니다."], fallback_law="bank")
    assert "bank:7" not in linked(res)


def test_old_version_is_held(r):
    # 구 시행령(2003년 개정 전) 제15조는 지금의 제15조와 내용이 다름 (예전: 현행 시행령 제15조)
    res = r.resolve(["구「보험업법」 제19조제3항의 위임에 따라 구「보험업법 시행령」(2003. 8. 27. 대통령령 제18093호로 "
                     "개정되어 2003. 8. 30. 시행되기 전의 것) 제15조제4항과 제16조제2항에서 보험회사로 하여금"])
    assert not {"ins:19", "ins-ed:15", "ins-ed:16"} & linked(res)


def test_short_law_name_is_held(r):
    # 상법 제438조 (예전: 자본시장법 제438조)
    res = r.resolve(["ㅇ 자본시장법 314조 제5항 3호의 취지 및 명목상 감자에 있어 주주총회 일반결의를 규정하고 있는 "
                     "상법 제438조 제2항의 규정취지를 고려하면"])
    assert "fscma:438" not in linked(res)


def test_title_mismatch_is_held(r):
    # 원문 '시행령 제4조(주요주주의 범위)'는 지배구조법 시행령 → 우리 제4조(기업어음증권의 요건)와 제목이 다름
    res = r.resolve(["자본시장법 제42조 관련",
                     "1% 미만인 경우에는 시행령 제4조 각호에 해당하지 않는 이상, 대주주 변경 승인이 필요하지 않으나 "
                     "시행령 제4조(주요주주의 범위) 법 제2조제6호나목2)에서"])
    assert "fscma-ed:4" not in linked(res)


def test_dongbeop_with_two_laws_before_is_held(r):
    # '동법'이 기술이전법인지 자본시장법인지 모름 → 보류 (예전: 자본시장법 제4조)
    res = r.resolve(["기술이전법 제35조의2 제1항은 자본시장법 제12조에 따라 인가를 받은 경우 허가를 받지 아니하고 "
                     "기술신탁관리업을 할 수 있도록 하고 있으며, 동법 제4조제2항은 이 법에 따른 기술신탁관리업에 대하여는 "
                     "자본시장법을 적용하지 아니한다고 규정"])
    assert "fscma:4" not in linked(res)


def test_chinese_dongbeop_after_other_law_is_held(r):
    # 同法 = 금융실명법 (예전: 은행법 제7조)
    res = r.resolve(["「은행법」 제34조의2에 따른 내부통제",
                     "「금융실명거래 및 비밀보장에 관한 법률」 제5조의2에 따라 조치를 요구할 수 있다. 또한 同法 제7조 제1항은 "
                     "과태료를 부과한다고 규정"])
    assert "bank:7" not in linked(res)


def test_spaced_sub_article_number(r):
    # '은행법시행령 제 20 조의 2' → 제20조의2 (예전: 제20조)
    res = r.resolve(["□ 은행법 제 34 조의 2, 은행법 시행령 제 20 조의 2 및 은행업감독규정 제 29 조의 3 는 불건전 영업행위로 금지"])
    assert "bank-ed:20의2" in linked(res)
    assert "bank-ed:20" not in linked(res)


# ---------------------------------------------------------------- 계속 연결돼야 하는 경우 (예전에 맞은 연결)
def test_same_article_with_one_candidate_still_links(r):
    res = r.resolve(["「보험업법」 제123조제1항에 따라 재무건전성 기준을 지켜야 하며, 같은 조 제2항에 따라"])
    assert ("ins:123", 2) in keys(res)


def test_parent_ref_in_decree_context_still_links(r):
    res = r.resolve(["｢자본시장과 금융투자업에 관한 법률 시행령｣ [별표1] 장내파생상품은 법 제5조제2항 각 호 중 어느 하나에 "
                     "해당하는 것을 말하며"])
    assert ("fscma:5", 2) in keys(res)


def test_same_law_after_one_law_still_links(r):
    res = r.resolve(["□「전자금융거래법」제28조제2항에서는 선불전자지급수단의 발행 및 관리업무를 하려는 자가 등록하도록 하되, "
                     "ㅇ 동법 제28조제3항제1호가목에서 하나의 가맹점에서만 사용되는 선불전자지급수단은 면제하고 있습니다."])
    assert ("efta:28", 3) in keys(res)


def test_same_law_decree_still_links(r):
    res = r.resolve(["ㅇ 자본시장법 시행령 제99조제1항제1호에 따라 투자일임업자가 겸영하는 경우, 투자매매·중개업을 겸영하는 "
                     "투자일임업자는 동법 시행령 제72조에서 한정한 신용공여의 범위 내에서"])
    assert "fscma-ed:72" in linked(res)


def test_bare_article_near_law_still_links(r):
    res = r.resolve(["보험업법 제95조의2에 따른 설명의무가 보험 상품별로 개별적으로 이행되어야 한다는 취지로 해석됩니다."])
    assert "ins:95의2" in linked(res)


def test_matching_title_still_links(r):
    res = r.resolve(["보험업법 제120조에 따라", "제129조(보험요율 산출의 원칙) 보험회사는 보험요율을 산출할 때"])
    assert "ins:129" in linked(res)


# ---------------------------------------------------------------- 2차 표본(정확도 96%)에서 남은 오류
def test_article_number_typo_without_ui(r):
    # '제14조2', '제24조4' 는 제14조의2, 제24조의4 를 뜻한다 (예전: 제14조, 제24조)
    res = r.resolve(["전자금융감독규정 제14조2에 따른 클라우드컴퓨팅서비스 이용절차를 준수하여야 하는지 여부"])
    assert "efta-reg:14의2" in linked(res) and "efta-reg:14" not in linked(res)


def test_quoted_decree_name(r):
    # '자본시장과 금융투자업에 관한 법률(이하 '자본시장법') 시행령' 제109조 → 시행령 (예전: 법률 제109조)
    res = r.resolve(["국고채를 편입하는 경우 '자본시장과 금융투자업에 관한 법률(이하 '자본시장법') 시행령' 제109조제1항제4호에 따른 "
                     "고유재산과 신탁재산 간의 거래제한의 예외로 인정받을 수 있는지 여부"])
    assert "fscma-ed:109" in linked(res) and "fscma:109" not in linked(res)


def test_same_article_after_out_of_scope_law_is_held(r):
    # '「전자서명법」 제2조제4호 … 및 같은 조제7호' 의 같은 조는 전자서명법 제2조 (예전: 전자금융거래법 제2조 제7호)
    res = r.resolve(["「전자금융거래법」 제2조제10호 \"접근매체\"라 함은 다음 각 목의 수단을 말한다. "
                     "나. 「전자서명법」 제2조제4호의 전자서명생성정보 및 같은 조제7호의 인증서"])
    assert not any(l.key == "efta:2" and l.item == "7" for l in res.links)
