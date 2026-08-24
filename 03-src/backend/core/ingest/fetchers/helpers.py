"""Content parsing service - extract clean content from web pages."""
import re
import json
import httpx
import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse
from bs4 import BeautifulSoup
from markdownify import markdownify as md_convert

logger = logging.getLogger(__name__)

_FETCH_HTTP_TIMEOUT = httpx.Timeout(connect=15.0, read=30.0, write=15.0, pool=15.0)


def _http_error_detail(exc: BaseException) -> str:
    """httpx 超时等异常 str() 常为空，补全可读信息。"""
    msg = str(exc).strip()
    if msg:
        return msg
    return type(exc).__name__


def _get_plugin_bool(key: str, default: bool = True) -> bool:
    """Read boolean config from plugins settings."""
    try:
        from backend.core.config_manager import get_plugins_config
        cfg = get_plugins_config()
        val = cfg.get(key, str(default).lower())
        return val.lower() in ('true', '1', 'yes', 'on')
    except Exception:
        return default


def _get_plugin_int(key: str, default: int = 1800) -> int:
    try:
        from backend.core.config_manager import get_plugins_config
        cfg = get_plugins_config()
        return int(cfg.get(key, str(default)))
    except Exception:
        return default


def _get_plugin_str(key: str, default: str = '') -> str:
    try:
        from backend.core.config_manager import get_plugins_config
        cfg = get_plugins_config()
        return cfg.get(key, default)
    except Exception:
        return default


def _get_xhs_cookie() -> str:
    """Optional Xiaohongshu login cookie for authenticated note fetching."""
    cookie = _get_plugin_str('xhs_cookie', '')
    if not cookie:
        cookie = os.environ.get('XHS_COOKIE', '')
    return cookie.strip()


def _get_feishu_cookie() -> str:
    """Optional Feishu login cookie for authenticated document fetching."""
    cookie = _get_plugin_str('feishu_cookie', '')
    if not cookie:
        cookie = os.environ.get('FEISHU_COOKIE', '')
    return cookie.strip()


# Stealth JS injected before page load to suppress headless automation signals.
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}, app: {}};
Object.defineProperty(navigator, 'plugins', {get: () => [
  {name:'Chrome PDF Plugin'},{name:'Chrome PDF Viewer'},{name:'Native Client'}
]});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh','en']});
const origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (params) => (
  params.name === 'notifications'
    ? Promise.resolve({state: Notification.permission})
    : origQuery(params)
);
"""


def _xhs_block_reason(final_url: str) -> Optional[str]:
    """Detect XHS anti-bot / unavailable responses and return a user-facing reason."""
    if not final_url:
        return None

    parsed = urlparse(final_url)
    qs = parse_qs(parsed.query)
    error_code = (qs.get('error_code') or [''])[0]
    error_msg = unquote((qs.get('error_msg') or [''])[0])

    blocked = (
        '/404/sec_' in final_url
        or 'xhs_sec_server' in final_url
        or (parsed.path == '/404' and error_code)
    )
    if not blocked:
        return None

    if error_code == '300031':
        return (
            "小红书笔记当前不可浏览（可能已删除、设为私密，或未登录无法访问）。"
            "请在 设置 → 插件设置 填写小红书 Cookie，或使用「粘贴正文」手动导入。"
        )
    if error_msg:
        return (
            f"小红书访问被拦截：{error_msg}。"
            "请在 设置 → 插件设置 填写小红书 Cookie 后重试。"
        )
    return (
        "小红书访问被安全策略拦截，通常需要登录 Cookie 后才能抓取。"
        "请在 设置 → 插件设置 填写小红书 Cookie，或使用「粘贴正文」手动导入。"
    )


def _xhs_cookie_header(cookie: str) -> dict:
    return {'Cookie': cookie} if cookie else {}


def _xhs_playwright_cookies(cookie: str) -> list[dict]:
    if not cookie:
        return []
    cookies = []
    for part in cookie.split(';'):
        part = part.strip()
        if '=' not in part:
            continue
        name, value = part.split('=', 1)
        cookies.append({
            'name': name.strip(),
            'value': value.strip(),
            'domain': '.xiaohongshu.com',
            'path': '/',
        })
    return cookies


# Match http(s) URL up to whitespace, CJK char, or common Chinese punctuation.
# Used to extract the actual link from share text (抖音/头条 share blobs etc.).
_URL_RE = re.compile(
    r'https?://[^\s一-鿿"\'<>{}|\\^`,。、;:!?【】()《》""'']+',
    re.IGNORECASE,
)


def extract_url_from_text(text: str) -> Optional[str]:
    """Pull the first http(s):// URL out of a possibly-noisy share string."""
    if not text:
        return None
    m = _URL_RE.search(text)
    if not m:
        return None
    # Strip trailing punctuation that often clings to URLs in share blobs.
    return m.group(0).rstrip('.,;:!?)]')



def _extract_xhs_state(html: str) -> Optional[dict]:
    """Pull the note dict out of XHS' __INITIAL_STATE__ inline JSON.

    XHS sometimes emits a JS object literal (unquoted keys, `undefined` values,
    single quotes) rather than strict JSON. We try strict json.loads first,
    fall back to json_repair which handles these JS-isms.
    """
    if not html or '__INITIAL_STATE__' not in html and '__INITIAL_SSR_STATE__' not in html:
        return None

    blob: Optional[str] = None
    for pat in _XHS_STATE_PATTERNS:
        m = pat.search(html)
        if m:
            blob = m.group(1)
            break
    if not blob:
        return None

    state = None
    try:
        state = json.loads(blob)
    except Exception:
        try:
            from json_repair import repair_json
            state = json.loads(repair_json(blob, return_objects=False))
        except Exception as e:
            logger.warning(f"XHS state JSON repair failed: {e}")
            return None

    if not isinstance(state, dict):
        return None

    # Walk common shapes to find the note object.
    # Observed: state.note.noteDetailMap[<id>].note  OR  state.note.firstNoteId + map
    note_state = state.get('note') or state.get('noteData') or {}
    if isinstance(note_state, dict):
        nd_map = note_state.get('noteDetailMap') or note_state.get('note_detail_map') or {}
        if isinstance(nd_map, dict):
            for entry in nd_map.values():
                if isinstance(entry, dict):
                    n = entry.get('note') or entry.get('noteData') or entry
                    if isinstance(n, dict) and (n.get('noteId') or n.get('note_id') or n.get('title') or n.get('desc')):
                        return n
        # Sometimes the note is directly under state.note
        if note_state.get('noteId') or note_state.get('title') or note_state.get('desc'):
            return note_state
    return None


def _extract_xhs_video_url(note: dict) -> Optional[str]:
    """Find a playable video URL inside an XHS note dict (best effort).

    XHS video shape commonly looks like:
      note.video.media.stream.h264[0].master_url
      note.video.consumer.url_list[0]
      note.video.url
    Returns None for image notes or when extraction fails.
    """
    if not isinstance(note, dict):
        return None
    v = note.get('video') or {}
    if not isinstance(v, dict):
        return None
    # Try common paths in order
    media = v.get('media') or {}
    stream = (media.get('stream') or {}) if isinstance(media, dict) else {}
    for codec in ('h264', 'h265', 'av1'):
        arr = stream.get(codec) if isinstance(stream, dict) else None
        if isinstance(arr, list) and arr:
            entry = arr[0]
            url = (entry.get('master_url') if isinstance(entry, dict) else None) \
                  or (entry.get('backup_urls', [None])[0] if isinstance(entry, dict) else None)
            if url:
                return url
    # consumer.url_list
    consumer = v.get('consumer') or {}
    if isinstance(consumer, dict):
        urls = consumer.get('url_list') or []
        if urls:
            return urls[0]
    # plain url
    if isinstance(v.get('url'), str):
        return v['url']
    return None


async def _xhs_playwright_fetch(url: str, ua: str, cookie: str = ""):
    """Playwright fallback for XHS: renders the page with desktop UA, captures HTML.

    XHS reliably rejects iPhone-mobile UAs (sec_server redirect); desktop Chrome
    UA passes through to /explore/<id> with full noteDetailMap state.

    Returns (note_dict_or_None, html, final_url).
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None, "", url

    note = None
    html = ""
    final_url = url
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-blink-features=AutomationControlled'],
            )
            ctx = await browser.new_context(
                user_agent=ua,
                viewport={'width': 1920, 'height': 1080},
                locale='zh-CN',
                extra_http_headers=_xhs_cookie_header(cookie),
            )
            pw_cookies = _xhs_playwright_cookies(cookie)
            if pw_cookies:
                await ctx.add_cookies(pw_cookies)
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            except Exception as e:
                logger.warning(f"XHS playwright nav: {e}")
            # Give SSR/CSR a moment to populate __INITIAL_STATE__
            import asyncio as _a
            await _a.sleep(4)
            try:
                final_url = await page.evaluate("location.href") or url
            except Exception:
                pass
            html = await page.content()
            await browser.close()
    except Exception as e:
        logger.warning(f"XHS playwright failed: {e}")

    if html:
        note = _extract_xhs_state(html)
    return note, html, final_url
