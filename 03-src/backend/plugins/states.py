"""plugin_states 表读写 —— API 型插件的功能开关（enabled）持久化。

默认 enabled=true（迁移 020 初始化）；未建行时按 enabled 处理（向后兼容）。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import PluginState


async def get_enabled(db: AsyncSession, plugin_id: str) -> bool:
    r = await db.execute(select(PluginState.enabled).where(PluginState.plugin_id == plugin_id))
    val = r.scalar_one_or_none()
    return True if val is None else bool(val)


async def set_enabled(db: AsyncSession, plugin_id: str, enabled: bool) -> None:
    r = await db.execute(select(PluginState).where(PluginState.plugin_id == plugin_id))
    st = r.scalar_one_or_none()
    if st is None:
        db.add(PluginState(plugin_id=plugin_id, enabled=enabled))
    else:
        st.enabled = enabled
    await db.commit()
