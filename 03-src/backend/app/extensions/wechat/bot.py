"""Multi-account WeChat bot runner.

Reads bound WeChat accounts from the wechat_accounts table, spawns one async
long-polling loop per account, routes each inbound message to its owning
inFlow AI user via the X-Act-As-User header (requires the bot's service token
to be mapped to a superadmin user).

Run inside the same Docker image as the backend (which gives us DB access and
parser_service):

    inFlow_BASE=http://backend:8000 inFlow_TOKEN=<superadmin-token> \
    python -m app.extensions.wechat.bot

See memory: inFlow_wechat_bot, reference_openclaw_weixin.
"""
from __future__ import annotations

import asyncio
import base64
import html
import json
import os
import re
import secrets
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Callable, Dict, Optional
from uuid import UUID

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import async_session
from app.core.models import User, WechatAccount
from app.core.utils.logger import configure_third_party_loggers, get_logger, setup_logging

logger = get_logger("wexinBot")


# ── ilinkai wire constants ─────────────────────────────────────────────
ILINK_APP_ID = "bot"
ILINK_APP_CLIENT_VERSION = "132099"
BOT_AGENT = "inFlowBot/0.2-multi"
LONGPOLL_TIMEOUT_S = 35
# 相同 errcode（如 -14 session timeout）持续出现时，日志节流间隔（秒）
ERRCODE_LOG_THROTTLE_S = 300
# getupdates 常见错误码 → 用户可看懂的中文说明（首次出现时以 ERROR 级打印 + 操作指引）
ERRCODE_HINTS: dict[int, str] = {
    -14: "微信登录会话已过期，请到「个人中心 → 微信绑定」解绑后重新扫码绑定。",
    40001: "ilink 凭证无效，请在「个人中心 → 微信绑定」解绑后重新扫码绑定。",
    42001: "ilink access_token 已过期，请在「个人中心 → 微信绑定」解绑后重新扫码绑定。",
    88001: "ilink 会话已失效，请在「个人中心 → 微信绑定」解绑后重新扫码绑定。",
}

URL_RE = re.compile(
    r"https?://[^\s一-鿿\"'<>{}|\\^`，。、；：！？（）【】《》]+",
    re.IGNORECASE,
)

# Heuristic: queries containing any of these keywords are routed to deep research
# automatically (no need for /r prefix). Conservative — only obvious "synthesis"
# verbs. Other queries default to the fast single-shot RAG path.
COMPLEX_KEYWORDS = (
    "梳理", "综述", "对比", "比较", "演化", "演变", "整理一下", "归纳",
    "哪些", "全面", "系统讲", "系统总结", "汇总", "不同观点",
    "演进", "发展脉络", "区别和联系",
)


def _is_complex_query(text: str) -> bool:
    """Cheap rule-based classifier — no LLM call.

    Returns True if the query is "obviously" a synthesis/comparison/list task.
    Errs on the side of False (fast path) when ambiguous; users can force the
    research path with /r prefix.
    """
    if not text or len(text) < 12:
        return False
    return any(kw in text for kw in COMPLEX_KEYWORDS)


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
    return {"channel_version": "2.4.3", "bot_agent": BOT_AGENT}


def _client_id() -> str:
    return f"inFlow-bot:{int(time.time() * 1000)}-{secrets.token_hex(4)}"


def _extract_url(text: str) -> Optional[str]:
    m = URL_RE.search(html.unescape(text or ""))
    return m.group(0).rstrip(".,;:!?)]") if m else None


def _looks_like_url(text: str) -> bool:
    t = text.strip().lower()
    return t.startswith("http://") or t.startswith("https://")


def _reply_with_title(base: str, title: Optional[str]) -> str:
    """Append article title when API returns one, e.g. 「已在库里了：Token | …」."""
    t = (title or "").strip()
    if not t or _looks_like_url(t):
        return base
    return f"{base}：{t}"


# ── inFlow AI backend calls (per-user via X-Act-As-User) ────────────────
class inFlowClient:
    def __init__(self, base_url: str, service_token: str):
        self.base_url = base_url.rstrip("/")
        self.token = service_token
        # one shared httpx client; longer than long-poll for upload paths
        # trust_env=False: macOS 系统代理会把 localhost 走代理，导致 503
        self._client = httpx.AsyncClient(timeout=90.0, trust_env=False)

    async def close(self):
        await self._client.aclose()

    def _h(self, target_user_id: UUID) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "X-Act-As-User": str(target_user_id),
            "Content-Type": "application/json",
        }

    async def add_article(
        self, target_user_id: UUID, url: str
    ) -> tuple[bool, str, Optional[str], Optional[str]]:
        """Submit a URL for ingestion.

        Returns:
            (ok, reply_text, job_id, status)
            job_id is None on network/auth errors or when no IngestJob exists.
            status is one of: capturing | already_exists | already_processing | None.
        """
        try:
            r = await self._client.post(
                f"{self.base_url}/api/ingest/url",
                headers=self._h(target_user_id),
                json={"url": url},
            )
        except Exception as e:
            return False, f"❌ 网络错误：{type(e).__name__}", None, None

        if r.status_code == 202:
            body: dict = {}
            try:
                body = r.json()
            except Exception:
                pass
            api_status = body.get("status", "")
            job_id: Optional[str] = body.get("job_id")  # may be None for already_exists
            title = body.get("title")
            if api_status == "already_exists":
                return True, _reply_with_title(
                    "📚 这篇文章已在你的 inFlow 库里了", title
                ), job_id, api_status
            if api_status == "already_processing":
                return True, _reply_with_title(
                    "⏳ 这篇文章正在处理中，稍后即可在 inFlow 阅读", title
                ), job_id, api_status
            return True, _reply_with_title(
                "✅ 已加入队列，解析完成后即可在 inFlow 阅读", title
            ), job_id, api_status
        if r.status_code == 401:
            return False, (
                "❌ 添加失败：后端未认可 bot 凭证。"
                "请确认 .env 中 SERVICE_TOKENS 与 SERVICE_TOKEN_WECHAT_BOT 一致，"
                "且 SERVICE_TOKENS 含「token:weaiw」。"
                "云端：./deploy/cloud/stop-server.sh && ./deploy/cloud/start-server.sh --restart。"
            ), None, None
        if r.status_code == 503:
            return False, (
                "❌ 添加失败：无法连接本地后端（可能被系统代理拦截）。"
                "请执行 ./deploy/cloud/stop-server.sh && ./deploy/cloud/start-server.sh 重启服务后重试。"
            ), None, None
        try:
            detail = r.json().get("detail", "")
        except Exception:
            detail = r.text[:100]
        return False, f"❌ 添加失败 ({r.status_code})：{detail}", None, None

    async def research_stream(
        self, target_user_id: UUID, query: str, mode: str = "sequential"
    ) -> AsyncIterator[dict]:
        """Open an SSE stream against research endpoints, yielding decoded events.

        mode='sequential' → /ask (fixed 4-stage)
        mode='tool'       → /agent (ReAct loop with library tools)
        """
        endpoint = "/api/research/agent" if mode == "tool" else "/api/research/ask"
        async with self._client.stream(
            "POST",
            f"{self.base_url}{endpoint}",
            headers=self._h(target_user_id),
            json={"query": query},
            timeout=300,
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                yield {"stage": "error", "message": f"研究助理启动失败 ({resp.status_code}): {body[:200]!r}"}
                return
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                try:
                    yield json.loads(line[6:])
                except Exception as e:
                    logger.warning(f"bad SSE line: {e}: {line[:120]}")

    async def create_spark(self, target_user_id: UUID, sentence: str) -> dict:
        """Call /api/articles/spark — generates a full article from a one-liner topic.
        Returns the article dict (id, title, content...) or {error: str}."""
        try:
            r = await self._client.post(
                f"{self.base_url}/api/articles/spark",
                headers=self._h(target_user_id),
                json={"sentence": sentence, "enable_search": False},
                timeout=240,
            )
        except Exception as e:
            return {"error": f"网络错误：{type(e).__name__}"}
        if r.status_code != 201:
            try:
                detail = r.json().get("detail", "")
            except Exception:
                detail = r.text[:200]
            return {"error": f"生成失败 ({r.status_code})：{detail}"}
        return r.json()

    async def ask(self, target_user_id: UUID, question: str) -> str:
        try:
            r = await self._client.post(
                f"{self.base_url}/api/assistant/ask",
                headers=self._h(target_user_id),
                json={"question": question, "top_k": 5},
            )
        except Exception as e:
            return f"❌ 网络错误：{type(e).__name__}"
        if r.status_code != 200:
            try:
                detail = r.json().get("detail", "")
            except Exception:
                detail = r.text[:100]
            return f"❌ 检索失败 ({r.status_code})：{detail}"
        data = r.json()
        answer = (data.get("answer") or "").strip() or "（空回答）"
        cites = data.get("citations") or []
        if cites:
            titles = "、".join(c.get("title", "")[:20] for c in cites[:3])
            return f"{answer}\n\n📚 参考：{titles}"
        return answer


# ── Per-account long-poll loop ─────────────────────────────────────────
class AccountWorker:
    def __init__(self, account_id: UUID, lm: inFlowClient):
        self.account_id = account_id
        self.lm = lm
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        # Latest context_token per WeChat user (required for ilink sendmessage)
        self._context_tokens: Dict[str, str] = {}
        # 相同 errcode 日志节流：仅首次 + 每隔 N 秒打印一次，避免 session timeout 刷屏
        self._last_errcode: Optional[int] = None
        self._last_errcode_log_ts: float = 0.0
        self._errcode_repeat: int = 0
        # -14 session timeout 连续出现次数（≥3 次才判定会话失效并自动解绑，防瞬时抖动）
        self._session_timeout_streak: int = 0
        # 账号所属用户名（首次加载时缓存，用于日志区分是哪个用户的账号）
        self._owner_name: Optional[str] = None

    def start(self):
        self._task = asyncio.create_task(self._run(), name=f"wechat-{self.account_id}")
        self._cb_task = asyncio.create_task(
            self._callback_loop(), name=f"wechat-cb-{self.account_id}"
        )

    async def stop(self):
        self._stop.set()
        for t in (self._task, getattr(self, "_cb_task", None)):
            if t:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

    async def _load(self) -> Optional[WechatAccount]:
        async with async_session() as db:
            r = await db.execute(
                select(WechatAccount).where(WechatAccount.id == self.account_id)
            )
            return r.scalar_one_or_none()

    async def _save_cursor(self, cursor: str):
        async with async_session() as db:
            await db.execute(
                update(WechatAccount)
                .where(WechatAccount.id == self.account_id)
                .values(sync_cursor=cursor)
            )
            await db.commit()

    async def _mark_seen(self):
        async with async_session() as db:
            await db.execute(
                update(WechatAccount)
                .where(WechatAccount.id == self.account_id)
                .values(last_seen_at=datetime.now(timezone.utc))
            )
            await db.commit()

    async def _touch_context_token(self, sender: str, ctx: str) -> None:
        """Cache fresh context_token and refresh pending callbacks for this user."""
        if not sender or not ctx:
            return
        self._context_tokens[sender] = ctx
        from app.core.models.wechat_callback import WechatCallbackQueue

        async with async_session() as db:
            await db.execute(
                update(WechatCallbackQueue)
                .where(
                    WechatCallbackQueue.wechat_account_id == self.account_id,
                    WechatCallbackQueue.sender_id == sender,
                    WechatCallbackQueue.status.in_(["pending", "ready", "failed"]),
                )
                .values(context_token=ctx)
            )
            await db.commit()

    async def _post_sendmessage(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        token: str,
        msg: dict,
        *,
        label: str = "sendmessage",
        timeout: float = 30,
        suppress_ok_log: bool = False,
    ) -> bool:
        """POST ilink sendmessage; return True only on HTTP 200."""
        body = {"msg": msg, "base_info": _base_info()}
        try:
            r = await client.post(
                f"{base_url}/ilink/bot/sendmessage",
                headers=_ilink_headers(token),
                json=body,
                timeout=timeout,
            )
            if r.status_code != 200:
                logger.warning(
                    "[%s] %s HTTP %s: %s",
                    self.account_id,
                    label,
                    r.status_code,
                    r.text[:500],
                )
                return False
            try:
                data = r.json() if r.text.strip() else {}
            except Exception:
                data = {}
            ret = data.get("ret", 0)
            errcode = data.get("errcode", 0)
            if (ret not in (0, None) and ret != 0) or (
                errcode not in (0, None) and errcode != 0
            ):
                logger.warning(
                    "[%s] %s API error ret=%s errcode=%s body=%s",
                    self.account_id,
                    label,
                    ret,
                    errcode,
                    r.text[:500],
                )
                return False
            if not suppress_ok_log:
                logger.info("[%s] %s ok: %s", self.account_id, label, r.text[:200])
            return True
        except Exception as exc:
            logger.warning("[%s] %s failed: %s", self.account_id, label, exc)
            return False

    async def _send_text(self, client: httpx.AsyncClient, base_url: str, token: str,
                         to_user_id: str, context_token: Optional[str], text: str) -> None:
        body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": _client_id(),
                "message_type": 2,
                "message_state": 2,
                "item_list": [{"type": 1, "text_item": {"text": text}}],
                **({"context_token": context_token} if context_token else {}),
            },
            "base_info": _base_info(),
        }
        try:
            r = await client.post(
                f"{base_url}/ilink/bot/sendmessage",
                headers=_ilink_headers(token),
                json=body,
                timeout=15,
            )
            if r.status_code != 200:
                logger.warning(f"[{self.account_id}] sendmessage {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.warning(f"[{self.account_id}] sendmessage failed: {e}")

    async def _handle(self, client: httpx.AsyncClient, acct: WechatAccount, msg: dict):
        sender = msg.get("from_user_id") or ""
        ctx = msg.get("context_token") or ""
        if sender and ctx:
            await self._touch_context_token(sender, ctx)
        text = ""
        for it in (msg.get("item_list") or []):
            if it.get("type") == 1:
                text = (it.get("text_item") or {}).get("text", "") or ""
                break

        if not text:
            await self._send_text(client, acct.base_url, acct.token, sender, ctx,
                                  "目前只支持文本消息（链接或问题）哦")
            return

        text_stripped = text.strip()

        # /h or /help — show available commands
        if text_stripped in ("/h", "/help", "帮助"):
            await self._send_text(
                client, acct.base_url, acct.token, sender, ctx,
                "📚 inFlow AI 用法\n\n"
                "• 直接发链接 → 自动存入你的知识库\n"
                "• 直接发问题 → 自动判断走快路径（3-5s）或深度研究（20-40s）\n"
                "  含「梳理/综述/对比/演化/哪些…」等词会自动深度研究\n"
                "• /r <问题> → 强制 4 阶段研究（拆解→检索→综述→自审）\n"
                "• /a <问题> → 强制工具型 Agent（ReAct 循环：自己选 search/read/list 工具）\n"
                "• /c <主题> → 灵感创作（AI 一句话生成完整文章入库，30-90s）\n"
                "  例：/c AI Agent 在 PM 工作流中的应用\n"
                "• /help → 显示本帮助",
            )
            return

        url = _extract_url(text)
        if url:
            ok, reply, job_id, api_status = await self.lm.add_article(acct.user_id, url)
            await self._send_text(client, acct.base_url, acct.token, sender, ctx, reply)
            if ok and job_id:
                callback_status = await self._enqueue_callback(
                    account_id=self.account_id,
                    job_id=job_id,
                    sender_id=sender,
                    context_token=ctx,
                    api_status=api_status or "",
                )
                from app.core.pipeline.pipeline_log import log_wechat_url_submitted

                log_wechat_url_submitted(
                    job_id,
                    ok=ok,
                    api_status=api_status or "",
                    callback_status=callback_status,
                )
            return

        # Spark creation: /c <topic> → AI 灵感创作 generates full article
        if text_stripped.startswith("/c ") or text_stripped.startswith("/create "):
            topic = text_stripped.split(" ", 1)[1].strip()
            if not topic:
                await self._send_text(
                    client, acct.base_url, acct.token, sender, ctx,
                    "请在 /c 后面写主题。例：/c AI Agent 在产品经理工作流中的应用",
                )
                return
            await self._handle_spark(client, acct, sender, ctx, topic)
            return

        # Tool-using agent: /a or /agent prefix
        if text_stripped.startswith("/a ") or text_stripped.startswith("/agent "):
            query = text_stripped.split(" ", 1)[1].strip()
            if not query:
                await self._send_text(
                    client, acct.base_url, acct.token, sender, ctx,
                    "请在 /a 后面写具体问题。例：/a 帮我从库里挑 5 篇做 AI Agent 综述的素材",
                )
                return
            await self._handle_research(client, acct, sender, ctx, query, mode="tool")
            return

        # Sequential research: explicit /r or /research prefix
        explicit_research = False
        if text_stripped.startswith("/r ") or text_stripped.startswith("/research "):
            text_stripped = text_stripped.split(" ", 1)[1].strip()
            explicit_research = True
            if not text_stripped:
                await self._send_text(
                    client, acct.base_url, acct.token, sender, ctx,
                    "请在 /r 后面写具体问题。例：/r 梳理我对 AI Agent 的看法演化",
                )
                return

        # Automatic routing: complex queries (by rule) go sequential research even without /r
        if explicit_research or _is_complex_query(text_stripped):
            await self._handle_research(
                client, acct, sender, ctx, text_stripped, mode="sequential"
            )
            return

        # Default: single-turn RAG (fast path)
        reply = await self.lm.ask(acct.user_id, text)
        logger.info(f"[{acct.account_id}] ask q={text[:40]!r} → {reply[:80]}")
        await self._send_text(client, acct.base_url, acct.token, sender, ctx, reply)

    async def _send_image(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        token: str,
        to_user_id: str,
        context_token: Optional[str],
        png_path: str,
        *,
        job_id: UUID | str | None = None,
        push_label: str | None = None,
    ) -> bool:
        """Upload PNG to iLink CDN and send as type=2 image message."""
        from app.extensions.wechat.ilink_media import upload_image_item

        png = Path(png_path)
        if not png.is_file():
            logger.warning("[%s] send_image: file not found: %s", self.account_id, png_path)
            return False

        image_bytes = png.read_bytes()
        size_kb = len(image_bytes) // 1024
        ctx = self._context_tokens.get(to_user_id) or context_token
        label = f"send_image to={to_user_id[:16]} size={size_kb}KB"

        try:
            item = await upload_image_item(
                client,
                base_url=base_url,
                headers=_ilink_headers(token),
                to_user_id=to_user_id,
                image_bytes=image_bytes,
                base_info=_base_info(),
            )
        except Exception as exc:
            logger.warning("[%s] %s CDN upload failed: %s", self.account_id, label, exc)
            return False

        msg: dict = {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": _client_id(),
            "message_type": 2,
            "message_state": 2,
            "item_list": [item],
        }
        if ctx:
            msg["context_token"] = ctx
        else:
            logger.warning(
                "[%s] %s: no context_token (message may not deliver)",
                self.account_id,
                label,
            )

        sent = await self._post_sendmessage(
            client,
            base_url,
            token,
            msg,
            label=label,
            timeout=60,
            suppress_ok_log=bool(job_id and push_label),
        )
        if sent and job_id and push_label:
            from app.core.pipeline.pipeline_log import log_job_event

            log_job_event(
                job_id,
                push_label,
                f"send_image to={to_user_id[:16]}",
                f"size={size_kb}KB",
                "ok",
            )
        return sent

    async def _enqueue_callback(
        self,
        *,
        account_id: UUID,
        job_id: str,
        sender_id: str,
        context_token: Optional[str],
        api_status: str,
    ) -> str:
        """Write a callback row; if the job is already done, mark it ready immediately."""
        from uuid import UUID as _UUID
        from app.core.models.wechat_callback import WechatCallbackQueue
        from app.core.models.ingest_job import IngestJob
        from sqlalchemy import select as _select

        job_uuid = _UUID(job_id)
        initial_status = "pending"

        # If the job is already at 'ready', no pipeline notification will come — mark ready now.
        if api_status == "already_exists":
            async with async_session() as db:
                result = await db.execute(
                    _select(IngestJob).where(IngestJob.id == job_uuid)
                )
                job = result.scalar_one_or_none()
            if job and job.status == "ready" and job.raw_file_path:
                initial_status = "ready"

        async with async_session() as db:
            row = WechatCallbackQueue(
                job_id=job_uuid,
                wechat_account_id=account_id,
                sender_id=sender_id,
                context_token=context_token,
                status=initial_status,
            )
            db.add(row)
            await db.commit()
        return initial_status

    async def _revive_failed_callbacks(self) -> None:
        """Re-queue failed callbacks whose ingest job already finished (ready)."""
        from sqlalchemy import text as _text

        async with async_session() as db:
            result = await db.execute(
                _text(
                    """
                    UPDATE wechat_callback_queue AS q
                    SET status = 'ready', error = NULL
                    FROM ingest_jobs AS j
                    WHERE q.job_id = j.id
                      AND q.wechat_account_id = :aid
                      AND q.status = 'failed'
                      AND j.status = 'ready'
                    RETURNING q.job_id
                    """
                ),
                {"aid": str(self.account_id)},
            )
            rows = result.fetchall()
            await db.commit()
            if rows:
                ids = ", ".join(str(r[0]).split("-")[0] for r in rows)
                logger.info(
                    "[%s] revived failed callback(s) → ready: %s",
                    self.account_id,
                    ids,
                )

    async def _callback_loop(self) -> None:
        """Poll wechat_callback_queue every 5 s; push ready cards (pre-rendered by pipeline)."""
        await self._revive_failed_callbacks()

        async with httpx.AsyncClient(timeout=30) as img_client:
            while not self._stop.is_set():
                try:
                    await self._process_ready_callbacks(img_client)
                except Exception as exc:
                    logger.exception(f"[{self.account_id}] callback_loop err: {exc}")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass

    async def _process_ready_callbacks(self, img_client: httpx.AsyncClient) -> None:
        """Pick up to 3 ready callbacks, push pre-rendered PNG, mark sent."""
        from app.core.models.wechat_callback import WechatCallbackQueue
        from app.core.models.ingest_job import IngestJob
        from sqlalchemy import select as _sel, update as _upd

        # Fetch ready rows for this account
        async with async_session() as db:
            result = await db.execute(
                _sel(WechatCallbackQueue)
                .where(
                    WechatCallbackQueue.wechat_account_id == self.account_id,
                    WechatCallbackQueue.status == "ready",
                )
                .limit(3)
            )
            rows = result.scalars().all()

        for row in rows:
            row_id = row.id
            job_id = row.job_id
            sender_id = row.sender_id
            ctx = row.context_token
            from app.core.pipeline.pipeline_log import log_job_event, resolve_phase_label, resolve_phase_task_name

            push_label = resolve_phase_label("wechat_push", "article")

            # Atomically claim the row
            async with async_session() as db:
                updated = await db.execute(
                    _upd(WechatCallbackQueue)
                    .where(
                        WechatCallbackQueue.id == row_id,
                        WechatCallbackQueue.status == "ready",
                    )
                    .values(status="rendering")
                )
                await db.commit()
                if updated.rowcount == 0:
                    continue  # another worker claimed it

            try:
                from pathlib import Path
                from app.core.models.article import Article
                from app.core.shared.storage.conventions import display_card_png_path

                # Resolve ingest job + article content type
                async with async_session() as db:
                    job_result = await db.execute(
                        _sel(IngestJob).where(IngestJob.id == job_id)
                    )
                    job = job_result.scalar_one_or_none()
                    content_type = "article"
                    if job and job.article_id:
                        article = await db.get(Article, job.article_id)
                        if article and article.content_type:
                            content_type = article.content_type

                if not job:
                    raise ValueError(f"IngestJob not found: {job_id}")
                if not job.raw_file_path:
                    raise ValueError(f"No raw_file_path for job {job_id}")

                push_label = resolve_phase_label("wechat_push", content_type)
                png_path = display_card_png_path(job.raw_file_path, job_id)
                if not Path(png_path).is_file() or Path(png_path).stat().st_size == 0:
                    if job.external_processing:
                        # 外部 worker job：PNG 由本地 worker 经 SFTP 回传云端，
                        # 云端无 raw/parsed/asr 文件可补渲染，直接失败等 worker 重跑重传。
                        raise ValueError(
                            f"Card PNG not uploaded for external job {job_id}: "
                            f"{png_path}（等待本地 worker SFTP 回传）"
                        )
                    # Fallback: jobs from mixed versions / path drifts may miss the
                    # expected 03_display PNG; try a one-shot re-render before failing.
                    from app.s4_compose.card_renderer import render_card_png_for_job

                    log_job_event(job_id, push_label, "卡片缺失", "尝试即时补渲染")
                    try:
                        rendered_png = await render_card_png_for_job(
                            str(job_id),
                            raw_file_path=job.raw_file_path,
                            asr_file_path=job.asr_file_path,
                            parsed_file_path=job.parsed_file_path,
                            source_platform=job.source_platform,
                            progress_cb=lambda m: log_job_event(job_id, push_label, f"补渲染: {m}"),
                        )
                    except Exception as exc:
                        raise ValueError(
                            f"Card PNG rerender failed for job {job_id}: {exc}"
                        ) from exc
                    png_path = rendered_png
                    if not Path(png_path).is_file() or Path(png_path).stat().st_size == 0:
                        raise ValueError(
                            f"Card PNG not found for job {job_id} after rerender"
                        )

                size_kb = Path(png_path).stat().st_size // 1024
                push_task = resolve_phase_task_name("wechat_push", content_type)
                log_job_event(
                    job_id,
                    push_label,
                    f"▶ 任务开始：{push_task}",
                    f"platform={job.source_platform or '?'}",
                    f"png={size_kb}KB",
                )
                log_job_event(job_id, push_label, "回调已就绪", "等待 Bot 推送")

                acct = await self._load()
                if not acct:
                    raise ValueError("Account disappeared while rendering")

                sent_ok = await self._send_image(
                    img_client,
                    acct.base_url,
                    acct.token,
                    sender_id,
                    ctx,
                    png_path,
                    job_id=job_id,
                    push_label=push_label,
                )
                if not sent_ok:
                    # context_token 过期时回退 ready，等用户再发一条消息刷新 token
                    async with async_session() as db:
                        await db.execute(
                            _upd(WechatCallbackQueue)
                            .where(WechatCallbackQueue.id == row_id)
                            .values(
                                status="ready",
                                error="send_image failed: context_token stale?",
                            )
                        )
                        await db.commit()
                    logger.warning(
                        "[%s] card send deferred (will retry): job=%s",
                        self.account_id,
                        str(job_id).split("-")[0],
                    )
                    continue

                async with async_session() as db:
                    await db.execute(
                        _upd(WechatCallbackQueue)
                        .where(WechatCallbackQueue.id == row_id)
                        .values(
                            status="sent",
                            card_path=png_path,
                            sent_at=datetime.now(timezone.utc),
                        )
                    )
                    await db.commit()

                log_job_event(job_id, push_label, "■ 完成", "推送成功")

            except Exception as exc:
                log_job_event(job_id, push_label, "✗ 失败", str(exc)[:120])
                logger.exception(
                    f"[{self.account_id}] card push failed: {exc}"
                )
                async with async_session() as db:
                    await db.execute(
                        _upd(WechatCallbackQueue)
                        .where(WechatCallbackQueue.id == row_id)
                        .values(status="failed", error=str(exc)[:500])
                    )
                    await db.commit()

    async def _handle_spark(
        self, client: httpx.AsyncClient, acct: WechatAccount,
        sender: str, ctx: str, topic: str,
    ):
        """Generate a full article from a topic via /api/articles/spark and push the result."""
        # ack
        await self._send_text(
            client, acct.base_url, acct.token, sender, ctx,
            f"✨ 灵感创作启动：「{topic[:50]}」\n（LLM 写大纲+各章节，约 30-90 秒，完成后会推送链接）",
        )

        result = await self.lm.create_spark(acct.user_id, topic)
        if "error" in result:
            await self._send_text(
                client, acct.base_url, acct.token, sender, ctx,
                f"⚠️ {result['error']}",
            )
            return

        article_id = result.get("id", "")
        title = (result.get("title") or "Untitled").strip()
        # First paragraph of content as preview
        content = (result.get("content") or "").strip()
        preview = ""
        if content:
            # strip leading markdown heading if any
            first_para = next(
                (p.strip() for p in content.split("\n\n") if p.strip() and not p.strip().startswith("#")),
                "",
            )
            preview = first_para[:180] + ("…" if len(first_para) > 180 else "")

        # deep link to /read
        public_base = os.environ.get("inFlow_PUBLIC_BASE", "http://localhost")
        link = f"{public_base}/read/{article_id}" if article_id else ""

        msg = f"✅ 已生成《{title[:50]}》"
        if preview:
            msg += f"\n\n{preview}"
        if link:
            msg += f"\n\n📖 完整阅读：{link}"
        await self._send_text(client, acct.base_url, acct.token, sender, ctx, msg)

    async def _handle_research(
        self, client: httpx.AsyncClient, acct: WechatAccount,
        sender: str, ctx: str, query: str, mode: str = "sequential",
    ):
        """Multi-stage research with progress messages between stages.

        Educational value: user sees the Agent's thinking unfold. In sequential
        mode (4 stages); in tool mode (Agent picks tools each step).
        """
        # Initial ack — wording differs slightly to teach user the distinction
        ack = (
            "🤖 智能体已启动（会自主选工具调用，约 20-40 秒）"
            if mode == "tool"
            else "🔬 研究助理已启动（4 阶段：拆解→检索→综述→自审，约 20-40 秒）"
        )
        await self._send_text(client, acct.base_url, acct.token, sender, ctx, ack)

        STAGE_ICONS = {
            "plan": "🧩", "retrieve": "🔍", "synthesize": "✍️",
            "critique": "🪞", "final": "✅", "error": "⚠️",
            "start": "🚀", "thought": "💭", "tool_call": "🔧", "tool_result": "✓",
        }
        last_stage = ""
        final_data: Optional[dict] = None
        try:
            async for ev in self.lm.research_stream(acct.user_id, query, mode=mode):
                stage = ev.get("stage", "")
                msg = ev.get("message", "")
                if stage == "final":
                    final_data = ev.get("data") or {}
                    continue
                if stage == "error":
                    await self._send_text(
                        client, acct.base_url, acct.token, sender, ctx,
                        f"⚠️ {msg}",
                    )
                    return
                # Only send progress on stage transition or when stage stays same
                # but message is different (e.g. plan: "拆解…" → "拆出 N 个子问题…").
                icon = STAGE_ICONS.get(stage, "•")
                await self._send_text(
                    client, acct.base_url, acct.token, sender, ctx,
                    f"{icon} {msg}",
                )
                last_stage = stage
        except Exception as e:
            logger.exception(f"research stream failed: {e}")
            await self._send_text(
                client, acct.base_url, acct.token, sender, ctx,
                f"⚠️ 研究助理出错：{type(e).__name__}",
            )
            return

        if not final_data or not final_data.get("answer"):
            await self._send_text(
                client, acct.base_url, acct.token, sender, ctx,
                "（没拿到最终结果，请重试）",
            )
            return

        answer = final_data["answer"]
        critique = final_data.get("critique") or ""
        cites = final_data.get("citations") or []
        cite_text = ""
        if cites:
            titles = "、".join((c.get("title", "")[:20]) for c in cites[:5])
            cite_text = f"\n\n📚 参考：{titles}"

        # Send answer (may be 300-500字)
        await self._send_text(
            client, acct.base_url, acct.token, sender, ctx,
            f"✅ 综述：\n\n{answer}{cite_text}",
        )
        if critique:
            await self._send_text(
                client, acct.base_url, acct.token, sender, ctx,
                f"🪞 自我审稿：\n\n{critique}",
            )

    def _log_errcode(self, account_id: str, errcode: int, errmsg: str) -> None:
        """节流打印 getupdates 的 errcode：相同错误码仅首次立即打印，
        之后每隔 ERRCODE_LOG_THROTTLE_S 打印一次，并附带累计次数，避免刷屏。
        对已知「会话失效」类错误码，首次以 ERROR 级打印并附中文操作指引。"""
        who = f" ({self._owner_name})" if self._owner_name else ""
        now = time.time()
        hint = ERRCODE_HINTS.get(errcode)
        first_sight = errcode != self._last_errcode
        if first_sight:
            self._errcode_repeat = 1
            if hint:
                logger.error(
                    f"[{account_id}{who}] 微信 bot 会话异常 (errcode={errcode}, {errmsg})。{hint}"
                )
            else:
                logger.warning(f"[{account_id}{who}] server errcode={errcode} msg={errmsg}")
        else:
            self._errcode_repeat += 1
            if now - self._last_errcode_log_ts < ERRCODE_LOG_THROTTLE_S:
                return
            logger.warning(
                f"[{account_id}{who}] server errcode={errcode} msg={errmsg} "
                f"(持续出现，已重复 {self._errcode_repeat} 次，每 "
                f"{ERRCODE_LOG_THROTTLE_S}s 汇报一次)"
                + (f"。{hint}" if hint else "")
            )
        self._last_errcode = errcode
        self._last_errcode_log_ts = now

    def _reset_errcode_log(self) -> None:
        """一次成功轮询后重置节流状态，使下次出现的错误能立即打印首条。"""
        self._last_errcode = None
        self._last_errcode_log_ts = 0.0
        self._errcode_repeat = 0
        self._session_timeout_streak = 0

    async def _run(self):
        # Per-worker httpx client (long-poll-friendly timeout).
        read_timeout = LONGPOLL_TIMEOUT_S + 15
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=read_timeout, write=10.0, pool=10.0)
        ) as client:
            backoff = 1.0
            while not self._stop.is_set():
                acct = await self._load()
                if not acct or not acct.is_active:
                    logger.info(f"[{self.account_id}] account gone/inactive — exiting worker")
                    return

                # 首次加载时缓存账号所属用户名，便于日志区分是哪个用户的账号
                if self._owner_name is None:
                    async with async_session() as db:
                        r = await db.execute(
                            select(User.username).where(User.id == acct.user_id)
                        )
                        self._owner_name = r.scalar_one_or_none()

                try:
                    r = await client.post(
                        f"{acct.base_url}/ilink/bot/getupdates",
                        headers=_ilink_headers(acct.token),
                        json={"get_updates_buf": acct.sync_cursor or "",
                              "base_info": _base_info()},
                    )
                    r.raise_for_status()
                    resp = r.json()
                    backoff = 1.0
                except httpx.ReadTimeout:
                    # ilink 长轮询在部分网络下会以读超时结束，仍视为 worker 存活
                    await self._mark_seen()
                    continue
                except Exception as e:
                    logger.warning(f"[{acct.account_id}] poll err: {str(e)[:30]}; backoff {backoff}s")
               
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue

                errcode = resp.get("errcode") or resp.get("ret")
                if errcode and errcode != 0:
                    errmsg = resp.get("errmsg") or ""
                    self._log_errcode(acct.account_id, errcode, errmsg)
                    # -14 session timeout：连续出现 ≥3 次（约 15s）才判定会话失效，防瞬时抖动误杀
                    if errcode == -14:
                        self._session_timeout_streak += 1
                    else:
                        self._session_timeout_streak = 0
                    # 会话失效/凭证无效 → 标记解绑，supervisor 不再为该账号起 worker，直到重新绑定
                    if errcode in (40001, 42001, 88001) or (
                        errcode == -14 and self._session_timeout_streak >= 3
                    ):
                        who = f" ({self._owner_name})" if self._owner_name else ""
                        logger.error(
                            f"[{acct.account_id}{who}] 微信会话已失效 (errcode={errcode})，"
                            f"已自动解绑。请该用户在「个人中心 → 微信绑定」重新扫码。"
                        )
                        async with async_session() as db:
                            await db.execute(
                                update(WechatAccount)
                                .where(WechatAccount.id == acct.id)
                                .values(is_active=False,
                                        unbound_at=datetime.now(timezone.utc))
                            )
                            await db.commit()
                        return
                    await asyncio.sleep(5)
                    continue

                # 仅真正成功的轮询（errcode 为 0/None）才重置节流状态；
                # 否则 -14 等错误码每次都被当作「首次」，日志节流永远无法生效
                self._reset_errcode_log()

                new_cursor = resp.get("get_updates_buf") or acct.sync_cursor or ""
                if new_cursor != (acct.sync_cursor or ""):
                    await self._save_cursor(new_cursor)
                await self._mark_seen()

                for m in (resp.get("msgs") or []):
                    if m.get("message_type") != 1:  # USER only
                        continue
                    try:
                        await self._handle(client, acct, m)
                    except Exception as e:
                        import traceback
                        logger.error(f"[{acct.account_id}] handle err: {e}\n{traceback.format_exc()}")


# ── Supervisor: spawns / culls workers from DB ─────────────────────────
class BotSupervisor:
    REFRESH_INTERVAL_S = 30

    def __init__(self, lm: inFlowClient):
        self.lm = lm
        self.workers: Dict[UUID, AccountWorker] = {}
        self._stop = asyncio.Event()

    async def _list_active_ids(self) -> set[UUID]:
        async with async_session() as db:
            r = await db.execute(
                select(WechatAccount.id).where(WechatAccount.is_active.is_(True))
            )
            return {row[0] for row in r.all()}

    async def stop(self):
        self._stop.set()
        for w in list(self.workers.values()):
            await w.stop()
        await self.lm.close()

    async def run(self):
        logger.info("Bot supervisor started")
        while not self._stop.is_set():
            try:
                active = await self._list_active_ids()
                # Spawn new
                for aid in active - self.workers.keys():
                    logger.info(f"Spawning worker for account {aid}")
                    w = AccountWorker(aid, self.lm)
                    w.start()
                    self.workers[aid] = w
                # Cull removed
                for aid in list(self.workers.keys() - active):
                    logger.info(f"Stopping worker for account {aid}")
                    await self.workers[aid].stop()
                    del self.workers[aid]
            except Exception as e:
                logger.exception(f"Supervisor refresh err: {e}")

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.REFRESH_INTERVAL_S)
            except asyncio.TimeoutError:
                pass


async def _async_main():
    base = os.environ.get("inFlow_BASE", "http://localhost:8000")
    token = os.environ.get("inFlow_TOKEN", "")
    if not token:
        logger.error("Missing inFlow_TOKEN env (superadmin service token)")
        sys.exit(2)

    sup = BotSupervisor(inFlowClient(base, token))
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(sup.stop()))
    await sup.run()


def main():
    settings = get_settings()
    # 与 backend 共用 04-log/backend/日期.log，便于 ./deploy/cloud/start-server.sh --logs 一处查看
    setup_logging(
        log_dir=settings.get_log_dir_path(),
        file_level=settings.log_level,
    )
    configure_third_party_loggers(
        log_sql=settings.log_sql,
        log_access=False,
    )
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
