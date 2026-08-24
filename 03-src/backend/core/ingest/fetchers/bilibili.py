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

from backend.core.ingest.fetchers.helpers import _get_plugin_bool, _get_plugin_int, logger

"""B 站视频/文章抓取。"""

class BilibiliParserMixin:
    async def _fetch_bilibili(self, url: str) -> Dict:
        """Bilibili: route by URL shape.
        - 专栏 (read/cv...) and opus (新版图文动态/笔记): HTML scrape
        - 视频 (video/BV...): official API + subtitle
        """
        is_article_like = (
            'read.bilibili.com' in url
            or '/read/cv' in url
            or '/read/mobile' in url
            or '/opus/' in url
            or '/dynamic/' in url
        )
        if is_article_like:
            return await self._fetch_bilibili_article(url)
        return await self._fetch_bilibili_video(url)

    async def _fetch_bilibili_article(self, url: str) -> Dict:
        """Bilibili 专栏 - anti-bot is mild, plain GET works."""
        headers = self._get_headers('bilibili', url)
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            html = resp.text

        soup = BeautifulSoup(html, 'lxml')
        # Title
        title = ''
        if soup.find('h1'):
            title = soup.find('h1').get_text(strip=True)
        if not title:
            og = soup.find('meta', property='og:title')
            if og:
                title = og.get('content', '')
        # Author
        author = ''
        author_meta = soup.find('meta', attrs={'name': 'author'})
        if author_meta:
            author = author_meta.get('content', '')
        # Cover
        cover = ''
        og_img = soup.find('meta', property='og:image')
        if og_img:
            cover = og_img.get('content', '')
        # Main content
        main = (
            soup.find('div', class_='opus-module-content')
            or soup.find('div', class_='article-content')
            or soup.find('article')
        )
        raw_content = str(main) if main else html

        return {
            'title': title or 'Bilibili 专栏',
            'raw_html': html,
            'raw_content': raw_content,
            'platform': 'bilibili',
            'author': author,
            'cover_image': cover,
        }

    async def _fetch_bilibili_video(self, url: str) -> Dict:
        """Bilibili 视频 - pull metadata + subtitle via official API."""
        # b23.tv 短链 → 跳转拿到含 bvid 的真实 URL
        if 'b23.tv' in url:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                r = await client.get(url, headers=self._get_headers('bilibili', url))
                url = str(r.url)

        m = re.search(r'(BV[0-9A-Za-z]{10})', url)
        if not m:
            raise Exception(f"Cannot extract bvid from URL: {url}")
        bvid = m.group(1)

        from bilibili_api import video as bv, Credential
        v = bv.Video(bvid=bvid, credential=Credential(sessdata='_', bili_jct='_', buvid3='_'))
        info = await v.get_info()

        title = info.get('title', '')
        desc = info.get('desc', '') or ''
        cover = info.get('pic', '')
        owner = (info.get('owner') or {}).get('name', '')
        cid = info.get('cid')
        duration = info.get('duration', 0)  # seconds

        # Subtitle (best effort - many videos have none)
        subtitle_text = ''
        try:
            sub_info = await v.get_subtitle(cid=cid) if cid else None
            subtitles = (sub_info or {}).get('subtitles', [])
            if subtitles:
                sub_url = subtitles[0].get('subtitle_url', '')
                if sub_url and sub_url.startswith('//'):
                    sub_url = 'https:' + sub_url
                if sub_url:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        sub_resp = await client.get(sub_url)
                        sub_resp.raise_for_status()
                        sub_data = sub_resp.json()
                        body = sub_data.get('body', [])
                        subtitle_text = '\n'.join(
                            line.get('content', '') for line in body if line.get('content')
                        )
        except Exception as e:
            logger.warning(f"bilibili subtitle fetch failed for {bvid}: {e}")

        # ASR: if no subtitle, embed hidden marker for background transcription
        asr_marker = ''
        if not subtitle_text and cid and _get_plugin_bool('enable_asr', True):
            try:
                play_url = f'https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&qn=0&fnval=16'
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.get(play_url, headers=self._get_headers('bilibili', url))
                    dash = (r.json().get('data') or {}).get('dash', {})
                    audio_streams = dash.get('audio', [])
                    if audio_streams:
                        audio_streams.sort(key=lambda a: a.get('bandwidth', 999999))
                        asr_url = audio_streams[0].get('base_url', '')
                        if asr_url and duration <= _get_plugin_int('asr_max_duration', 1800):
                            asr_marker = f'\n<!-- ASR_PENDING: {asr_url} -->'
            except Exception as e:
                logger.warning(f"bilibili ASR prep failed for {bvid}: {e}")

        raw_md = f"# {title}\n\n**UP 主:** {owner}\n\n## 简介\n\n{desc}"
        if subtitle_text:
            raw_md += f"\n\n## 视频字幕\n\n{subtitle_text}"
        elif asr_marker:
            raw_md += f"\n\n*(后台语音转录中,稍后自动更新...)*{asr_marker}"
        elif duration > _get_plugin_int('asr_max_duration', 1800):
            raw_md += f"\n\n*(视频 {duration // 60} 分钟,超出自动转录上限,可手动下载音频转录。)*"
        else:
            raw_md += "\n\n*(该视频未提供字幕,ASR 转录亦不可用)*"

        return {
            'title': title or f'B 站视频 {bvid}',
            'raw_html': '',
            'raw_content': raw_md,
            'platform': 'bilibili',
            'author': owner,
            'cover_image': cover,
        }

