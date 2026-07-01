"""Generic web page adapter — fallback for any URL not claimed by a platform adapter.

Uses the existing parser_service._fetch_generic() cascade:
  trafilatura → Playwright (JS-rendered fallback) → BeautifulSoup.

This adapter always returns True from can_handle() and must be registered last
in the registry so it only matches after all specific adapters have declined.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from app.s1_ingest.adapters.base import AbstractAdapter, AdapterError
from app.s1_ingest.schema import RawCapture, RawMeta, RawContent

logger = logging.getLogger("trove.ingest.adapters.generic")


class GenericAdapter(AbstractAdapter):
    platform = "generic"
    version = "1.0.0"

    def can_handle(self, url: str) -> bool:
        # Accepts everything — must be last in registry.
        return True

    async def fetch(
        self,
        url: str,
        *,
        user_id: UUID,
        capture_method: str = "url",
        extra_context: Optional[dict] = None,
    ) -> RawCapture:
        logger.debug("GenericAdapter.fetch: %s", url[:100])

        try:
            from app.s1_ingest.fetchers import parser_service
            detected_platform = parser_service.detect_platform(url)
            result = await parser_service._fetch_generic(url, detected_platform)
        except Exception as exc:
            raise AdapterError(
                f"Generic fetch failed: {exc}",
                platform=self.platform,
                url=url,
            ) from exc

        meta = RawMeta(
            source_platform=self.platform,
            capture_method=capture_method,
            original_url=url,
            adapter_version=self.version,
            user_id=user_id,
        )

        raw = RawContent(
            title=result.get("title"),
            author=result.get("author"),
            content_type="article",
            raw_html=result.get("raw_html"),
            raw_text=result.get("raw_content"),
            cover_image=result.get("cover_image"),
            extra={"og_meta": result.get("og_meta", {})},
        )

        return RawCapture(meta=meta, raw=raw)

    def get_parse_template_id(self) -> str:
        return "generic"
