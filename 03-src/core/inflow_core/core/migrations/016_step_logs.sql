-- Migration 016: add step_logs column to ingest_jobs
-- Each entry: {"step": "transcribing", "ts": "2026-...", "msg": "..."}
ALTER TABLE ingest_jobs
    ADD COLUMN IF NOT EXISTS step_logs JSONB NOT NULL DEFAULT '[]'::jsonb;
