from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import List

from app.core.paths import get_env_file, get_project_root

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
    database_url: str = "postgresql+asyncpg://trove:trove@localhost:5432/trove"
    database_url_sync: str = "postgresql://trove:trove@localhost:5432/trove"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # CORS — comma-separated list of allowed origins.
    allowed_origins: str = "http://localhost:3000,http://localhost:80"

    # File storage root — data/raw and data/parsed sit under this path.
    data_root: str = "data"

    # ── Auth（非敏感）────────────────────────────────────────
    # 登录 JWT 有效期（天）。7=一周，30=一月，0=近似永久（仅自建环境）
    access_token_expire_days: int = 30

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
    groq_api_key: str = ""
    whisper_model: str = "large-v3"
    whisper_model_path: str = ""
    transcribe_timeout_sec: int = 300

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
