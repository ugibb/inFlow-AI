"""LocalStorage — concrete AbstractStorage backed by the local filesystem.

Reads and writes JSON files under a configurable ``data_root`` directory
(default: ``data/``).  Suitable for single-server and Docker-volume
deployments.  Swap to an S3/OSS implementation by replacing this class
without touching any pipeline business logic.
"""

from __future__ import annotations

import json
import logging
import os
from uuid import UUID
from typing import Any

from app.core.shared.storage.base import AbstractStorage
from app.core.shared.storage.conventions import (
    article_folder_name,
    ingest_json_path,
    parse_json_path,
)

logger = logging.getLogger("inFlow.storage.local")


class LocalStorage(AbstractStorage):
    """Filesystem-backed storage.

    Args:
        data_root: Root directory for all pipeline files.  Created on demand.
    """

    def __init__(self, data_root: str = "data") -> None:
        self._root = data_root

    # ------------------------------------------------------------------ #
    # Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _ensure_dir(self, path: str) -> None:
        """Create parent directories for *path* if they do not exist."""
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def _resolve(self, path: str) -> str:
        """Return an absolute path, treating relative paths as relative to cwd."""
        return os.path.abspath(path)

    # ------------------------------------------------------------------ #
    # Raw capture                                                         #
    # ------------------------------------------------------------------ #

    async def write_raw(
        self,
        *,
        platform: str,
        job_id: UUID,
        data: dict[str, Any],
        title: str = "",
    ) -> str:
        """Write a RawCapture JSON file and return its path.

        The title is used to generate the human-readable article folder name
        (e.g. '001-Vol.121｜硅谷AI大转弯，软件正在死').  Falls back to
        'untitled' when omitted.
        """
        title = title or (data.get("raw") or {}).get("title") or ""
        folder = article_folder_name(self._root, platform, title or "untitled")
        path = ingest_json_path(self._root, platform, folder, job_id)
        self._ensure_dir(path)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, default=str)
        logger.debug("Wrote raw capture: %s", path)
        return path

    async def read_raw(self, path: str) -> dict[str, Any]:
        return await self.read_json(path)

    # ------------------------------------------------------------------ #
    # Parsed content                                                      #
    # ------------------------------------------------------------------ #

    async def write_parsed(
        self,
        *,
        job_id: UUID,
        data: dict[str, Any],
        raw_file_path: str,
    ) -> str:
        """Write a ParsedContent JSON file and return its path.

        The parse path is derived from *raw_file_path* by swapping the step
        prefix (01_ingest → 02_parse), keeping the same article folder name.
        """
        path = parse_json_path(raw_file_path, job_id)
        self._ensure_dir(path)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, default=str)
        logger.debug("Wrote parsed content: %s", path)
        return path

    async def read_parsed(self, path: str) -> dict[str, Any]:
        return await self.read_json(path)

    # ------------------------------------------------------------------ #
    # Generic helpers                                                     #
    # ------------------------------------------------------------------ #

    async def read_json(self, path: str) -> dict[str, Any]:
        abs_path = self._resolve(path)
        with open(abs_path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    async def file_exists(self, path: str) -> bool:
        return os.path.isfile(self._resolve(path))
