-- 018_external_processing.sql
-- 本地独立 worker 承接 inFlow 完整 pipeline 的分流字段。
--
-- 语义：
--   external_processing = TRUE   → 该 job 由本地 worker 处理，云端不跑 capture/pipeline
--   processing_host             → 最近认领该 job 的 worker 主机（hostname-pid），审计 + 重启自回收
--   claimed_at                  → 租约时间戳；NULL=可认领，超时（600s）可被其他 worker 重新认领
--
-- 幂等：init_db() 每次启动按序重跑，全部 IF NOT EXISTS。

ALTER TABLE ingest_jobs
    ADD COLUMN IF NOT EXISTS external_processing BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS processing_host      VARCHAR(64),
    ADD COLUMN IF NOT EXISTS claimed_at           TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_ingest_jobs_ext_status
    ON ingest_jobs (external_processing, status, claimed_at);
