from pathlib import Path
from urllib.parse import quote_plus
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import List

from backend.core.paths import get_env_file, get_project_root

_PROJECT_ROOT = get_project_root()
_ENV_FILE = get_env_file()


class Settings(BaseSettings):
    """应用配置。

    非敏感参数默认值在此定义；.env 仅放密钥与凭证（API Key、SECRET_KEY、DB 密码等）。
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "inFlow AI"
    debug: bool = True

    # Database — 组件参数（推荐）。POSTGRES_* 由代码自动拼 URL，
    # 无需再手动配 DATABASE_URL（host/user/port/db 有默认值，生产即本机 127.0.0.1:5432）。
    # 旧部署仍可显式设 DATABASE_URL / DATABASE_URL_SYNC（非 change_me 占位符时优先）。
    postgres_user: str = "inflow"
    postgres_password: str = "inFlow"  # 仅本地开发兜底；生产必须从 .env 的 POSTGRES_PASSWORD 读
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "inflow"
    database_url: str = ""  # 兼容旧部署：显式 asyncpg 连接串
    database_url_sync: str = ""  # 兼容旧部署：显式同步连接串

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Pipeline 数据目录 —— worker 经 SFTP 回传的卡片 PNG/HTML 落盘根
    # （须与 worker 侧 SFTP_PIPELINE_DIR 一致；bot 推送与 deep-read 截图按此回读）
    inflow_pipeline_data_dir: str = "./03-src/backend/data"

    # CORS — comma-separated list of allowed origins.
    allowed_origins: str = "http://localhost:3000,http://localhost:80"

    # File storage root — data/raw and data/parsed sit under this path.
    data_root: str = "data"

    # ── Auth（非敏感）────────────────────────────────────────
    # 登录 JWT 有效期（天）。7=一周，30=一月，0=近似永久（仅自建环境）
    access_token_expire_days: int = 30

    # ── 本地 worker 分流 ──────────────────────────────────────
    # True：url/upload/paste 三入口的 job 全部置 external_processing=True，
    #      由本地 worker 承接完整 pipeline；云端只登记（upload/paste 收件
    #      落盘 data/00_staging/ 后等 worker 经 SFTP 拉取）。
    # False：仅限云端调试 —— 云端 venv 已做依赖瘦身（无 playwright/markitdown/
    #      fastembed 等重依赖），关闭后 upload/paste/url 入口会 ImportError。
    #
    # 默认 True：worker 未运行时新 job 停在 pending（前端可见），不会静默丢数据。
    external_processing: bool = True

    # ── 云端观测告警（轻量巡检，见 core/observer.py）────────────────
    # 兜住「worker 长时间失联无人知」：进度停滞>10min / 租约超时>10min /
    # 日失败率>30% / worker 失联，命中写 WARNING/ERROR 日志。
    # 仅 4 条 SELECT 每 5min 一次，非重任务；无需可设 OBSERVER_ENABLED=false。
    observer_enabled: bool = True
    observer_interval_sec: int = 300

    # ── 免费额度配额（worker 契约 quota_check.sql，免费 10 条/人/天）──
    # 「条」= 当日到 ready 的 ingest_jobs 数（成功产出卡片）；登记新 job 时
    # 检查，超限拒绝返回 429。0=不限制（自托管全部放开）。
    free_quota_per_day: int = 10

    # ── 微信 Bot 服务令牌（插件体系使用）───────────────────────
    # .env 中 SERVICE_TOKEN_WECHAT_BOT；wechat 插件启动 bot 进程时注入 inFlow_TOKEN。
    service_token_wechat_bot: str = ""

    # ── 微信小程序「微信一键登录」─────────────────────────────
    # AppID 非敏感（代码里兜底正式号）；AppSecret 仅 .env。
    # openid 绑定到哪个账号：空 = 自动取第一个超管（个人库自用场景）。
    # 邀请码：空 = 免验直进（体验版分发默认，体验成员白名单已是门禁）；
    #         公开上架时必须设置，防止陌生人绑进账号看整库。
    wechat_appid: str = "wxe091ce737f45cacc"
    wechat_secret: str = ""
    wechat_bind_username: str = ""
    wechat_invite_code: str = ""

    # ── Logging — see 02-docs/20260623_06_的日志系统重构方案.md ──
    log_dir: str = "04-log/backend"
    log_level: str = "INFO"
    log_sql: bool = False
    log_access: bool = False
    log_access_skip: str = "/api/ingest/jobs,/api/health"

    # ── Embedding（语义搜索向量化，非敏感）──────────────────
    embedding_provider: str = "siliconflow"
    embedding_api_base: str = "https://api.siliconflow.cn/v1"
    embedding_model: str = "BAAI/bge-large-zh-v1.5"

    # NOTE: LLM / Embedding 的 API Key 放 .env（SILICONFLOW_API_KEY 等）。
    # 网页「设置」写入 config_store.json 的覆盖项优先级最高。

    def _build_url(self, driver: str) -> str:
        """按 POSTGRES_* 组件拼连接串（密码特殊字符自动 URL 编码）。"""
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        return (
            f"{driver}://{user}:{password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def resolved_database_url(self) -> str:
        """asyncpg 连接串：显式 DATABASE_URL（非 change_me 占位符）优先，否则 POSTGRES_* 自动拼。

        change_me 检测用于兼容旧部署：若 .env 里 DATABASE_URL 是 .env.example 的占位符
        密码（而 POSTGRES_PASSWORD 已被 start-server.sh 自动生成真实值），此处会
        忽略占位符 DSN 改走组件拼，避免「建库密码与连接密码不匹配」。
        """
        if self.database_url and "change_me" not in self.database_url:
            return self.database_url
        return self._build_url("postgresql+asyncpg")

    @property
    def resolved_database_url_sync(self) -> str:
        """同步驱动连接串（psycopg2/SQLAlchemy sync），规则同 resolved_database_url。"""
        if self.database_url_sync and "change_me" not in self.database_url_sync:
            return self.database_url_sync
        return self._build_url("postgresql")

    def get_allowed_origins(self) -> List[str]:
        """Parse ALLOWED_ORIGINS into a list, stripping whitespace."""
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    def get_log_dir_path(self) -> Path:
        """Resolve log_dir relative to project root."""
        path = Path(self.log_dir)
        if not path.is_absolute():
            path = _PROJECT_ROOT / path
        return path

    def get_log_access_skip_paths(self) -> List[str]:
        return [p.strip() for p in self.log_access_skip.split(",") if p.strip()]

    def get_access_token_expire_hours(self) -> float:
        """Login JWT lifetime in hours."""
        if self.access_token_expire_days <= 0:
            return 24 * 365 * 10
        return float(self.access_token_expire_days) * 24


@lru_cache()
def get_settings() -> Settings:
    return Settings()
