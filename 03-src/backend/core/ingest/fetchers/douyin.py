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

from backend.core.ingest.fetchers.helpers import logger

"""抖音视频抓取。"""

class DouyinParserMixin:
    async def _fetch_douyin(self, url: str) -> Dict:
        """Fetch Douyin content using Playwright - intercepts the internal API.

        Douyin is a React SPA. Instead of trying to generate X-Bogus signatures
        to call the API directly, we let Playwright load the page and intercept
        the /aweme/v1/web/aweme/detail/ XHR response that the SPA itself makes.
        This gives us the full structured JSON from Douyin's own API - no
        signature cracking required.

        Supports:
        - Share links: https://v.douyin.com/xxxxx/
        - Video pages: https://www.douyin.com/video/xxxxx
        - Note/articles: https://www.douyin.com/note/xxxxx (图文)
        """
        import asyncio
        import os

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ValueError(
                "playwright not installed. Add 'playwright>=1.40.0' to requirements.txt"
            )

        logger.info(f"Fetching Douyin via Playwright: {url}")

        # Capture the API response via request interception
        api_response = None

        async def on_response(response):
            nonlocal api_response
            if api_response is not None:
                return
            # Intercept the aweme detail API call.
            # Multiple endpoints - video shares hit /aweme/v1/web/aweme/detail/,
            # image-note shares (/share/note/...) hit different paths.
            req_url = response.request.url
            api_patterns = (
                '/aweme/v1/web/aweme/detail/',
                '/aweme/v1/web/aweme/iteminfo/',
                '/aweme/v1/web/aweme/post/',
                '/web/api/v2/aweme/iteminfo/',
                '/aweme/v1/web/note/',
            )
            if any(p in req_url for p in api_patterns):
                status = response.status
                if status == 200:
                    try:
                        body = await response.json()
                        if body.get('aweme_detail'):
                            api_response = body
                            logger.info(f"Douyin API intercepted: {len(str(body))} bytes")
                    except Exception:
                        pass

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                ]
            )

            context = await browser.new_context(
                user_agent=(
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/124.0.0.0 Safari/537.36'
                ),
                viewport={'width': 1920, 'height': 1080},
                locale='zh-CN',
            )

            page = await context.new_page()

            # Register response handler BEFORE navigation
            page.on('response', on_response)

            # Navigate to the douyin page
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            except Exception as e:
                logger.warning(f"Page navigation error (may be ok): {e}")

            # Wait for the API response (polling)
            import time as time_mod
            wait_start = time_mod.time()
            while api_response is None and (time_mod.time() - wait_start) < 15:
                await asyncio.sleep(0.5)

            if api_response is None:
                logger.warning(
                    "Timeout waiting for Douyin API response. "
                    "Falling back to DOM extraction."
                )

            # If API interception failed, try the SSR data in the DOM
            if api_response is None:
                try:
                    # state='attached' - RENDER_DATA is a <script> tag, never "visible"
                    await page.wait_for_selector(
                        '#RENDER_DATA, [data-e2e="feed-active-video"], .video-info-detail',
                        state='attached',
                        timeout=8000,
                    )
                except Exception:
                    pass

                # Try extracting from rendered DOM
                html = await page.content()
                page_text = await page.evaluate("document.body.innerText")

                # Check for error pages
                if len(page_text) < 100 and '验证' in page_text:
                    raise ValueError(
                        "Douyin captcha/verification page detected. "
                        "Try again later or use a different IP."
                    )

                # First try: parse RENDER_DATA from HTML directly (works without JS execution)
                import re
                from urllib.parse import unquote
                m = re.search(
                    r'<script[^>]*id="RENDER_DATA"[^>]*>(.*?)</script>',
                    html, re.DOTALL,
                )
                if m:
                    raw = m.group(1).strip()
                    try:
                        data = json.loads(unquote(raw))
                        # douyin RENDER_DATA shape: data.app.videoDetail or data.<route>.aweme
                        for key_path in [
                            lambda d: d.get('app', {}).get('videoDetail'),
                            lambda d: (d.get('app') or {}).get('aweme'),
                            lambda d: next(iter(d.values())) if d else None,
                        ]:
                            try:
                                result = key_path(data)
                                if result and isinstance(result, dict) and (
                                    result.get('aweme_id') or result.get('awemeId') or result.get('aweme_detail')
                                ):
                                    api_response = result if 'aweme_detail' in result else {'aweme_detail': result}
                                    logger.info(f"Douyin RENDER_DATA parsed via regex fallback")
                                    break
                            except Exception:
                                continue
                    except Exception as parse_err:
                        logger.warning(f"Failed parsing RENDER_DATA: {parse_err}")

                # Second try: window._ROUTER_DATA via JS
                if api_response is None:
                    try:
                        router_data = await page.evaluate("window._ROUTER_DATA")
                        if router_data and isinstance(router_data, dict):
                            api_response = {'routerData': router_data}
                    except Exception:
                        pass

                # Capture resolved URL + OG meta now (we use them either as the
                # final fallback below or to enrich the result above).
                try:
                    resolved_url = await page.evaluate("location.href") or url
                except Exception:
                    resolved_url = url
                try:
                    og_meta_capture = await page.evaluate("""() => {
                        const get = (sel) => document.querySelector(sel)?.getAttribute('content') || '';
                        // Fall back to the first douyinpic / douyinvod image rendered on the page
                        // when og:image isn't present (note pages emit only meta name="description").
                        const cdnImg = Array.from(document.images || [])
                            .map(i => i.src || '')
                            .find(s => s && (s.includes('douyinpic.com') || s.includes('douyinvod.com')));
                        return {
                            title: get('meta[property=\\"og:title\\"]') || document.title || '',
                            description: get('meta[property=\\"og:description\\"]') || get('meta[name=\\"description\\"]') || '',
                            image: get('meta[property=\\"og:image\\"]') || cdnImg || '',
                        };
                    }""")
                except Exception:
                    og_meta_capture = {}

                # Third try: SSR JSON in a <script id="RENDER_DATA"> - already attempted
                # above, but for image-note pages it can also be inside an inline
                # script literal. As a last resort, scan the rendered HTML for any
                # plausible "aweme_detail" / "noteDetail" JSON blob.
                if api_response is None:
                    for needle in ('"aweme_detail":', '"noteDetail":', '"videoDetail":'):
                        idx = html.find(needle)
                        if idx < 0:
                            continue
                        # Walk back to the enclosing '{', then count braces forward.
                        start = html.rfind('{', 0, idx)
                        if start < 0:
                            continue
                        depth = 0
                        end = -1
                        for j in range(start, min(len(html), start + 2_000_000)):
                            c = html[j]
                            if c == '{':
                                depth += 1
                            elif c == '}':
                                depth -= 1
                                if depth == 0:
                                    end = j
                                    break
                        if end > start:
                            try:
                                blob = json.loads(html[start:end + 1])
                                api_response = {'fromHtmlBlob': blob}
                                logger.info(f"Douyin extracted via HTML blob scan ({needle})")
                                break
                            except Exception:
                                continue

                # Fourth try (last resort): OG meta fallback. For note pages where
                # all structured extraction fails, OG meta tags still contain
                # title / description / image - better than failing.
                if api_response is None and og_meta_capture and (
                    og_meta_capture.get('description') or og_meta_capture.get('title')
                ):
                    api_response = {'fromOgMeta': og_meta_capture, 'resolvedUrl': resolved_url}
                    logger.info(
                        f"Douyin extracted via OG meta fallback (note-style page). "
                        f"title head: {(og_meta_capture.get('title') or '')[:40]}"
                    )

            await browser.close()

        if api_response is None:
            raise ValueError(
                "Could not extract Douyin video data. "
                "The page may be blocked or the link may be invalid."
            )

        # ── Parse the API response ──
        # Sources we may have: aweme_detail (API), routerData (window._ROUTER_DATA),
        # fromHtmlBlob (HTML scan). Walk them to find the aweme detail dict.
        aweme = None
        if 'aweme_detail' in api_response:
            aweme = api_response['aweme_detail']
        elif 'routerData' in api_response:
            router = api_response['routerData']
            loader = (router.get('loaderData') or {}) if isinstance(router, dict) else {}
            # Walk every loaderData entry - covers video_(id)_0, note_(id)_0, and
            # any future variants without hardcoding the prefix.
            for v in loader.values():
                if not isinstance(v, dict):
                    continue
                # Common shapes seen in the wild
                candidates = [
                    v.get('aweme_detail'),
                    (v.get('aweme') or {}).get('detail'),
                    v.get('noteDetail'),
                    v.get('videoDetail'),
                ]
                for cand in candidates:
                    if isinstance(cand, dict) and (cand.get('aweme_id') or cand.get('awemeId')):
                        aweme = cand
                        break
                if aweme:
                    break
        elif 'fromHtmlBlob' in api_response:
            blob = api_response['fromHtmlBlob']
            for cand in (
                blob.get('aweme_detail') if isinstance(blob, dict) else None,
                blob.get('noteDetail') if isinstance(blob, dict) else None,
                blob.get('videoDetail') if isinstance(blob, dict) else None,
                blob if isinstance(blob, dict) and (blob.get('aweme_id') or blob.get('awemeId')) else None,
            ):
                if isinstance(cand, dict) and (cand.get('aweme_id') or cand.get('awemeId')):
                    aweme = cand
                    break
        elif 'fromOgMeta' in api_response:
            # OG meta is the last-resort path for SSR-only note pages.
            # The description format is, empirically:
            #   "<note content> - <author>于YYYYMMDD发布在抖音,已经收获了N个喜欢,..."
            og = api_response['fromOgMeta']
            resolved = api_response.get('resolvedUrl', '')
            desc_full = og.get('description') or og.get('title') or ''
            content_text = desc_full
            author_name = ''
            create_time = 0
            m = re.match(r'^(.*?) - (.+?)于(\d{8})发布在抖音', desc_full)
            if m:
                content_text = m.group(1).strip()
                author_name = m.group(2).strip()
                try:
                    from datetime import datetime
                    create_time = int(datetime.strptime(m.group(3), "%Y%m%d").timestamp())
                except Exception:
                    pass
            # aweme_id from resolved URL: /note/<id> or /video/<id>
            aweme_id_match = re.search(r'/(?:note|video)/(\d+)', resolved or '')
            aweme_id_val = aweme_id_match.group(1) if aweme_id_match else (resolved or url).rstrip('/').split('/')[-1]
            is_note = '/note/' in (resolved or '')
            aweme = {
                'aweme_id': aweme_id_val,
                'desc': content_text,
                'author': {'nickname': author_name} if author_name else {},
                'create_time': create_time,
                'aweme_type': 68 if is_note else 0,
                'cover': {'url_list': [og['image']]} if og.get('image') else {},
                'images': [{'url_list': [og['image']]}] if (is_note and og.get('image')) else [],
            }

        if aweme is None:
            raise ValueError(
                f"Could not find aweme data in API response. "
                f"Keys: {list(api_response.keys())[:10]}"
            )

        # ── Extract data from aweme object ──
        aweme_id = aweme.get('aweme_id', '')
        desc = aweme.get('desc', '')
        create_time = aweme.get('create_time', 0)
        aweme_type = aweme.get('aweme_type', 0)  # 0=video, 68=image/note

        # Author
        author_data = aweme.get('author', {})
        author_name = author_data.get('nickname', '')
        author_unique_id = author_data.get('unique_id', '')

        # Statistics
        stats = aweme.get('statistics', {})
        digg_count = stats.get('digg_count', 0) or stats.get('admire_count', 0)
        comment_count = stats.get('comment_count', 0)
        share_count = stats.get('share_count', 0)

        # Cover
        cover_data = aweme.get('video', {}).get('cover', {}) or aweme.get('cover', {})
        cover_url_list = cover_data.get('url_list', [])
        cover_url = cover_url_list[0] if cover_url_list else ''

        # Hashtags
        hashtags = []
        for tag in (aweme.get('text_extra', []) or []):
            if isinstance(tag, dict) and tag.get('hashtag_name'):
                hashtags.append(tag['hashtag_name'])

        # Music
        music_data = aweme.get('music', {})
        music_title = music_data.get('title', '')
        music_author = music_data.get('author', '')

        # ── Build content HTML ──
        content_parts = []

        if desc:
            content_parts.append(f"<p>{desc}</p>")

        if aweme_type == 68:
            # Image note / 图文
            images = aweme.get('images', [])
            if images:
                content_parts.append('<div class="douyin-images">')
                for img in images:
                    url_list = img.get('url_list', [])
                    if url_list:
                        content_parts.append(
                            f'<img src="{url_list[0]}" alt="douyin image" />'
                        )
                content_parts.append('</div>')
            type_label = 'image'
        else:
            # Video
            video_data = aweme.get('video', {})
            play_addr = video_data.get('play_addr', {})
            play_url_list = play_addr.get('url_list', [])

            nwm_url = ''
            if play_url_list:
                # Replace watermark URL with non-watermark equivalent
                nwm_url = play_url_list[0].replace('playwm', 'play')
                content_parts.append(
                    f'<div class="douyin-video">'
                    f'<p>📹 视频链接: <a href="{nwm_url}">播放</a></p>'
                    f'</div>'
                )

            # Download address if available
            download_addr = video_data.get('download_addr', {})
            dl_url_list = download_addr.get('url_list', [])
            if dl_url_list:
                content_parts.append(
                    f'<div class="douyin-download">'
                    f'<p>⬇️ <a href="{dl_url_list[0]}">下载视频</a></p>'
                    f'</div>'
                )

            type_label = 'video'

        # Music metadata
        if music_title:
            content_parts.append(
                f'<div class="douyin-music">'
                f'🎵 {music_title}'
            )
            if music_author:
                content_parts.append(f' - {music_author}')
            content_parts.append('</div>')

        # Statistics
        content_parts.append(
            f'<div class="douyin-stats" style="color:#999;font-size:12px;">'
            f'👍 {digg_count} · 💬 {comment_count} · 🔄 {share_count}'
        )
        if hashtags:
            content_parts.append(
                f' · {" ".join("#"+t for t in hashtags)}'
            )
        content_parts.append('</div>')

        content_html = '\n'.join(content_parts)

        # OG metadata
        og_meta = {
            'title': desc[:100] if desc else f'抖音{type_label}_{aweme_id}',
            'author': author_name or author_unique_id,
            'image': cover_url,
            'description': desc[:500] if desc else '',
            'published_time': str(create_time),
            'site_name': '抖音',
        }

        author_display = author_name or author_unique_id or 'unknown'

        logger.info(
            f"Douyin parse SUCCESS: type={type_label}, id={aweme_id}, "
            f"desc='{desc[:50]}', author='{author_display}', "
            f"likes={digg_count}, comments={comment_count}"
        )

        # Rewrite hotlink-protected CDN URLs (douyinpic / douyinvod) through proxy
        content_html = self._proxy_imgs_in_html(content_html)
        cover_url_final = self._proxy_url(cover_url) if cover_url else None

        return {
            'title': desc[:200] if desc else f'抖音{type_label}_{aweme_id}',
            'raw_html': content_html,
            'raw_content': content_html,
            'platform': 'douyin',
            'author': author_display,
            'cover_image': cover_url_final,
            'og_meta': og_meta,
        }

