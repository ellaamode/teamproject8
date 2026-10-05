# 금융규제통합조회 · 백엔드

조문을 중심으로 법령·해석·비조치의견·행정지도·입법예고를 연결하는 수집 배치와 조회 API.

**대상 범위 (1단계)**: 자본시장법 · 외국환거래법 · 은행법 · 보험업법 · 전자금융거래법과 각 하위법령 전부
(시행령·시행규칙·감독규정·고시·시행세칙, 21건). 대상 법령은 추후 확대할 예정이며, 후보는 `batch/config.py` 의
`PHASE2_LAWS` 에 있다. 후보를 `TARGET_LAWS` 로 옮기면 다음 배치에서 수집·연결되고, 빼면 `parse` 단계가
조문·연결을 정리한다(원본 `raw_payloads` 는 남겨 두어 재수집 없이 복원 가능).

```
backend/
├─ sql/
│  ├─ 001_schema.sql     테이블 10개 + 집계 뷰, RLS
│  └─ 002_roles.sql      batch_writer(쓰기) / api_reader(읽기) 계정과 정책
├─ batch/                ── 쓰기: GitHub Actions 가 매일 실행
│  ├─ run.py             실행기: python -m batch.run all|fetch|parse|link|derive [--all]
│  ├─ pipeline.py        4단계 (fetch → parse → link → derive)
│  ├─ config.py          대상 법령 목록·약칭·부서 단서·운영 설정  ← 법령을 늘릴 때 여기만
│  ├─ http.py            원천 서버용 공통 클라이언트 (헤더·간격·재시도·형식 검사)
│  ├─ sources/lawgo.py   법제처 Open API
│  ├─ sources/fscportal.py 금융규제·법령해석포털 (회신사례·행정지도)
│  ├─ lawtext.py         법령 본문 → 조문 (부칙 제외, 시행예정 버전 분리)
│  ├─ normalize.py       HTML 정리, 조문 번호 표기
│  ├─ linker.py          인용 연결 엔진 (서비스의 핵심)
│  └─ store.py           DB 쓰기 (모두 UPSERT, 실행 기록)
├─ app/                  ── 읽기: Render 에서 FastAPI 로 실행
│  ├─ main.py            CORS, 캐시 헤더, 오류 형식
│  └─ routes/            health · laws · articles · graph(연결 지도) · search · documents · feed
├─ seed/                 데모 데이터 (실제 조문 + 예시 문서) 와 적재 스크립트
├─ tools/export_static.py  API 응답 → 화면용 정적 스냅숏(service/app/data)
└─ tests/                인용 엔진·파서 테스트 20개
```

## 로컬 실행
```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q                               # 테스트
export DATABASE_URL=postgresql://...              # 로컬 Postgres 또는 Supabase
python -m seed.load_demo                          # 스키마 + 데모 데이터 (실제 파이프라인 경유)
uvicorn app.main:app --port 8000                  # http://127.0.0.1:8000/docs
python -m tools.export_static                     # 화면용 스냅숏 갱신
```

## 설계 원칙 (요약)
- **쓰기는 배치만, 읽기는 API만.** API 계정은 SELECT 권한뿐이고 쿼리 5초 제한.
- **원본 먼저.** 원천 응답을 `raw_payloads` 에 그대로 두고 가공한다 → 규칙을 고치면 `link --all` 만 다시.
- **증분·멱등.** 내용 해시로 바뀐 것만 처리, 모든 쓰기는 자연키 UPSERT, 이벤트는 dedupe_key 로 1회만.
- **조문은 시행일 버전.** 현행과 시행예정 본문을 함께 저장, 시행예정만 있는 신설 조문은 현행으로 보이지 않음.
- **연결에는 근거.** 모든 링크에 원문 표현·방법·신뢰도. 존재하지 않는 조문은 연결하지 않고 `unresolved_mentions` 로.

## 확인이 필요한 곳 (코드에 [확인 필요] 표시)
- (완료 2026-10-05) 법제처 Open API 응답 형식은 실제 응답으로 확인해 반영했다 (`sources/lawgo.py` 머리말, `lawtext.py`).
  키를 다시 시험하려면 `python -m tools.lawgo_probe`(견본 저장) · `python -m tools.lawgo_trial`(로컬 DB 시험 수집).
- `config.py` `DEPT_HINTS`: 금융위 부서명 → 주 법령 단서. 직제 개편 시 보강.
