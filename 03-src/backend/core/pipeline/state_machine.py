"""IngestJob state machine.

Enforces valid status transitions for ingest_jobs rows and persists them to
the database.  All pipeline steps must transition job status through these
helpers — never by writing raw SQL directly.

Valid status graph (图文 path):
    pending → capturing → captured → parsing → parsed → indexing → ready

Valid status graph (音频 path):
    pending → capturing → captured → transcribing → transcribed
      → parsing → parsed → indexing → ready

Valid status graph (视频 path, reserved):
    pending → capturing → captured
      → preprocessing → preprocessed → transcribing → transcribed
      → parsing → parsed → indexing → ready

Any stage can transition to: failed | cancelled

Retry semantics:
    resume_for_retry() resets a failed job to the specified target step so the
    orchestrator can resume from that point using already-computed files.
    retry_count is incremented each time; after MAX_RETRIES the job stays failed.

MAX_RETRIES: maximum retries before permanently failing.
"""

from __future__ import annotations

import logging
from uuid import UUID
from typing import Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models.ingest_job import IngestJob

logger = logging.getLogger("inFlow.pipeline.state_machine")

MAX_RETRIES = 3

# Allowed forward transitions.  A transition not in this map is forbidden.
_TRANSITIONS: dict[str, list[str]] = {
    "pending":        ["capturing"],
    "capturing":      ["captured", "failed", "cancelled"],
    "captured":       ["normalizing", "transcribing", "parsing", "preprocessing", "failed", "cancelled"],
    # 图文 text normalization
    "normalizing":    ["normalized", "failed", "cancelled"],
    "normalized":     ["parsing", "failed", "cancelled"],
    # 音频/视频 transcription path
    "transcribing":   ["transcribed", "failed", "cancelled"],
    "transcribed":    ["parsing", "failed", "cancelled"],
    # 视频 preprocessing path (reserved for future video support)
    "preprocessing":  ["preprocessed", "failed", "cancelled"],
    "preprocessed":   ["transcribing", "failed", "cancelled"],
    # AI parse path (shared by all content types)
    "parsing":        ["parsed", "failed", "cancelled"],
    "parsed":         ["composing", "failed", "cancelled"],
    "composing":      ["composed", "failed", "cancelled"],
    "composed":       ["indexing", "failed", "cancelled"],
    # Semantic index step (renamed from "displaying")
    "indexing":       ["ready", "failed", "cancelled"],
    "ready":          [],           # terminal
    "failed":         ["pending"],  # manual retry resets to pending
    "cancelled":      [],           # terminal
}

# Steps that can be used as retry entry points, mapped to the job status
# they require the job to be set to before the orchestrator resumes.
# The orchestrator reads existing file paths from IngestJob to skip already-done work.
RETRY_ENTRY_POINTS: dict[str, str] = {
    "capturing":     "pending",       # restart from scratch
    "transcribing":  "captured",      # reuse raw_file_path
    "normalizing":   "captured",      # reuse raw_file_path
    "preprocessing": "captured",      # reuse video file (reserved)
    # parsing 的断点由 resume_for_retry 按 asr_file_path 分派：
    # 音频已转写 → transcribed（复用 asr 只重跑 AI 链）；图文/未转写 → captured。
    "parsing":       "captured",      # audio with asr overridden to "transcribed"
    "composing":     "parsed",        # reuse parsed_file_path
    "indexing":      "composed",      # reuse composed artifacts + parsed_file_path
}


def _assert_valid(current: str, target: str) -> None:
    allowed = _TRANSITIONS.get(current, [])
    if target not in allowed:
        raise ValueError(
            f"Illegal ingest_job transition: {current!r} → {target!r}. "
            f"Allowed: {allowed}"
        )


async def transition(
    db: AsyncSession,
    *,
    job_id: UUID,
    current_status: str,
    target_status: str,
    raw_file_path: Optional[str] = None,
    asr_file_path: Optional[str] = None,
    parsed_file_path: Optional[str] = None,
    index_file_path: Optional[str] = None,
    article_id: Optional[UUID] = None,
    error_stage: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Validate and apply a status transition for *job_id*.

    Args:
        db:                Active database session.
        job_id:            UUID of the ingest_jobs row to update.
        current_status:    Status the caller believes the row currently has.
        target_status:     Desired new status.
        raw_file_path:     Set when transitioning to ``captured``.
        asr_file_path:     Set when transitioning to ``transcribed``.
        parsed_file_path:  Set when transitioning to ``parsed``.
        index_file_path:   Set when transitioning to ``ready``.
        article_id:        Set when transitioning to ``ready``.
        error_stage:       Set when transitioning to ``failed``.
        error_message:     Set when transitioning to ``failed``.

    Raises:
        ValueError: If the transition is not allowed by the state graph.
    """
    _assert_valid(current_status, target_status)

    values: dict = {"status": target_status}

    if raw_file_path is not None:
        values["raw_file_path"] = raw_file_path
    if asr_file_path is not None:
        values["asr_file_path"] = asr_file_path
    if parsed_file_path is not None:
        values["parsed_file_path"] = parsed_file_path
    if index_file_path is not None:
        values["index_file_path"] = index_file_path
    if article_id is not None:
        values["article_id"] = article_id
    if error_stage is not None:
        values["error_stage"] = error_stage
    if error_message is not None:
        values["error_message"] = error_message

    result = await db.execute(
        update(IngestJob)
        .where(
            IngestJob.id == job_id,
            # Compare-and-set：仅当 DB 实际状态仍为 current_status 才生效。
            # 云端单写入者时恒为 1 行；worker 多写入者（租约超时被抢）时，
            # 过期 owner 的 transition 在这里失败而非回退/覆盖新 owner 的进度。
            IngestJob.status == current_status,
        )
        .values(**values)
    )
    if result.rowcount == 0:
        await db.rollback()
        logger.warning(
            "ingest_job %s: 状态变更 %s → %s 未生效（rowcount=0，实际状态与预期不符）",
            job_id, current_status, target_status,
        )
        raise RuntimeError(
            f"ingest_job {job_id} 状态变更未生效: {current_status} → {target_status} "
            f"（可能已被其他 worker/进程抢先变更）"
        )

    await db.commit()
    logger.debug("ingest_job %s: %s → %s", job_id, current_status, target_status)


async def resume_for_retry(
    db: AsyncSession,
    *,
    job_id: UUID,
    from_step: str,
) -> bool:
    """Reset a failed job to the status needed to resume from *from_step*.

    Returns False if the job is not in a retryable state or MAX_RETRIES exceeded.

    ``from_step`` must be one of the keys in RETRY_ENTRY_POINTS.
    The orchestrator then reads existing file paths from IngestJob to skip
    already-completed steps.
    """
    if from_step not in RETRY_ENTRY_POINTS:
        logger.warning("resume_for_retry: unknown from_step=%r", from_step)
        return False

    job = await db.get(IngestJob, job_id)
    if job is None:
        return False
    if job.status not in ("failed", "cancelled", "ready"):
        return False

    target_status = RETRY_ENTRY_POINTS[from_step]
    if (
        from_step == "parsing"
        and job.asr_file_path  # 非空 ⟺ 音频且已完成转写（executor 同款判据）
    ):
        # 音频「重新生成 AI」：复用已转写文本，只重跑 parse→compose→index，
        # 不再整段重转录。worker 认领 transcribed 走 _resume_after_transcribed。
        target_status = "transcribed"
    is_reprocess = job.status == "ready"
    # Manual retries are always user-initiated, so never block them.
    # Reset counter when the previous limit was reached so the job doesn't stay permanently stuck.
    new_retry_count = 0 if (is_reprocess or job.retry_count >= MAX_RETRIES) else job.retry_count + 1

    await db.execute(
        update(IngestJob)
        .where(IngestJob.id == job_id)
        .values(
            status=target_status,
            retry_count=new_retry_count,
            error_stage=None,
            error_message=None,
        )
    )
    await db.commit()
    logger.info(
        "ingest_job %s: retry from=%r → reset to %r (retry %d)",
        job_id, from_step, target_status, job.retry_count + 1,
    )
    return True
