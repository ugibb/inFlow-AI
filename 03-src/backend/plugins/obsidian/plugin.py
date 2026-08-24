"""Obsidian 同步插件声明 —— API 型（backend 内路由，功能开关）。

enabled/disabled 状态存 plugin_states 表：disabled 时 /api/sync 路由整体返回
503（经 PluginManager 挂载时注入开关依赖），路由代码本身不动。
"""
from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugins import states
from backend.plugins.base import Plugin, PluginStatus


class ObsidianPlugin(Plugin):
    id = "obsidian"
    name = "Obsidian 同步"
    description = "Obsidian 插件经 /api/sync 拉取文章到本地仓库"
    version = "1.0.0"
    kind = "api"
    auto_start = True

    def routers(self):
        from backend.plugins.obsidian.router import router
        return [router]

    async def status(self, db: AsyncSession | None = None) -> PluginStatus:
        enabled = True
        if db is not None:
            enabled = await states.get_enabled(db, self.id)
        return PluginStatus(
            status="enabled" if enabled else "disabled",
            config_ready=True,
        )

    async def health(self, db: AsyncSession | None = None) -> dict:
        from sqlalchemy import select, func
        from backend.core.models import Article
        health = {}
        if db is not None:
            try:
                r = await db.execute(select(func.count(Article.id)))
                health["articles"] = r.scalar_one_or_none() or 0
            except Exception:
                pass
        return health

    async def start(self, db: AsyncSession | None = None):
        if db is not None:
            await states.set_enabled(db, self.id, True)
        return True

    async def stop(self, db: AsyncSession | None = None):
        if db is not None:
            await states.set_enabled(db, self.id, False)
        return True


obsidian_plugin = ObsidianPlugin()
