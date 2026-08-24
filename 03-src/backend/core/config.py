from pathlib import Path
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

    # Database — override via DATABASE_URL env in docker-compose (set from .env)
    database_url: str = "postgresql+asyncpg://inflow:inFlow@localhost:5432/inflow"
    database_url_sync: str = "postgresql://inflow:inFlow@localhost:5432/inflow"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

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

    # ── 微信 Bot 服务令牌（插件体系使用）───────────────────────
    # .env 中 SERVICE_TOKEN_WECHAT_BOT；wechat 插件启动 bot 进程时注入 inFlow_TOKEN。
    service_token_wechat_bot: str = ""

    # ── Logging — see 02-docs/20260623_06_的日志系统重构方案.md ──
    log_dir: str = "04-log/backend"
    log_level: str = "INFO"
    log_sql: bool = False
    log_access: bool = False
    log_access_skip: str = "/api/ingest/jobs,/api/health"

    # ── 精华卡截图（Playwright）──────────────────────────────
    card_viewport_width: int = 750
    card_screenshot_scale: int = 2

    # ── Transcription ────────────────────────────────────────
    # ASR_PROVIDER: groq（默认，Groq Whisper）| tingwu（通义听悟）
    asr_provider: str = "groq"
    groq_api_key: str = ""
    whisper_model: str = "large-v3"
    whisper_model_path: str = ""
    transcribe_timeout_sec: int = 300
    # 通义听悟（ASR_PROVIDER=tingwu 时必填）
    tingwu_app_key: str = ""
    alibaba_cloud_access_key_id: str = ""
    alibaba_cloud_access_key_secret: str = ""
    tingwu_oss_bucket: str = ""
    tingwu_oss_endpoint: str = "oss-cn-beijing.aliyuncs.com"
    tingwu_source_language: str = "cn"
    tingwu_poll_interval_sec: int = 30
    tingwu_max_wait_sec: int = 10800

    # ── Embedding（语义搜索向量化，非敏感）──────────────────
    embedding_provider: str = "siliconflow"
    embedding_api_base: str = "https://api.siliconflow.cn/v1"
    embedding_model: str = "BAAI/bge-large-zh-v1.5"

    # NOTE: LLM / Embedding 的 API Key 放 .env（SILICONFLOW_API_KEY 等）。
    # 网页「设置」写入 config_store.json 的覆盖项优先级最高。

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
