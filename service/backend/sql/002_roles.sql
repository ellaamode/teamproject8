-- ============================================================================
-- 계정 분리: 배치는 쓰기, API는 읽기만.
-- Supabase SQL Editor(postgres 계정)에서 001_schema.sql 다음에 실행.
-- 비밀번호는 실행 전에 바꾸고, 이 파일에 실제 비밀번호를 남기지 않는다.
-- ============================================================================
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'batch_writer') THEN
    CREATE ROLE batch_writer LOGIN PASSWORD 'CHANGE_ME_WRITER';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'api_reader') THEN
    CREATE ROLE api_reader LOGIN PASSWORD 'CHANGE_ME_READER';
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO batch_writer, api_reader;

-- 배치: 원본·정규화·파생 테이블 쓰기
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO batch_writer;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO batch_writer;

-- API: 조회만. 원본(raw_payloads)은 API가 볼 필요가 없으므로 제외 (수집 현황은 derive 가 pipeline_runs 에 요약)
-- unresolved_mentions: 분석 페이지의 '연결하지 못한 인용' 집계용
GRANT SELECT ON laws, articles, article_versions, delegations, documents, article_links,
                unresolved_mentions, change_events, pipeline_runs, article_stats TO api_reader;

-- RLS가 켜진 테이블은 정책이 있어야 행이 보인다
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['raw_payloads','pipeline_runs','laws','articles','article_versions',
                           'delegations','documents','article_links','unresolved_mentions','change_events']
  LOOP
    EXECUTE format('DROP POLICY IF EXISTS batch_all ON %I', t);
    EXECUTE format('CREATE POLICY batch_all ON %I FOR ALL TO batch_writer USING (true) WITH CHECK (true)', t);
  END LOOP;
  FOREACH t IN ARRAY ARRAY['pipeline_runs','laws','articles','article_versions','delegations',
                           'documents','article_links','unresolved_mentions','change_events']
  LOOP
    EXECUTE format('DROP POLICY IF EXISTS api_read ON %I', t);
    EXECUTE format('CREATE POLICY api_read ON %I FOR SELECT TO api_reader USING (true)', t);
  END LOOP;
END $$;

-- 구체화 뷰는 소유자만 REFRESH 할 수 있다 → 소유자 권한으로 실행하는 함수를 배치에 위임
CREATE OR REPLACE FUNCTION refresh_article_stats() RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = public AS
$$ REFRESH MATERIALIZED VIEW CONCURRENTLY article_stats $$;
REVOKE ALL ON FUNCTION refresh_article_stats() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION refresh_article_stats() TO batch_writer;

-- API 계정이 실수로 무거운 쿼리를 오래 붙잡지 않도록
ALTER ROLE api_reader SET statement_timeout = '5s';
