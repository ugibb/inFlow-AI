"""Plugin 基类 + 状态模型 —— 外部协同能力（进程型 bot / API 型同步）插件化。

一个插件 = `plugins/<id>/` 下一个自包含目录：声明（plugin.py）+ 对外路由（router.py）
+ 可选进程入口（bot.py），自带版本与配置声明。新增插件 = 新增一个目录 + registry 注册一行。
"""
from abc import ABC
from dataclasses import dataclass, field
from typing import Optional

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class PluginStatus:
    """插件当前状态（`/api/plugins` 对前端的序列化视图）。

    状态机：进程型 `not_configured → stopped ⇄ running → error`；
            API 型 `not_configured → disabled ⇄ enabled`。
    """
    status: str                 # running / stopped / error / not_configured（API 型: enabled / disabled）
    config_ready: bool
    detail: str = ""
    health: dict = field(default_factory=dict)


class Plugin(ABC):
    """插件契约。

    进程型（kind="process"）：独立子进程，`start/stop` = 拉起 / 杀掉子进程（subprocess + PID）；
    API 型（kind="api"）：backend 内路由，`start/stop` = 功能开关（plugin_states 表 enabled）。
    """
    id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    kind: str = "api"           # "process" | "api"
    auto_start: bool = True
    required_config: list = field(default_factory=list)

    def routers(self) -> list:
        """插件对外提供的 API 路由（backend 启动时经 PluginManager 挂载）。"""
        return []

    def config_ready(self) -> bool:
        """required_config 是否已配齐（配齐才算可用，否则 not_configured）。"""
        return True

    async def status(self, db: AsyncSession | None = None) -> PluginStatus:
        """当前状态快照（含 health）。API 型可能需要 db 读 plugin_states。"""
        return PluginStatus(status="stopped", config_ready=self.config_ready())

    async def health(self, db: AsyncSession | None = None) -> dict:
        """心跳 / 最后活跃 / 错误详情等附加信息。"""
        return {}

    async def start(self, db: AsyncSession | None = None):
        """进程型: process.py 拉起子进程; API 型: 置 enabled。"""
        raise NotImplementedError

    async def stop(self, db: AsyncSession | None = None):
        """进程型: 杀子进程; API 型: 置 disabled。"""
        raise NotImplementedError
