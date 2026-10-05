from datetime import date

from batch.lawtext import lines_from_json, split_articles
from batch.normalize import article_label, article_no, for_citation, sort_key


def test_article_numbers():
    assert article_no("제25조의2") == "25의2"
    assert article_no("제4-20조") == "4-20"
    assert article_label("25의2") == "제25조의2"
    assert sorted(["26", "25의2", "4-21", "25", "4-20"], key=sort_key) == ["4-20", "4-21", "25", "25의2", "26"]


def test_split_current_pending_and_stop_at_addenda():
    lines = [
        "제1장 총칙",
        "제1조(목적) 이 법은 …",
        "제2조(정의) 이 법에서 사용하는 용어는 …",
        "제2조(정의) 이 법에서 사용하는 용어는 (개정본) …",
        "[시행일: 2026. 12. 17.] 제2조",
        "제3장 안전성",
        "제25조의2(선불충전금의 보호) ① 선불업자는 …",
        "② 누구든지 …",
        "제51조(과태료) …",
        "제1조(시행일) 이 법은 공포한 날부터 시행한다.",     # 부칙 (번호가 되돌아감)
        "제2조(경과조치) …",
    ]
    arts = split_articles(lines)
    assert [a.no for a in arts] == ["1", "2", "2", "25의2", "51"]
    assert arts[2].pending_from == date(2026, 12, 17) and arts[1].pending_from is None
    assert arts[3].chapter == "제3장 안전성" and "② 누구든지" in arts[3].body


def test_json_flatten_skips_addenda():
    payload = {"법령": {"조문": {"조문단위": [{"조문내용": "제1조(목적) 본문"}]},
                        "부칙": {"부칙단위": [{"부칙내용": "제1조(시행일) 부칙"}]}}}
    assert lines_from_json(payload) == ["제1조(목적) 본문"]


def test_citation_normalization():
    assert for_citation("「 여신전문금융업법 」 제 2 조 제 3 호") == "「여신전문금융업법」 제2조 제3호"
    assert for_citation("제 25 조 의 2") == "제25조의2"


# ---- 법제처 Open API 응답 형식 (2026-10 실제 응답 구조를 줄인 것)
import json
from datetime import date as _date

from batch.lawtext import lines_from_admrul_json, lines_from_law_json, split_items
from batch.normalize import substance
from batch.sources.lawgo import delegation_pairs

LAW_JSON = {"조문": {"조문단위": [
    {"조문여부": "전문", "조문내용": "            제1장 총칙", "조문번호": "1", "조문시행일자": "20261002"},
    {"조문여부": "조문", "조문번호": "1", "조문내용": "제1조(목적) 이 법은 …을 목적으로 한다.", "조문시행일자": "20261002"},
    {"조문여부": "조문", "조문번호": "2", "조문내용": "제2조(정의) 이 법에서 사용하는 용어의 정의는 다음과 같다.",
     "조문시행일자": "20261002", "항": {"호": [{"호번호": "1.", "호내용": "1. \"전자금융거래\"라 함은 …"},
                                              {"호번호": "3.", "호내용": "3. \"금융회사\"란 다음 각 목의 …",
                                               "목": [{"목번호": "가.", "목내용": "가. 「은행법」에 따른 은행"}]}]}},
    {"조문여부": "조문", "조문번호": "18", "조문내용": "제18조(전자화폐 등의 양도성)", "조문시행일자": "20270101",
     "항": [{"항번호": "①", "항내용": "①선불전자지급수단 보유자는 …"}, {"항번호": "②", "항내용": "②발행자는 …"}]},
]}}


def test_law_json_lines_and_pending():
    lines = lines_from_law_json(LAW_JSON, today=_date(2026, 10, 5))
    assert lines[0] == "제1장 총칙"
    assert "3. \"금융회사\"란 다음 각 목의 …" in lines and "가. 「은행법」에 따른 은행" in lines
    assert "제18조(전자화폐 등의 양도성) ①선불전자지급수단 보유자는 …" in lines      # 제목 줄 + 첫 항 = 한 줄
    arts = split_articles(lines)
    assert [a.label for a in arts] == ["제1조", "제2조", "제18조"]
    assert arts[2].pending_from == _date(2027, 1, 1) and arts[1].pending_from is None
    assert arts[1].chapter == "제1장 총칙"


def test_admrul_items_are_split_but_dates_are_not():
    s = ('제3조(전자금융보조업자의 범위) 다음 각 호의 어느 하나에 해당하는 자를 말한다.1. 신용카드 승인을 지원하는 사업자'
         '2. 자금인출업무를 지원하는 사업자<개정 2013. 12. 3.>2의2. 결제중계 사업자3. 제1호 부터 제3호의 사업자가. 하위 항목나. 둘째')
    assert split_items(s) == ["제3조(전자금융보조업자의 범위) 다음 각 호의 어느 하나에 해당하는 자를 말한다.",
                              "1. 신용카드 승인을 지원하는 사업자", "2. 자금인출업무를 지원하는 사업자<개정 2013. 12. 3.>",
                              "2의2. 결제중계 사업자", "3. 제1호 부터 제3호의 사업자", "가. 하위 항목", "나. 둘째"]
    lines = lines_from_admrul_json({"조문내용": ["제5조(기준)", "제5조(기준)①금융회사는 …한다.② 제1항에 따른 …"][1:]})
    assert lines == ["제5조(기준) ①금융회사는 …한다.", "② 제1항에 따른 …"]


def test_substance_ignores_formatting_only():
    web = '제2조(정의) 용어의 정의는 다음과 같다. <개정 2007. 4. 27., 2008. 2. 29.>\n1. “전자금융거래”라 함은'
    api = '제2조(정의) 용어의 정의는 다음과 같다.<개정 2007.4.27, 2008.2.29>\n1.  "전자금융거래"라 함은'
    assert substance(web) == substance(api)
    assert substance(web) != substance(web.replace("정의는", "뜻은"))


def test_thdcmp_pairs():
    payload = json.dumps({"LspttnThdCmpLawXService": {"위임조문삼단비교": {"법률조문": [
        {"조제목": "", "조번호": "0001", "조가지번호": "00", "조내용": "제1장 총칙"},
        {"조제목": "제2조(정의)", "조번호": "0002", "조가지번호": "00",
         "시행령조문": {"조제목": "제4조의2(가맹점의 범위)", "조번호": "0004", "조가지번호": "02"}},
        {"조제목": "제6조의2(불법 광고)", "조번호": "0006", "조가지번호": "02",
         "시행령조문": [{"조번호": "0006", "조가지번호": "02"}], "시행규칙조문": {"조번호": "0003", "조가지번호": "00"}},
    ]}}}, ensure_ascii=False)
    assert delegation_pairs("efta", payload) == [("efta:2", "efta-ed:4의2"), ("efta:6의2", "efta-ed:6의2"),
                                                 ("efta:6의2", "efta-rule:3")]


def test_hyphen_rules_single_string_are_split_into_articles():
    # 실측 형태: '제1-1조' 체계 행정규칙은 본문 전체가 구분자 없는 문자열 하나
    body = ('제1편 총칙제1-1조(목적) 이 규정은 … 정함을 목적으로 한다.<개정 2013. 9. 17.>'
            '제1-2조(용어의 정의) 이 규정에서 … 다음과 같다.1. "투자자"란 …2. 제1-3조(해외 파생상품거래)에 따른 거래'
            '제1-3조 (해외 파생상품거래) 영 제5조에 따라 …한다.제4-29조(신용거래 등의 제한)제4-30조(신용거래종목 등)① 투자매매업자는 …'
            '제3절 통신판매 기준 <개정 2011. 1. 24.>제1관 신고기준제4-31조(공통사항) …')
    labels = [a.label for a in split_articles(lines_from_admrul_json({"조문내용": body}))]
    assert labels == ["제1-1조", "제1-2조", "제1-3조", "제4-29조", "제4-30조", "제4-31조"]
    arts = {a.label: a for a in split_articles(lines_from_admrul_json({"조문내용": body}))}
    assert "제1-3조(해외 파생상품거래)에 따른 거래" in arts["제1-2조"].body       # 인용은 자르지 않음
    assert "제3절" not in arts["제4-30조"].body and "제1관" not in arts["제4-30조"].body
    assert arts["제4-29조"].body == "제4-29조(신용거래 등의 제한)"                  # 제목만 있는 조문


def test_paragraph_16_and_image_tags():
    law = {"조문": {"조문단위": [{"조문여부": "조문", "조문번호": "9", "조문내용": "제9조(정의)", "조문시행일자": "20261002",
                                 "항": [{"항내용": "⑮ 이 법에서 …"}, {"항내용": "<16> 이 법에서 \"외국법인등\"이란 …"},
                                        {"항내용": "<17> 산식 <img src=\"http://www.law.go.kr/flDownload.do?flSeq=1\" alt=\"img\" > 에 따른다."}]}]}}
    arts = split_articles(lines_from_law_json(law, today=_date(2026, 10, 5)))
    assert arts[0].body.split("\n")[1:] == ["⑯ 이 법에서 \"외국법인등\"이란 …", "⑰ 산식 에 따른다."]
    assert split_items("① 가는 …한다. <16> 나는 …한다.") == ["① 가는 …한다.", "⑯ 나는 …한다."]
