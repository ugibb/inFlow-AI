"""Ingest orchestrator — unified entry point for all content capture methods.

ingest_url():       capture from a URL (auto-route to platform adapter)
ingest_upload():    capture from an uploaded file
ingest_text():      capture from pasted text
resume_job():       resume a failed job from a specific step (retry with file reuse)

Each ingest_* function:
1. Creates an Article stub immediately (fetch_status='ingesting').
2. Creates an IngestJob row with article_id already set.
3. Transitions status to 'capturing'.
4. Calls the appropriate adapter.
5. Writes the RawCapture file and updates Article with real metadata.
6. Transitions status to 'captured'.
7. Routes to the correct pipeline chain based on content_type:
   - 图文 (article): run_parse → run_index
   - 音频 (audio):   run_transcribe → run_parse → run_index
   - 视频 (video):   [reserved — stub only]

resume_job() reads existing file paths from IngestJob and resumes from the
specified step, skipping already-completed work.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from inflow_core.core.models.ingest_job import IngestJob
from inflow_core.core.models.article import Article
from inflow_core.ingest.adapters.registry import adapter_registry
from inflow_core.core.config import get_settings
from inflow_core.core.pipeline.state_machine import transition
from inflow_core.core.pipeline.steps import (
    run_chapters,
    run_compose_card,
    run_index,
    run_normalize_text,
    run_parse,
    run_transcribe,
)
from inflow_core.core.pipeline.pipeline_log import PhaseLogger, log_task_start, sanitize_log_text
from inflow_core.core.shared.storage import default_storage

logger = logging.getLogger("inFlow.ingest.orchestrator")
settings = get_settings()

# Platforms inferred as audio before capture begins
_AUDIO_PLATFORMS = frozenset({"xiaoyuzhou", "bilibili"})


def _infer_content_type(platform: str | None) -> str:
    return "audio" if platform in _AUDIO_PLATFORMS else "article"


# ------------------------------------------------------------------ #
# Pipeline routing (called from within background tasks)             #
# ------------------------------------------------------------------ #

async def _route_pipeline(
    db: AsyncSession,
    *,
    job_id: UUID,
    article_id: UUID,
    user_id: UUID,
    content_type: str,
    raw_file_path: str,
    source_url: str | None,
    source_platform: str | None,
    on_composed: Callable[[UUID, str], Awaitable[bool]] | None = None,
) -> None:
    """Route to the correct pipeline chain based on content_type.

    ``on_composed``：compose 成功后、index 之前调用的可选钩子（本地 worker 用它把
    PNG 回传云端）。返回 False 表示回传失败 → job 停在 composed→failed，
    不再继续 run_index。云端路径传 None，行为零变化。
    """
    asr_for_card: str | None = None

    if content_type == "audio":
        asr_path = await run_transcribe(
            db, job_id=job_id, raw_file_path=raw_file_path, content_type=content_type,
        )
        if asr_path is None:
            return
        asr_for_card = asr_path

        await run_chapters(
            db,
            job_id=job_id,
            raw_file_path=raw_file_path,
            current_status="transcribed",
            content_type=content_type,
        )
        parsed_path = await run_parse(
            db,
            job_id=job_id,
            raw_file_path=raw_file_path,
            asr_file_path=asr_path,
            current_status="parsing",
            content_type=content_type,
        )
    else:
        asr_txt = await run_normalize_text(
            db, job_id=job_id, raw_file_path=raw_file_path, content_type=content_type,
        )
        if asr_txt is None:
            return
        asr_for_card = asr_txt

        await run_chapters(
            db,
            job_id=job_id,
            raw_file_path=raw_file_path,
            current_status="normalized",
            content_type=content_type,
        )
        parsed_path = await run_parse(
            db,
            job_id=job_id,
            raw_file_path=raw_file_path,
            asr_file_path=asr_txt,
            current_status="parsing",
            content_type=content_type,
        )

    if parsed_path is None:
        return

    await _compose_and_continue(
        db,
        job_id=job_id,
        article_id=article_id,
        user_id=user_id,
        raw_file_path=raw_file_path,
        parsed_file_path=parsed_path,
        asr_file_path=asr_for_card,
        source_platform=source_platform,
        content_type=content_type,
        source_url=source_url,
        on_composed=on_composed,
    )


async def _upload_png_or_fail(
    db: AsyncSession,
    *,
    job_id: UUID,
    png_path: str,
    on_composed: Callable[[UUID, str], Awaitable[bool]],
) -> bool:
    """调用 on_composed 回传 PNG；成功返回 True。

    失败（on_composed 返回 False 或抛异常）时把 job 置 composed→failed
    （error_stage=composing）并返回 False。幂等：SFTP .tmp→rename 覆盖，
    崩溃后重复回传安全。
    """
    try:
        ok = await on_composed(job_id, png_path)
    except Exception as exc:
        logger.error("on_composed PNG 回传异常 job=%s: %s", job_id, exc)
        ok = False
    if ok:
        return True
    try:
        await transition(
            db,
            job_id=job_id,
            current_status="composed",
            target_status="failed",
            error_stage="composing",
            error_message="PNG 回传云端失败",
        )
    except Exception as exc:
        # transition 原子化后，若 composed 已被抢先变更，这里只记录不掩盖。
        logger.error("composed→failed 回滚失败 job=%s: %s", job_id, exc)
    return False


async def _compose_and_continue(
    db: AsyncSession,
    *,
    job_id: UUID,
    article_id: UUID | None,
    user_id: UUID,
    raw_file_path: str,
    parsed_file_path: str,
    asr_file_path: str | None,
    source_platform: str | None,
    content_type: str,
    source_url: str | None,
    on_composed: Callable[[UUID, str], Awaitable[bool]] | None = None,
) -> None:
    """Run compose_card, then (optionally) upload PNG before indexing.

    收敛 retry/_route_pipeline 里多处内联的 compose+index 序列：
      1. run_compose_card 失败（返回 None）→ 已由步骤自身转 failed，直接返回
      2. 外部 worker 时 on_composed 负责把本地 PNG 回传云端：
         - 回传失败 → job 停在 composed→failed（error_stage=composing），不再 index
         - 成功 → 继续 run_index（composed→indexing→ready）
    """
    composed = await run_compose_card(
        db,
        job_id=job_id,
        raw_file_path=raw_file_path,
        parsed_file_path=parsed_file_path,
        asr_file_path=asr_file_path,
        source_platform=source_platform,
        content_type=content_type,
    )
    if composed is None or article_id is None:
        return

    if on_composed is not None:
        if not await _upload_png_or_fail(
            db, job_id=job_id, png_path=composed[1], on_composed=on_composed
        ):
            return

    await run_index(
        db,
        job_id=job_id,
        article_id=article_id,
        user_id=user_id,
        parsed_file_path=parsed_file_path,
        raw_file_path=raw_file_path,
        source_url=source_url,
        source_platform=source_platform,
        content_type=content_type,
    )


# ------------------------------------------------------------------ #
# Public entry points                                                 #
# ------------------------------------------------------------------ #

async def _peek_url_title(url: str) -> str | None:
    """Best-effort title from og:title / <title> before full capture runs."""
    from bs4 import BeautifulSoup
    import httpx
    from inflow_core.ingest.fetchers import extract_url_from_text, parser_service

    clean = extract_url_from_text(url) or url
    if not clean:
        return None
    try:
        platform = parser_service.detect_platform(clean)
        headers = parser_service._get_headers(platform, clean)
        async with httpx.AsyncClient(
            timeout=8.0, follow_redirects=True, trust_env=False
        ) as client:
            r = await client.get(clean, headers=headers)
            r.raise_for_status()
        soup = BeautifulSoup(r.text[:100_000], "lxml")
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            t = og.get("content", "").strip()
            if t:
                return t
        title_tag = soup.find("title")
        if title_tag:
            t = title_tag.get_text(strip=True)
            if t:
                return t
    except Exception as e:
        logger.debug("peek_url_title failed for %s: %s", clean[:80], e)
    return None


async def ingest_url(
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    *,
    url: str,
    user_id: UUID,
    capture_method: str = "url",
) -> UUID:
    """Capture content from a URL.

    Creates an Article stub and IngestJob atomically, then queues capture.
    Returns the UUID of the created ingest_job record.
    """
    from inflow_core.ingest.fetchers import extract_url_from_text
    clean_url = extract_url_from_text(url) or url

    adapter = adapter_registry.resolve(clean_url)
    peeked_title = await _peek_url_title(clean_url)

    existing_result = await db.execute(
        select(Article).where(
            Article.user_id == user_id,
            Article.url == clean_url,
        ).limit(1)
    )
    existing_article = existing_result.scalar_one_or_none()

    if existing_article:
        article_id = existing_article.id
        existing_article.fetch_status = "ingesting"
        existing_article.source_platform = adapter.platform
        existing_article.content_type = _infer_content_type(adapter.platform)
        if peeked_title:
            existing_article.title = peeked_title[:500]
    else:
        article_stub = Article(
            user_id=user_id,
            url=clean_url,
            title=(peeked_title or clean_url)[:500],
            source_platform=adapter.platform,
            content_type=_infer_content_type(adapter.platform),
            fetch_status="ingesting",
        )
        db.add(article_stub)
        await db.flush()
        article_id = article_stub.id

    job = IngestJob(
        user_id=user_id,
        source_url=clean_url,
        capture_method=capture_method,
        source_platform=adapter.platform,
        article_id=article_id,
    )
    db.add(job)
    await db.flush()
    job_id = job.id

    if settings.external_processing:
        # 本地 worker 承接完整 pipeline：云端只登记 job，不跑 capture/后台任务。
        # job 停在 pending，等本地 worker 认领。
        job.external_processing = True
        await db.commit()
        log_task_start(
            job_id=job_id,
            article_id=article_id,
            method="url",
            platform=adapter.platform,
            url=clean_url,
        )
        logger.info(
            "外部处理分流: job=%s → 交给本地 worker（external_processing）", job_id
        )
        return job_id

    await transition(
        db,
        job_id=job_id,
        current_status="pending",
        target_status="capturing",
    )

    log_task_start(
        job_id=job_id,
        article_id=article_id,
        method="url",
        platform=adapter.platform,
        url=clean_url,
    )

    background_tasks.add_task(
        _run_url_capture,
        job_id=job_id,
        url=clean_url,
        user_id=user_id,
        capture_method=capture_method,
    )

    return job_id


async def ingest_upload(
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    *,
    filename: str,
    content: bytes,
    user_id: UUID,
    mime_type: str | None = None,
) -> UUID:
    """Capture content from an uploaded file.

    Returns the UUID of the created ingest_job record.
    """
    article_stub = Article(
        user_id=user_id,
        url=None,
        title=filename[:500],
        source_platform="upload",
        fetch_status="ingesting",
    )
    db.add(article_stub)
    await db.flush()
    article_id = article_stub.id

    job = IngestJob(
        user_id=user_id,
        source_url=None,
        capture_method="upload",
        source_platform="upload",
        article_id=article_id,
    )
    db.add(job)
    await db.flush()
    job_id = job.id

    await transition(
        db,
        job_id=job_id,
        current_status="pending",
        target_status="capturing",
    )

    background_tasks.add_task(
        _run_upload_capture,
        job_id=job_id,
        filename=filename,
        content=content,
        user_id=user_id,
        mime_type=mime_type,
    )

    log_task_start(
        job_id=job_id,
        article_id=article_id,
        method="upload",
        platform="upload",
        file=filename,
    )
    return job_id


async def ingest_text(
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    *,
    text: str,
    title: str | None,
    user_id: UUID,
) -> UUID:
    """Capture pasted plain text as a raw note.

    Returns the UUID of the created ingest_job record.
    """
    real_title = title or "Pasted note"

    article_stub = Article(
        user_id=user_id,
        url=None,
        title=real_title[:500],
        source_platform="generic",
        content_type="article",
        fetch_status="ingesting",
    )
    db.add(article_stub)
    await db.flush()
    article_id = article_stub.id

    job = IngestJob(
        user_id=user_id,
        source_url=None,
        capture_method="paste",
        source_platform="generic",
        article_id=article_id,
    )
    db.add(job)
    await db.flush()
    job_id = job.id

    await transition(
        db,
        job_id=job_id,
        current_status="pending",
        target_status="capturing",
    )

    background_tasks.add_task(
        _run_text_capture,
        job_id=job_id,
        text=text,
        title=real_title,
        user_id=user_id,
    )

    log_task_start(
        job_id=job_id,
        article_id=article_id,
        method="paste",
        platform="generic",
        title=real_title,
    )
    return job_id


async def resume_job(
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    *,
    job_id: UUID,
) -> None:
    """Resume a job that has been reset by resume_for_retry().

    Reads the job's current status and existing file paths to determine
    which step to start from, reusing already-computed files.

    Must be called after resume_for_retry() has reset the job status.
    """
    job = await db.get(IngestJob, job_id)
    if job is None:
        logger.warning("resume_job: job %s not found", job_id)
        return

    if job.external_processing:
        # 由本地 worker 承接的 job：云端不调度，交给 worker 的 claim/心跳循环处理
        logger.info("resume_job: job %s 由本地 worker 处理，云端跳过调度", job_id)
        return

    background_tasks.add_task(run_job_resume, job_id=job_id)
    logger.info(
        "resume_job queued: job=%s from_status=%s", job_id, job.status,
    )


# ------------------------------------------------------------------ #
# Background capture tasks                                            #
# ------------------------------------------------------------------ #

async def _update_article_from_raw(db: AsyncSession, job_id: UUID, raw_capture) -> None:
    """Update the Article stub with real metadata from a successful raw capture."""
    job = await db.get(IngestJob, job_id)
    if not job or not job.article_id:
        return
    article = await db.get(Article, job.article_id)
    if not article or article.fetch_status != "ingesting":
        return
    raw = raw_capture.raw
    if raw.title:
        article.title = raw.title[:500]
    if raw.cover_image:
        article.cover_image = raw.cover_image
    if raw.author:
        article.author = raw.author
    if raw.content_type:
        article.content_type = raw.content_type
    await db.commit()


async def _run_url_capture(
    *,
    job_id: UUID,
    url: str,
    user_id: UUID,
    capture_method: str,
) -> None:
    from inflow_core.core.database import async_session
    from inflow_core.ingest.adapters.registry import adapter_registry

    async with async_session() as db:
        try:
            adapter = adapter_registry.resolve(url)
            phase = PhaseLogger(
                job_id, "capturing", content_type=_infer_content_type(adapter.platform),
            )
            phase.start()
            # phase.detail("抓取页面元数据…")

            raw_capture = await adapter.fetch(url, user_id=user_id, capture_method=capture_method)
            title = sanitize_log_text(raw_capture.raw.title or "")[:60]
            phase.detail(f"抓取页面元数据完成，标题：{title or '（无）'}")

            raw_path = await default_storage.write_raw(
                platform=adapter.platform,
                job_id=job_id,
                data=raw_capture.to_dict(),
            )
            # phase.detail("原始数据已写入")

            await _download_media_if_needed(raw_capture, raw_path, job_id, phase=phase)

            await transition(
                db,
                job_id=job_id,
                current_status="capturing",
                target_status="captured",
                raw_file_path=raw_path,
            )

            await _update_article_from_raw(db, job_id, raw_capture)

            end_details: dict = {"title": title}
            if getattr(raw_capture.raw, "content_type", None) == "audio":
                from pathlib import Path
                from inflow_core.core.shared.storage.conventions import ingest_media_path
                from urllib.parse import urlparse
                media_urls = raw_capture.raw.media_urls or []
                if media_urls:
                    url_suffix = Path(urlparse(media_urls[0]).path).suffix.lower()
                    ext = url_suffix if url_suffix in {".mp3", ".m4a", ".ogg", ".flac", ".wav", ".aac"} else ".m4a"
                    media_path = Path(ingest_media_path(raw_path, job_id, ext))
                    if media_path.is_file():
                        end_details["audio"] = f"{media_path.stat().st_size / 1024 / 1024:.1f}MB"
            phase.end(**end_details)

            job = await db.get(IngestJob, job_id)
            article = await db.get(Article, job.article_id) if job and job.article_id else None
            if job and job.article_id:
                await _route_pipeline(
                    db,
                    job_id=job_id,
                    article_id=job.article_id,
                    user_id=user_id,
                    content_type=article.content_type if article else "article",
                    raw_file_path=raw_path,
                    source_url=job.source_url,
                    source_platform=job.source_platform,
                )

        except Exception as exc:
            phase.fail(str(exc)[:200])
            try:
                await transition(
                    db,
                    job_id=job_id,
                    current_status="capturing",
                    target_status="failed",
                    error_stage="capturing",
                    error_message=str(exc)[:500],
                )
            except Exception:
                pass


async def _run_upload_capture(
    *,
    job_id: UUID,
    filename: str,
    content: bytes,
    user_id: UUID,
    mime_type: str | None,
) -> None:
    from inflow_core.core.database import async_session
    from inflow_core.ingest.adapters.upload import UploadAdapter

    async with async_session() as db:
        phase = PhaseLogger(job_id, "capturing", content_type="article")
        try:
            adapter = UploadAdapter()
            phase.start()
            phase.detail("解析上传文件…")

            raw_capture = await adapter.fetch_from_bytes(
                filename=filename,
                content=content,
                user_id=user_id,
                mime_type=mime_type,
            )

            raw_path = await default_storage.write_raw(
                platform="upload",
                job_id=job_id,
                data=raw_capture.to_dict(),
            )
            # phase.detail("原始数据已写入")

            await transition(
                db,
                job_id=job_id,
                current_status="capturing",
                target_status="captured",
                raw_file_path=raw_path,
            )

            await _update_article_from_raw(db, job_id, raw_capture)

            phase.end()

            job = await db.get(IngestJob, job_id)
            article = await db.get(Article, job.article_id) if job and job.article_id else None
            await _route_pipeline(
                db,
                job_id=job_id,
                article_id=job.article_id,
                user_id=user_id,
                content_type=article.content_type if article else "article",
                raw_file_path=raw_path,
                source_url=None,
                source_platform="upload",
            )

        except Exception as exc:
            phase.fail(str(exc)[:200])
            try:
                await transition(
                    db,
                    job_id=job_id,
                    current_status="capturing",
                    target_status="failed",
                    error_stage="capturing",
                    error_message=str(exc)[:500],
                )
            except Exception:
                pass


async def _run_text_capture(
    *,
    job_id: UUID,
    text: str,
    title: str,
    user_id: UUID,
) -> None:
    from inflow_core.core.database import async_session
    from inflow_core.ingest.schema import RawCapture, RawMeta, RawContent

    async with async_session() as db:
        phase = PhaseLogger(job_id, "capturing", content_type="article")
        try:
            phase.start()

            meta = RawMeta(
                source_platform="generic",
                capture_method="paste",
                user_id=user_id,
            )
            raw = RawContent(
                title=title,
                content_type="article",
                raw_text=text,
            )
            raw_capture = RawCapture(meta=meta, raw=raw)

            raw_path = await default_storage.write_raw(
                platform="generic",
                job_id=job_id,
                data=raw_capture.to_dict(),
            )
            # phase.detail("原始数据已写入")

            await transition(
                db,
                job_id=job_id,
                current_status="capturing",
                target_status="captured",
                raw_file_path=raw_path,
            )

            phase.end()

            job = await db.get(IngestJob, job_id)
            await _route_pipeline(
                db,
                job_id=job_id,
                article_id=job.article_id,
                user_id=user_id,
                content_type="article",
                raw_file_path=raw_path,
                source_url=None,
                source_platform="generic",
            )

        except Exception as exc:
            phase.fail(str(exc)[:200])
            try:
                await transition(
                    db,
                    job_id=job_id,
                    current_status="capturing",
                    target_status="failed",
                    error_stage="capturing",
                    error_message=str(exc)[:500],
                )
            except Exception:
                pass


async def run_job_resume(
    *,
    job_id: UUID,
    on_composed: Callable[[UUID, str], Awaitable[bool]] | None = None,
) -> None:
    """Background task for resuming a retried job from its current status.

    ``on_composed``：本地 worker 传入时，compose 后先把 PNG 回传云端再 index。
    """
    from inflow_core.core.database import async_session

    async with async_session() as db:
        job = await db.get(IngestJob, job_id)
        if job is None:
            return

        article = await db.get(Article, job.article_id) if job.article_id else None
        content_type = (article.content_type if article else None) or "article"
        source_url = job.source_url
        source_platform = job.source_platform
        article_id = job.article_id
        user_id = job.user_id

        # Determine resume point from current status
        if job.status == "pending":
            # Restart from capture — re-queue the correct capture task
            await transition(
                db,
                job_id=job_id,
                current_status="pending",
                target_status="capturing",
            )
            if source_url:
                from inflow_core.ingest.adapters.registry import adapter_registry
                adapter = adapter_registry.resolve(source_url)
                raw_capture = await adapter.fetch(source_url, user_id=user_id, capture_method="url")
                raw_path = await default_storage.write_raw(
                    platform=adapter.platform,
                    job_id=job_id,
                    data=raw_capture.to_dict(),
                )
                await transition(
                    db,
                    job_id=job_id,
                    current_status="capturing",
                    target_status="captured",
                    raw_file_path=raw_path,
                )
                await _update_article_from_raw(db, job_id, raw_capture)
                await _route_pipeline(
                    db,
                    job_id=job_id,
                    article_id=article_id,
                    user_id=user_id,
                    content_type=content_type,
                    raw_file_path=raw_path,
                    source_url=source_url,
                    source_platform=source_platform,
                    on_composed=on_composed,
                )
            return

        if job.status == "captured":
            if not job.raw_file_path:
                logger.error("resume: job %s has no raw_file_path for captured status", job_id)
                return
            await _route_pipeline(
                db,
                job_id=job_id,
                article_id=article_id,
                user_id=user_id,
                content_type=content_type,
                raw_file_path=job.raw_file_path,
                source_url=source_url,
                source_platform=source_platform,
                on_composed=on_composed,
            )
            return

        if job.status == "transcribed":
            if not job.raw_file_path or not job.asr_file_path:
                logger.error("resume: job %s missing paths for transcribed status", job_id)
                return
            await run_chapters(
                db,
                job_id=job_id,
                raw_file_path=job.raw_file_path,
                current_status="transcribed",
                content_type=content_type,
            )
            parsed_path = await run_parse(
                db,
                job_id=job_id,
                raw_file_path=job.raw_file_path,
                asr_file_path=job.asr_file_path,
                current_status="parsing",
                content_type=content_type,
            )
            if not parsed_path or not article_id:
                return
            await _compose_and_continue(
                db,
                job_id=job_id,
                article_id=article_id,
                user_id=user_id,
                raw_file_path=job.raw_file_path,
                parsed_file_path=parsed_path,
                asr_file_path=job.asr_file_path,
                source_platform=source_platform,
                content_type=content_type,
                source_url=source_url,
                on_composed=on_composed,
            )
            return

        if job.status == "normalized":
            if not job.raw_file_path:
                logger.error("resume: job %s missing raw_file_path for normalized status", job_id)
                return
            from inflow_core.core.shared.storage.conventions import parse_asr_txt_path
            asr_txt = parse_asr_txt_path(job.raw_file_path, job_id)
            await run_chapters(
                db,
                job_id=job_id,
                raw_file_path=job.raw_file_path,
                current_status="normalized",
                content_type=content_type,
            )
            parsed_path = await run_parse(
                db,
                job_id=job_id,
                raw_file_path=job.raw_file_path,
                asr_file_path=asr_txt,
                current_status="parsing",
                content_type=content_type,
            )
            if not parsed_path or not article_id:
                return
            await _compose_and_continue(
                db,
                job_id=job_id,
                article_id=article_id,
                user_id=user_id,
                raw_file_path=job.raw_file_path,
                parsed_file_path=parsed_path,
                asr_file_path=asr_txt,
                source_platform=source_platform,
                content_type=content_type,
                source_url=source_url,
                on_composed=on_composed,
            )
            return

        if job.status == "parsed":
            if not job.parsed_file_path or not job.raw_file_path or not article_id:
                logger.error("resume: job %s missing paths for parsed status", job_id)
                return
            from inflow_core.core.shared.storage.conventions import parse_asr_txt_path
            asr_for_card = job.asr_file_path
            if content_type != "audio":
                asr_for_card = parse_asr_txt_path(job.raw_file_path, job_id)
            await _compose_and_continue(
                db,
                job_id=job_id,
                article_id=article_id,
                user_id=user_id,
                raw_file_path=job.raw_file_path,
                parsed_file_path=job.parsed_file_path,
                asr_file_path=asr_for_card,
                source_platform=source_platform,
                content_type=content_type,
                source_url=source_url,
                on_composed=on_composed,
            )
            return

        if job.status == "composed":
            if not job.parsed_file_path or not job.raw_file_path or not article_id:
                logger.error("resume: job %s missing paths for composed status", job_id)
                return
            # 崩溃于 compose 之后、SFTP 回传完成前：重跑回传（幂等 .tmp→rename 覆盖），
            # 失败则 job 停在 composed→failed，绝不出现 ready 却无云端 PNG。
            if on_composed is not None:
                from inflow_core.core.shared.storage.conventions import display_card_png_path

                png_path = display_card_png_path(job.raw_file_path, job_id)
                if not await _upload_png_or_fail(
                    db, job_id=job_id, png_path=png_path, on_composed=on_composed
                ):
                    return
            await run_index(
                db,
                job_id=job_id,
                article_id=article_id,
                user_id=user_id,
                parsed_file_path=job.parsed_file_path,
                raw_file_path=job.raw_file_path,
                source_url=source_url,
                source_platform=source_platform,
                content_type=content_type,
            )
            return

        # ── Interrupted mid-step: roll back to last completed checkpoint ──

        if job.status == "normalizing":
            if not job.raw_file_path:
                return
            await force_set_status(db, job_id, "captured")
            await _route_pipeline(
                db,
                job_id=job_id,
                article_id=article_id,
                user_id=user_id,
                content_type=content_type,
                raw_file_path=job.raw_file_path,
                source_url=source_url,
                source_platform=source_platform,
                on_composed=on_composed,
            )
            return

        if job.status == "transcribing":
            # Transcription was interrupted — roll back to captured and redo.
            if not job.raw_file_path:
                logger.error("resume: job %s has no raw_file_path for transcribing rollback", job_id)
                return
            await force_set_status(db, job_id, "captured")
            await _route_pipeline(
                db,
                job_id=job_id,
                article_id=article_id,
                user_id=user_id,
                content_type=content_type,
                raw_file_path=job.raw_file_path,
                source_url=source_url,
                source_platform=source_platform,
                on_composed=on_composed,
            )
            return

        if job.status == "parsing":
            from inflow_core.core.shared.storage.conventions import parse_asr_txt_path
            parsed_path = None
            if job.asr_file_path:
                await force_set_status(db, job_id, "transcribed")
                await run_chapters(
                    db,
                    job_id=job_id,
                    raw_file_path=job.raw_file_path or "",
                    current_status="transcribed",
                    content_type=content_type,
                )
                parsed_path = await run_parse(
                    db,
                    job_id=job_id,
                    raw_file_path=job.raw_file_path or "",
                    asr_file_path=job.asr_file_path,
                    current_status="parsing",
                    content_type=content_type,
                )
            else:
                if not job.raw_file_path:
                    logger.error("resume: job %s has no raw_file_path for parsing rollback", job_id)
                    return
                asr_txt = parse_asr_txt_path(job.raw_file_path, job_id)
                await force_set_status(db, job_id, "normalized")
                await run_chapters(
                    db,
                    job_id=job_id,
                    raw_file_path=job.raw_file_path,
                    current_status="normalized",
                    content_type=content_type,
                )
                parsed_path = await run_parse(
                    db,
                    job_id=job_id,
                    raw_file_path=job.raw_file_path,
                    asr_file_path=asr_txt,
                    current_status="parsing",
                    content_type=content_type,
                )
            if parsed_path and job.raw_file_path:
                asr_for_card = job.asr_file_path or parse_asr_txt_path(job.raw_file_path, job_id)
                await _compose_and_continue(
                    db,
                    job_id=job_id,
                    article_id=article_id,
                    user_id=user_id,
                    raw_file_path=job.raw_file_path,
                    parsed_file_path=parsed_path,
                    asr_file_path=asr_for_card,
                    source_platform=source_platform,
                    content_type=content_type,
                    source_url=source_url,
                    on_composed=on_composed,
                )
            return

        if job.status == "composing":
            if not job.parsed_file_path or not job.raw_file_path or not article_id:
                return
            await force_set_status(db, job_id, "parsed")
            asr_for_card = job.asr_file_path
            if content_type != "audio":
                from inflow_core.core.shared.storage.conventions import parse_asr_txt_path
                asr_for_card = parse_asr_txt_path(job.raw_file_path, job_id)
            await _compose_and_continue(
                db,
                job_id=job_id,
                article_id=article_id,
                user_id=user_id,
                raw_file_path=job.raw_file_path,
                parsed_file_path=job.parsed_file_path,
                asr_file_path=asr_for_card,
                source_platform=source_platform,
                content_type=content_type,
                source_url=source_url,
                on_composed=on_composed,
            )
            return

        if job.status == "indexing":
            if not job.parsed_file_path or not job.raw_file_path or not article_id:
                logger.error("resume: job %s missing paths for indexing rollback", job_id)
                return
            await force_set_status(db, job_id, "composed")
            await run_index(
                db,
                job_id=job_id,
                article_id=article_id,
                user_id=user_id,
                parsed_file_path=job.parsed_file_path,
                raw_file_path=job.raw_file_path,
                source_url=source_url,
                source_platform=source_platform,
                content_type=content_type,
            )
            return

        logger.warning("resume: job %s has unexpected status=%r", job_id, job.status)


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

async def force_set_status(db: AsyncSession, job_id: UUID, status: str) -> None:
    """Directly write a job status bypassing the state machine.

    Only for startup recovery: roll an interrupted mid-step job back to
    its last completed checkpoint so the normal pipeline can re-run it.
    """
    from sqlalchemy import update as sa_update
    await db.execute(
        sa_update(IngestJob)
        .where(IngestJob.id == job_id)
        .values(status=status)
    )
    await db.commit()
    logger.info("Recovery: force-reset job %s to status=%r", job_id, status)

async def _download_media_if_needed(
    raw_capture,
    raw_path: str,
    job_id: UUID,
    *,
    phase: PhaseLogger | None = None,
) -> None:
    """Download audio/video media file during the capture step.

    Ensures "采集完成" reflects that the actual media is ready, not just metadata.
    Safe to call even if the file already exists — AudioDownloader skips cached files.
    """
    from pathlib import Path
    from urllib.parse import urlparse

    media_urls = getattr(raw_capture.raw, "media_urls", None) or []
    content_type = getattr(raw_capture.raw, "content_type", None)
    # Video download belongs in the preprocessing step (separate pipeline stage).
    # Only pull audio files here so the capture step stays fast for video.
    if not media_urls or content_type != "audio":
        return

    from inflow_core.core.shared.storage.conventions import ingest_media_path
    from inflow_core.parse.audio.downloader import AudioDownloader

    audio_url = media_urls[0]
    url_suffix = Path(urlparse(audio_url).path).suffix.lower()
    ext = url_suffix if url_suffix in {".mp3", ".m4a", ".ogg", ".flac", ".wav", ".aac"} else ".mp3"

    audio_dest = Path(ingest_media_path(raw_path, job_id, ext))
    if audio_dest.is_file() and audio_dest.stat().st_size > 0:
        if phase:
            phase.detail(f"音频已缓存 {audio_dest.stat().st_size / 1024 / 1024:.1f} MB")
        return

    if phase:
        phase.detail("下载音频文件…")
    downloader = AudioDownloader()

    def _on_progress(msg: str) -> None:
        if phase:
            phase.detail(msg)

    await downloader.download(
        audio_url,
        dest_dir=audio_dest.parent,
        filename=audio_dest.name,
        progress_cb=_on_progress if phase else None,
    )
    if phase:
        rel_path = audio_dest.relative_to(audio_dest.anchor)
        # phase.detail(f"音频文件下载完成：{audio_dest.stat().st_size / 1024 / 1024:.1f} MB（{rel_path}）")
   


# ------------------------------------------------------------------ #
# Startup recovery                                                    #
# ------------------------------------------------------------------ #

async def recover_captured_jobs() -> None:
    """On server startup, resume any jobs interrupted mid-pipeline.

    Recovers jobs in intermediate states that were left hanging by a server
    crash or restart.  Terminal states (ready / failed / cancelled) are left
    alone — only active in-flight states are re-queued.
    """
    from sqlalchemy import select
    from inflow_core.core.database import async_session

    # States that represent interrupted in-progress work.
    _RECOVERABLE = (
        "captured", "normalizing", "normalized",
        "transcribing", "transcribed", "parsing", "parsed",
        "composing", "composed", "indexing",
    )

    try:
        async with async_session() as db:
            result = await db.execute(
                select(IngestJob).where(
                    IngestJob.status.in_(_RECOVERABLE),
                    IngestJob.article_id.isnot(None),
                    # 由本地 worker 承接的 job 不在云端恢复，避免云端抢跑/重复处理
                    IngestJob.external_processing.is_(False),
                )
            )
            jobs = result.scalars().all()

        if not jobs:
            return

        logger.info("Startup recovery: found %d interrupted job(s) — resuming", len(jobs))

        import asyncio
        for job in jobs:
            if not job.raw_file_path:
                logger.warning("Recovery: job %s has no raw_file_path — skipping", job.id)
                continue
            asyncio.create_task(
                run_job_resume(job_id=job.id),
                name=f"recover-{job.id}",
            )

    except Exception as exc:
        logger.error("Startup recovery failed: %s", exc)
