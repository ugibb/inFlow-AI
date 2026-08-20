-- Migration 012: Add processing_stage and processing_error to articles table.
-- These fields track the pipeline position of each article through the
-- ingest → parse → display lifecycle.
--
-- processing_stage values:
--   pending    — article record created but pipeline not yet started
--   parsing    — parse step is running (LLM call in progress)
--   indexing   — wiki indexer is building embedding + knowledge edges
--   ready      — fully processed and visible to user
--   failed     — pipeline encountered an unrecoverable error

ALTER TABLE articles
    ADD COLUMN IF NOT EXISTS processing_stage VARCHAR(20) DEFAULT 'ready',
    ADD COLUMN IF NOT EXISTS processing_error TEXT;

-- Back-fill existing records as ready (they were processed by the old pipeline).
UPDATE articles
    SET processing_stage = 'ready'
    WHERE processing_stage IS NULL;

CREATE INDEX IF NOT EXISTS idx_articles_processing_stage ON articles(processing_stage);
