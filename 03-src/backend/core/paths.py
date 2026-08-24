"""Resolve monorepo root (local) or backend root (Docker)."""
from pathlib import Path


def get_project_root() -> Path:
    """Local: monorepo root（含 docker-compose.yml / .env.example）。Docker: /app (backend WORKDIR)。

    不假设固定目录深度：向上探测含仓库标志文件（docker-compose.yml / .env.example）的
    祖先即本地根；找不到（Docker 镜像内）则回退到 backend 上一级（WORKDIR）。
    """
    here = Path(__file__).resolve()  # .../backend/core/paths.py
    for parent in here.parents:
        if (parent / "docker-compose.yml").exists() or (parent / ".env.example").exists():
            return parent
    return here.parents[2]


def get_env_file() -> Path | None:
    env_path = get_project_root() / ".env"
    return env_path if env_path.is_file() else None
