"""插件管理 API —— 全插件状态快照 + 一键启停（超管权限）。

    GET  /api/plugins               全插件列表 + 状态（含配置就绪 / 进程存活 / 心跳）
    POST /api/plugins/{id}/start    启动
    POST /api/plugins/{id}/stop     停止
    POST /api/plugins/{id}/restart  重启
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.dependencies import require_superadmin
from backend.plugins.manager import plugin_manager

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


async def _one(db: AsyncSession, plugin_id: str) -> dict:
    for row in await plugin_manager.snapshot(db):
        if row["id"] == plugin_id:
            return row
    raise HTTPException(status_code=404, detail="插件不存在")


_OK_KEYS = {"start": "started", "stop": "stopped", "restart": "restarted"}


async def _run_action(plugin_id: str, db: AsyncSession, action: str) -> dict:
    try:
        ok = await getattr(plugin_manager, f"{action}_plugin")(plugin_id, db)
    except KeyError:
        raise HTTPException(status_code=404, detail="插件不存在")
    state = await _one(db, plugin_id)
    state[_OK_KEYS[action]] = ok
    return state


@router.get("")
async def list_plugins(
    _super=Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    return await plugin_manager.snapshot(db)


@router.post("/{plugin_id}/start")
async def start_plugin(
    plugin_id: str,
    _super=Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    return await _run_action(plugin_id, db, "start")


@router.post("/{plugin_id}/stop")
async def stop_plugin(
    plugin_id: str,
    _super=Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    return await _run_action(plugin_id, db, "stop")


@router.post("/{plugin_id}/restart")
async def restart_plugin(
    plugin_id: str,
    _super=Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    return await _run_action(plugin_id, db, "restart")
