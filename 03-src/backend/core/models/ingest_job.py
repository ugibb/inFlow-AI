"""IngestJob — database model for pipeline state tracking.

Each row represents one content-ingestion attempt, tracking the job from
initial submission through capture, optional transcription, AI parse,
semantic indexing, and finally completion or failure.

Status lifecycle (图文):
    pending → capturing → captured → parsing → parsed → indexing → ready

Status lifecycle (音频):
    pending → capturing → captured → transcribing → transcribed
      → parsing → parsed → indexing → ready

Any stage can transition to: failed | cancelled
"""

from __future__ import annotations

import json as _json
from datetime import datetime, timezone
from uuid import UUID as _UUID

from sqlalchemy import Boolean, Column, String, Text, SmallInteger, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid

from backend.core.database import Base


class IngestJob(Base):
    __tablename__ = "ingest_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Ownership
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Set immediately at job creation (article stub created alongside job)
    article_id = Column(
        UUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Source metadata
    source_url = Column(Text, nullable=True)
    capture_method = Column(String(30), nullable=True)
    # url | wechat_bot | browser_ext | upload | paste
    source_platform = Column(String(50), nullable=True)
    # wechat | bilibili | xiaoyuzhou | xhs | douyin | youtube |
    # toutiao | juejin | csdn | upload | generic
    # skill（worker 路由推导 source_platform → skill，capture 时写入；可空则不归因）
    skill_id = Column(Text, nullable=True)

    # File paths set by pipeline steps (used for retry file-reuse)
    raw_file_path = Column(Text, nullable=True)     # set at: captured
    asr_file_path = Column(Text, nullable=True)     # set at: transcribed (audio only)
    parsed_file_path = Column(Text, nullable=True)  # set at: parsed
    index_file_path = Column(Text, nullable=True)   # set at: ready (chunks.json path)
    # upload/paste 分流暂存（云端收件落盘 data/00_staging/...，worker 经 SFTP 拉取）
    staging_file_path = Column(Text, nullable=True)  # set at: 登记（external 分流时）

    # Pipeline status
    status = Column(String(20), nullable=False, default="pending", index=True)
    # pending | capturing | captured
    # | transcribing | transcribed           (audio/video path)
    # | preprocessing | preprocessed        (video path, reserved)
    # | parsing | parsed | indexing | ready
    # | failed | cancelled

    retry_count = Column(SmallInteger, nullable=False, default=0)

    # ── 本地 worker 分流（外部处理）────────────────────────────
    # external_processing=True  → 由本地 worker 承接，云端不跑 capture/pipeline
    # processing_host           → 最近认领主机（hostname-pid），审计 + 重启自回收
    # claimed_at                → 租约时间戳；NULL=可认领，超时被重新认领
    external_processing = Column(Boolean, nullable=False, default=False, index=True)
    processing_host = Column(String(64), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)

    # Error diagnostics
    error_stage = Column(String(30), nullable=True)
    error_message = Column(Text, nullable=True)

    # Per-step runtime logs — appended during active steps for live progress visibility
    step_logs = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


async def append_step_log(job_id: _UUID, step: str, msg: str) -> None:
    """Append one log entry to ingest_jobs.step_logs for live progress visibility.

    Opens its own short-lived DB session so it can be called safely from any
    async context, including those scheduled via run_coroutine_threadsafe.
    """
    from backend.core.database import async_session

    entry = _json.dumps([{
        "step": step,
        "ts": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "msg": msg,
    }])
    async with async_session() as db:
        await db.execute(
            text(
                "UPDATE ingest_jobs"
                " SET step_logs = step_logs || CAST(:entry AS jsonb)"
                " WHERE id = :job_id"
            ),
            {"entry": entry, "job_id": str(job_id)},
        )
        await db.commit()
