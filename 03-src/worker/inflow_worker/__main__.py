"""本地 worker 主入口：``python -m inflow_worker``。

独立进程，复用 backend venv。**不调用 init_db()**（schema 归云端管），
只复用 ``inflow_core.core.database.async_session`` 直连云端 PostgreSQL。
启动时先 ``reclaim_own_host()`` 清理本机遗留租约，再进入认领循环。
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from inflow_core.core.utils.logger import setup_logging
from inflow_worker.settings import worker_settings

logger = logging.getLogger("inFlow.local_worker")


async def _run_loop() -> None:
    from inflow_worker.claims import claim_next_job, reclaim_own_host, release_lease
    from inflow_worker.runner import _heartbeat, mark_failed_guarded, process_job

    try:
        await reclaim_own_host()
    except Exception as exc:
        # DB 暂未就绪（如云端 5432 未开）不阻塞启动，进入轮询自愈
        logger.warning("reclaim_own_host 失败（DB 未就绪？）: %s", exc)

    logger.info(
        "worker 启动: host=%s scan=%.0fs lease=%ds heartbeat=%.0fs sftp=%s",
        worker_settings.worker_host,
        worker_settings.scan_interval_s,
        worker_settings.lease_seconds,
        worker_settings.heartbeat_interval_s,
        "on" if worker_settings.sftp_enabled else "off",
    )
    if not worker_settings.sftp_enabled:
        logger.warning(
            "SFTP 未配置（SFTP_HOST / SFTP_PIPELINE_DIR 为空）：PNG 卡片将不回传云端，"
            "job 会照常到 ready，但微信 bot 推卡将因云端无 PNG 而失败。"
            "生产启用请在 .env.local-worker 配置 SFTP_HOST 与 SFTP_PIPELINE_DIR。"
        )

    while True:
        try:
            job = await claim_next_job()
        except Exception as exc:
            logger.warning("认领失败（DB 不可达？）: %s，%ds 后重试", exc, worker_settings.scan_interval_s)
            await asyncio.sleep(worker_settings.scan_interval_s)
            continue

        if job is None:
            await asyncio.sleep(worker_settings.scan_interval_s)
            continue

        heartbeat = asyncio.create_task(_heartbeat(job.id))
        try:
            await process_job(job.id)
            logger.info("job %s 处理完成", job.id)
        except Exception as exc:
            logger.exception("job %s 处理异常: %s", job.id, exc)
            await mark_failed_guarded(job.id, f"worker 处理异常: {exc}")
        finally:
            heartbeat.cancel()
            await release_lease(job.id)


def main() -> None:
    setup_logging(log_dir="04-log/worker")
    try:
        asyncio.run(_run_loop())
    except KeyboardInterrupt:
        logger.info("worker 收到中断信号，退出")


if __name__ == "__main__":
    main()
