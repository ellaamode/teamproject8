"""수집 대상과 운영 설정. 대상 법령을 늘릴 때는 이 파일만 고친다.

1단계 범위 (2026-10): 법률 5개 + 각 법률의 하위법령 전부(시행령·시행규칙·감독규정·고시·시행세칙)
  자본시장법 · 외국환거래법 · 은행법 · 보험업법 · 전자금융거래법
  하위법령은 국가법령정보센터에서 실제로 존재하는 것만 넣었다(2026-10-05 확인).
  은행법·외국환거래법·전자금융거래법은 시행규칙이 없고, 외국환거래법의 하위 규정은 감독규정이 아닌
  기획재정부 고시 '외국환거래규정'이다.
2단계 확대 예정: PHASE2_LAWS (회신 인용 빈도 순으로 추가 — 데이터 분석의 '대상 밖 법령' 집계가 근거)
"""
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LawSpec:
    slug: str
    name: str
    kind: str                      # 법률 | 시행령 | 시행규칙 | 감독규정 | 고시 | 시행세칙
    parent: str | None = None      # 위임 계층의 상위(모법) slug
    sectors: tuple = ()
    aliases: tuple = ()            # 실무 약칭
    source: str = "lawgo.law"      # 행정규칙(감독규정·고시·세칙)은 lawgo.admrul


def family(slug, name, sectors, aliases=(), *, rule=False, reg=None, reg_kind="감독규정", reg_aliases=(), detail=None, det_aliases=()):
    """법률 하나와 그 하위법령 묶음. rule=시행규칙 유무, reg=감독규정·고시 이름, detail=시행세칙 이름"""
    out = [LawSpec(slug, name, "법률", None, sectors, aliases),
           LawSpec(f"{slug}-ed", f"{name} 시행령", "시행령", slug, sectors)]
    if rule:
        out.append(LawSpec(f"{slug}-rule", f"{name} 시행규칙", "시행규칙", slug, sectors))
    if reg:
        out.append(LawSpec(f"{slug}-reg", reg, reg_kind, slug, sectors, reg_aliases, "lawgo.admrul"))
    if detail:
        out.append(LawSpec(f"{slug}-det", detail, "시행세칙", slug, sectors, det_aliases, "lawgo.admrul"))
    return out


TARGET_LAWS: list[LawSpec] = [
    *family("fscma", "자본시장과 금융투자업에 관한 법률", ("금융투자",), ("자본시장법", "자통법"),
            rule=True, reg="금융투자업규정", detail="금융투자업규정시행세칙"),
    *family("fx", "외국환거래법", ("외환",), ("외환법",), reg="외국환거래규정", reg_kind="고시"),
    *family("bank", "은행법", ("은행",), (), reg="은행업감독규정", detail="은행업감독업무시행세칙",
            det_aliases=("은행업감독규정시행세칙",)),
    *family("ins", "보험업법", ("보험",), (), rule=True, reg="보험업감독규정", detail="보험업감독업무시행세칙",
            det_aliases=("보험업감독규정시행세칙",)),
    *family("efta", "전자금융거래법", ("전자금융",), ("전금법",), reg="전자금융감독규정", detail="전자금융감독규정시행세칙"),
]

# 2단계 확대 후보 (회신 6,174건에서 '대상 밖 법령'으로 많이 인용된 순). 여기서 TARGET_LAWS 로 옮기면 수집·연결된다.
PHASE2_LAWS: list[LawSpec] = [
    *family("loan", "대부업 등의 등록 및 금융이용자 보호에 관한 법률", ("대부업",), ("대부업법",)),
    *family("yjb", "여신전문금융업법", ("여신·카드",), ("여전법",), reg="여신전문금융업감독규정"),
    *family("credit", "신용정보의 이용 및 보호에 관한 법률", ("신용정보",), ("신용정보법", "신정법"), reg="신용정보업감독규정"),
    *family("fcpa", "금융소비자 보호에 관한 법률", ("금융소비자",), ("금융소비자보호법", "금소법"),
            reg="금융소비자 보호에 관한 감독규정"),
    *family("sb", "상호저축은행법", ("저축은행",), ("저축은행법",), reg="상호저축은행업감독규정"),
    *family("fhc", "금융지주회사법", ("금융지주",), (), reg="금융지주회사감독규정"),
    *family("gov", "금융회사의 지배구조에 관한 법률", ("지배구조",), ("지배구조법", "금융사지배구조법")),
    *family("realname", "금융실명거래 및 비밀보장에 관한 법률", ("공통",), ("금융실명법",)),
    *family("cu", "신용협동조합법", ("상호금융",), ("신협법",), reg="상호금융업감독규정"),
    *family("fiu", "특정 금융거래정보의 보고 및 이용 등에 관한 법률", ("AML·가상자산",), ("특정금융정보법", "특금법")),
    *family("fsia", "금융산업의 구조개선에 관한 법률", ("구조개선",), ("금산법", "금융산업구조개선법")),
]

LAW_BY_SLUG = {s.slug: s for s in TARGET_LAWS}

# 포털 '소관부서' → 주 법령 보조 신호. 본문에 법령명이 전혀 없을 때만 쓴다('법 제N조', '영 제N조'만 있는 회신).
# [확인 필요] 금융위 직제 개편 시 부서명이 바뀌므로, 미해결 기록을 보며 주기적으로 보강한다.
DEPT_HINTS = {
    "전자금융과": "efta", "디지털금융총괄과": "efta", "금융안전과": "efta",
    "자본시장과": "fscma", "자산운용과": "fscma", "공정시장과": "fscma", "자본시장조사과": "fscma",
    "은행과": "bank", "보험과": "ins", "외화자금과": "fx", "외환제도과": "fx",
}

# 데모 범위: 전자금융 3단(법률·시행령·감독규정)
DEMO_SLUGS = ("efta", "efta-ed", "efta-reg")


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", ""))
    law_oc: str = field(default_factory=lambda: os.environ.get("LAW_GO_KR_OC", ""))
    assembly_key: str = field(default_factory=lambda: os.environ.get("ASSEMBLY_API_KEY", ""))
    contact: str = field(default_factory=lambda: os.environ.get("CRAWLER_CONTACT", "team8"))
    # 원천 서버 배려: 같은 호스트에 대한 최소 요청 간격(초)
    min_interval: float = float(os.environ.get("FETCH_MIN_INTERVAL", "1.5"))
    # 첫 적재(backfill) 때 포털 회신사례 최대 건수 (0 = 전체)
    backfill_limit: int = int(os.environ.get("BACKFILL_LIMIT", "0"))
    # 행정지도 '만료임박' 기준(일)
    expiring_days: int = int(os.environ.get("EXPIRING_DAYS", "30"))


SETTINGS = Settings()
