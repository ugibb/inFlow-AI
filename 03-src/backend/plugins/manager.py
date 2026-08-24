"""PluginManager —— 插件状态聚合、启停调度、进程监督。

- 注册表：内置插件在 registry.py 声明，backend 启动时加载
- 状态聚合：为前端 `/api/plugins` 提供全插件状态快照
- 启停调度：start/stop/restart 收敛到 manager；进程型经 process.py，API 型改 plugin_states 开关
- 进程监督：进程型插件 PID 落 `.server/plugins/{id}.pid`；backend 退出时优雅停止
- 自动恢复：auto_start=true 的进程型插件在 backend 启动时自动拉起
"""
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugins.base import Plugin, PluginStatus

logger = logging.getLogger(__name__)


class PluginManager:
    def __init__(self):
        self._plugins: dict[str, Plugin] = {}
        self._loaded = False

    def load_registry(self) -> None:
        from backend.plugins.registry import BUILTIN_PLUGINS
        self._plugins = dict(BUILTIN_PLUGINS)
        self._loaded = True

    def all(self) -> list:
        if not self._loaded:
            self.load_registry()
        return list(self._plugins.values())

    def get(self, plugin_id: str):
        if not self._loaded:
            self.load_registry()
        return self._plugins.get(plugin_id)

    async def startup(self, db: AsyncSession | None = None) -> None:
        """backend 启动：进程型 auto_start 插件自动拉起（API 型开关由 plugin_states 决定）。"""
        self.load_registry()
        for plugin in self.all():
            if plugin.kind != "process" or not plugin.auto_start:
                continue
            try:
                ok = await plugin.start(db)
                logger.info("plugin %s auto-start -> %s", plugin.id, "running" if ok else "skipped")
            except Exception:
                logger.exception("plugin %s auto-start failed", plugin.id)

    async def shutdown(self, db: AsyncSession | None = None) -> None:
        """backend 退出：优雅停止全部运行中进程型插件。"""
        for plugin in reversed(self.all()):
            if plugin.kind != "process":
                continue
            try:
                await plugin.stop(db)
                logger.info("plugin %s stopped on shutdown", plugin.id)
            except Exception:
                logger.exception("plugin %s stop on shutdown failed", plugin.id)

    async def snapshot(self, db: AsyncSession | None = None) -> list:
        """全插件状态快照（`/api/plugins` 响应）。"""
        out = []
        for plugin in self.all():
            try:
                st = await plugin.status(db)
                health = st.health or {}
            except Exception:
                st = PluginStatus(
                    status="error",
                    config_ready=plugin.config_ready(),
                    detail="状态判定异常",
                )
                health = {}
            out.append({
                "id": plugin.id,
                "name": plugin.name,
                "description": plugin.description,
                "version": plugin.version,
                "kind": plugin.kind,
                "status": st.status,
                "config_ready": st.config_ready,
                "auto_start": plugin.auto_start,
                "detail": st.detail,
                "health": health,
            })
        return out

    async def _action(self, plugin_id: str, db: AsyncSession | None, action: str) -> bool:
        plugin = self.get(plugin_id)
        if plugin is None:
            raise KeyError(plugin_id)
        if action == "start":
            return bool(await plugin.start(db))
        if action == "stop":
            return bool(await plugin.stop(db))
        if action == "restart":
            await plugin.stop(db)
            return bool(await plugin.start(db))
        raise ValueError(action)

    async def start_plugin(self, plugin_id: str, db: AsyncSession | None = None) -> bool:
        return await self._action(plugin_id, db, "start")

    async def stop_plugin(self, plugin_id: str, db: AsyncSession | None = None) -> bool:
        return await self._action(plugin_id, db, "stop")

    async def restart_plugin(self, plugin_id: str, db: AsyncSession | None = None) -> bool:
        return await self._action(plugin_id, db, "restart")


plugin_manager = PluginManager()
