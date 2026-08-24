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

from backend.core.ingest.fetchers.helpers import _get_xhs_cookie, _xhs_block_reason, _xhs_cookie_header, _extract_xhs_state, _extract_xhs_video_url, _xhs_playwright_fetch, logger

"""小红书笔记抓取。"""

class XhsParserMixin:
    async def _fetch_xhs(self, url: str) -> Dict:
        """Fetch Xiaohongshu (小红书) note content.

        URL forms:
        - https://xhslink.com/<short>  (302 → discovery/item or explore)
        - https://www.xiaohongshu.com/explore/<note_id>
        - https://www.xiaohongshu.com/discovery/item/<note_id>

        Strategy:
        1. curl_cffi with mobile UA + Chrome impersonate (covers TLS fingerprint)
        2. Parse window.__INITIAL_STATE__ inline JSON for full note data
        3. Playwright fallback if HTML doesn't carry usable state
        4. OG meta last resort (title/cover/snippet)
        """
        logger.info(f"Fetching XHS: {url}")

        xhs_cookie = _get_xhs_cookie()
        if xhs_cookie:
            logger.info("XHS: using configured login cookie")

        # XHS sec_server redirects iPhone-mobile UAs to /404/sec_xxx (anti-scraping).
        # Desktop Chrome Mac UA passes - the page resolves to /explore/<id> with
        # full noteDetailMap in __INITIAL_STATE__.
        desktop_ua = (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/124.0.0.0 Safari/537.36'
        )

        html = ""
        final_url = url
        blocked_reason = None
        try:
            from curl_cffi import requests as curl_requests
            resp = curl_requests.get(
                url,
                headers={
                    'User-Agent': desktop_ua,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Referer': 'https://www.xiaohongshu.com/',
                    **_xhs_cookie_header(xhs_cookie),
                },
                impersonate='chrome124',
                timeout=20,
                allow_redirects=True,
            )
            html = resp.text or ""
            final_url = str(resp.url) if hasattr(resp, 'url') else url
            block_reason = _xhs_block_reason(final_url)
            if block_reason and not xhs_cookie:
                blocked_reason = block_reason
                logger.info(f"XHS curl_cffi blocked: {block_reason[:80]} final={final_url[:120]}")
                html = ""
            elif block_reason:
                raise ValueError(block_reason)
            else:
                logger.info(f"XHS curl_cffi: {len(html)} chars, final={final_url[:120]}")
        except Exception as e:
            logger.warning(f"XHS curl_cffi failed: {e}")

        # Try __INITIAL_STATE__ / __INITIAL_SSR_STATE__ from HTML
        note = _extract_xhs_state(html) if html else None

        # Fallback to Playwright if state parsing failed
        if note is None:
            note, html_pw, final_url_pw = await _xhs_playwright_fetch(url, desktop_ua, xhs_cookie)
            if html_pw:
                html = html_pw
            if final_url_pw:
                final_url = final_url_pw

        # Build OG meta dict from whatever HTML we have, for last-resort fields
        og_meta = {}
        if html:
            try:
                soup = BeautifulSoup(html, 'lxml')
                og_meta = self._extract_og_metadata(soup)
            except Exception:
                pass

        if note is None and not og_meta.get('title'):
            block_reason = blocked_reason or _xhs_block_reason(final_url)
            if block_reason:
                raise ValueError(block_reason)
            raise ValueError(
                "无法解析小红书笔记内容，链接可能已失效。"
                "请在 设置 → 插件设置 填写小红书 Cookie，或使用「粘贴正文」手动导入。"
            )

        # ── Extract fields ──
        if note:
            title = (note.get('title') or '').strip()
            desc = (note.get('desc') or '').strip()
            author = ''
            user_info = note.get('user') or note.get('author') or {}
            if isinstance(user_info, dict):
                author = (user_info.get('nickname') or user_info.get('name') or '').strip()
            images = []
            for img in (note.get('imageList') or note.get('images_list') or note.get('images') or []):
                if isinstance(img, dict):
                    src = img.get('url') or img.get('urlDefault') or img.get('url_default') or ''
                    if not src and isinstance(img.get('infoList'), list):
                        for info in img['infoList']:
                            if isinstance(info, dict) and info.get('url'):
                                src = info['url']
                                break
                    if src:
                        images.append(src)
                elif isinstance(img, str):
                    images.append(img)
            tags = []
            for tag in (note.get('tagList') or note.get('tag_list') or []):
                if isinstance(tag, dict) and tag.get('name'):
                    tags.append(tag['name'])
            note_type = note.get('type') or ('video' if note.get('video') else 'normal')
            # If video note: try to extract a playable URL and transcribe.
            xhs_video_url = _extract_xhs_video_url(note)
        else:
            xhs_video_url = None
            title = og_meta.get('title', '')
            desc = og_meta.get('description', '')
            author = og_meta.get('author', '')
            images = [og_meta['image']] if og_meta.get('image') else []
            tags = []
            note_type = 'normal'

        # Cover: first image, or OG image
        cover_url = (images[0] if images else '') or og_meta.get('image', '')

        # Build content HTML
        parts = []
        if title and title != desc:
            parts.append(f'<h1>{title}</h1>')
        if desc:
            parts.append(f'<p>{desc}</p>')
        if images:
            parts.append('<div class="xhs-images">')
            for img_url in images:
                parts.append(f'<img src="{img_url}" alt="xhs image" />')
            parts.append('</div>')
        if tags:
            parts.append(
                '<div class="xhs-tags" style="color:#888;font-size:12px;">'
                + ' '.join(f'#{t}' for t in tags)
                + '</div>'
            )

        content_html = '\n'.join(parts)

        display_title = title or (desc[:80] if desc else '小红书笔记')

        # Rewrite hotlink-protected CDN URLs through /api/images/proxy
        content_html = self._proxy_imgs_in_html(content_html)
        cover_url_final = self._proxy_url(cover_url) if cover_url else None

        logger.info(
            f"XHS parse SUCCESS: type={note_type}, "
            f"title={display_title[:40]}, images={len(images)}"
        )

        return {
            'title': display_title[:200],
            'raw_html': content_html,
            'raw_content': content_html,
            'platform': 'xhs',
            'author': author or 'unknown',
            'cover_image': cover_url_final,
            'og_meta': og_meta,
        }

