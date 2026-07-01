-- Migration 015: Extend ingest_jobs for pipeline v2.
--
-- New columns:
--   asr_file_path    set after transcribing step (audio path: _asr_verbose.json)
--   index_file_path  set after indexing step     (data/02_parse/…/{job_id}_chunks.json)
--
-- Status lifecycle extensions:
--   audio path: captured → transcribing → transcribed → parsing → parsed → indexing → ready
--   图文  path: captured → parsing → parsed → indexing → ready
--   (old "displaying" renamed to "indexing" going forward; existing rows unaffected)
--
-- error_stage widened from VARCHAR(20) → VARCHAR(30) to fit new step names.
-- cancelled added as a valid terminal status alongside failed.

ALTER TABLE ingest_jobs
    ADD COLUMN IF NOT EXISTS asr_file_path   TEXT,
    ADD COLUMN IF NOT EXISTS index_file_path TEXT;

-- Widen error_stage to accommodate longer step names (transcribing, indexing, …)
ALTER TABLE ingest_jobs
    ALTER COLUMN error_stage TYPE VARCHAR(30);
