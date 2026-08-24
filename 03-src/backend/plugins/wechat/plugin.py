"""微信 Bot 插件声明 —— 进程型（独立子进程，长轮询接收收藏与 /r /a /c 命令）。

启动方式：backend PluginManager 按 auto_start 拉起（`python -m backend.plugins.wechat.bot`）；
与 start-server.sh 直跑双路径兼容（探测到已存活不重复拉起）。
"""
import os
import sys

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import get_settings
from backend.core.paths import get_project_root
from backend.core.models import WechatAccount
from backend.plugins import process
from backend.plugins.base import Plugin, PluginStatus


class WechatPlugin(Plugin):
    id = "wechat"
    name = "微信 Bot"
    description = "长轮询接收微信收藏与 /r /a /c 命令，推送精华卡"
    version = "1.0.0"
    kind = "process"
    auto_start = True
    required_config = ["service_token_wechat_bot"]

    # ── 配置 ───────────────────────────────────────────────
    def config_ready(self) -> bool:
        return bool(get_settings().service_token_wechat_bot)

    def routers(self):
        from backend.plugins.wechat.router import router
        return [router]

    def _bot_env(self) -> dict:
        env = dict(os.environ)
        settings = get_settings()
        # bot 进程读取 inFlow_BASE / inFlow_TOKEN / inFlow_PUBLIC_BASE（见 bot.py:1140）
        env.setdefault("inFlow_BASE", "http://127.0.0.1:8000")
        env.setdefault("inFlow_PUBLIC_BASE", "http://127.0.0.1:8080")
        env["inFlow_TOKEN"] = settings.service_token_wechat_bot or ""
        return env

    # ── 状态 ───────────────────────────────────────────────
    async def status(self, db: AsyncSession | None = None) -> PluginStatus:
        if not self.config_ready():
            return PluginStatus(
                status="not_configured", config_ready=False,
                detail="缺少 SERVICE_TOKEN_WECHAT_BOT",
            )
        alive, _ = process.find_alive_pid(self.id)
        health = await self.health(db)
        if alive:
            return PluginStatus(status="running", config_ready=True, health=health)
        return PluginStatus(status="stopped", config_ready=True, health=health)

    async def health(self, db: AsyncSession | None = None) -> dict:
        alive, pid = process.find_alive_pid(self.id)
        health = {"alive": alive, "pid": pid}
        if db is not None:
            try:
                r = await db.execute(
                    select(func.count(WechatAccount.id)).where(
                        WechatAccount.is_active.is_(True)
                    )
                )
                health["accounts"] = r.scalar_one_or_none() or 0
            except Exception:
                pass  # 心跳数据非关键，失败不影响状态判定
        return health

    # ── 启停 ───────────────────────────────────────────────
    async def start(self, db: AsyncSession | None = None):
        if not self.config_ready():
            return False
        alive, _ = process.find_alive_pid(self.id)
        if alive:
            return True  # start-server.sh 已拉起，识别为 running 不重复启动
        log_dir = get_project_root() / "04-log" / "wechat-bot"
        cmd = [sys.executable, "-m", "backend.plugins.wechat.bot"]
        pid = process.start_bot(self.id, cmd, self._bot_env(), log_dir)
        return pid is not None

    async def stop(self, db: AsyncSession | None = None):
        return process.stop_bot(self.id)


wechat_plugin = WechatPlugin()
