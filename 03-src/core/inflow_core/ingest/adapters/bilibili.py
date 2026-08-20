"""Bilibili adapter — articles (专栏/opus) and videos (BV*)."""

from __future__ import annotations

import re
import logging
from typing import Optional
from uuid import UUID

from inflow_core.ingest.adapters.base import AbstractAdapter, AdapterError
from inflow_core.ingest.schema import RawCapture, RawMeta, RawContent

logger = logging.getLogger("inFlow.ingest.adapters.bilibili")

_BILI_URL_RE = re.compile(
    r"https?://(?:www\.bilibili\.com|b23\.tv|bilibili\.com)/",
    re.IGNORECASE,
)


class BilibiliAdapter(AbstractAdapter):
    platform = "bilibili"
    version = "1.0.0"

    def can_handle(self, url: str) -> bool:
        return bool(_BILI_URL_RE.search(url))

    async def fetch(
        self,
        url: str,
        *,
        user_id: UUID,
        capture_method: str = "url",
        extra_context: Optional[dict] = None,
    ) -> RawCapture:
        logger.debug("BilibiliAdapter.fetch: %s", url[:100])

        is_video = (
            "/video/" in url or "BV" in url or "b23.tv" in url
        ) and "/read/" not in url and "/opus/" not in url

        content_type = "video" if is_video else "article"

        try:
            from inflow_core.ingest.fetchers import parser_service
            result = await parser_service._fetch_bilibili(url)
        except Exception as exc:
            raise AdapterError(
                f"Bilibili fetch failed: {exc}",
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
            content_type=content_type,
            raw_html=result.get("raw_html"),
            raw_text=result.get("raw_content"),
            cover_image=result.get("cover_image"),
            extra={"og_meta": result.get("og_meta", {})},
        )

        return RawCapture(meta=meta, raw=raw)

    def get_parse_template_id(self) -> str:
        return "bilibili_video"
