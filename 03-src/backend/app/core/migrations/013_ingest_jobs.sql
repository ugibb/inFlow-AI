-- Migration 013: Create ingest_jobs table for pipeline state tracking.
-- Each row represents one content-ingestion attempt.
--
-- Status lifecycle:
--   pending → capturing → captured → parsing → parsed → displaying → ready
--                                                                   → failed (any stage)
--
-- raw_file_path    set after capturing  (data/raw/{platform}/{YYYYMMDD}/{uuid}.json)
-- parsed_file_path set after parsing    (data/parsed/{YYYYMMDD}/{uuid}.json)
-- article_id       set after displaying (FK to articles.id)

CREATE TABLE IF NOT EXISTS ingest_jobs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    article_id       UUID REFERENCES articles(id) ON DELETE SET NULL,

    source_url       TEXT,
    capture_method   VARCHAR(30),
    -- url | wechat_bot | browser_ext | upload | paste
    source_platform  VARCHAR(50),
    -- wechat | bilibili | xiaoyuzhou | xhs | douyin | youtube | toutiao |
    -- juejin | csdn | upload | generic

    raw_file_path    TEXT,
    parsed_file_path TEXT,

    status           VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- pending | capturing | captured | parsing | parsed | displaying | ready | failed

    retry_count      SMALLINT NOT NULL DEFAULT 0,
    error_stage      VARCHAR(20),
    error_message    TEXT,

    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ingest_jobs_user_id  ON ingest_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_ingest_jobs_status   ON ingest_jobs(status);
CREATE INDEX IF NOT EXISTS idx_ingest_jobs_article  ON ingest_jobs(article_id);
