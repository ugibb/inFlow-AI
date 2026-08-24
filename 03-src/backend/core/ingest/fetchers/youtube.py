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

from backend.core.ingest.fetchers.helpers import _get_plugin_bool, _get_plugin_int, _get_plugin_str, logger

"""YouTube 视频抓取。"""

class YoutubeParserMixin:
    async def _fetch_youtube(self, url: str) -> Dict:
        """Fetch YouTube video: subtitles via yt-dlp, title/desc from -j."""
        import json as _json
        import subprocess

        # Only parse YouTube if yt-dlp is enabled
        if not _get_plugin_bool('enable_yt_dlp', True):
            return self._youtube_fallback('YouTube Video',
                '(YouTube 解析未开启,可在 系统管理 → 插件设置 中开启)', url)

        proxy = _get_plugin_str('proxy', '')

        # Get video metadata + subtitle list as JSON
        try:
            ytdlp_args = ['yt-dlp', '-j', '--no-playlist', '--skip-download', '--no-warnings']
            if proxy:
                ytdlp_args += ['--proxy', proxy]
            ytdlp_args += [url]
            proc = await asyncio.create_subprocess_exec(
                *ytdlp_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=90)
        except asyncio.TimeoutError:
            logger.warning(f"YouTube: yt-dlp -j timeout for {url}")
            return self._youtube_fallback('YouTube Video', '', url)
        except Exception as e:
            logger.warning(f"YouTube: yt-dlp -j failed: {e}")
            return self._youtube_fallback('YouTube Video', '', url)

        if proc.returncode != 0 or not stdout:
            logger.warning(f"YouTube: yt-dlp -j returned {proc.returncode}")
            return self._youtube_fallback('YouTube Video', '', url)

        try:
            info = _json.loads(stdout)
        except _json.JSONDecodeError:
            return self._youtube_fallback('YouTube Video', '', url)

        title = info.get('title', 'YouTube Video')
        desc = (info.get('description') or '')[:2000]
        uploader = info.get('uploader', '')
        duration = info.get('duration', 0) or 0
        thumbnail = info.get('thumbnail', '')

        # Try to get Chinese subtitles first, then English, then auto
        subtitle_text = ''
        subs_to_try = [
            (['zh-Hans', 'zh', 'zh-CN', 'zh-TW', 'zh-Hant'], True),
            (['en'], True),
        ]
        for langs, auto in subs_to_try:
            if subtitle_text:
                break
            for lang in langs:
                try:
                    sub_proc = await asyncio.create_subprocess_exec(
                        'yt-dlp', '--skip-download', '--no-playlist',
                        '--no-warnings',
                        '--write-auto-subs' if auto else '--write-subs',
                        f'--sub-lang={lang}', '--convert-subs=srt',
                        '-o', '-', '--get-comments', url,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    # Instead, use --write-subs to file approach
                    break
                except Exception:
                    continue

        # Simpler: use --write-auto-subs + --sub-format srt + output to tempdir
        if not subtitle_text:
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    cmd = [
                        'yt-dlp', '--skip-download', '--no-playlist', '--no-warnings',
                        '--write-auto-subs', '--sub-lang', 'zh-Hans,en,zh',
                        '--sub-format', 'srt/vtt/ass',
                    ]
                    if proxy:
                        cmd += ['--proxy', proxy]
                    cmd += ['-o', f'{tmpdir}/%(title)s.%(ext)s', url]
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await asyncio.wait_for(proc.communicate(), timeout=90)

                    # Find subtitle files
                    sub_files = list(Path(tmpdir).glob('*.srt')) + \
                                list(Path(tmpdir).glob('*.vtt')) + \
                                list(Path(tmpdir).glob('*.ass'))
                    if sub_files:
                        # Prefer Chinese
                        zh_files = [f for f in sub_files if any(
                            tag in f.name.lower() for tag in ['zh', 'zh-hans', 'zh-cn', 'chs']
                        )]
                        chosen = (zh_files or sub_files)[0]
                        with open(chosen, 'r', encoding='utf-8', errors='ignore') as f:
                            raw_sub = f.read()
                        # Strip SRT timestamps/numbers - keep just text
                        subtitle_text = self._clean_srt(raw_sub)
                        logger.info(f"YouTube: subtitle from {chosen.name} ({len(subtitle_text)} chars)")
            except Exception as e:
                logger.warning(f"YouTube subtitle download failed: {e}")

        raw_md = f"# {title}\n\n**频道:** {uploader}\n\n## 简介\n\n{desc}"
        if subtitle_text:
            raw_md += f"\n\n## 视频字幕\n\n{subtitle_text}"

        # ASR fallback (same pattern as Bilibili)
        asr_marker = ''
        if _get_plugin_bool('enable_asr', True):
            asr_max = _get_plugin_int('asr_max_duration', 1800)
            if not subtitle_text and duration <= asr_max:
                asr_marker = f'\n<!-- ASR_PENDING: {url} -->'  # URL-based: ASR task will use yt-dlp
                raw_md += f"\n\n*（后台语音转录中，稍后自动更新…）*{asr_marker}"
            elif not subtitle_text and duration > asr_max:
                raw_md += f"\n\n*（视频 {duration // 60} 分钟，超出自动转录上限。）*"

        return {
            'title': title,
            'raw_html': '',
            'raw_content': raw_md,
            'platform': 'youtube',
            'author': uploader,
            'cover_image': thumbnail,
        }

    def _youtube_fallback(self, title: str, desc: str, url: str) -> Dict:
        return {
            'title': title,
            'raw_html': '',
            'raw_content': f"# {title}\n\n{desc}\n\n*(无法获取视频详情)*",
            'platform': 'youtube',
            'author': '',
            'cover_image': '',
        }

    @staticmethod
    def _clean_srt(srt_text: str) -> str:
        """Strip SRT timestamps and numbers, return clean text."""
        import re
        # Remove sequence numbers and timestamps
        cleaned = re.sub(r'^\d+\s*$', '', srt_text, flags=re.MULTILINE)
        cleaned = re.sub(r'\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}', '', cleaned)
        # Remove HTML tags from VTT
        cleaned = re.sub(r'<[^>]+>', '', cleaned)
        # Remove VTT header
        cleaned = re.sub(r'^WEBVTT.*?\n', '', cleaned, flags=re.DOTALL)
        # Collapse blank lines
        lines = [l.strip() for l in cleaned.split('\n') if l.strip()]
        # Remove duplicate consecutive lines (common in auto-subs)
        result = []
        prev = ''
        for line in lines:
            if line != prev:
                result.append(line)
                prev = line
        return '\n'.join(result)


