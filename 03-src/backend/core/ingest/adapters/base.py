"""AbstractAdapter — interface contract for all platform adapters.

Implementing a new adapter requires only:
1. Subclass AbstractAdapter.
2. Set the class attributes: platform, version.
3. Implement can_handle() and fetch().
4. Register the instance in registry.py.

The adapter is responsible for producing a valid RawCapture.  It must NOT:
- Call an LLM.
- Write to the database.
- Perform Markdown conversion.
- Write to the articles table.
"""

from __future__ import annotations

import abc
from typing import Optional
from uuid import UUID

from backend.core.ingest.schema import RawCapture


class AbstractAdapter(abc.ABC):
    """Base class for all platform content adapters."""

    #: Unique platform identifier.  Used in file paths and ingest_jobs records.
    platform: str

    #: Adapter version string.  Increment when the platform changes its layout.
    #: Old raw files are preserved so content can be re-parsed without re-fetching.
    version: str = "1.0.0"

    @abc.abstractmethod
    def can_handle(self, url: str) -> bool:
        """Return True if this adapter can handle the given URL.

        Used by the registry to route an incoming URL to the correct adapter.
        The method should be fast (regexp match, domain check) — no network I/O.
        """

    @abc.abstractmethod
    async def fetch(
        self,
        url: str,
        *,
        user_id: UUID,
        capture_method: str = "url",
        extra_context: Optional[dict] = None,
    ) -> RawCapture:
        """Fetch raw content from *url* and return a RawCapture.

        Args:
            url:             The source URL to fetch.
            user_id:         ID of the user who initiated the capture.
            capture_method:  How the URL arrived (url | wechat_bot | browser_ext | paste).
            extra_context:   Optional platform-specific hints (e.g., pre-fetched HTML).

        Raises:
            AdapterError: If the content cannot be fetched after retries.
        """

    def get_parse_template_id(self) -> str:
        """Return the template ID used by the parse layer for this platform.

        Defaults to the platform name.  Override when the template ID differs.
        """
        return self.platform


class AdapterError(Exception):
    """Raised when an adapter cannot fetch the requested content."""

    def __init__(self, message: str, platform: str, url: str) -> None:
        super().__init__(message)
        self.platform = platform
        self.url = url
