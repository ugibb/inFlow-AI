"""AbstractStorage — interface contract for all storage backends.

Concrete implementations (local filesystem, S3, OSS) must satisfy this
protocol.  Pipeline steps depend only on this interface, never on a concrete
class, so the storage backend can be swapped without touching business logic.
"""

from __future__ import annotations

import abc
from uuid import UUID
from typing import Any


class AbstractStorage(abc.ABC):
    """Storage backend interface for pipeline file I/O."""

    # ------------------------------------------------------------------ #
    # Raw capture files  (Step 1 → Step 2)                               #
    # ------------------------------------------------------------------ #

    @abc.abstractmethod
    async def write_raw(
        self,
        *,
        platform: str,
        job_id: UUID,
        data: dict[str, Any],
    ) -> str:
        """Serialise *data* and persist it as a raw-capture file.

        Returns the canonical path string that callers should store in
        ``ingest_jobs.raw_file_path``.

        Path convention:  data/raw/{platform}/{YYYYMMDD}/{job_id}.json
        """

    @abc.abstractmethod
    async def read_raw(self, path: str) -> dict[str, Any]:
        """Load and deserialise the raw-capture file at *path*."""

    # ------------------------------------------------------------------ #
    # Parsed-content files  (Step 2 → Step 3)                            #
    # ------------------------------------------------------------------ #

    @abc.abstractmethod
    async def write_parsed(
        self,
        *,
        job_id: UUID,
        data: dict[str, Any],
    ) -> str:
        """Serialise *data* and persist it as a parsed-content file.

        Returns the canonical path string stored in
        ``ingest_jobs.parsed_file_path``.

        Path convention:  data/parsed/{YYYYMMDD}/{job_id}.json
        """

    @abc.abstractmethod
    async def read_parsed(self, path: str) -> dict[str, Any]:
        """Load and deserialise the parsed-content file at *path*."""

    # ------------------------------------------------------------------ #
    # Generic helpers                                                     #
    # ------------------------------------------------------------------ #

    @abc.abstractmethod
    async def read_json(self, path: str) -> dict[str, Any]:
        """Read any JSON file by its storage-relative or absolute path."""

    @abc.abstractmethod
    async def file_exists(self, path: str) -> bool:
        """Return True if *path* exists in the storage backend."""
