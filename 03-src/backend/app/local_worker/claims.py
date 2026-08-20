"""本地 worker 的 job 认领 / 租约 / 回收。

原子性：``FOR UPDATE SKIP LOCKED`` 防止多 worker 并发认领同一 job
（与云端 review_cron_loop 同款）。租约：认领时写 claimed_at，超时
（LEASE_SECONDS）后其他 worker 可重新认领；长任务靠心跳持续刷新。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import or_, select, update

from app.core.database import async_session
from app.core.models.ingest_job import IngestJob
from app.local_worker.settings import worker_settings

logger = logging.getLogger("inFlow.local_worker.claims")

# 外部 worker 可认领的中途状态（终态 ready/failed/cancelled 不认领）
_CLAIMABLE = (
    "pending", "capturing", "captured",
    "normalizing", "normalized",
    "transcribing", "transcribed",
    "parsing", "parsed",
    "composing", "composed",
    "indexing",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def claim_next_job() -> IngestJob | None:
    """原子认领一个可处理的外部 job；无则返回 None。"""
    lease_until = _now() - timedelta(seconds=worker_settings.lease_seconds)
    async with async_session() as db:
        stmt = (
            select(IngestJob)
            .where(
                IngestJob.external_processing.is_(True),
                IngestJob.status.in_(_CLAIMABLE),
                IngestJob.article_id.isnot(None),
                or_(
                    IngestJob.claimed_at.is_(None),
                    IngestJob.claimed_at < lease_until,
                ),
            )
            .order_by(IngestJob.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = (await db.execute(stmt)).scalar_one_or_none()
        if job is None:
            return None

        await db.execute(
            update(IngestJob)
            .where(IngestJob.id == job.id)
            .values(
                processing_host=worker_settings.worker_host,
                claimed_at=_now(),
            )
        )
        await db.commit()
        logger.info("认领 job=%s status=%s host=%s", job.id, job.status, worker_settings.worker_host)
        return job


async def release_lease(job_id: UUID) -> None:
    """释放租约（处理完成/失败后）。保留 processing_host 用于审计。

    所有权守卫：仅当 processing_host 仍是本机时才清空 claimed_at。
    若租约已被其他 worker 抢占（处理过程中超时被抢），本机不再越权修改。
    """
    async with async_session() as db:
        await db.execute(
            update(IngestJob)
            .where(
                IngestJob.id == job_id,
                IngestJob.processing_host == worker_settings.worker_host,
            )
            .values(claimed_at=None)
        )
        await db.commit()


async def reclaim_own_host() -> int:
    """清理本机遗留租约：重启后把本机曾认领但已中断的 job 置空 claimed_at。

    processing_host 存的是 ``hostname-pid``，重启后 PID 变化，故按 ``hostname-%``
    前缀匹配（host_prefix）。这样本机重启后能重新认领这些 job，避免永久卡死。
    返回清理数量。
    """
    async with async_session() as db:
        result = await db.execute(
            update(IngestJob)
            .where(
                IngestJob.processing_host.like(f"{worker_settings.host_prefix}-%"),
                IngestJob.status.in_(_CLAIMABLE),
            )
            .values(claimed_at=None)
            .returning(IngestJob.id)
        )
        ids = [row[0] for row in result.all()]
        await db.commit()
    if ids:
        logger.info("reclaim_own_host: 回收 %d 个本机遗留租约", len(ids))
    return len(ids)
