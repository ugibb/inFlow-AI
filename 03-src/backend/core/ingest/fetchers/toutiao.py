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

"""头条文章抓取。"""

class ToutiaoParserMixin:
    async def _fetch_toutiao(self, url: str) -> Dict:
        """Fetch Toutiao article via mobile SSR endpoint (m.toutiao.com).

        Desktop www.toutiao.com returns a JS VM challenge (byted_acrawler) that
        appears as garbled text. The mobile site m.toutiao.com uses pure SSR with
        all article data in a <script id="RENDER_DATA"> JSON block - no anti-crawling.
        """
        # Convert desktop URL to mobile equivalent
        mobile_url = re.sub(
            r'https?://(?:www\.)?toutiao\.com',
            'https://m.toutiao.com',
            url
        )
        # If it's a short link, follow redirects to get the real URL
        # e.g., toutiao.com/article/xxx → same on mobile

        mobile_headers = {
            'User-Agent': (
                'Mozilla/5.0 (Linux; Android 13; Pixel 7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Mobile Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(mobile_url, headers=mobile_headers)
            resp.raise_for_status()
            html = resp.text

        # Extract the RENDER_DATA JSON block
        # Format: <script id="RENDER_DATA" type="application/json">URL_ENCODED_JSON</script>
        match = re.search(
            r'<script[^>]*id="RENDER_DATA"[^>]*type="application/json"[^>]*>(.*?)</script>',
            html,
            re.DOTALL
        )

        if not match:
            raise ValueError(
                f"Could not find RENDER_DATA block in Toutiao page. "
                f"Page length: {len(html)} chars. "
                f"First 200 chars: {html[:200]}"
            )

        raw_json = match.group(1).strip()
        if not raw_json:
            raise ValueError("RENDER_DATA block is empty")

        try:
            data = json.loads(unquote(raw_json))
        except json.JSONDecodeError:
            # Sometimes the JSON is not URL-encoded
            data = json.loads(raw_json)

        # Navigate to article data - structure varies slightly
        article = None
        for path in [
            lambda d: d.get("articleInfo"),
            lambda d: (d.get("data") or {}).get("articleInfo"),
            lambda d: d.get("data", {}),
        ]:
            try:
                article = path(data)
                if article and isinstance(article, dict) and article.get("content"):
                    break
            except Exception:
                continue

        if not article or not isinstance(article, dict):
            raise ValueError(
                f"Could not extract article from RENDER_DATA. "
                f"Top-level keys: {list(data.keys())[:10]}"
            )

        # Extract fields - most string values are URL-encoded
        def safe_unquote(v):
            """Unquote a value, handling None and non-string types."""
            if v is None:
                return ""
            if isinstance(v, (int, float)):
                return str(v)
            result = unquote(v)
            # Sometimes values are double-encoded
            if '%' in result:
                try:
                    result = unquote(result)
                except Exception:
                    pass
            return result

        title = safe_unquote(article.get("title", ""))
        content_html = safe_unquote(article.get("content", ""))

        if not content_html:
            # Some articles are video-only or short-form
            detail = article.get("detailSource") or article.get("abstract") or ""
            if detail:
                content_html = f"<p>{safe_unquote(detail)}</p>"
            else:
                raise ValueError("Toutiao article has no text content (may be video-only)")

        # Author info
        media_user = article.get("mediaUser") or article.get("userInfo") or {}
        author_name = safe_unquote(media_user.get("screenName") or media_user.get("name") or "")

        # Cover image
        cover = ""
        if media_user.get("avatarUrl"):
            cover = safe_unquote(media_user.get("avatarUrl", ""))
        if article.get("coverImage") or article.get("cover"):
            cover = article.get("coverImage") or article.get("cover") or cover

        # Publish time (Unix timestamp in seconds)
        publish_time = article.get("publishTime") or article.get("createTime") or 0

        # Engagement stats for metadata
        comment_count = article.get("commentCount", 0)
        digg_count = article.get("diggCount", 0)

        # Build OG metadata for downstream consumers
        og_meta = {
            'title': title,
            'author': author_name,
            'image': cover,
            'description': safe_unquote(article.get("abstract") or article.get("detailSource") or ""),
            'published_time': str(publish_time),
            'site_name': '今日头条',
        }

        logger.info(
            f"Toutiao parse success: title='{title[:50]}', "
            f"content_len={len(content_html)}, author='{author_name}', "
            f"comments={comment_count}, likes={digg_count}"
        )

        return {
            'title': title,
            'raw_html': html,
            'raw_content': content_html,
            'platform': 'toutiao',
            'author': author_name or 'unknown',
            'cover_image': cover or None,
            'og_meta': og_meta,
        }

