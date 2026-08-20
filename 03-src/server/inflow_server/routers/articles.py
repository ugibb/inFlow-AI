"""Article management API routes."""
import asyncio
import os
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, BackgroundTasks, Body
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, desc, text, update
from typing import Optional, List
from uuid import UUID

from inflow_core.core.database import get_db
from inflow_core.core.dependencies import get_current_user
from inflow_core.core.models.article import Article, Tag, Folder, ArticleStatus, KnowledgeEdge, article_tags
from inflow_core.core.models.ingest_job import IngestJob
from inflow_core.core.models.user import User
from inflow_core.core.schemas.article import (
    ArticleCreate, ArticleBatchCreate, ArticleManualCreate, ArticleUpdate, NoteCreate,
    ArticleResponse, ArticleDetailResponse, ArticleListResponse,
    DeepReadScreenshotRequest,
    AIProcessResponse, SearchRequest,
    SparkCreateRequest, SparkResponse, SparkSectionResponse,
    FileUploadResponse, ArticleTagsUpdate,
)
from inflow_core.ingest.fetchers import parser_service, extract_url_from_text
from inflow_core.ingest.orchestrator import ingest_url, ingest_upload, ingest_text
from inflow_core.core.shared.ai_service import llm_service
from inflow_core.display.services.graph_service import graph_service
from inflow_core.display.services.spark_service import generate_article

router = APIRouter(prefix="/api/articles", tags=["articles"])


PROACTIVE_DISTANCE_THRESHOLD = 0.45  # bge-small-zh cosine distance (<=>); lower = closer match
PROACTIVE_PUBLIC_BASE = os.getenv("inFlow_PUBLIC_BASE", "http://localhost")


def _canonical_url(url: str) -> str:
    """Normalize URL for dedup: strip query/fragment and trailing slash."""
    p = urlparse(url.strip())
    normalized_path = (p.path or "/").rstrip("/") or "/"
    return urlunparse((p.scheme, p.netloc.lower(), normalized_path, "", "", ""))


async def _maybe_push_proactive_relation(db, article_id):
    """If the just-added article has a strongly-related sibling in the same
    user's library, push a brief WeChat message: 「你刚存的《X》跟之前的《Y》
    主题相似，要不要对照看？」+ deep link to /read/<sibling_id>.

    Hooks bot push only when user has an active wechat binding.
    """
    from sqlalchemy import text as sql_text
    from inflow_core.core.models import WechatAccount
    article = await db.get(Article, article_id)
    if not article or article.embedding is None:
        return

    emb_str = "[" + ",".join(str(v) for v in article.embedding) + "]"
    sim_sql = sql_text(f"""
        SELECT id, title, (embedding <=> '{emb_str}'::vector) AS distance
        FROM articles
        WHERE embedding IS NOT NULL
          AND user_id = :uid
          AND id != :aid
        ORDER BY embedding <=> '{emb_str}'::vector
        LIMIT 1
    """)
    r = await db.execute(sim_sql, {"uid": article.user_id, "aid": article_id})
    row = r.first()
    if not row:
        return  # no other articles in library yet
    sibling_id, sibling_title, distance = row
    if float(distance) >= PROACTIVE_DISTANCE_THRESHOLD:
        return  # not close enough; skip silently

    # Find user's bound wechat account
    acct_r = await db.execute(
        select(WechatAccount).where(
            WechatAccount.user_id == article.user_id,
            WechatAccount.is_active.is_(True),
        )
    )
    acct = acct_r.scalar_one_or_none()
    if not acct:
        return  # no bot to push through

    new_title = (article.title or "Untitled").strip()
    old_title = (sibling_title or "Untitled").strip()
    deep_link = f"{PROACTIVE_PUBLIC_BASE}/read/{sibling_id}"
    msg = (
        f"📌 你刚存的《{new_title[:30]}》跟之前的《{old_title[:30]}》"
        f"主题很相似（距离 {float(distance):.2f}）。\n\n"
        f"要不要打开对照看？{deep_link}"
    )
    import httpx
    from inflow_server.extensions.review.service import send_wechat
    async with httpx.AsyncClient(timeout=20.0) as client:
        await send_wechat(client, acct, msg)
    logger.info(
        f"proactive: pushed relation to user={article.user_id} "
        f"new={article_id} sibling={sibling_id} dist={float(distance):.3f}"
    )


async def _run_asr_and_update(article_id: UUID, audio_url: str):
    """Background task: run ASR on audio URL and update article."""
    import logging
    logger = logging.getLogger("inFlow.asr")
    from inflow_core.core.database import async_session
    from inflow_core.parse.audio.service import transcription_service

    async with async_session() as db:
        try:
            article = await db.get(Article, article_id)
            if not article:
                return
            logger.info(f"ASR bg: starting for {article_id}")
            asr_text = await transcription_service.transcribe_url(
                audio_url, referer='https://www.bilibili.com'
            )
            if asr_text:
                article.raw_content += f"\n\n## 视频字幕（ASR 转录）\n\n{asr_text}"
                article.word_count = len(article.raw_content)
                await db.commit()
                logger.info(f"ASR bg: success, {len(asr_text)} chars")
            else:
                logger.warning(f"ASR bg: no text returned for {article_id}")
        except Exception as e:
            logger.exception(f"ASR bg: failed for {article_id}: {e}")


async def process_article_background(article_id: UUID, raw_content: str, raw_html: str, url: str, db_session_factory):
    """Background task: AI process a newly added article."""
    import logging
    logger = logging.getLogger("inFlow.background")
    from inflow_core.core.database import async_session
    
    async with async_session() as db:
        try:
            article = await db.get(Article, article_id)
            if not article:
                return
            
            # Clean content to markdown (skip for spark - already generated markdown)
            platform = article.source_platform or parser_service.detect_platform(url)
            # Skip HTML-cleanup when raw_content is already markdown:
            # - spark: AI-generated markdown
            # - bilibili videos / other API-based fetchers: empty raw_html signals "already markdown"
            if platform == "spark" or not raw_html:
                clean_md = raw_content
            else:
                clean_md = parser_service.clean_to_markdown(raw_content, platform)
            plain_text = clean_md  # For search purposes
            
            article.clean_content = clean_md
            article.plain_text = plain_text
            
            # AI parse — pass raw_html for richer context when plain_text is thin
            ai_result = await llm_service.parse_article(plain_text, url, raw_html)
            
            article.title = ai_result.get('title', article.title)
            article.summary = ai_result.get('summary', '')
            article.key_points = ai_result.get('key_points', [])
            # source_platform priority: URL domain (most accurate) > existing > AI guess > 'other'.
            # Don't let AI overwrite a domain-detected platform (AI prompt's enum is incomplete).
            detected = parser_service.detect_platform(url) if url else 'other'
            if article.source_platform in (None, '', 'other') and detected == 'other':
                article.source_platform = ai_result.get('source_platform', 'other')
            elif article.source_platform in (None, '',):
                article.source_platform = detected
            # Author: parser-extracted value (from platform metadata) wins over AI guess.
            # AI often returns "unknown" for short-text platforms (douyin/xhs) where the
            # author isn't in the textual content but IS in the structured metadata.
            ai_author = (ai_result.get('author') or '').strip()
            if not article.author and ai_author and ai_author.lower() != 'unknown':
                article.author = ai_author
            if not article.author:
                article.author = 'unknown'
            article.reading_time = ai_result.get('estimated_reading_minutes', 5)
            article.word_count = parser_service.count_words(plain_text)
            
            # Process tags
            ai_tags = ai_result.get('tags', [])
            for tag_name in ai_tags:
                # Find or create tag
                result = await db.execute(
                    select(Tag).where(func.lower(Tag.name) == tag_name.lower())
                )
                tag = result.scalar_one_or_none()
                if not tag:
                    tag = Tag(name=tag_name, is_ai_generated=True, user_id=article.user_id)
                    db.add(tag)
                    await db.flush()
                article.tags.append(tag)
            
            await db.commit()
            
            # Generate knowledge graph connections
            try:
                await graph_service.generate_graph(db, article_id)
                await db.commit()
            except Exception as graph_err:
                logger.warning(f"Graph generation error for {article_id}: {graph_err}")
            
            # Generate embedding for semantic search
            try:
                title_part = (article.title or "")[:100]
                summary_part = (article.summary or "")[:350]
                content_for_embedding = f"{title_part}. {summary_part}".strip(". ") or plain_text[:400]
                embedding = await llm_service.get_embedding(content_for_embedding)
                article.embedding = embedding
                await db.commit()
            except Exception as embed_err:
                logger.warning(f"Embedding generation error for {article_id}: {embed_err} (will be retried by auto-backfill)")

            # Proactive: find a strongly-related earlier article and ping the user via bot.
            # Cheap: one SQL similarity query + at most one WeChat sendmessage.
            try:
                await _maybe_push_proactive_relation(db, article_id)
            except Exception as e:
                logger.warning(f"proactive relation push failed for {article_id}: {e}")

        except Exception as e:
            import traceback
            logger.error(f"Background processing FATAL for {article_id}: {e}")
            logger.error(traceback.format_exc())
            await db.rollback()


@router.post("", status_code=202)
async def create_article(
    data: ArticleCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a new article by URL. Returns job_id; pipeline processes asynchronously."""
    clean_url = extract_url_from_text(data.url) or data.url.strip()
    if not clean_url.startswith(('http://', 'https://')):
        raise HTTPException(status_code=400, detail="Could not find a valid URL in input")
    canonical = _canonical_url(clean_url)
    url_variants = list({clean_url, canonical})

    # Check if this URL already exists in the user's library
    existing = await db.execute(
        select(Article)
        .where(Article.user_id == current_user.id, Article.url.in_(url_variants))
        .limit(1)
    )
    existing_article = existing.scalar_one_or_none()
    if existing_article:
        return {
            "job_id": None,
            "status": "already_exists",
            "article_id": str(existing_article.id),
            "message": "这篇文章已经在你的库里了",
        }

    job_id = await ingest_url(db, background_tasks, url=canonical, user_id=current_user.id)
    await db.commit()
    return {"job_id": str(job_id), "status": "capturing"}


@router.post("/batch", status_code=202)
async def batch_create_articles(
    data: ArticleBatchCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Batch add articles by URLs. Returns list of queued job IDs."""
    jobs = []
    for raw in data.urls:
        raw_url = extract_url_from_text(raw) or raw.strip()
        if not raw_url.startswith(('http://', 'https://')):
            continue
        canonical = _canonical_url(raw_url)
        variants = list({raw_url, canonical})
        existing = await db.execute(
            select(Article)
            .where(Article.user_id == current_user.id, Article.url.in_(variants))
            .limit(1)
        )
        if existing.scalar_one_or_none():
            continue
        try:
            job_id = await ingest_url(db, background_tasks, url=canonical, user_id=current_user.id)
            jobs.append({"job_id": str(job_id), "url": canonical})
        except Exception:
            continue

    await db.commit()
    return {"jobs": jobs, "count": len(jobs)}


@router.patch("/batch-move", status_code=200)
async def batch_move_articles(
    article_ids: list[UUID] = Body(...),
    folder_id: Optional[UUID] = Body(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Batch move articles to a folder. folder_id=null moves to root."""
    # User isolation: superadmins can move any, normal users only own articles
    stmt = update(Article).where(Article.id.in_(article_ids))
    if not current_user.is_super_admin:
        stmt = stmt.where(Article.user_id == current_user.id)
    stmt = stmt.values(folder_id=folder_id)
    result = await db.execute(stmt)
    await db.commit()
    
    count = result.rowcount
    return {"message": f"Moved {count} articles", "count": count}


@router.post("/manual", status_code=202)
async def create_article_manual(
    data: ArticleManualCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an article from manually pasted content (for platforms that block scraping)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(data.content, 'lxml')
    extracted = soup.get_text(separator='\n', strip=True)

    job_id = await ingest_text(
        db, background_tasks,
        text=extracted,
        title=data.title,
        user_id=current_user.id,
    )
    await db.commit()
    return {"job_id": str(job_id), "status": "capturing"}


@router.post("/notes", status_code=202)
async def create_note(
    data: NoteCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a Markdown note. Enters the ingest pipeline for AI processing."""
    if not data.content or not data.content.strip():
        raise HTTPException(status_code=422, detail="Note content is empty")

    job_id = await ingest_text(
        db, background_tasks,
        text=data.content,
        title=data.title,
        user_id=current_user.id,
    )
    await db.commit()
    return {"job_id": str(job_id), "status": "capturing"}


# ---- Spark: 一句话→文章生成 ----
@router.post("/spark", response_model=SparkResponse, status_code=201)
async def spark_create_article(
    data: SparkCreateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a full article from a single sentence using AI pipeline."""
    import logging
    logger = logging.getLogger(__name__)

    try:
        result = await generate_article(data.sentence)
    except Exception as e:
        logger.error(f"Spark pipeline failed: {e}")
        raise HTTPException(status_code=500, detail=f"Article generation failed: {str(e)}")

    # Use the sentence as URL (unique identifier for spark-generated articles)
    import time
    spark_url = f"spark://{data.sentence[:50]}-{int(time.time())}"

    article = Article(
        url=spark_url,
        title=result["title"],
        raw_content=result["content"],
        clean_content=result["content"],  # Already markdown, ready for reader
        plain_text=result["content"],
        source_platform="spark",
        author="inFlow AI AI",
        word_count=len(result["content"]),
        user_id=current_user.id,
    )

    db.add(article)
    await db.commit()
    await db.refresh(article)

    # Trigger background AI processing for tags/summary/key_points
    background_tasks.add_task(
        process_article_background,
        article.id,
        result["content"],      # raw_content (markdown)
        result["content"],      # raw_html (pass markdown as fallback for AI context)
        spark_url,
        None,
    )

    return SparkResponse(
        id=str(article.id),
        title=result["title"],
        content=result["content"],
        sections=[
            SparkSectionResponse(
                heading=s["heading"],
                key_points=s["key_points"],
                content=s["content"],
            )
            for s in result.get("sections", [])
        ],
        steps_completed=result.get("steps_completed", []),
        status=result.get("status", "completed"),
    )


# ---- File Upload: MarkItDown conversion ----
ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".xlsx", ".pptx",
    ".png", ".jpg", ".jpeg", ".txt", ".html",
    ".epub", ".csv", ".md",
}

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "image/png",
    "image/jpeg",
    "text/plain",
    "text/html",
    "application/epub+zip",
    "text/csv",
    "text/markdown",
    "application/zip",
}

# Extended mime types that should still be accepted
ADDITIONAL_MIME_TYPES = {
    "application/vnd.ms-excel",        # .xls
    "application/vnd.ms-powerpoint",   # .ppt
    "application/msword",              # .doc
    "text/x-markdown",
    "text/x-csv",
}


@router.post("/upload", status_code=202)
async def upload_article_file(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    file: UploadFile = None,
):
    """Upload a file. Enters the ingest pipeline for MarkItDown conversion and AI parsing."""
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    _, ext = os.path.splitext(file.filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format: {ext}. Supported formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    if ext in IMAGE_EXTS and len(file_bytes) > 2 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"图片不能超过 2MB（当前 {len(file_bytes) / 1024 / 1024:.2f}MB）",
        )

    job_id = await ingest_upload(
        db,
        background_tasks,
        filename=file.filename,
        content=file_bytes,
        user_id=current_user.id,
        mime_type=file.content_type,
    )
    await db.commit()
    return {"job_id": str(job_id), "status": "capturing"}


@router.get("", response_model=ArticleListResponse)
async def list_articles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    folder_id: Optional[UUID] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    source_platform: Optional[str] = None,
    search_mode: str = Query("semantic", regex="^(semantic|keyword)$"),
    sort: str = Query("created_at", regex="^(created_at|updated_at|title)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    username_query: str | None = Query(None, alias="username", description="Superadmin: filter by username"),
):
    """List articles with filtering, search, and pagination."""
    
    query = select(Article)
    count_query = select(func.count(Article.id))
    
    # User isolation: superadmin sees own by default, or specific user via ?username=xxx
    target_user_id = current_user.id
    if current_user.is_super_admin and username_query:
        user_result = await db.execute(select(User).where(User.username == username_query))
        target_user = user_result.scalar_one_or_none()
        target_user_id = target_user.id if target_user else current_user.id
    query = query.where(Article.user_id == target_user_id)
    count_query = count_query.where(Article.user_id == target_user_id)
    
    # Filters
    if status:
        if status == "favorite":
            query = query.where(Article.is_favorited == True)
            count_query = count_query.where(Article.is_favorited == True)
        else:
            query = query.where(Article.status == status)
            count_query = count_query.where(Article.status == status)
    
    if folder_id:
        query = query.where(Article.folder_id == folder_id)
        count_query = count_query.where(Article.folder_id == folder_id)
    
    if tag:
        query = query.join(article_tags).join(Tag).where(
            func.lower(Tag.name) == tag.lower()
        )
        count_query = count_query.join(article_tags).join(Tag).where(
            func.lower(Tag.name) == tag.lower()
        )
    
    # Search — semantic by default, keyword fallback
    if search:
        if search_mode == "semantic":
            try:
                query_embedding = await llm_service.get_embedding(search, emb_type="query")
                query = query.where(Article.embedding.isnot(None))
                query = query.order_by(Article.embedding.cosine_distance(query_embedding))
                count_query = count_query.where(Article.embedding.isnot(None))
            except Exception:
                # Fallback to keyword search on embedding failure
                search_filter = or_(
                    Article.title.ilike(f"%{search}%"),
                    Article.plain_text.ilike(f"%{search}%"),
                    Article.summary.ilike(f"%{search}%"),
                )
                query = query.where(search_filter).order_by(desc(Article.created_at))
                count_query = count_query.where(search_filter)
        else:
            search_filter = or_(
                Article.title.ilike(f"%{search}%"),
                Article.plain_text.ilike(f"%{search}%"),
                Article.summary.ilike(f"%{search}%"),
            )
            query = query.where(search_filter).order_by(desc(Article.created_at))
            count_query = count_query.where(search_filter)
    else:
        sort_col = getattr(Article, sort)
        query = query.order_by(desc(sort_col))

    # Source platform filter (case-insensitive)
    if source_platform:
        platform_filter = func.lower(Article.source_platform) == source_platform.lower()
        query = query.where(platform_filter)
        count_query = count_query.where(platform_filter)
    
    # Count
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # Sort (only when no search — search modes handle their own ordering)
    if not search:
        sort_col = getattr(Article, sort)
        query = query.order_by(desc(sort_col))
    
    # Paginate
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    
    result = await db.execute(query)
    articles = result.scalars().all()
    
    return ArticleListResponse(
        items=articles,
        total=total,
        page=page,
        page_size=page_size,
    )


async def _get_ingest_extras(
    db: AsyncSession, article_id: UUID
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Read media_url, raw_text, cover_image, and content_type from the ingest file.

    Returns (media_url, raw_text, cover_image, content_type). All may be None.
    """
    import json as _json
    try:
        r = await db.execute(
            select(IngestJob).where(IngestJob.article_id == article_id).limit(1)
        )
        job = r.scalar_one_or_none()
        if not job or not job.raw_file_path or not os.path.exists(job.raw_file_path):
            return None, None, None, None
        with open(job.raw_file_path, encoding="utf-8") as f:
            raw = _json.load(f)
        raw_section = raw.get("raw", {})
        urls = raw_section.get("media_urls", [])
        media_url = urls[0] if urls else None
        raw_text = raw_section.get("raw_text") or None
        cover_image = raw_section.get("cover_image") or None
        content_type = raw_section.get("content_type") or None
        return media_url, raw_text, cover_image, content_type
    except Exception:
        return None, None, None, None


@router.get("/{article_id}/chapters")
async def get_article_chapters(
    article_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return rich chapter data from the {job_id}_chapters.json file."""
    import json as _json
    from pathlib import Path
    from inflow_core.core.shared.storage.conventions import parse_chapters_path

    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if not current_user.is_super_admin and article.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Article not found")

    r = await db.execute(select(IngestJob).where(IngestJob.article_id == article_id).limit(1))
    job = r.scalar_one_or_none()
    if not job or not job.raw_file_path:
        raise HTTPException(status_code=404, detail="Chapters not available")

    chapters_file = Path(parse_chapters_path(job.raw_file_path, job.id))
    if not chapters_file.is_file():
        raise HTTPException(status_code=404, detail="Chapters not yet generated")

    try:
        data = _json.loads(chapters_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read chapters: {exc}") from exc

    # If total_duration is missing, fill from ASR verbose JSON (display only — chapter times come from LLM)
    if not data.get("total_duration"):
        try:
            from inflow_core.core.shared.storage.conventions import parse_transcript_base
            base = parse_transcript_base(job.raw_file_path, job.id)
            verbose = Path(base).parent / (Path(base).stem + "_verbose.json")
            if verbose.is_file():
                vdata = _json.loads(verbose.read_text(encoding="utf-8"))
                real_dur = float(vdata.get("duration") or 0)
                if real_dur > 0:
                    data["total_duration"] = real_dur
        except Exception:
            pass

    return data


@router.get("/{article_id}/transcript")
async def get_article_transcript(
    article_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return ASR transcript segments for a completed audio article."""
    import json as _json
    from pathlib import Path
    from inflow_core.core.shared.storage.conventions import parse_transcript_base

    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if not current_user.is_super_admin and article.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Article not found")

    r = await db.execute(
        select(IngestJob).where(IngestJob.article_id == article_id).limit(1)
    )
    job = r.scalar_one_or_none()
    if not job or not job.raw_file_path:
        raise HTTPException(status_code=404, detail="Transcript not available")

    base = parse_transcript_base(job.raw_file_path, job.id)
    verbose_path = Path(base).parent / (Path(base).stem + "_verbose.json")
    if not verbose_path.is_file():
        raise HTTPException(status_code=404, detail="Transcript not yet available")

    try:
        data = _json.loads(verbose_path.read_text(encoding="utf-8"))
        segments = [
            {"start": s["start"], "end": s["end"], "text": s["text"]}
            for s in (data.get("segments") or [])
        ]
        return {"language": data.get("language"), "duration": data.get("duration"), "segments": segments}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read transcript: {exc}") from exc


@router.get("/{article_id}/deep-read", response_class=HTMLResponse)
async def get_article_deep_read(
    article_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HTMLResponse:
    """Return the AI deep-read card HTML from data/03_display/…/{job_id}.html."""
    from pathlib import Path
    from inflow_core.core.shared.storage.conventions import display_card_html_path

    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if not current_user.is_super_admin and article.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Article not found")

    r = await db.execute(select(IngestJob).where(IngestJob.article_id == article_id).limit(1))
    job = r.scalar_one_or_none()
    if not job or not job.raw_file_path:
        raise HTTPException(status_code=404, detail="Deep read not available")

    html_path = Path(display_card_html_path(job.raw_file_path, job.id))
    if not html_path.is_file():
        raise HTTPException(status_code=404, detail="Deep read not yet generated")

    try:
        html_content = html_path.read_text(encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read deep read HTML: {exc}") from exc

    return HTMLResponse(content=html_content)


@router.post("/{article_id}/deep-read/screenshot")
async def capture_article_deep_read_screenshot(
    article_id: UUID,
    body: DeepReadScreenshotRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Playwright screenshot of the current deep-read HTML (matches pipeline card quality)."""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if not current_user.is_super_admin and article.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Article not found")

    from inflow_core.compose.card_renderer import screenshot_html_content

    try:
        png_bytes = await screenshot_html_content(body.html)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Screenshot failed: {exc}") from exc

    return Response(content=png_bytes, media_type="image/png")


@router.post("/{article_id}/regenerate-ai", status_code=202)
async def regenerate_article_ai(
    article_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Re-run AI analysis (chapters + summary) for an audio article, skipping ASR."""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if not current_user.is_super_admin and article.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Article not found")
    if article.content_type != "audio":
        raise HTTPException(status_code=400, detail="Regeneration only supported for audio articles")

    r = await db.execute(select(IngestJob).where(IngestJob.article_id == article_id).limit(1))
    job = r.scalar_one_or_none()
    if not job or not job.raw_file_path:
        raise HTTPException(status_code=404, detail="Source data not available for regeneration")

    background_tasks.add_task(
        _run_regenerate_ai,
        job_id=job.id,
        article_id=article_id,
        user_id=current_user.id,
        raw_file_path=job.raw_file_path,
        source_url=job.source_url,
        source_platform=job.source_platform,
    )
    return {"status": "started", "article_id": str(article_id)}


@router.get("/{article_id}/regen-status")
async def get_article_regen_status(
    article_id: UUID,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return current regeneration progress for display in the frontend."""
    from inflow_core.core.shared.progress import get_progress
    msg = get_progress(str(article_id))
    return {"active": msg is not None, "message": msg or ""}


async def _run_regenerate_ai(
    *,
    job_id: UUID,
    article_id: UUID,
    user_id: UUID,
    raw_file_path: str,
    source_url: str | None,
    source_platform: str | None,
) -> None:
    import logging as _log
    import time as _time
    _logger = _log.getLogger("inFlow.articles.regenerate")
    from inflow_core.core.shared.progress import set_progress, clear_progress

    key = str(article_id)
    t0 = _time.perf_counter()
    _logger.info("[regenerate] START | job=%s | article=%s", job_id, article_id)
    set_progress(key, "正在准备…")
    try:
        from inflow_core.core.database import async_session
        from inflow_core.parse.parser import parse_job
        from inflow_core.display.renderer import render_job

        def _cb(msg: str) -> None:
            set_progress(key, msg)
            _logger.info("[regenerate] progress: %s | elapsed=%.1fs", msg, _time.perf_counter() - t0)

        parsed_path = await parse_job(
            job_id=job_id,
            raw_file_path=raw_file_path,
            _t0=t0,
            progress_cb=_cb,
        )

        set_progress(key, "正在保存…")
        _logger.info("[regenerate] step=render_job | elapsed=%.1fs", _time.perf_counter() - t0)
        async with async_session() as db:
            await render_job(
                db,
                job_id=job_id,
                user_id=user_id,
                parsed_file_path=parsed_path,
                source_url=source_url,
                source_platform=source_platform,
            )
            await db.commit()

        set_progress(key, "完成 ✓")
        _logger.info("[regenerate] DONE | job=%s | total=%.1fs", job_id, _time.perf_counter() - t0)
        await asyncio.sleep(3)
    except Exception as exc:
        set_progress(key, f"生成失败：{exc}")
        _logger.error("[regenerate] FAILED | job=%s | elapsed=%.1fs | %s", job_id, _time.perf_counter() - t0, exc, exc_info=True)
        await asyncio.sleep(5)
    finally:
        clear_progress(key)


@router.get("/{article_id}", response_model=ArticleDetailResponse)
async def get_article(
    article_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get article detail with full content."""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    # User isolation: normal users can only access their own articles
    if not current_user.is_super_admin and article.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Article not found")

    media_url, ingest_raw_text, ingest_cover, ingest_content_type = await _get_ingest_extras(db, article_id)
    detail = ArticleDetailResponse.model_validate(article)
    detail.media_url = media_url
    if not detail.raw_content and ingest_raw_text:
        detail.raw_content = ingest_raw_text
    if not detail.cover_image and ingest_cover:
        detail.cover_image = ingest_cover
    # Backfill content_type if DB still has default 'article' but ingest says otherwise
    if ingest_content_type and ingest_content_type != 'article' and detail.content_type == 'article':
        detail.content_type = ingest_content_type
    return detail


@router.patch("/{article_id}", response_model=ArticleResponse)
async def update_article(
    article_id: UUID,
    data: ArticleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update article metadata."""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    # User isolation: normal users can only update their own articles
    if not current_user.is_super_admin and article.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Article not found")
    
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(article, key, value)

    # For notes, clean_content IS the source of truth — mirror it into raw_content
    # so reprocess / AI extraction has something to work with.
    if 'clean_content' in update_data and article.content_type == 'note':
        article.raw_content = update_data['clean_content'] or ''
        article.word_count = len(update_data['clean_content'] or '')

    await db.commit()
    await db.refresh(article)
    return article


@router.delete("/{article_id}", status_code=204)
async def delete_article(
    article_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an article."""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    # User isolation: normal users can only delete their own articles
    if not current_user.is_super_admin and article.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Article not found")
    
    # Cancel any active ingest jobs before deleting.
    # article_id FK is SET NULL on delete, so jobs must be cancelled first
    # or they will be re-queued on the next server restart.
    _TERMINAL_STATUSES = ("ready", "failed", "cancelled")
    await db.execute(
        update(IngestJob)
        .where(
            IngestJob.article_id == article_id,
            IngestJob.status.notin_(_TERMINAL_STATUSES),
        )
        .values(status="cancelled")
    )
    await db.flush()

    await db.delete(article)
    await db.commit()


@router.patch("/{article_id}/tags", response_model=ArticleResponse)
async def update_article_tags(
    article_id: UUID,
    data: ArticleTagsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replace all tags on an article with the given tag IDs."""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    # User isolation: normal users can only modify their own articles
    if not current_user.is_super_admin and article.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Article not found")

    # Clear existing tags
    article.tags.clear()

    # Look up each tag_id and add valid ones
    for tag_id in data.tag_ids:
        tag = await db.get(Tag, tag_id)
        if tag:
            article.tags.append(tag)

    await db.commit()
    await db.refresh(article)
    return article


@router.post("/{article_id}/reprocess", response_model=AIProcessResponse)
async def reprocess_article(
    article_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-run AI processing on an article."""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    # User isolation: normal users can only reprocess their own articles
    if not current_user.is_super_admin and article.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Article not found")
    
    # Notes use clean_content as source of truth; backfill raw if empty.
    if article.content_type == 'note' and not article.raw_content:
        article.raw_content = article.clean_content or ''

    if not article.raw_content:
        raise HTTPException(status_code=400, detail="No raw content to process")

    # Re-clean with platform-aware conversion (skip for spark/note - already markdown)
    platform = article.source_platform or (parser_service.detect_platform(article.url) if article.url else 'other')
    if platform in ("spark", "note") or article.content_type == 'note':
        clean_md = article.raw_content  # Already markdown, don't re-process
    else:
        clean_md = parser_service.clean_to_markdown(article.raw_content, platform)
    article.clean_content = clean_md
    article.plain_text = clean_md
    
    # Re-parse — pass raw_content as raw_html fallback for thin content
    ai_result = await llm_service.parse_article(clean_md, article.url, article.raw_content or "")
    
    article.title = ai_result.get('title', article.title)
    article.summary = ai_result.get('summary', '')
    article.key_points = ai_result.get('key_points', [])
    article.reading_time = ai_result.get('estimated_reading_minutes', 5)
    article.word_count = parser_service.count_words(clean_md)
    
    # Tags
    article.tags.clear()
    for tag_name in ai_result.get('tags', []):
        result = await db.execute(
            select(Tag).where(func.lower(Tag.name) == tag_name.lower())
        )
        tag = result.scalar_one_or_none()
        if not tag:
            tag = Tag(name=tag_name, is_ai_generated=True, user_id=article.user_id)
            db.add(tag)
            await db.flush()
        article.tags.append(tag)
    
    await db.commit()
    await db.refresh(article)
    
    # Generate knowledge graph connections
    try:
        await graph_service.generate_graph(db, article_id)
    except Exception as graph_err:
        logger.warning(f"Graph generation error for {article_id}: {graph_err}")
    
    return AIProcessResponse(
        article_id=article.id,
        title=article.title,
        summary=article.summary or "",
        key_points=article.key_points or [],
        tags=article.tags,
        reading_time=article.reading_time or 5,
        word_count=article.word_count or 0,
        source_platform=article.source_platform or "other",
        author=article.author or "unknown",
    )


@router.get("/{article_id}/related")
async def get_related_articles(
    article_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    username_query: str | None = Query(None, alias="username", description="Superadmin: filter by username"),
):
    """Get related articles grouped by relation type."""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    # User isolation: normal users can only access their own articles
    if not current_user.is_super_admin and article.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Article not found")

    # Query all edges connected to this article
    result = await db.execute(
        select(KnowledgeEdge).where(
            (KnowledgeEdge.source_article_id == article_id) |
            (KnowledgeEdge.target_article_id == article_id)
        )
    )
    edges = result.scalars().all()

    if not edges:
        return {"article_id": str(article_id), "groups": []}

    # Collect connected article IDs (excluding self-references)
    connected_ids = set()
    for edge in edges:
        connected_id = edge.target_article_id if edge.source_article_id == article_id else edge.source_article_id
        if connected_id != article_id:
            connected_ids.add(connected_id)

    # Fetch connected articles with user isolation
    articles_map = {}
    if connected_ids:
        query = select(Article).where(Article.id.in_(connected_ids))
        # User isolation for related articles (superadmin uses ?username=xxx to view others)
        target_user_id = current_user.id
        if current_user.is_super_admin and username_query:
            user_result = await db.execute(select(User).where(User.username == username_query))
            target_user = user_result.scalar_one_or_none()
            target_user_id = target_user.id if target_user else current_user.id
        query = query.where(Article.user_id == target_user_id)
        result = await db.execute(query)
        for a in result.scalars().all():
            articles_map[a.id] = a

    # Group by relation_type
    relation_labels = {
        "related": "相关文章",
        "prerequisite": "前置知识",
        "extends": "延伸阅读",
        "contradicts": "观点对立",
    }

    groups_dict = {}
    for edge in edges:
        connected_id = edge.target_article_id if edge.source_article_id == article_id else edge.source_article_id
        if connected_id == article_id:
            continue
        article_data = articles_map.get(connected_id)
        if not article_data:
            continue
        rt = edge.relation_type or "related"
        if rt not in groups_dict:
            groups_dict[rt] = {
                "relation_type": rt,
                "relation_label": relation_labels.get(rt, rt),
                "articles": [],
            }
        groups_dict[rt]["articles"].append({
            "id": str(article_data.id),
            "title": article_data.title,
            "summary": (article_data.summary or "")[:80],
            "relation_desc": edge.relation_desc or "",
        })

    groups = list(groups_dict.values())

    return {"article_id": str(article_id), "groups": groups}


@router.post("/backfill-embeddings")
async def backfill_embeddings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    username_query: str | None = Query(None, alias="username", description="Superadmin: filter by username"),
):
    """Backfill embeddings for articles that don't have them yet."""
    import logging, traceback
    logger = logging.getLogger(__name__)
    
    query = select(Article).where(Article.embedding.is_(None))
    
    # User isolation: superadmin sees own by default, or specific user via ?username=xxx
    target_user_id = current_user.id
    if current_user.is_super_admin and username_query:
        user_result = await db.execute(select(User).where(User.username == username_query))
        target_user = user_result.scalar_one_or_none()
        target_user_id = target_user.id if target_user else current_user.id
    query = query.where(Article.user_id == target_user_id)
    
    result = await db.execute(query)
    articles = result.scalars().all()
    
    count = 0
    for article in articles:
        try:
            content = f"{article.title}. {article.summary or ''}. {(article.plain_text or '')[:2000]}"
            logger.info(f"Generating embedding for article {article.id}: title={article.title[:30]}")
            embedding = await llm_service.get_embedding(content)
            logger.info(f"Got embedding dims={len(embedding)}")
            article.embedding = embedding
            count += 1
        except Exception as e:
            logger.error(f"Backfill embedding error for {article.id}: {e}")
            logger.error(traceback.format_exc())
    
    await db.commit()
    return {"status": "ok", "backfilled": count, "total_articles": len(articles)}
