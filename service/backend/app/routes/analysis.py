"""데이터 분석 API (과제 필수: 수집한 데이터의 설명과 기초 분석·정리).

GET /analysis 한 번으로 분석 페이지 전체를 그릴 수 있는 집계를 돌려준다. 모든 값은 DB 에서 바로 계산한다.
  1) 수집 현황   : 출처별 수집 건수, 수집 방식(API·크롤링), 마지막 수집 시각
  2) 회신사례    : 연도별·유형별 건수, 소관부서 상위
  3) 인용 분석   : 많이 인용된 법령·조문, 인용 연결률, 해석 방법별 분포, 미해결 사유, 대상 밖 법령(보강 후보)
  4) 행정지도    : 시행 중·만료 임박·만료·예고, 평균 존속기간
  5) 법령 구조   : 법령별 법률·시행령·시행규칙·감독규정(고시)·시행세칙 조문 수, 위임 관계 수, 시행예정 조문 수
  6) 대상 범위   : 1단계 대상 법률과 2단계 확대 후보 (scope)
"""
import re

from fastapi import APIRouter

from batch.config import PHASE2_LAWS

from ..db import q

router = APIRouter(tags=["분석"])

SOURCES = [
    {"key": "lawgo", "name": "국가법령정보 (법령·행정규칙 본문)", "provider": "법제처", "url": "https://www.law.go.kr",
     "api": "https://open.law.go.kr", "method": "Open API (법제처 국가법령정보 공동활용, 인증키 OC)",
     "method_fallback": "웹페이지 크롤링 (Open API 인증키 발급 전)",
     "items": "법률·시행령·시행규칙·감독규정·고시·시행세칙 조문(현행·시행예정), 시행일, 3단비교(위임조문)",
     "raw": ("lawgo.law", "lawgo.admrul")},
    {"key": "fsc.reply", "name": "금융규제·법령해석포털 회신사례", "provider": "금융위원회·금융감독원",
     "url": "https://better.fsc.go.kr/fsc_new/replyCase/TotalReplyList.do", "method": "크롤링 (목록 JSON + 상세 HTML)",
     "items": "구분, 제목, 소관부서, 회신일, 질의요지, 회답, 이유", "raw": ("fsc.lawreq", "fsc.opinion", "fsc.pastreq")},
    {"key": "fsc.guidance", "name": "금융위원회 행정지도 (예고·시행)", "provider": "금융위원회",
     "url": "https://better.fsc.go.kr/fsc_new/status/adminMap/OpertnList.do", "method": "크롤링 (목록 JSON)",
     "items": "관리번호, 제목, 소관부서, 존속기간(시작~종료), 단계", "raw": ("fsc.guidance",)},
]


@router.get("/analysis", summary="수집 데이터 분석·정리 (분석 페이지용 집계 전체)")
def analysis():
    # 1) 수집 현황 — 원본 표는 조회 계정이 읽을 수 없으므로 배치(derive)가 실행 기록에 남긴 요약을 쓴다
    last_run = q("""SELECT stats->'sources' AS src FROM pipeline_runs
                    WHERE stage='derive' AND status IN ('ok','partial') AND stats ? 'sources'
                    ORDER BY started_at DESC LIMIT 1""")
    raw = (last_run[0]["src"] if last_run else None) or {}
    sources = []
    for s in SOURCES:
        n = sum(raw[r]["n"] for r in s["raw"] if r in raw)
        last = max((raw[r]["last"] for r in s["raw"] if r in raw), default=None)
        via_api = any(raw[r].get("api") for r in s["raw"] if r in raw)
        method = s["method"] if via_api or "method_fallback" not in s else s["method_fallback"]
        sources.append({k: v for k, v in s.items() if k not in ("raw", "method_fallback")}
                       | {"method": method, "collected": n, "last_fetched": last})
    totals = q("""SELECT (SELECT count(*) FROM laws WHERE EXISTS (SELECT 1 FROM articles a WHERE a.law_slug=laws.slug)) AS laws,
                         (SELECT count(*) FROM articles) AS articles,
                         (SELECT count(*) FROM article_versions WHERE effective_from > current_date) AS pending_versions,
                         (SELECT count(*) FROM delegations) AS delegations,
                         (SELECT count(*) FROM documents) AS documents,
                         (SELECT count(*) FROM article_links) AS links,
                         (SELECT min(published_on) FROM documents WHERE kind IN ('법령해석','비조치의견')) AS first_reply,
                         (SELECT max(published_on) FROM documents WHERE kind IN ('법령해석','비조치의견')) AS last_reply""")[0]
    portal_total = q("""SELECT (stats->>'total')::int AS t FROM pipeline_runs WHERE source='fsc.reply' AND stats ? 'total'
                        ORDER BY started_at DESC LIMIT 1""")
    totals["portal_listed_total"] = portal_total[0]["t"] if portal_total else None

    # 2) 회신사례
    by_year = q("""SELECT extract(year FROM published_on)::int AS year,
                          count(*) FILTER (WHERE kind='법령해석') AS interp,
                          count(*) FILTER (WHERE kind='비조치의견') AS noaction
                   FROM documents WHERE kind IN ('법령해석','비조치의견') AND published_on IS NOT NULL GROUP BY 1 ORDER BY 1""")
    by_dept = q("""SELECT coalesce(dept,'(부서 미기재 · 과거 회신)') AS dept, count(*) AS n FROM documents
                   WHERE kind IN ('법령해석','비조치의견') GROUP BY 1 ORDER BY 2 DESC LIMIT 12""")

    # 3) 인용 분석
    top_laws = q("""SELECT coalesce(w.parent_slug, w.slug) AS slug, r.name, count(DISTINCT l.doc_id) AS docs
                    FROM article_links l JOIN articles a ON a.key=l.article_key JOIN laws w ON w.slug=a.law_slug
                    JOIN laws r ON r.slug=coalesce(w.parent_slug, w.slug)
                    GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 12""")
    top_articles = q("""SELECT a.key, a.label, a.title, w.name AS law_name, w.kind AS law_kind, count(DISTINCT l.doc_id) AS docs
                        FROM article_links l JOIN articles a ON a.key=l.article_key JOIN laws w ON w.slug=a.law_slug
                        GROUP BY a.key, w.name, w.kind ORDER BY docs DESC, a.key LIMIT 15""")
    quality = q("""SELECT count(*) AS docs,
                          count(*) FILTER (WHERE EXISTS (SELECT 1 FROM article_links l WHERE l.doc_id=d.id)) AS linked
                   FROM documents d WHERE kind IN ('법령해석','비조치의견')""")[0]
    # 대상 법령(1단계)을 본문에서 언급한 회신 중 조문까지 연결된 비율 — 대상 밖 회신을 빼고 본 엔진 성능
    names = [n for r in q("SELECT name, aliases FROM laws") for n in [r["name"], *(r["aliases"] or [])]]
    scope_re = "(" + "|".join(re.escape(n) for n in sorted(set(names), key=len, reverse=True)) + ")"
    in_scope = q("""SELECT count(*) AS docs,
                           count(*) FILTER (WHERE EXISTS (SELECT 1 FROM article_links l WHERE l.doc_id=d.id)) AS linked
                    FROM documents d WHERE kind IN ('법령해석','비조치의견')
                    AND concat_ws(' ', title, question, answer, reason, body) ~ %s""", (scope_re,))[0]
    by_method = q("SELECT method, count(*) AS n FROM article_links GROUP BY 1 ORDER BY 2 DESC")
    unresolved = q("SELECT reason, count(*) AS n FROM unresolved_mentions GROUP BY 1 ORDER BY 2 DESC")
    unknown_raw = q("SELECT raw_text FROM unresolved_mentions WHERE reason='unknown_law'")
    unknown = {}
    generic = {"법률", "법", "규정", "감독규정", "업무규정", "시행세칙", "세칙", "규칙", "시행령", "고시", "지침", "기준",
               "감독업무시행세칙", "감독규정시행세칙", "업무시행세칙"}
    for r in unknown_raw:
        name = re.split(r"\s*제?\d", r["raw_text"])[0].strip("「」[] ")
        if name and name not in generic:
            unknown[name] = unknown.get(name, 0) + 1
    unknown_laws = sorted(({"name": k, "n": v} for k, v in unknown.items()), key=lambda x: -x["n"])[:12]

    # 4) 행정지도
    guidance = q("""SELECT count(*) FILTER (WHERE stage='시행' AND (valid_to IS NULL OR valid_to >= current_date)) AS active,
                           count(*) FILTER (WHERE stage='시행' AND valid_to BETWEEN current_date AND current_date + 60) AS expiring_60,
                           count(*) FILTER (WHERE stage='시행' AND valid_to < current_date) AS expired,
                           count(*) FILTER (WHERE stage='예고') AS notice,
                           round(avg(valid_to - valid_from) FILTER (WHERE stage='시행' AND valid_from IS NOT NULL AND valid_to IS NOT NULL))::int AS avg_days
                    FROM documents WHERE kind='행정지도'""")[0]
    guidance_dept = q("""SELECT coalesce(dept,'(미기재)') AS dept, count(*) AS n FROM documents WHERE kind='행정지도'
                         GROUP BY 1 ORDER BY 2 DESC LIMIT 8""")

    # 5) 법령 구조
    structure = q("""SELECT r.slug, r.name,
                            count(a.key) FILTER (WHERE w.kind='법률') AS law_articles,
                            count(a.key) FILTER (WHERE w.kind='시행령') AS decree_articles,
                            count(a.key) FILTER (WHERE w.kind='시행규칙') AS rule_articles,
                            count(a.key) FILTER (WHERE w.kind IN ('감독규정','고시')) AS reg_articles,
                            count(a.key) FILTER (WHERE w.kind='시행세칙') AS detail_articles,
                            (SELECT count(*) FROM delegations d JOIN articles fa ON fa.key=d.from_key JOIN laws fw ON fw.slug=fa.law_slug
                              WHERE coalesce(fw.parent_slug, fw.slug)=r.slug) AS delegations,
                            (SELECT count(DISTINCT v.article_key) FROM article_versions v JOIN articles va ON va.key=v.article_key
                              JOIN laws vw ON vw.slug=va.law_slug WHERE coalesce(vw.parent_slug, vw.slug)=r.slug
                              AND v.effective_from > current_date) AS pending
                     FROM laws r JOIN laws w ON coalesce(w.parent_slug, w.slug)=r.slug
                     LEFT JOIN articles a ON a.law_slug=w.slug
                     WHERE r.parent_slug IS NULL GROUP BY r.slug, r.name
                     HAVING count(a.key) > 0 ORDER BY count(a.key) DESC""")
    scope = {"phase": 1, "laws": [r["name"] for r in structure],
             "note": "1단계는 5개 법률과 그 하위법령 전부(시행령·시행규칙·감독규정·고시·시행세칙)입니다. 추후 확대할 예정입니다.",
             "next": [s.aliases[0] if s.aliases else s.name for s in PHASE2_LAWS if s.kind == "법률"]}
    return {"scope": scope, "sources": sources, "totals": totals, "replies_by_year": by_year, "replies_by_dept": by_dept,
            "top_laws": top_laws, "top_articles": top_articles,
            "link_quality": {"docs": quality["docs"], "linked": quality["linked"],
                             "rate": round(quality["linked"] / quality["docs"], 3) if quality["docs"] else None,
                             "in_scope": in_scope | {"rate": round(in_scope["linked"] / in_scope["docs"], 3)
                                                     if in_scope["docs"] else None},
                             "by_method": by_method, "unresolved": unresolved, "unknown_laws": unknown_laws},
            "guidance": guidance | {"by_dept": guidance_dept}, "law_structure": structure}
