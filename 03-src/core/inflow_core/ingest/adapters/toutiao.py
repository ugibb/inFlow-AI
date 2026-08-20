"""Toutiao (今日头条) adapter.

Delegates to parser_service._fetch_toutiao() which uses the mobile SSR
endpoint (m.toutiao.com) to bypass the desktop JS challenge.
"""

from __future__ import annotations

import re
import logging
from typing import Optional
from uuid import UUID

from inflow_core.ingest.adapters.base import AbstractAdapter, AdapterError
from inflow_core.ingest.schema import RawCapture, RawMeta, RawContent

logger = logging.getLogger("inFlow.ingest.adapters.toutiao")

_TOUTIAO_URL_RE = re.compile(
    r"https?://(?:www\.|m\.)?toutiao\.com/",
    re.IGNORECASE,
)


class ToutiaoAdapter(AbstractAdapter):
    platform = "toutiao"
    version = "1.0.0"

    def can_handle(self, url: str) -> bool:
        return bool(_TOUTIAO_URL_RE.search(url))

    async def fetch(
        self,
        url: str,
        *,
        user_id: UUID,
        capture_method: str = "url",
        extra_context: Optional[dict] = None,
    ) -> RawCapture:
        logger.debug("ToutiaoAdapter.fetch: %s", url[:100])

        try:
            from inflow_core.ingest.fetchers import parser_service
            result = await parser_service._fetch_toutiao(url)
        except Exception as exc:
            raise AdapterError(
                f"Toutiao fetch failed: {exc}",
                platform=self.platform,
                url=url,
            ) from exc

        og = result.get("og_meta", {})

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
            extra={"og_meta": og},
        )

        return RawCapture(meta=meta, raw=raw)

    def get_parse_template_id(self) -> str:
        return "generic"
