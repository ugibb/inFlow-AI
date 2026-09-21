r"""微信视频号 adapter — 登记专用（云端不抓取，由本地 worker + 人工播放完成）。

视频号与微信公众号**同域**（weixin.qq.com），唯一判别特征是路径前缀 ``/sph/``：

    https://weixin.qq.com/sph/<token>      → 视频号（本 adapter）
    https://mp.weixin.qq.com/s/<token>     → 公众号（WechatAdapter）
    https://channels.weixin.qq.com/...     → 视频号网页域

本 adapter 在 registry 中**必须排在 WechatAdapter 之前** —— 后者是
``https?://(?:mp\.weixin\.qq\.com|weixin\.qq\.com)/`` 的宽松正则，会抢先认领
``weixin.qq.com/sph/...``。

fetch() 直接拒绝：视频号媒体需要本地微信 PC 端的活跃页面连接（用户手动播放触发），
云端既无登录态也无该通道。云端只登记收件，抓取交给本地 worker 的
``skills/wechat_channels``（其失败会以 error_stage="manual_action" 落到前端，
提示用户「在微信里播放一次后重试」）。
"""

from __future__ import annotations

import re
import logging
from typing import Optional
from uuid import UUID

from backend.core.ingest.adapters.base import AbstractAdapter, AdapterError
from backend.core.ingest.schema import RawCapture

logger = logging.getLogger("inFlow.ingest.adapters.wechat_channels")

# 只认分享链路径，不认整个 weixin.qq.com 域（否则会抢走公众号）
_SPH_URL_RE = re.compile(
    r"https?://(?:[\w-]+\.)?weixin\.qq\.com/sph/",
    re.IGNORECASE,
)
# 视频号网页域（用户在 PC 端浏览时的域名）
_CHANNELS_HOST_RE = re.compile(
    r"https?://(?:[\w-]+\.)?channels\.weixin\.qq\.com/",
    re.IGNORECASE,
)


class WechatChannelsAdapter(AbstractAdapter):
    platform = "wechat_channels"
    version = "1.0.0"

    def can_handle(self, url: str) -> bool:
        return bool(_SPH_URL_RE.match(url) or _CHANNELS_HOST_RE.match(url))

    async def fetch(
        self,
        url: str,
        *,
        user_id: UUID,
        capture_method: str = "url",
        extra_context: Optional[dict] = None,
    ) -> RawCapture:
        logger.debug("WechatChannelsAdapter.fetch: %s", url[:100])
        raise AdapterError(
            "视频号仅由本地 worker 抓取（需本机微信 PC 端播放一次建立页面连接）",
            platform=self.platform,
            url=url,
        )

    def get_parse_template_id(self) -> str:
        # 视频号只有视频形态（无图文），采集前即可确定
        return "wechat_channels_video"
