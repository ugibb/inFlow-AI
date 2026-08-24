"""WeChat 推送助手——spark 建文后相似文章推送。

原 `extensions/review/service.py` 的 `send_wechat` 迁出；该文件是唯一入口
（articles.py 引用）。review 的生成/调度逻辑已并入 routers/_pending/review.py。
"""
import base64
import logging
import secrets
import time

import httpx

from backend.core.models import WechatAccount

logger = logging.getLogger("inFlow.wechat_push")

ILINK_APP_ID = "bot"
ILINK_APP_CLIENT_VERSION = "132099"
BOT_AGENT_PUSH = "inFlowReview/0.1"


# ── Wire helpers (parallel to wechat_bot.py) ───────────────────────────
def _random_uin() -> str:
    n = secrets.randbelow(2**32)
    return base64.b64encode(str(n).encode()).decode()


def _ilink_headers(token: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": _random_uin(),
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": ILINK_APP_CLIENT_VERSION,
    }


def _base_info() -> dict:
    return {"channel_version": "2.4.3", "bot_agent": BOT_AGENT_PUSH}


def _client_id() -> str:
    return f"inFlow-review:{int(time.time() * 1000)}-{secrets.token_hex(4)}"


async def send_wechat(client: httpx.AsyncClient, acct: WechatAccount, text: str) -> bool:
    """Send a single text message to the user via their bound bot.

    The recipient is `acct.wechat_user_id` (the user who scanned to bind).
    Returns True on HTTP 200, False otherwise.
    """
    if not acct.wechat_user_id:
        logger.warning(f"acct {acct.id} has no wechat_user_id; cannot push")
        return False
    body = {
        "msg": {
            "from_user_id": "",
            "to_user_id": acct.wechat_user_id,
            "client_id": _client_id(),
            "message_type": 2,
            "message_state": 2,
            "item_list": [{"type": 1, "text_item": {"text": text}}],
        },
        "base_info": _base_info(),
    }
    try:
        r = await client.post(
            f"{acct.base_url}/ilink/bot/sendmessage",
            headers=_ilink_headers(acct.token),
            json=body,
            timeout=20,
        )
        if r.status_code != 200:
            logger.warning(f"sendmessage {r.status_code}: {r.text[:200]}")
            return False
        return True
    except Exception as e:
        logger.warning(f"sendmessage error: {e}")
        return False
