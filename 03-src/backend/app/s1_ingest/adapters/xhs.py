"""Xiaohongshu (小红书) adapter.

Delegates to parser_service._fetch_xhs() which implements:
  curl_cffi (Chrome TLS impersonation) → __INITIAL_STATE__ parse
  → Playwright fallback → OG meta last resort.
"""

from __future__ import annotations

import re
import logging
from typing import Optional
from uuid import UUID

from app.s1_ingest.adapters.base import AbstractAdapter, AdapterError
from app.s1_ingest.schema import RawCapture, RawMeta, RawContent

logger = logging.getLogger("inFlow.ingest.adapters.xhs")

_XHS_URL_RE = re.compile(
    r"https?://(?:www\.xiaohongshu\.com|xhslink\.com)/",
    re.IGNORECASE,
)


class XhsAdapter(AbstractAdapter):
    platform = "xhs"
    version = "1.0.0"

    def can_handle(self, url: str) -> bool:
        return bool(_XHS_URL_RE.search(url))

    async def fetch(
        self,
        url: str,
        *,
        user_id: UUID,
        capture_method: str = "url",
        extra_context: Optional[dict] = None,
    ) -> RawCapture:
        logger.debug("XhsAdapter.fetch: %s", url[:100])

        try:
            from app.s1_ingest.fetchers import parser_service
            result = await parser_service._fetch_xhs(url)
        except Exception as exc:
            raise AdapterError(
                f"XHS fetch failed: {exc}",
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
        return "xhs_note"
