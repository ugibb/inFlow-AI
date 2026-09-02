"""Ingest orchestrator — cloud-side registration entry points.

云端只登记收件，完整 capture/parse/compose/index 管道由本地 worker
（ugibb/inflow-worker）承接：
- ingest_url():      URL 抓取 → 创建 Article stub + IngestJob，标记 external 后
                     等本地 worker 认领（含收件标题预取，供前端立即可见）。
- ingest_upload():   文件上传 → 收件原子落盘 data/00_staging/，worker 经 SFTP 拉取。
- ingest_text():     粘贴文本 → 同上。
- resume_job():      重试入口 → 云端只重置/标记状态，实际处理交给本地 worker。

历史 non-external job（旧版云端自跑管道遗留）在 resume 时统一标记 external
转交 worker；云端 venv 已做依赖瘦身，不再包含 parse/display 等重引擎。
"""

from __future__ import annotations

import logging
import os
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models.ingest_job import IngestJob
from backend.core.models.article import Article
from backend.core.ingest.adapters.registry import adapter_registry
from backend.core.config import get_settings
from backend.core.pipeline.pipeline_log import log_task_start
from backend.core.shared.storage.conventions import staging_file_path

logger = logging.getLogger("inFlow.ingest.orchestrator")
settings = get_settings()

# Platforms inferred as audio before capture begins
_AUDIO_PLATFORMS = frozenset({"xiaoyuzhou", "bilibili"})


def _infer_content_type(platform: str | None) -> str:
    return "audio" if platform in _AUDIO_PLATFORMS else "article"


def _write_staging_file(job_id: UUID, filename: str, content: bytes) -> str:
    """upload/paste 全量分流：云端收件原子落盘 data/00_staging/，返回相对路径。

    worker 认领 job 后经 SFTP 拉取该文件完成 capture（markitdown/parse 全在 worker）。
    """
    path = staging_file_path(settings.data_root, job_id, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "wb") as fh:
        fh.write(content)
    os.replace(tmp_path, path)
    return path


# ------------------------------------------------------------------ #
# Public entry points                                                 #
# ------------------------------------------------------------------ #

async def _peek_url_title(url: str) -> str | None:
    """Best-effort title from og:title / <title> before full capture runs."""
    from bs4 import BeautifulSoup
    import httpx
    from backend.core.ingest.fetchers import extract_url_from_text, parser_service

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


def _mark_external(job: IngestJob) -> None:
    """Mark a job as worker-owned (cloud no longer runs any pipeline)."""
    job.external_processing = True


async def _count_ready_today(db: AsyncSession, user_id: UUID) -> int:
    """当日已到 ready 的 job 数（worker 契约 quota_check.sql 判定口径）。

    按 updated_at 归日（当天完成即占当天额度），status='ready' 才算成功产出。
    """
    result = await db.execute(
        select(func.count())
        .select_from(IngestJob)
        .where(
            IngestJob.user_id == user_id,
            IngestJob.status == "ready",
            IngestJob.updated_at >= func.date_trunc("day", func.now()),
        )
    )
    return int(result.scalar_one())


async def ensure_within_quota(db: AsyncSession, user_id: UUID) -> None:
    """免费额度配额前置检查：登记新 job 前调用，超限拒绝（HTTP 429）。

    额度来源：系统管理 UI（config_store.json quota 组）> FREE_QUOTA_PER_DAY /
    默认 10；返回 <=0 表示不限制（自托管全放开）。config_manager 每次现读，
    因此 UI 改动后立即生效。
    """
    from backend.core.config_manager import get_quota_limit

    quota = get_quota_limit()
    if quota <= 0:
        return
    used = await _count_ready_today(db, user_id)
    if used >= quota:
        raise HTTPException(
            status_code=429,
            detail=f"今日免费额度（{quota} 条）已用完，明天再来",
        )


async def ingest_url(
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    *,
    url: str,
    user_id: UUID,
    capture_method: str = "url",
) -> UUID:
    """Register an IngestJob for a URL, to be captured by the local worker.

    Creates an Article stub and IngestJob atomically.  The job is marked
    external_processing and left pending for the worker to claim.

    `background_tasks` is retained for signature compatibility with callers.
    """
    await ensure_within_quota(db, user_id)

    from backend.core.ingest.fetchers import extract_url_from_text
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

    # 云端只登记：job 标记 external 交给本地 worker 承接完整 pipeline。
    # （即使配置意外为 False，云端 venv 已瘦身不跑管道，仍按登记处理。）
    _mark_external(job)
    await db.commit()
    log_task_start(
        job_id=job_id,
        article_id=article_id,
        method="url",
        platform=adapter.platform,
        url=clean_url,
    )
    logger.info("外部处理分流: job=%s → 交给本地 worker", job_id)
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
    """Register an IngestJob for an uploaded file, staged for the worker.

    The raw bytes are written atomically to data/00_staging/ so the worker
    can pull them over SFTP and run markitdown/parse locally.
    """
    await ensure_within_quota(db, user_id)

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

    staging_rel = _write_staging_file(job_id, filename, content)
    _mark_external(job)
    job.staging_file_path = staging_rel
    await db.commit()
    log_task_start(
        job_id=job_id,
        article_id=article_id,
        method="upload",
        platform="upload",
        file=filename,
    )
    logger.info("外部处理分流: job=%s → 交给本地 worker（upload 暂存 %s）", job_id, staging_rel)
    return job_id


async def ingest_text(
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    *,
    text: str,
    title: str | None,
    user_id: UUID,
) -> UUID:
    """Register an IngestJob for pasted text, staged for the worker."""
    await ensure_within_quota(db, user_id)

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

    staging_rel = _write_staging_file(job_id, "note.md", text.encode("utf-8"))
    _mark_external(job)
    job.staging_file_path = staging_rel
    await db.commit()
    log_task_start(
        job_id=job_id,
        article_id=article_id,
        method="paste",
        platform="generic",
        title=real_title,
    )
    logger.info("外部处理分流: job=%s → 交给本地 worker（paste 暂存 %s）", job_id, staging_rel)
    return job_id


async def resume_job(
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    *,
    job_id: UUID,
) -> None:
    """Retry entry: hand a reset job to the local worker.

    Cloud schedules no pipeline.  Historical non-external jobs are marked
    external here so the worker picks them up on its claim/heartbeat loop.

    `background_tasks` is retained for signature compatibility with callers.
    """
    job = await db.get(IngestJob, job_id)
    if job is None:
        logger.warning("resume_job: job %s not found", job_id)
        return

    if not job.external_processing:
        # 历史 non-external job：云端已无自跑管道，标记转交本地 worker 续跑。
        _mark_external(job)
        await db.commit()

    logger.info("resume_job: job %s 由本地 worker 承接，云端跳过调度", job_id)
