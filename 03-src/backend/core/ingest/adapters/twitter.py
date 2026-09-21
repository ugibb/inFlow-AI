"""X / Twitter adapter — 登记专用（云端不抓取，由本地 worker 携带浏览器 cookie 抓取）。

匹配域：``twitter.com`` / ``x.com``（含 www.、mobile. 等子域）/ ``t.co`` 短链。

云端只登记 stub，实际抓取由本地 worker 的 ``skills/twitter`` 承接：先 yt-dlp
探测（带 Firefox cookie）判断有无视频轨，有则走视频管线，无则带 cookie 抓图文正文。
因此云端**不猜** content_type（stub 一律 article，worker capture 回写真实值）。

fetch() 拒绝的原因：X 的图文与视频均需登录态 cookie，云端无浏览器 cookie 通道。
"""

from __future__ import annotations

import re
import logging
from typing import Optional
from uuid import UUID

from backend.core.ingest.adapters.base import AbstractAdapter, AdapterError
from backend.core.ingest.schema import RawCapture

logger = logging.getLogger("inFlow.ingest.adapters.twitter")

# 锚定 host，不用子串 —— ``"x.com" in url`` 会命中 netflix.com
_TWITTER_URL_RE = re.compile(
    r"https?://(?:[\w-]+\.)?(?:twitter\.com|x\.com|t\.co)/",
    re.IGNORECASE,
)


class TwitterAdapter(AbstractAdapter):
    platform = "twitter"
    version = "1.0.0"

    def can_handle(self, url: str) -> bool:
        return bool(_TWITTER_URL_RE.match(url))

    async def fetch(
        self,
        url: str,
        *,
        user_id: UUID,
        capture_method: str = "url",
        extra_context: Optional[dict] = None,
    ) -> RawCapture:
        logger.debug("TwitterAdapter.fetch: %s", url[:100])
        raise AdapterError(
            "X / Twitter 仅由本地 worker 抓取（需本机浏览器登录态 cookie）",
            platform=self.platform,
            url=url,
        )

    # get_parse_template_id 用默认值（= platform）：图文/视频两形态在云端无法区分，
    # worker capture 回写 raw.content_type 与 template_used 后再由解析层决定。
