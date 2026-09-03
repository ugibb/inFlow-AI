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

from backend.core.database import get_db
from backend.core.dependencies import get_current_user
from backend.core.models.article import Article, Tag, Folder, ArticleStatus, KnowledgeEdge, article_tags
from backend.core.models.ingest_job import IngestJob
from backend.core.models.user import User
from backend.core.schemas.article import (
    ArticleCreate, ArticleBatchCreate, ArticleManualCreate, ArticleUpdate, NoteCreate,
    ArticleResponse, ArticleDetailResponse, ArticleListResponse,
    DeepReadScreenshotRequest, RegenerateBlockRequest,
    AIProcessResponse, SearchRequest,
    SparkCreateRequest, SparkResponse, SparkSectionResponse,
    FileUploadResponse, ArticleTagsUpdate,
)
from backend.core.ingest.fetchers import parser_service, extract_url_from_text
from backend.core.ingest.orchestrator import ingest_url, ingest_upload, ingest_text
from backend.core.shared.ai_service import llm_service
from backend.core.display.services.graph_service import graph_service
from backend.core.display.services.spark_service import generate_article

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
    from backend.core.models import WechatAccount
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
    from backend.services.wechat_push import send_wechat
    async with httpx.AsyncClient(timeout=20.0) as client:
        await send_wechat(client, acct, msg)
    logger.info(
        f"proactive: pushed relation to user={article.user_id} "
        f"new={article_id} sibling={sibling_id} dist={float(distance):.3f}"
    )


async def process_article_background(article_id: UUID, raw_content: str, raw_html: str, url: str, db_session_factory):
    """Background task: AI process a newly added article."""
    import logging
    logger = logging.getLogger("inFlow.background")
    from backend.core.database import async_session
    
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


@router.get("/platforms")
async def list_platform_counts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """侧边栏「平台」tab 数据：按 source_platform 分组计数，仅本用户文章。

    注册于 /{article_id} 之前，避免被路径参数吞掉；count 降序方便前端直接渲染。
    """
    result = await db.execute(
        select(
            func.coalesce(func.nullif(Article.source_platform, ""), "other").label("platform"),
            func.count(Article.id).label("count"),
        )
        .where(Article.user_id == current_user.id)
        .group_by("platform")
        .order_by(desc("count"))
    )
    return [{"platform": row.platform, "count": row.count} for row in result]


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


# 内容类型门控：与 read 页 tab 展示规则一致。哪些 tab（内容块）对该类型可见，
# 以及该块产出位于 worker 流水线哪一阶段入口（用于单块重新生成的续跑点）。
_BLOCK_APPLICABLE = {
    "raw":        {"article", "video"},
    "transcript": {"audio"},
    "chapters":   {"audio", "article"},
    "deepRead":   {"article", "audio", "video"},
    "ai":         {"article", "audio", "video", "note"},
}
# worker 阶段产出块 → resume_for_retry 入口（from_step）。ai 块文本类走云端同步，
# 不入此表；audio 的 ai 与章节同源于 parsing 续跑。
_BLOCK_WORKER_STEP = {
    "raw":        ("capturing",    {"article", "video"}),
    "transcript": ("transcribing", {"audio"}),
    "chapters":   ("parsing",      {"audio", "article"}),
    "deepRead":   ("composing",    {"article", "audio", "video"}),
    "ai":         ("parsing",      {"audio"}),  # 仅音频：AI 依赖转写链，需 worker 续跑
}


def _chapters_present(article: Article) -> bool:
    data = article.chapters
    if not data:
        return False
    return bool(data.get("chapters")) if isinstance(data, dict) else bool(data)


def _transcript_present(article: Article) -> bool:
    data = article.transcript
    if not data:
        return False
    return bool(data.get("segments")) if isinstance(data, dict) else bool(data)


def _content_block_summary(
    article: Article,
    raw_fallback: Optional[str] = None,
    content_type: Optional[str] = None,
) -> dict:
    """read 页各内容块的存在性快照（含是否对该内容类型适用）。

    Keys 与 read 页 tab 一致：raw / transcript / chapters / deepRead / ai。
    每项形如 {"applicable": bool, "present": bool}，供前端展示生成进度、
    并按缺失块提供单块重新生成入口。
    """
    ct = (content_type or article.content_type or "article").lower()
    ai_present = bool(
        (article.summary or "").strip() or (article.key_points or [])
    )
    return {
        "raw": {
            "applicable": ct in _BLOCK_APPLICABLE["raw"],
            "present": bool(article.raw_content or raw_fallback),
        },
        "transcript": {
            "applicable": ct in _BLOCK_APPLICABLE["transcript"],
            "present": _transcript_present(article),
        },
        "chapters": {
            "applicable": ct in _BLOCK_APPLICABLE["chapters"],
            "present": _chapters_present(article),
        },
        "deepRead": {
            "applicable": ct in _BLOCK_APPLICABLE["deepRead"],
            "present": bool(article.deep_read_html),
        },
        "ai": {
            "applicable": True,
            "present": ai_present,
        },
    }


async def _find_article_job(
    db: AsyncSession, article_id: UUID
) -> Optional[IngestJob]:
    """文章最近的 IngestJob（同一 article 下通常单 job）。"""
    r = await db.execute(
        select(IngestJob).where(IngestJob.article_id == article_id).limit(1)
    )
    return r.scalar_one_or_none()


@router.get("/{article_id}/chapters")
async def get_article_chapters(
    article_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return rich chapter data from the articles.chapters JSONB column."""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if not current_user.is_super_admin and article.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Article not found")

    data = article.chapters
    if not data or not data.get("chapters"):
        raise HTTPException(status_code=404, detail="Chapters not yet generated")

    # If total_duration is missing, fill from transcript column (display only — chapter times come from LLM)
    if not data.get("total_duration") and article.transcript:
        real_dur = float((article.transcript or {}).get("duration") or 0)
        if real_dur > 0:
            data = {**data, "total_duration": real_dur}

    return data


@router.get("/{article_id}/transcript")
async def get_article_transcript(
    article_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return ASR transcript segments from the articles.transcript JSONB column."""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if not current_user.is_super_admin and article.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Article not found")

    data = article.transcript
    if not data:
        raise HTTPException(status_code=404, detail="Transcript not yet available")

    return {
        "language": data.get("language"),
        "duration": data.get("duration"),
        "segments": data.get("segments") or [],
    }


@router.get("/{article_id}/deep-read", response_class=HTMLResponse)
async def get_article_deep_read(
    article_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HTMLResponse:
    """Return the AI deep-read card HTML from the articles.deep_read_html column."""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if not current_user.is_super_admin and article.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Article not found")

    if not article.deep_read_html:
        raise HTTPException(status_code=404, detail="Deep read not yet generated")

    return HTMLResponse(content=article.deep_read_html)


@router.post("/{article_id}/deep-read/screenshot")
async def capture_article_deep_read_screenshot(
    article_id: UUID,
    body: DeepReadScreenshotRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """返回 worker 回传的 deep-read 卡片 PNG（云端不再本地渲染 Playwright 截图）。

    兼容旧契约：请求体仍带 html（前端零改动），但云端只按 job 定位
    data/03_display/…/{job_id}.png 直接回读；文件缺失=尚未回传，404。
    """
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if not current_user.is_super_admin and article.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Article not found")

    from pathlib import Path
    from backend.core.config import get_settings
    from backend.core.shared.storage.conventions import card_png_candidates

    r = await db.execute(select(IngestJob).where(IngestJob.article_id == article_id).limit(1))
    job = r.scalar_one_or_none()
    if not job or not job.raw_file_path:
        raise HTTPException(status_code=404, detail="Deep read not available")

    # 兼容新旧管线登记形态：旧云端管线为绝对路径；本地 worker 为 04-output/...
    # 相对形态，需剥前缀拼 INFLOW_PIPELINE_DATA_DIR（SFTP 回传落盘根）
    png_path = next(
        (
            p for p in card_png_candidates(
                job.raw_file_path, job.id,
                pipeline_data_dir=get_settings().inflow_pipeline_data_dir,
            )
            if Path(p).is_file() and Path(p).stat().st_size > 0
        ),
        None,
    )
    if not png_path:
        raise HTTPException(status_code=404, detail="Card PNG not yet returned by worker")

    try:
        png_bytes = Path(png_path).read_bytes()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read card PNG: {exc}") from exc

    return Response(content=png_bytes, media_type="image/png")


@router.post("/{article_id}/regenerate-ai", status_code=202)
async def regenerate_article_ai(
    article_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Re-run the full AI chain for an article, handing off to the local worker.

    - audio：复用已转写文本（asr_file_path），重跑 parse→compose→index，不重转录。
    - article（图文/公众号等）：复用已抓 raw_file_path，worker 从 captured 起重跑
      normalize→parse→compose→index，不重新抓取网络。
    - note / video：无此流水线形态，拒绝（note 走云端 reprocess）。
    """
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if not current_user.is_super_admin and article.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Article not found")
    if article.content_type not in ("audio", "article"):
        raise HTTPException(
            status_code=400,
            detail=f"该内容类型（{article.content_type}）不支持从 worker 重新生成",
        )

    r = await db.execute(select(IngestJob).where(IngestJob.article_id == article_id).limit(1))
    job = r.scalar_one_or_none()
    if not job or not job.raw_file_path:
        raise HTTPException(status_code=404, detail="Source data not available for regeneration")

    if not job.external_processing:
        # 历史 non-external job：云端已无自跑管道，统一标记转交本地 worker。
        job.external_processing = True
        await db.commit()

    # 云端只重置状态（parsing 起，ASR 文件复用不重转录），由本地 worker 认领
    # 重跑 parse → compose → index，卡片经 SFTP 回传。
    from backend.core.pipeline.state_machine import resume_for_retry

    ok = await resume_for_retry(db, job_id=job.id, from_step="parsing")
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not in a retryable state (current: {job.status})",
        )
    return {"status": "started", "article_id": str(article_id)}


@router.get("/{article_id}/regen-status")
async def get_article_regen_status(
    article_id: UUID,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return current regeneration progress for display in the frontend."""
    from backend.core.shared.progress import get_progress
    msg = get_progress(str(article_id))
    return {"active": msg is not None, "message": msg or ""}


# ------------------------------------------------------------------ #
# 单块重新生成                                                          #
# ------------------------------------------------------------------ #


async def _regenerate_ai_block(db: AsyncSession, article: Article) -> Article:
    """文本内容 AI 块同步重生成：复用干净文本/原文重跑 LLM 解析。

    只回写 AI 相关字段（title/summary/key_points/reading_time/word_count/
    AI 标签），不重抓取、不改写正文、不动图谱与流水线任务。
    """
    # Notes 以 clean_content 为正文源；为空时用 raw 兜底
    if article.content_type == "note" and not article.raw_content:
        article.raw_content = article.clean_content or ""

    content = article.clean_content or article.raw_content
    if not content:
        raise HTTPException(
            status_code=400,
            detail="暂无可解析的正文，请先完成内容抓取后再试",
        )

    # 仅在还没有干净文本时才做平台化清理 —— 块级重生成不改写既有正文
    if not article.clean_content:
        platform = article.source_platform or (
            parser_service.detect_platform(article.url) if article.url else "other"
        )
        if platform in ("spark", "note") or article.content_type == "note":
            clean_md = content  # Already markdown, don't re-process
        else:
            clean_md = parser_service.clean_to_markdown(content, platform)
        article.clean_content = clean_md
        article.plain_text = clean_md

    ai_result = await llm_service.parse_article(
        article.clean_content, article.url, article.raw_content or ""
    )
    if ai_result.get("title"):
        article.title = ai_result.get("title")[:500]
    article.summary = ai_result.get("summary", "") or ""
    article.key_points = ai_result.get("key_points") or []
    article.reading_time = ai_result.get("estimated_reading_minutes", 5) or 0
    article.word_count = parser_service.count_words(article.clean_content)

    # 标签：仅替换由 AI 生成的标签，保留用户手动添加的标签
    for tag in [t for t in list(article.tags) if t.is_ai_generated]:
        article.tags.remove(t)
    for name in (ai_result.get("tags") or []):
        name = (name or "").strip()
        if not name:
            continue
        res = await db.execute(
            select(Tag).where(func.lower(Tag.name) == name.lower())
        )
        tag = res.scalar_one_or_none()
        if not tag:
            tag = Tag(name=name, is_ai_generated=True, user_id=article.user_id)
            db.add(tag)
            await db.flush()
        if tag not in article.tags:
            article.tags.append(tag)

    await db.commit()
    await db.refresh(article)
    return article


async def _resume_worker_block(
    db: AsyncSession,
    job: IngestJob,
    *,
    block: str,
    from_step: str,
    article_id: UUID,
) -> dict:
    """把已结束的 job 从该块对应流水线入口续跑，交给本地 worker 补齐对应产出。

    云端不调度任何管道：仅重置状态 + 标记 external，等 worker 认领。
    """
    if not job.external_processing:
        # 历史 non-external job：云端已无自跑管道，统一标记转交本地 worker。
        job.external_processing = True
        await db.commit()

    from backend.core.pipeline.state_machine import resume_for_retry

    ok = await resume_for_retry(db, job_id=job.id, from_step=from_step)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=f"该任务当前状态（{job.status}）不可从此处重新生成，请稍后重试",
        )
    # 登记单块标记（resume 已统一清空）：worker 落库层据此只写目标块，
    # 其它字段（摘要/正文/精读/转录等）保持不变。
    await db.execute(
        update(IngestJob).where(IngestJob.id == job.id).values(regen_block=block)
    )
    await db.commit()
    return {
        "ok": True,
        "status": "started",
        "mode": "async",
        "block": block,
        "article_id": str(article_id),
        "job_id": str(job.id),
        "from_step": from_step,
    }


@router.post("/{article_id}/regenerate-block")
async def regenerate_article_block(
    article_id: UUID,
    body: RegenerateBlockRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """按块重新生成文章内容 —— 尽量只补齐对应内容块，不整条链路重跑。

    - ``ai``：文本类（article/video/note）在云端**同步**重跑 LLM 解析
      （复用干净文本/原文，不重抓取、不动图谱）；音频因 AI 依赖转写链，
      走本地 worker 的 parsing 续跑。
    - ``raw/transcript/chapters/deepRead``：均由 worker 某阶段产出，云端只把
      已结束的 job 重置到该块对应的流水线入口，交本地 worker 续跑补齐。

    内容类型门控与 read 页 tab 展示一致；找不到任务 / 状态不可续跑时 400/404。
    """
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if not current_user.is_super_admin and article.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Article not found")

    ct = (article.content_type or "article").lower()

    # ── ai：文本类 → 云端同步 LLM 解析（只回写 AI 块） ──────────────
    if body.block == "ai" and ct != "audio":
        updated = await _regenerate_ai_block(db, article)
        return {
            "ok": True,
            "status": "completed",
            "mode": "sync",
            "block": "ai",
            "article_id": str(article_id),
            "summary": updated.summary or "",
            "word_count": updated.word_count or 0,
        }

    # ── 其余（含 audio 的 ai）：需要本地 worker 按阶段续跑 ────────────
    from_step, allowed = _BLOCK_WORKER_STEP[body.block]
    if ct not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"该内容类型不支持单独重新生成“{body.block}”内容块",
        )

    job = await _find_article_job(db, article_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail="未找到该内容对应的生成任务，无法单独重新生成此块",
        )
    if ct == "audio" and not job.raw_file_path:
        raise HTTPException(
            status_code=404,
            detail="音频源文件缺失，无法重新生成（请重新添加该音频）",
        )

    return await _resume_worker_block(
        db, job, block=body.block, from_step=from_step, article_id=article_id
    )


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
    # DB 字段优先（worker capture 直写）；老管线文章走文件兜底
    detail.media_url = article.media_url or media_url
    if not detail.raw_content and ingest_raw_text:
        detail.raw_content = ingest_raw_text
    if not detail.cover_image and ingest_cover:
        detail.cover_image = ingest_cover
    # Backfill content_type if DB still has default 'article' but ingest says otherwise
    if ingest_content_type and ingest_content_type != 'article' and detail.content_type == 'article':
        detail.content_type = ingest_content_type
    # read 页内容块存在性快照（raw_fallback 也纳入 raw 判断）
    detail.content_blocks = _content_block_summary(
        article, raw_fallback=ingest_raw_text, content_type=detail.content_type
    )
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
