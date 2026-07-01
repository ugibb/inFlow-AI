"""inFlow AI — read-later + AI knowledge base for the Chinese internet"""
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
from urllib.parse import urlparse
import asyncio
import httpx

from app.core.config import get_settings
from app.core.utils.logger import (
    configure_quiet_module_loggers,
    configure_third_party_loggers,
    get_logger,
    setup_logging,
)
from app.core.database import init_db
from .routers import articles, knowledge, system, assistant, auth, users
from .s1_ingest.router import router as ingest_router
from .extensions.wechat.router import router as wechat_router
from .extensions.research.router import router as research_router
from .extensions.obsidian.router import router as obsidian_router

settings = get_settings()
setup_logging(
    log_dir=settings.get_log_dir_path(),
    file_level=settings.log_level,
)
configure_third_party_loggers(
    log_sql=settings.log_sql,
    log_access=settings.log_access,
    access_skip_paths=settings.get_log_access_skip_paths(),
)
configure_quiet_module_loggers()

logger = get_logger("main")


async def _transcribe_youtube(url: str) -> Optional[str]:
    """Extract audio from YouTube via yt-dlp and transcribe with Whisper."""
    import subprocess, tempfile, os

    # Read proxy from plugins config
    try:
        from app.core.config_manager import get_plugins_config
        plugins = get_plugins_config()
        proxy = plugins.get('proxy', '') if plugins else ''
    except Exception:
        proxy = ''

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, 'audio.mp3')
        try:
            ytdlp_args = [
                'yt-dlp', '-x', '--audio-format', 'mp3',
                '--audio-quality', '32K',
                '--no-playlist', '--no-warnings',
            ]
            if proxy:
                ytdlp_args += ['--proxy', proxy]
            ytdlp_args += ['-o', audio_path, url]
            proc = await asyncio.create_subprocess_exec(
                *ytdlp_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
            if proc.returncode != 0 or not os.path.exists(audio_path):
                logger.warning(f"YouTube ASR: yt-dlp audio download failed: {stderr[:200]}")
                return None

            from app.s2_parse.audio.service import transcription_service
            from pathlib import Path
            logger.info(f"YouTube ASR: audio downloaded, starting whisper...")
            return await transcription_service._transcribe_local(Path(audio_path))
        except asyncio.TimeoutError:
            logger.warning(f"YouTube ASR: audio download timeout")
            return None
        except Exception as e:
            logger.error(f"YouTube ASR: failed: {e}")
            return None


async def auto_backfill_asr():
    """Background task: scan for articles with ASR_PENDING marker and transcribe."""
    import re
    from app.core.database import async_session
    from sqlalchemy import select
    from app.core.models.article import Article

    await asyncio.sleep(30)
    # logger.info("ASR scanner: starting scan loop")

    while True:
        try:
            async with async_session() as db:
                result = await db.execute(
                    select(Article).where(Article.raw_content.contains('<!-- ASR_PENDING:'))
                )
                articles = result.scalars().all()

                for article in articles:
                    match = re.search(r'<!-- ASR_PENDING:\s*(\S+) -->', article.raw_content or '<!-- ASR_PENDING: -->')
                    if not match:
                        continue
                    audio_url = match.group(1)
                    marker = match.group(0)

                    # Claim this article by replacing marker with RUNNING to prevent double-processing
                    article.raw_content = article.raw_content.replace(marker, '<!-- ASR_RUNNING -->')
                    await db.commit()

                    try:
                        from app.s2_parse.audio.service import transcription_service
                        logger.info(f"ASR: transcribing {article.id} ({article.title[:40]}...)")
                        
                        # For YouTube URLs, extract audio via yt-dlp first
                        if 'youtube.com' in audio_url or 'youtu.be' in audio_url:
                            asr_text = await _transcribe_youtube(audio_url)
                        else:
                            asr_text = await transcription_service.transcribe_url(
                                audio_url, referer='https://www.bilibili.com'
                            )
                        if asr_text:
                            article.raw_content = article.raw_content.replace(
                                '<!-- ASR_RUNNING -->', f'\n\n## 视频字幕（ASR 转录）\n\n{asr_text}'
                            ).replace(
                                '*（后台语音转录中，稍后自动更新…）*', ''
                            )
                            article.word_count = len(article.raw_content)
                            await db.commit()
                            logger.info(f"ASR: done {article.id} ({len(asr_text)} chars)")
                        else:
                            article.raw_content = article.raw_content.replace(
                                '<!-- ASR_RUNNING -->', ''
                            ).replace(
                                '*（后台语音转录中，稍后自动更新…）*',
                                '*（该视频未提供字幕，ASR 转录亦不可用）*'
                            )
                            await db.commit()
                            logger.warning(f"ASR: empty result for {article.id}, marker removed")
                    except Exception as e:
                        # Rollback marker to PENDING so another try can pick it up
                        article.raw_content = article.raw_content.replace(
                            '<!-- ASR_RUNNING -->', marker
                        )
                        await db.commit()
                        logger.error(f"ASR: failed for {article.id}, re-queued: {e}")
        except Exception as e:
            logger.error(f"ASR scan error: {e}")

        await asyncio.sleep(30)  # Scan every 30 seconds


async def auto_backfill_embeddings():
    """Background task: periodically check for articles without embeddings and backfill them."""
    # Wait for everything to be fully initialized before first run
    await asyncio.sleep(60)
    
    while True:
        try:
            from app.core.database import async_session
            from sqlalchemy import select
            from app.core.models.article import Article
            from app.core.shared.ai_service import llm_service
            
            async with async_session() as db:
                result = await db.execute(select(Article).where(Article.embedding.is_(None)))
                articles = result.scalars().all()
                
                if articles:
                    for article in articles:
                        try:
                            # bge-large-zh-v1.5 上下文窗口 512 token（中文约 1 字 ≈ 1 token）
                            # 用 title + summary 做嵌入已足够语义搜索，不拼 plain_text 避免超长
                            title_part = (article.title or "")[:100]
                            summary_part = (article.summary or "")[:350]
                            content = f"{title_part}. {summary_part}".strip(". ")
                            if not content:
                                content = (article.plain_text or article.raw_content or "")[:400]
                            embedding = await llm_service.get_embedding(content)
                            article.embedding = embedding
                        except Exception as e:
                            logger.error(f"Auto-backfill: embedding failed for {article.id}: {e}")

                    await db.commit()
        except Exception as e:
            logger.error(f"Auto-backfill scan error: {e}", exc_info=True)
        
        # Scan every 5 minutes
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    await init_db()

    # Preload whisper model at startup (avoid timeout on first ASR request)
    import concurrent.futures
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    from app.s2_parse.audio.service import preload_whisper
    asyncio.get_running_loop().run_in_executor(executor, preload_whisper)

    # Recover captured-but-unprocessed jobs from previous server run
    from app.s1_ingest.orchestrator import recover_captured_jobs
    await recover_captured_jobs()

    # Start auto-backfill background task
    backfill_task = asyncio.create_task(auto_backfill_embeddings())
    # logger.info("Auto-backfill background task started (scans every 5 minutes)")

    # Start background ASR transcription task
    asr_task = asyncio.create_task(auto_backfill_asr())
    # logger.info("ASR background task started (scans every 30 seconds)")

    get_logger("main").info("inFlow AI started successfully")
    yield
    # Shutdown
    backfill_task.cancel()
    asr_task.cancel()
    get_logger("main").info("inFlow AI shutting down")


app = FastAPI(
    title="inFlow AI",
    description="inFlow AI — read-later + AI knowledge base for the Chinese internet",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — origins driven by ALLOWED_ORIGINS env var (see config.py)
_allowed_origins = settings.get_allowed_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Handle OPTIONS preflight for ALL routes (fixes CORS preflight 405)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class OptionsHandler(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            origin = request.headers.get("origin", "")
            allow_origin = origin if origin in _allowed_origins else (_allowed_origins[0] if _allowed_origins else "")
            return Response(
                status_code=200,
                headers={
                    "Access-Control-Allow-Origin": allow_origin,
                    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "Authorization, Content-Type, *",
                    "Access-Control-Max-Age": "86400",
                }
            )
        return await call_next(request)

app.add_middleware(OptionsHandler)

# Routes
app.include_router(articles.router)
app.include_router(knowledge.router)
app.include_router(system.router)
app.include_router(assistant.router, prefix="/api")

# Auth & User management
app.include_router(auth.router)
app.include_router(users.router)

# WeChat bot binding API
app.include_router(wechat_router)

# Agentic research (SSE stream)
app.include_router(research_router)

# Obsidian sync API (Obsidian plugin pulls articles to local vault)
app.include_router(obsidian_router)

# Phase 1: Ingest pipeline API
app.include_router(ingest_router)

# Allowed image proxy domains (anti-SSRF protection)
ALLOWED_IMAGE_DOMAINS = {
    'mmbiz.qpic.cn',       # WeChat MP CDN
    'mmbiz.qlogo.cn',      # WeChat MP logo CDN
    'mmecoa.qpic.cn',      # WeChat alternate CDN
    'xhscdn.com',          # XHS image CDN (subdomains via endswith match)
    'douyinpic.com',       # Douyin image CDN
    'douyinvod.com',       # Douyin video/thumb CDN
}


@app.get("/api/images/proxy")
async def proxy_image(url: str = Query(..., description="Original image URL to proxy")):
    """Proxy images from blocked CDNs (e.g. WeChat mmbiz) with proper Referer headers."""
    # Validate domain
    try:
        parsed = urlparse(url)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL")

    domain = parsed.hostname or ""
    # Allow any subdomain of the trusted domains
    trusted = any(
        domain == allowed or domain.endswith('.' + allowed)
        for allowed in ALLOWED_IMAGE_DOMAINS
    )
    if not trusted:
        raise HTTPException(status_code=403, detail=f"Domain not allowed: {domain}")

    # Determine correct Referer based on domain
    if 'qpic.cn' in domain or 'qlogo.cn' in domain:
        referer = 'https://mp.weixin.qq.com/'
    elif 'xhscdn.com' in domain:
        referer = 'https://www.xiaohongshu.com/'
    elif 'douyinpic.com' in domain or 'douyinvod.com' in domain:
        referer = 'https://www.douyin.com/'
    else:
        referer = 'https://mp.weixin.qq.com/'

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            proxy_resp = await client.get(
                url,
                headers={
                    'User-Agent': (
                        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/120.0.0.0 Safari/537.36'
                    ),
                    'Referer': referer,
                    'Accept': 'image/webp,image/avif,image/*,*/*;q=0.8',
                },
            )
            proxy_resp.raise_for_status()

        content_type = proxy_resp.headers.get('content-type', 'image/jpeg')
        return StreamingResponse(
            content=proxy_resp.aiter_bytes(),
            media_type=content_type,
            headers={
                'Cache-Control': 'public, max-age=86400',  # 1 day
            },
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="Upstream error")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Failed to fetch image")


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "app": "inFlow AI"}
