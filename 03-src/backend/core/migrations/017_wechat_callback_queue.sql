-- Migration 017: wechat bot callback queue
-- Bridges pipeline completion → WeChat bot image push.
-- Bot writes a row when user submits a URL; run_index sets status='ready';
-- callback_loop renders the card and sends the image.

CREATE TABLE IF NOT EXISTS wechat_callback_queue (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id            UUID,                               -- NULL when article already existed with no job record
    wechat_account_id UUID NOT NULL,
    sender_id         TEXT NOT NULL,                     -- ilink to_user_id to reply to
    context_token     TEXT,                              -- ilink context_token for threaded reply
    status            TEXT NOT NULL DEFAULT 'pending',  -- pending | ready | rendering | sent | failed
    card_path         TEXT,                             -- absolute path to generated PNG
    error             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at           TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_wcq_status_created  ON wechat_callback_queue (status, created_at);
CREATE INDEX IF NOT EXISTS idx_wcq_account_status  ON wechat_callback_queue (wechat_account_id, status);
CREATE INDEX IF NOT EXISTS idx_wcq_job_id          ON wechat_callback_queue (job_id) WHERE job_id IS NOT NULL;
