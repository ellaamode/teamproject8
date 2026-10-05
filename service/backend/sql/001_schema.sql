-- ============================================================================
-- 금융규제통합조회 · 데이터베이스 스키마 (PostgreSQL 15+, Supabase)
--
-- 설계 원칙
--  1. 3계층 저장: raw(원본 그대로) → 정규화(laws/articles/documents) → 파생(links/events/stats)
--     인용 규칙을 고쳐도 원천을 다시 긁지 않고 raw부터 재처리할 수 있다.
--  2. 조문은 "번호+시행일" 단위로 버전 관리한다. 같은 조문에 현행·시행예정 본문이 공존한다.
--  3. 모든 쓰기는 자연키 기반 UPSERT → 배치를 몇 번 다시 돌려도 결과가 같다(멱등).
--  4. 쓰기는 batch_writer, 읽기는 api_reader 계정만. Supabase 공개 Data API는 RLS로 차단.
-- ============================================================================
-- pg_trgm: 한국어 부분일치 검색 인덱스. Supabase 에는 있고, 일부 로컬 Postgres 에는 없을 수 있어 실패해도 계속 진행
DO $$ BEGIN CREATE EXTENSION IF NOT EXISTS pg_trgm; EXCEPTION WHEN others THEN RAISE NOTICE 'pg_trgm 없음: 검색 인덱스 생략'; END $$;

-- ---------------------------------------------------------------- 1. 원천·운영
-- 원본 응답 보관소. 같은 내용(content_hash)이 다시 오면 저장하지 않는다.
CREATE TABLE IF NOT EXISTS raw_payloads (
  source        text        NOT NULL,              -- 'lawgo.law' | 'lawgo.admrul' | 'fsc.reply' | 'fsc.guidance' ...
  source_key    text        NOT NULL,              -- 원천 식별자 (법령일련번호, dataIdx 등)
  content_hash  text        NOT NULL,              -- sha256(payload)
  fetched_at    timestamptz NOT NULL DEFAULT now(),
  http_status   int         NOT NULL,
  payload       text        NOT NULL,              -- JSON 또는 HTML 원문
  parsed_at     timestamptz,                       -- 정규화 단계가 처리한 시각 (NULL = 미처리)
  PRIMARY KEY (source, source_key, content_hash)
);
CREATE INDEX IF NOT EXISTS raw_unparsed_idx ON raw_payloads (source) WHERE parsed_at IS NULL;

-- 배치 실행 기록. /health 가 "데이터가 언제 기준인지"를 여기서 읽는다.
CREATE TABLE IF NOT EXISTS pipeline_runs (
  id           bigserial   PRIMARY KEY,
  stage        text        NOT NULL CHECK (stage IN ('fetch','parse','link','derive')),
  source       text        NOT NULL,
  started_at   timestamptz NOT NULL DEFAULT now(),
  finished_at  timestamptz,
  status       text        NOT NULL DEFAULT 'running' CHECK (status IN ('running','ok','partial','failed')),
  stats        jsonb       NOT NULL DEFAULT '{}',  -- {"fetched":12,"new":3,"changed":1,"errors":0}
  error        text
);
CREATE INDEX IF NOT EXISTS runs_recent_idx ON pipeline_runs (source, stage, started_at DESC);

-- ---------------------------------------------------------------- 2. 법령 구조
-- 수집 대상 법령 목록(팀이 관리). 법률·시행령·감독규정이 parent_slug 로 위임 계층을 이룬다.
CREATE TABLE IF NOT EXISTS laws (
  slug          text PRIMARY KEY,                  -- 'efta', 'efta-ed', 'efta-reg' (URL에 쓰는 짧은 키)
  name          text NOT NULL,                     -- 전자금융거래법
  kind          text NOT NULL CHECK (kind IN ('법률','시행령','시행규칙','감독규정','고시','시행세칙')),
  parent_slug   text REFERENCES laws(slug),        -- 시행령 → 법률, 감독규정 → 법률
  source        text NOT NULL,                     -- 'lawgo.law' | 'lawgo.admrul'
  source_id     text,                              -- 법제처 법령ID 또는 행정규칙ID (버전이 바뀌어도 고정)
  ministry      text,
  sectors       text[] NOT NULL DEFAULT '{}',      -- {'전자금융','여신'}  업권 필터용
  aliases       text[] NOT NULL DEFAULT '{}',      -- {'전금법'}  인용 해석용 약칭
  current_seq   text,                              -- 현재 반영된 법령일련번호(MST) / 행정규칙일련번호
  promulgated_on date,
  effective_on   date,
  synced_at     timestamptz
);

-- 조문의 '정체성'. 번호가 같으면 같은 조문으로 본다(예: efta:25의2).
CREATE TABLE IF NOT EXISTS articles (
  key        text PRIMARY KEY,                     -- '{law_slug}:{no}'  no = '25의2' | '4-20'
  law_slug   text NOT NULL REFERENCES laws(slug) ON DELETE CASCADE,
  no         text NOT NULL,                        -- '25의2'
  label      text NOT NULL,                        -- '제25조의2'
  title      text,
  chapter    text,
  sort_key   int  NOT NULL,                        -- 목차 순서
  is_deleted boolean NOT NULL DEFAULT false,       -- '삭제' 조문
  UNIQUE (law_slug, no)
);

-- 조문의 '본문 버전'. 현행과 시행예정이 함께 존재할 수 있다.
CREATE TABLE IF NOT EXISTS article_versions (
  article_key    text NOT NULL REFERENCES articles(key) ON DELETE CASCADE,
  effective_from date NOT NULL,                    -- 이 본문이 효력을 갖는 첫날
  effective_to   date,                             -- 다음 버전 시행 전날 (NULL = 열려 있음)
  title          text,
  body           text NOT NULL,
  body_hash      text NOT NULL,
  source_seq     text,                             -- 이 본문을 가져온 법령일련번호
  PRIMARY KEY (article_key, effective_from)
);

-- 위임 관계 (법제처 3단비교 thdCmp 에서 추출): 법 제25조의2 → 시행령 제13조의2
CREATE TABLE IF NOT EXISTS delegations (
  from_key text NOT NULL REFERENCES articles(key) ON DELETE CASCADE,
  to_key   text NOT NULL REFERENCES articles(key) ON DELETE CASCADE,
  kind     text NOT NULL DEFAULT '위임' CHECK (kind IN ('위임','준용')),
  origin   text NOT NULL DEFAULT 'text' CHECK (origin IN ('thdcmp','text')),  -- 공식 3단비교 | 본문 인용 추정
  PRIMARY KEY (from_key, to_key)
);

-- ---------------------------------------------------------------- 3. 문서 (해석·비조치·행정지도·예고)
CREATE TABLE IF NOT EXISTS documents (
  id            text PRIMARY KEY,                  -- '{source}:{원천키}'  예) 'fsc.lawreq:3400'
  kind          text NOT NULL CHECK (kind IN ('법령해석','비조치의견','현장건의','행정지도','입법예고','규정변경예고')),
  org           text NOT NULL,                     -- 금융위원회 | 금융감독원 | 국회 | 법제처
  dept          text,                              -- 소관부서 (예: 전자금융과)
  title         text NOT NULL,
  question      text,                              -- 질의요지
  answer        text,                              -- 회답
  reason        text,                              -- 이유
  body          text,                              -- 행정지도·예고 본문
  published_on  date,                              -- 회신일 / 공고일 (실측: 원천에 날짜가 비어 있는 회신이 있어 NULL 허용)
  valid_from    date,                              -- 행정지도 존속기간 시작 / 예고 의견제출 시작
  valid_to      date,                              -- 행정지도 존속기간 끝 / 예고 의견제출 마감
  stage         text,                              -- 행정지도: '예고'|'시행' / 입법예고: '진행'|'종료'
  source_url    text NOT NULL,                     -- 원문 링크 (출처 표기 의무)
  source_name   text NOT NULL,                     -- '금융규제·법령해석포털'
  primary_law   text REFERENCES laws(slug),        -- 링크 단계가 추정한 주 법령
  content_hash  text NOT NULL,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  changed_at    timestamptz NOT NULL DEFAULT now(),
  search_text   text GENERATED ALWAYS AS (
    title || ' ' || coalesce(question,'') || ' ' || coalesce(answer,'') || ' ' ||
    coalesce(reason,'') || ' ' || coalesce(body,'')
  ) STORED
);
CREATE INDEX IF NOT EXISTS docs_pub_idx    ON documents (published_on DESC);
CREATE INDEX IF NOT EXISTS docs_kind_idx   ON documents (kind, published_on DESC);
CREATE INDEX IF NOT EXISTS docs_valid_idx  ON documents (valid_to) WHERE kind = '행정지도';
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
    CREATE INDEX IF NOT EXISTS docs_text_trgm  ON documents USING gin (search_text gin_trgm_ops);
    CREATE INDEX IF NOT EXISTS docs_title_trgm ON documents USING gin (title gin_trgm_ops);
  END IF;
END $$;

-- ---------------------------------------------------------------- 4. 연결 (서비스의 중심)
-- 문서 ↔ 조문. 근거 문장(evidence)과 해석 방법·신뢰도를 함께 남긴다.
CREATE TABLE IF NOT EXISTS article_links (
  doc_id      text NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  article_key text NOT NULL REFERENCES articles(key) ON DELETE CASCADE,
  paragraph   int  NOT NULL DEFAULT 0,             -- 항 (0 = 조 전체)
  item        text NOT NULL DEFAULT '',            -- 호 ('5', '1의2')
  method      text NOT NULL CHECK (method IN ('explicit','abbr','defined','same_law','this_law','parent_ref','title','inferred','manual')),
  confidence  real NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  evidence    text NOT NULL,                       -- 원문에서 잡힌 표현 (예: "여전법 제2조제5호")
  reviewed    boolean NOT NULL DEFAULT false,      -- 사람이 검수했는지
  PRIMARY KEY (doc_id, article_key, paragraph, item)
);
CREATE INDEX IF NOT EXISTS links_article_idx ON article_links (article_key);

-- 법령명은 잡혔지만 조문이 없거나, 대상 법령 목록에 없는 법령을 인용한 경우 → 별칭 사전 보강용
CREATE TABLE IF NOT EXISTS unresolved_mentions (
  doc_id   text NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  raw_text text NOT NULL,                          -- "통신사기피해환급법 2조의4"
  reason   text NOT NULL,                          -- 'unknown_law' | 'unknown_article' | 'ambiguous'
  PRIMARY KEY (doc_id, raw_text)
);

-- ---------------------------------------------------------------- 5. 변경 이벤트 (모니터링의 뼈대)
-- 새 해석, 조문 개정, 행정지도 시행·만료, 예고 마감 등 '변화'를 한 줄씩 쌓는다.
-- 홈 화면의 변화 피드와 관심 조문 모니터링이 모두 이 테이블 하나를 읽는다.
CREATE TABLE IF NOT EXISTS change_events (
  id          bigserial PRIMARY KEY,
  dedupe_key  text NOT NULL UNIQUE,                -- 'doc_new:fsc.lawreq:3400' → 재실행해도 중복 없음
  occurred_on date NOT NULL,
  kind        text NOT NULL CHECK (kind IN ('해석_신규','비조치_신규','조문_개정','조문_시행예정',
                                             '행정지도_예고','행정지도_시행','행정지도_만료임박','행정지도_만료',
                                             '입법예고_시작','입법예고_마감임박')),
  law_slug    text REFERENCES laws(slug),
  article_key text REFERENCES articles(key),
  doc_id      text REFERENCES documents(id) ON DELETE CASCADE,
  title       text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_recent_idx  ON change_events (occurred_on DESC);
CREATE INDEX IF NOT EXISTS events_article_idx ON change_events (article_key, occurred_on DESC);
CREATE INDEX IF NOT EXISTS events_law_idx     ON change_events (law_slug, occurred_on DESC);

-- ---------------------------------------------------------------- 6. 집계 (조회 성능용, derive 단계에서 갱신)
CREATE MATERIALIZED VIEW IF NOT EXISTS article_stats AS
SELECT l.article_key,
       count(DISTINCT l.doc_id)                                           AS total,
       count(DISTINCT l.doc_id) FILTER (WHERE d.kind = '법령해석')         AS interp,
       count(DISTINCT l.doc_id) FILTER (WHERE d.kind = '비조치의견')       AS noaction,
       count(DISTINCT l.doc_id) FILTER (WHERE d.kind = '행정지도')         AS guidance,
       count(DISTINCT l.doc_id) FILTER (WHERE d.kind IN ('입법예고','규정변경예고')) AS notice,
       max(d.published_on)                                                AS latest_on
FROM article_links l JOIN documents d ON d.id = l.doc_id
GROUP BY l.article_key;
CREATE UNIQUE INDEX IF NOT EXISTS article_stats_pk ON article_stats (article_key);

-- ---------------------------------------------------------------- 7. 보안
-- Supabase는 public 스키마를 anon 키로 REST 노출한다. 정책 없이 RLS만 켜서 외부 접근을 막고,
-- 백엔드는 002_roles.sql 의 전용 계정(테이블 권한 보유)으로 직접 접속한다.
ALTER TABLE raw_payloads        ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs       ENABLE ROW LEVEL SECURITY;
ALTER TABLE laws                ENABLE ROW LEVEL SECURITY;
ALTER TABLE articles            ENABLE ROW LEVEL SECURITY;
ALTER TABLE article_versions    ENABLE ROW LEVEL SECURITY;
ALTER TABLE delegations         ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents           ENABLE ROW LEVEL SECURITY;
ALTER TABLE article_links       ENABLE ROW LEVEL SECURITY;
ALTER TABLE unresolved_mentions ENABLE ROW LEVEL SECURITY;
ALTER TABLE change_events       ENABLE ROW LEVEL SECURITY;
