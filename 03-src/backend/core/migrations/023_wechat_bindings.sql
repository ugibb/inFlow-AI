-- 023: wechat_bindings —— 微信小程序「微信一键登录」openid 绑定表
-- 一个账号可绑多个微信（朋友各自 openid 一行，共享同一账号的库）；
-- ORM create_all 已建新表，本文件按项目双轨约定兜底（幂等）。
CREATE TABLE IF NOT EXISTS wechat_bindings (
    id          UUID PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    openid      VARCHAR(64) NOT NULL UNIQUE,
    nickname    VARCHAR(64),
    avatar      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_wechat_bindings_user_id ON wechat_bindings(user_id);
CREATE INDEX IF NOT EXISTS ix_wechat_bindings_openid ON wechat_bindings(openid);
