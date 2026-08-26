-- 021: skill_usage 记账表 + ingest_jobs.skill_id（worker 契约）
-- ==================================================================
-- 对齐 worker 仓库 deploy/cloud/skill_usage.sql 与全局架构方案 v1.1 §8：
--   worker 经 framework/contracts/usage.py 以 INSERT ... ON CONFLICT (job_id)
--   DO NOTHING 幂等写账，断点续跑不重复记 → job_id 必须为 PK，勿额外加唯一索引。
-- 建表时序：cloud 必须先建，worker 记账才落库（否则记账静默告警不落库）。
-- init_db 幂等执行：全部 IF NOT EXISTS，重复启动无副作用。
-- ==================================================================

-- M1 起 job 归属 skill（审计列；worker capture 时写入，可空则不归因）
ALTER TABLE ingest_jobs ADD COLUMN IF NOT EXISTS skill_id text;

-- skill_usage：一 job 一行（job 粒度记账）
CREATE TABLE IF NOT EXISTS skill_usage (
    job_id UUID PRIMARY KEY REFERENCES ingest_jobs(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    skill_id text NOT NULL,
    audio_seconds int,          -- ASR 计费时长（秒，来自 _asr.json duration）
    llm_tokens_in int,          -- LLM 输入 token 累计（经 RecordingLLM 采集）
    llm_tokens_out int,         -- LLM 输出 token 累计
    cost_cents numeric(10,4),   -- 折算成本（分；费率见 worker utils/rates.py，投产前按账单覆盖）
    created_at timestamptz NOT NULL DEFAULT now()
);

-- 常用查询索引（云端按实际查询模式补；worker 侧无需）
CREATE INDEX IF NOT EXISTS idx_skill_usage_user_created
    ON skill_usage (user_id, created_at);
