"""Feishu (飞书 / Lark) document adapter.

飞书文档是 React SPA，内容在前端 hydration 后注入 DOM，抓取需要 Playwright。
支持已开启公开分享（知情人可查看）的文档；私有文档会收到登录跳转错误。

Supported URL patterns:
    https://<tenant>.feishu.cn/docx/<doc_id>    — 新版文档
    https://<tenant>.feishu.cn/docs/<doc_id>    — 旧版文档
    https://<tenant>.feishu.cn/wiki/<wiki_id>   — 知识库页面
    https://<tenant>.larksuite.com/...           — 海外版 Lark
"""

from __future__ import annotations

import re
import logging
from typing import Optional
from uuid import UUID

from backend.core.ingest.adapters.base import AbstractAdapter, AdapterError
from backend.core.ingest.schema import RawCapture, RawMeta, RawContent

logger = logging.getLogger("inFlow.ingest.adapters.feishu")

_FEISHU_URL_RE = re.compile(
    r"https?://[^/]*(?:feishu\.cn|larksuite\.com)/",
    re.IGNORECASE,
)


class FeishuAdapter(AbstractAdapter):
    platform = "feishu"
    version = "1.0.0"

    def can_handle(self, url: str) -> bool:
        return bool(_FEISHU_URL_RE.search(url))

    async def fetch(
        self,
        url: str,
        *,
        user_id: UUID,
        capture_method: str = "url",
        extra_context: Optional[dict] = None,
    ) -> RawCapture:
        logger.debug("FeishuAdapter.fetch: %s", url[:100])

        try:
            from backend.core.ingest.fetchers import parser_service
            result = await parser_service._fetch_feishu(url)
        except Exception as exc:
            raise AdapterError(
                f"Feishu fetch failed: {exc}",
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
