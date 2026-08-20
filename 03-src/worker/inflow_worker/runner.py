"""本地 worker 的 job 执行器。

复用云端 ``run_job_resume`` 的断点续跑逻辑（pending/capturing 分支会重新采集），
仅在其 compose 成功后插入 ``on_composed`` 钩子：把本地 PNG 经 SFTP 直传云端
pipeline 目录（原子落盘 .tmp → rename），回传失败则 job 停在 composed→failed。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update

from inflow_core.core.database import async_session
from inflow_core.core.models.ingest_job import IngestJob
from inflow_worker.settings import worker_settings

logger = logging.getLogger("inFlow.local_worker.runner")


async def process_job(job_id: UUID) -> None:
    """处理一个外部 job。

    崩溃在采集中途（status=capturing）先回退 pending 让 run_job_resume 重新采集；
    其余状态直接走 run_job_resume 的断点续跑各分支，无需重写 pipeline 序列。
    """
    async with async_session() as db:
        job = await db.get(IngestJob, job_id)
        if job and job.status == "capturing":
            from inflow_core.ingest.orchestrator import force_set_status

            await force_set_status(db, job_id, "pending")

    from inflow_core.ingest.orchestrator import run_job_resume

    await run_job_resume(job_id=job_id, on_composed=_upload_card_png_via_sftp)


async def _heartbeat(job_id: UUID) -> None:
    """每 HEARTBEAT_INTERVAL_S 刷新 claimed_at，防止长任务（如听悟 ASR 数小时）超租约被抢。

    所有权守卫：仅当 processing_host 仍是本机时刷新。若租约已被抢占
    （rowcount=0），停止心跳——本机不再是 owner，不再为他人续租。
    """
    while True:
        await asyncio.sleep(worker_settings.heartbeat_interval_s)
        try:
            async with async_session() as db:
                result = await db.execute(
                    update(IngestJob)
                    .where(
                        IngestJob.id == job_id,
                        IngestJob.processing_host == worker_settings.worker_host,
                    )
                    .values(claimed_at=datetime.now(timezone.utc))
                )
                await db.commit()
                if result.rowcount == 0:
                    logger.warning("heartbeat: job %s 已非本机租约，停止心跳", job_id)
                    return
        except Exception as exc:
            logger.warning("heartbeat failed job=%s: %s", job_id, exc)


async def _upload_card_png_via_sftp(job_id: UUID, png_path: str) -> bool:
    """compose 成功后把本地 PNG 经 SFTP 直传云端 pipeline 目录。

    - 未配置 SFTP_HOST / SFTP_PIPELINE_DIR → 跳过（阶段 2 空跑），返回 True
    - 目标相对路径由 raw_file_path 推导（与 bot 读取路径同源），剥 data/ 前缀
    - 原子落盘：put 到 {rel}.tmp 再 rename，避免 bot 读到半文件
    - 失败返回 False → _compose_and_continue 让 job 停在 composed→failed
    """
    if not worker_settings.sftp_enabled:
        logger.info("SFTP 未配置，跳过 PNG 回传 job=%s png=%s", job_id, png_path)
        return True

    async with async_session() as db:
        job = await db.get(IngestJob, job_id)
        raw_file_path = job.raw_file_path if job else None
    if not raw_file_path:
        logger.error("SFTP 回传: job %s 无 raw_file_path，无法推导目标路径", job_id)
        return False

    from inflow_core.core.shared.storage.conventions import ext_display_card_png_rel

    rel = ext_display_card_png_rel(raw_file_path, job_id)
    return await _sftp_upload(png_path, rel)


async def _sftp_upload(local_path: str, rel_path: str) -> bool:
    """SFTP 直传（subprocess 调系统 sftp，走公钥鉴权，复用 SSH 22）。

    batch：mkdir -p 目标目录 → put 到 .tmp → rename 为最终名 → exit。
    """
    dest_dir = "/".join(rel_path.split("/")[:-1]) or "."
    dest_dir_abs = f"{worker_settings.sftp_pipeline_dir.rstrip('/')}/{dest_dir}"
    dest_abs = f"{worker_settings.sftp_pipeline_dir.rstrip('/')}/{rel_path}"
    host = f"{worker_settings.sftp_user}@{worker_settings.sftp_host}"

    batch = (
        f'mkdir -p "{dest_dir_abs}"\n'
        f'put "{local_path}" "{dest_abs}.tmp"\n'
        f'rename "{dest_abs}.tmp" "{dest_abs}"\n'
        "exit\n"
    )

    cmd = ["sftp", "-b", "-", "-P", str(worker_settings.sftp_port), host]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        logger.error("未找到 sftp 命令，无法回传 PNG（macOS/Linux 自带，确认 PATH）")
        return False

    # 超时兜底：网络黑洞时 sftp 可能永远挂起，worker 严格串行会因此卡死整个队列。
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=batch.encode("utf-8")),
            timeout=120,
        )
    except asyncio.TimeoutError:
        proc.kill()
        logger.error("sftp 回传超时（120s），已终止: %s", rel_path)
        return False

    if proc.returncode != 0:
        logger.error(
            "sftp 回传失败 rc=%s job=png=%s err=%s",
            proc.returncode, rel_path,
            stderr.decode("utf-8", "replace")[:300],
        )
        return False

    logger.info("PNG 已回传云端: %s (%s)", dest_abs, rel_path)
    return True


async def mark_failed_guarded(job_id: UUID, message: str) -> None:
    """process_job 抛出未捕获异常时，把 job 标记为 failed。

    仅当满足全部条件才标记：
    - job 非终态（ready/failed/cancelled 不动）
    - processing_host 仍是本机（已被其他 worker 抢占时不越权修改）
    状态变更走 transition()（原子 CAS，见 state_machine），保持状态机一致性。
    """
    try:
        from inflow_core.ingest.orchestrator import transition

        async with async_session() as db:
            job = (
                await db.execute(select(IngestJob).where(IngestJob.id == job_id))
            ).scalar_one_or_none()
            if job is None:
                return
            if job.status in ("ready", "failed", "cancelled"):
                return
            if job.processing_host != worker_settings.worker_host:
                logger.warning(
                    "mark_failed: job %s 已非本机租约（host=%s），跳过",
                    job_id, job.processing_host,
                )
                return
            await transition(
                db,
                job_id=job_id,
                current_status=job.status,
                target_status="failed",
                error_stage="worker",
                error_message=str(message)[:500],
            )
            logger.error("job %s 标记 failed (error_stage=worker)", job_id)
    except Exception as exc:
        logger.error("mark_failed_guarded 失败 job=%s: %s", job_id, exc)
