"""inFlow AI — read-later + AI knowledge base for the Chinese internet"""
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
from urllib.parse import urlparse
import httpx

from inflow_core.core.config import get_settings
from inflow_core.core.utils.logger import (
    configure_quiet_module_loggers,
    configure_third_party_loggers,
    get_logger,
    setup_logging,
)
from inflow_core.core.database import init_db
from .routers import articles, knowledge, system, assistant, auth, users
from inflow_core.ingest.router import router as ingest_router
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events.

    云端定位 = 功能交互及展示：不在启动时做任何重计算
    （无 whisper 预热 / 无 ASR·embedding 补扫 / 无遗留 job 回收——
    url/upload/paste 三入口全部交给本地 worker，云端只登记）。
    """
    # Startup：建表 + 跑迁移（含 019 staging 列）
    await init_db()

    if settings.external_processing:
        get_logger("main").warning(
            "EXTERNAL_PROCESSING=true：url/upload/paste 三入口全部交给本地 worker 承接，"
            "云端只登记（upload/paste 收件落盘 00_staging）。请确认本地 worker"
            "（start-worker.sh）已部署并运行，否则新 job 会停在 pending。"
        )

    get_logger("main").info("inFlow AI started successfully")
    yield
    # Shutdown
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


class ApiNoCacheMiddleware(BaseHTTPMiddleware):
    """Prevent CDN / reverse-proxy from caching authenticated API responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response


app.add_middleware(ApiNoCacheMiddleware)

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
