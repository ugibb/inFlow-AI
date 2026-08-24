"""Douyin (抖音) adapter.

Delegates to parser_service._fetch_douyin() which uses Playwright to intercept
the internal /aweme/v1/web/aweme/detail/ API call.

Supports:
    https://v.douyin.com/<short>/          (share links)
    https://www.douyin.com/video/<id>
    https://www.douyin.com/note/<id>       (image notes)
"""

from __future__ import annotations

import re
import logging
from typing import Optional
from uuid import UUID

from backend.core.ingest.adapters.base import AbstractAdapter, AdapterError
from backend.core.ingest.schema import RawCapture, RawMeta, RawContent

logger = logging.getLogger("inFlow.ingest.adapters.douyin")

_DOUYIN_URL_RE = re.compile(
    r"https?://(?:v\.douyin\.com|www\.douyin\.com|iesdouyin\.com)/",
    re.IGNORECASE,
)


class DouyinAdapter(AbstractAdapter):
    platform = "douyin"
    version = "1.0.0"

    def can_handle(self, url: str) -> bool:
        return bool(_DOUYIN_URL_RE.search(url))

    async def fetch(
        self,
        url: str,
        *,
        user_id: UUID,
        capture_method: str = "url",
        extra_context: Optional[dict] = None,
    ) -> RawCapture:
        logger.debug("DouyinAdapter.fetch: %s", url[:100])

        try:
            from backend.core.ingest.fetchers import parser_service
            result = await parser_service._fetch_douyin(url)
        except Exception as exc:
            raise AdapterError(
                f"Douyin fetch failed: {exc}",
                platform=self.platform,
                url=url,
            ) from exc

        og = result.get("og_meta", {})
        content_type = "video"
        if "/note/" in url:
            content_type = "image"

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
            extra={"og_meta": og},
        )

        return RawCapture(meta=meta, raw=raw)

    def get_parse_template_id(self) -> str:
        return "generic"
