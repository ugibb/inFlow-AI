-- 020: plugin_states —— API 型插件功能开关（enabled）持久化
-- 阶段 4 插件体系：obsidian（API 型）enabled/disabled 状态落表；
-- wechat（进程型）也登记一行作为运行偏好（进程实际存活由 PID 判定）。
CREATE TABLE IF NOT EXISTS plugin_states (
    plugin_id   TEXT PRIMARY KEY,
    enabled     BOOLEAN NOT NULL DEFAULT true,
    config      JSONB,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO plugin_states (plugin_id, enabled)
VALUES ('obsidian', true), ('wechat', true)
ON CONFLICT (plugin_id) DO NOTHING;
