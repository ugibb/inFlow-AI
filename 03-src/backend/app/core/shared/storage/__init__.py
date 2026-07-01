"""Storage abstraction layer.

Exposes a single default_storage instance backed by the local filesystem.
All pipeline steps (ingest, parse, display) read/write files through this
interface so the underlying storage can be swapped to S3/OSS without changing
callers.

Usage:
    from app.core.shared.storage import default_storage

    path = await default_storage.write_raw(platform="wechat", job_id=uuid, data=payload)
    content = await default_storage.read_json(path)
"""

from app.core.shared.storage.local import LocalStorage
from app.core.config import get_settings

_settings = get_settings()
default_storage = LocalStorage(data_root=_settings.data_root)

__all__ = ["default_storage", "LocalStorage"]
