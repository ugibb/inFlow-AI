"""Resolve monorepo root (local) or backend root (Docker)."""
from pathlib import Path


def get_project_root() -> Path:
    """Local: repo root with docker-compose.yml. Docker: /app (backend WORKDIR)."""
    here = Path(__file__).resolve()  # .../app/core/paths.py
    if len(here.parents) > 4:
        root = here.parents[4]
        if (root / "docker-compose.yml").exists() or (root / ".env.example").exists():
            return root
    return here.parents[2]


def get_env_file() -> Path | None:
    env_path = get_project_root() / ".env"
    return env_path if env_path.is_file() else None
