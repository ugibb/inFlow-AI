"""Ingest API router — /api/ingest/*

Endpoints:
    POST /api/ingest/url            Capture from a URL
    POST /api/ingest/upload         Capture from a file upload
    POST /api/ingest/text           Capture from pasted text
    GET  /api/ingest/jobs/{job_id}  Check job status
    POST /api/ingest/jobs/{job_id}/retry   Retry a failed job
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlparse, urlunparse
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from inflow_core.core.database import get_db
from inflow_core.core.dependencies import get_current_user
from inflow_core.core.models.article import Article
from inflow_core.core.models.ingest_job import IngestJob
from inflow_core.core.models.user import User
from inflow_core.core.pipeline.state_machine import resume_for_retry
from inflow_core.core.pipeline.pipeline_steps import compute_pipeline_steps
from inflow_core.ingest.orchestrator import ingest_url, ingest_upload, ingest_text, resume_job

router = APIRouter(prefix="/api/ingest", tags=["ingest"])
logger = logging.getLogger("inFlow.ingest.router")


def _canonical_url(url: str) -> str:
    """Strip query string and fragment — preserves content-identity for dedup."""
    p = urlparse(url.strip())
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))


# ── Request / Response schemas ────────────────────────────────────────

class IngestURLRequest(BaseModel):
    url: str
    capture_method: str = "url"


class IngestTextRequest(BaseModel):
    text: str
    title: str | None = None


class RawPreview(BaseModel):
    title: str | None = None
    author: str | None = None
    cover_image: str | None = None
    content_type: str | None = None
    text: str | None = None
    platform: str | None = None


class ChapterPreview(BaseModel):
    start_min: int
    title: str
    description: str


class ParsedPreview(BaseModel):
    summary: str | None = None
    key_points: list[str] | None = None
    reading_time: int | None = None
    word_count: int | None = None
    chapters: list[ChapterPreview] | None = None


class PipelineStepView(BaseModel):
    id: str
    label: str
    short_label: str
    state: str
    artifact_path: str | None = None
    retry_from: str | None = None


class IngestJobResponse(BaseModel):
    job_id: UUID
    status: str
    source_platform: str | None
    source_url: str | None
    article_id: UUID | None
    error_stage: str | None
    error_message: str | None
    raw_preview: RawPreview | None = None
    parsed_preview: ParsedPreview | None = None
    pipeline_steps: list[PipelineStepView] | None = None


def _job_content_type(job: IngestJob, raw_preview: RawPreview | None) -> str:
    if raw_preview and raw_preview.content_type:
        return raw_preview.content_type
    return "article"


def _build_job_response(
    job: IngestJob,
    *,
    raw_preview: RawPreview | None,
    parsed_preview: ParsedPreview | None,
) -> IngestJobResponse:
    content_type = _job_content_type(job, raw_preview)
    steps = compute_pipeline_steps(job, content_type=content_type)
    return IngestJobResponse(
        job_id=job.id,
        status=job.status,
        source_platform=job.source_platform,
        source_url=job.source_url,
        article_id=job.article_id,
        error_stage=job.error_stage,
        error_message=job.error_message,
        raw_preview=raw_preview,
        parsed_preview=parsed_preview,
        pipeline_steps=[PipelineStepView(**s) for s in steps],
    )


# ── Endpoints ─────────────────────────────────────────────────────────

@router.post("/url", status_code=202)
async def ingest_from_url(
    body: IngestURLRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Queue a URL for capture → parse → display pipeline."""
    # Normalize: strip tracking query params (e.g. xiaoyuzhou ?s=, utm_*)
    clean_url = _canonical_url(body.url)
    url_variants = list({body.url, clean_url})  # deduplicated list

    # Check if this URL already exists as a completed article
    existing_result = await db.execute(
        select(Article).where(
            Article.user_id == current_user.id,
            Article.url.in_(url_variants),
        ).limit(1)
    )
    existing = existing_result.scalar_one_or_none()
    if existing and existing.fetch_status != "ingesting":
        return {
            "job_id": None,
            "status": "already_exists",
            "article_id": str(existing.id),
            "title": existing.title,
            "message": "这篇文章已经在你的库里了",
        }

    # 上次采集失败会留下 fetch_status=ingesting 的 stub；优先复用 failed job 重试
    if existing and existing.fetch_status == "ingesting":
        failed_job_result = await db.execute(
            select(IngestJob).where(
                IngestJob.user_id == current_user.id,
                IngestJob.article_id == existing.id,
                IngestJob.status.in_(["failed", "cancelled"]),
            ).order_by(IngestJob.created_at.desc()).limit(1)
        )
        failed_job = failed_job_result.scalar_one_or_none()
        if failed_job:
            ok = await resume_for_retry(db, job_id=failed_job.id, from_step="capturing")
            if ok:
                await resume_job(db, background_tasks, job_id=failed_job.id)
                return {
                    "job_id": str(failed_job.id),
                    "status": "retrying",
                    "article_id": str(existing.id),
                    "title": existing.title,
                    "message": "正在重新采集这篇文章",
                }

    # Also check if this URL is already being processed (in-flight job)
    existing_job_result = await db.execute(
        select(IngestJob).where(
            IngestJob.user_id == current_user.id,
            IngestJob.source_url.in_(url_variants),
            IngestJob.status.not_in(["failed", "cancelled"]),
        ).limit(1)
    )
    existing_job = existing_job_result.scalar_one_or_none()
    if existing_job:
        # Job completed successfully and has an article → treat as already_exists
        if existing_job.status == "ready" and existing_job.article_id:
            article_result = await db.execute(
                select(Article).where(Article.id == existing_job.article_id).limit(1)
            )
            dup_article = article_result.scalar_one_or_none()
            return {
                "job_id": str(existing_job.id),
                "status": "already_exists",
                "article_id": str(existing_job.article_id),
                "title": dup_article.title if dup_article else None,
                "message": "这篇文章已经在你的库里了",
            }
        # Job is ready but article_id is missing (orphan) → fall through to re-ingest
        if existing_job.status == "ready" and not existing_job.article_id:
            logger.warning(
                "Job %s is ready but has no article_id; allowing re-ingest for URL %s",
                existing_job.id, clean_url,
            )
        else:
            # Genuinely in-flight
            inflight_title: str | None = None
            if existing_job.article_id:
                inflight_result = await db.execute(
                    select(Article).where(Article.id == existing_job.article_id).limit(1)
                )
                inflight_article = inflight_result.scalar_one_or_none()
                if inflight_article:
                    inflight_title = inflight_article.title
            return {
                "job_id": str(existing_job.id),
                "status": "already_processing",
                "article_id": str(existing_job.article_id) if existing_job.article_id else None,
                "title": inflight_title,
                "message": "这篇文章正在处理中",
            }

    job_id = await ingest_url(
        db,
        background_tasks,
        url=clean_url,  # always store/fetch the clean URL
        user_id=current_user.id,
        capture_method=body.capture_method,
    )
    title_result = await db.execute(
        select(Article.title)
        .join(IngestJob, IngestJob.article_id == Article.id)
        .where(IngestJob.id == job_id)
    )
    return {
        "job_id": str(job_id),
        "status": "capturing",
        "title": title_result.scalar_one_or_none(),
    }


@router.post("/upload", status_code=202)
async def ingest_from_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Queue an uploaded file for capture → parse → display pipeline."""
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:  # 50 MB limit
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")

    job_id = await ingest_upload(
        db,
        background_tasks,
        filename=file.filename or "upload",
        content=content,
        user_id=current_user.id,
        mime_type=file.content_type,
    )
    return {"job_id": str(job_id), "status": "capturing"}


@router.post("/text", status_code=202)
async def ingest_from_text(
    body: IngestTextRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Queue pasted text for capture → parse → display pipeline."""
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="Text content is empty")

    job_id = await ingest_text(
        db,
        background_tasks,
        text=body.text,
        title=body.title,
        user_id=current_user.id,
    )
    return {"job_id": str(job_id), "status": "capturing"}


@router.get("/jobs", response_model=list[IngestJobResponse])
async def list_active_jobs(
    article_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[IngestJobResponse]:
    """Return ingest jobs for the current user.

    Without params: all non-terminal jobs (for library processing cards).
    With article_id: the latest job for that article regardless of status
    (used by the read page to auto-show PipelineBar on direct navigation).
    """
    if article_id is not None:
        result = await db.execute(
            select(IngestJob).where(
                IngestJob.user_id == current_user.id,
                IngestJob.article_id == article_id,
            ).order_by(IngestJob.created_at.desc()).limit(1)
        )
    else:
        result = await db.execute(
            select(IngestJob).where(
                IngestJob.user_id == current_user.id,
                IngestJob.status.not_in(["ready", "failed", "cancelled"]),
            ).order_by(IngestJob.created_at.desc())
        )
    jobs = result.scalars().all()

    responses: list[IngestJobResponse] = []
    for job in jobs:
        raw_preview: RawPreview | None = None
        if job.raw_file_path:
            try:
                from inflow_core.core.shared.storage import default_storage
                raw_data = await default_storage.read_raw(job.raw_file_path)
                raw = raw_data.get("raw", {})
                meta = raw_data.get("meta", {})
                raw_preview = RawPreview(
                    title=raw.get("title") or None,
                    author=raw.get("author") or None,
                    cover_image=raw.get("cover_image") or None,
                    content_type=raw.get("content_type") or "article",
                    text=(raw.get("raw_text") or "")[:300] or None,
                    platform=meta.get("source_platform") or job.source_platform,
                )
            except Exception:
                pass
        responses.append(_build_job_response(
            job, raw_preview=raw_preview, parsed_preview=None,
        ))

    return responses


@router.get("/jobs/{job_id}", response_model=IngestJobResponse)
async def get_job_status(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> IngestJobResponse:
    """Return the current status of an ingest job, including raw capture preview when available."""
    job = await db.get(IngestJob, job_id)
    if job is None or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    raw_preview: RawPreview | None = None
    if job.raw_file_path:
        try:
            from inflow_core.core.shared.storage import default_storage
            raw_data = await default_storage.read_raw(job.raw_file_path)
            raw = raw_data.get("raw", {})
            meta = raw_data.get("meta", {})
            raw_preview = RawPreview(
                title=raw.get("title") or None,
                author=raw.get("author") or None,
                cover_image=raw.get("cover_image") or None,
                content_type=raw.get("content_type") or "article",
                text=(raw.get("raw_text") or "")[:600] or None,
                platform=meta.get("source_platform") or job.source_platform,
            )
        except Exception:
            pass

    parsed_preview: ParsedPreview | None = None
    if job.article_id:
        try:
            from inflow_core.core.models.article import Article
            article = await db.get(Article, job.article_id)
            if article:
                kp = article.key_points
                if isinstance(kp, str):
                    import json as _json
                    try:
                        kp = _json.loads(kp)
                    except Exception:
                        kp = None
                chapters_raw = article.chapters or []
                chapters = [
                    ChapterPreview(
                        start_min=int(c.get("start_min", 0)),
                        title=str(c.get("title", "")),
                        description=str(c.get("description", "")),
                    )
                    for c in chapters_raw
                    if isinstance(c, dict) and c.get("title")
                ]
                parsed_preview = ParsedPreview(
                    summary=article.summary or None,
                    key_points=kp if isinstance(kp, list) else None,
                    reading_time=article.reading_time or None,
                    word_count=article.word_count or None,
                    chapters=chapters or None,
                )
        except Exception:
            pass

    return _build_job_response(
        job, raw_preview=raw_preview, parsed_preview=parsed_preview,
    )


@router.get("/jobs/{job_id}/logs")
async def get_job_logs(
    job_id: UUID,
    step: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return step_logs for a job, optionally filtered by step name."""
    job = await db.get(IngestJob, job_id)
    if job is None or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    logs: list = job.step_logs or []
    if step:
        logs = [e for e in logs if e.get("step") == step]

    return {"logs": logs}


@router.get("/jobs/{job_id}/transcript")
async def get_job_transcript(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return ASR transcript segments from _asr_verbose.json for an audio job."""
    import json as _json
    from pathlib import Path
    from inflow_core.core.shared.storage.conventions import parse_transcript_base

    job = await db.get(IngestJob, job_id)
    if job is None or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.raw_file_path:
        raise HTTPException(status_code=404, detail="No raw file path for this job")

    base = parse_transcript_base(job.raw_file_path, job_id)
    verbose_path = Path(base).parent / (Path(base).stem + "_verbose.json")

    if not verbose_path.is_file():
        raise HTTPException(status_code=404, detail="Transcript not yet available")

    try:
        data = _json.loads(verbose_path.read_text(encoding="utf-8"))
        segments = [
            {"start": s["start"], "end": s["end"], "text": s["text"]}
            for s in (data.get("segments") or [])
        ]
        return {
            "language": data.get("language"),
            "duration": data.get("duration"),
            "segments": segments,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read transcript: {exc}") from exc


@router.delete("/jobs/{job_id}", status_code=204, response_class=Response)
async def cancel_ingest_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel an ingest job and mark the associated article as failed."""
    job = await db.get(IngestJob, job_id)
    if job is None or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = "cancelled"
    # Mark article stub so the read page shows a cancelled state
    if job.article_id:
        article = await db.get(Article, job.article_id)
        if article and article.fetch_status == "ingesting":
            article.fetch_status = "failed"
    await db.commit()
    return Response(status_code=204)


class RetryRequest(BaseModel):
    from_step: str = "capturing"
    # "capturing" | "transcribing" | "parsing" | "indexing"


@router.post("/jobs/{job_id}/retry", status_code=202)
async def retry_job(
    job_id: UUID,
    background_tasks: BackgroundTasks,
    body: RetryRequest = RetryRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Retry a failed/cancelled ingest job from a specific step (max 3 retries).

    from_step controls which pipeline step to resume from, reusing
    already-computed files for steps before it:
      - "capturing"    → restart from scratch
      - "transcribing" → reuse raw_file_path, redo transcription onward
      - "parsing"      → reuse raw + asr files, redo AI parse onward
      - "indexing"     → reuse parsed_file_path, redo semantic index only
    """
    job = await db.get(IngestJob, job_id)
    if job is None or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("failed", "cancelled", "ready"):
        raise HTTPException(
            status_code=400,
            detail=f"Job is not in a retryable state (current: {job.status})",
        )

    ok = await resume_for_retry(db, job_id=job_id, from_step=body.from_step)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail="Maximum retries exceeded or invalid from_step. Check the job manually.",
        )

    # Restore article fetch_status to ingesting so the read page resumes polling
    if job.article_id:
        article = await db.get(Article, job.article_id)
        if article and article.fetch_status in ("failed", "completed"):
            article.fetch_status = "ingesting"
            await db.commit()

    await resume_job(db, background_tasks, job_id=job_id)

    return {"job_id": str(job_id), "status": "retrying", "from_step": body.from_step}
