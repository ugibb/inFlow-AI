"""WeChat Official Account adapter.

Delegates HTML fetching to the existing parser_service._fetch_generic()
with platform='wechat', then wraps the result in the standard RawCapture format.

Supported URL patterns:
    https://mp.weixin.qq.com/s/...
    https://weixin.qq.com/...
"""

from __future__ import annotations

import re
import logging
from typing import Optional
from uuid import UUID

from app.s1_ingest.adapters.base import AbstractAdapter, AdapterError
from app.s1_ingest.schema import RawCapture, RawMeta, RawContent

logger = logging.getLogger("inFlow.ingest.adapters.wechat")

_WECHAT_URL_RE = re.compile(
    r"https?://(?:mp\.weixin\.qq\.com|weixin\.qq\.com)/",
    re.IGNORECASE,
)


class WechatAdapter(AbstractAdapter):
    platform = "wechat"
    version = "1.0.0"

    def can_handle(self, url: str) -> bool:
        return bool(_WECHAT_URL_RE.match(url))

    async def fetch(
        self,
        url: str,
        *,
        user_id: UUID,
        capture_method: str = "url",
        extra_context: Optional[dict] = None,
    ) -> RawCapture:
        logger.debug("WechatAdapter.fetch: %s", url[:100])

        try:
            from app.s1_ingest.fetchers import parser_service
            result = await parser_service._fetch_generic(url, "wechat")
        except Exception as exc:
            detail = str(exc).strip() or type(exc).__name__
            raise AdapterError(
                f"WeChat fetch failed: {detail}",
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
        return "wechat_article"
