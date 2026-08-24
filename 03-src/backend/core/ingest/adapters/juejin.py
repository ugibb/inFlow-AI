"""Juejin (掘金) adapter.

Juejin uses standard SSR HTML.  trafilatura handles it well via the generic
cascade, so we delegate directly to _fetch_generic().
"""

from __future__ import annotations

import re
import logging
from typing import Optional
from uuid import UUID

from backend.core.ingest.adapters.base import AbstractAdapter, AdapterError
from backend.core.ingest.schema import RawCapture, RawMeta, RawContent

logger = logging.getLogger("inFlow.ingest.adapters.juejin")

_JUEJIN_URL_RE = re.compile(
    r"https?://juejin\.cn/",
    re.IGNORECASE,
)


class JuejinAdapter(AbstractAdapter):
    platform = "juejin"
    version = "1.0.0"

    def can_handle(self, url: str) -> bool:
        return bool(_JUEJIN_URL_RE.search(url))

    async def fetch(
        self,
        url: str,
        *,
        user_id: UUID,
        capture_method: str = "url",
        extra_context: Optional[dict] = None,
    ) -> RawCapture:
        logger.debug("JuejinAdapter.fetch: %s", url[:100])

        try:
            from backend.core.ingest.fetchers import parser_service
            result = await parser_service._fetch_generic(url, "juejin")
        except Exception as exc:
            raise AdapterError(
                f"Juejin fetch failed: {exc}",
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
