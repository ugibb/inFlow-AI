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

from backend.core.ingest.fetchers.helpers import _http_error_detail, extract_url_from_text, logger, _FETCH_HTTP_TIMEOUT

"""ParserService 通用能力 —— 平台检测、抓取、内容提取与转换。"""

class ParserServiceBase:
    """Extract and clean article content from various platforms."""

    PLATFORM_DETECT = {
        'weixin.qq.com': 'wechat',
        'mp.weixin.qq.com': 'wechat',
        'toutiao.com': 'toutiao',
        'jianshu.com': 'jianshu',
        'csdn.net': 'csdn',
        'medium.com': 'medium',
        'juejin.cn': 'juejin',
        'sspai.com': 'sspai',
        '36kr.com': '36kr',
        'weibo.com': 'weibo',
        'bilibili.com': 'bilibili',
        'b23.tv': 'bilibili',          # bilibili 短链
        'douban.com': 'douban',
        'douyin.com': 'douyin',
        'iesdouyin.com': 'douyin',     # 抖音分享口令短链域
        'xiaohongshu.com': 'xhs',      # 小红书
        'xhslink.com': 'xhs',          # 小红书短链
        'youtube.com': 'youtube',      # YouTube
        'youtu.be': 'youtube',         # YouTube 短链
        'feishu.cn': 'feishu',         # 飞书（国内版）
        'larksuite.com': 'feishu',     # 飞书（海外版 Lark）
    }

    def detect_platform(self, url: str) -> str:
        """Detect source platform from URL."""
        for domain, platform in self.PLATFORM_DETECT.items():
            if domain in url:
                return platform
        return 'other'

    def _get_headers(self, platform: str, url: str) -> Dict[str, str]:
        """Get platform-specific HTTP headers to avoid 403 and anti-scraping."""
        base_headers = {
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
        }

        if platform == 'toutiao':
            base_headers.update({
                'Referer': 'https://www.toutiao.com/',
                'Cache-Control': 'max-age=0',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'cross-site',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Ch-Ua': '"Google Chrome";v="120", "Chromium";v="120", "Not_A Brand";v="24"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"macOS"',
            })
        elif platform == 'wechat':
            base_headers.update({
                'Referer': 'https://mp.weixin.qq.com/',
            })
        elif platform == 'feishu':
            base_headers.update({
                'Referer': 'https://www.feishu.cn/',
                'Accept-Language': 'zh-CN,zh;q=0.9',
            })

        return base_headers

    def _extract_og_metadata(self, soup: BeautifulSoup) -> Dict:
        """Extract OpenGraph and other meta tag metadata."""
        meta = {}
        for og_tag in soup.find_all('meta'):
            prop = og_tag.get('property', '') or og_tag.get('name', '')
            content = og_tag.get('content', '')
            if not content:
                continue

            if prop == 'og:title':
                meta['title'] = content
            elif prop == 'og:description' or prop == 'description':
                if 'description' not in meta:
                    meta['description'] = content
            elif prop == 'og:image':
                meta['image'] = content
            elif prop == 'og:site_name':
                meta['site_name'] = content
            elif prop == 'author' or prop == 'og:article:author':
                meta['author'] = content
            elif prop == 'article:published_time':
                meta['published_time'] = content
        return meta

    async def fetch_content(self, url: str) -> Dict:
        """Fetch and parse article content from URL."""
        url = extract_url_from_text(url) or url
        platform = self.detect_platform(url)

        # P0: Toutiao - use mobile SSR endpoint (m.toutiao.com) to bypass
        # byte跳's byted_acrawler JS VM on desktop site
        if platform == 'toutiao':
            return await self._fetch_toutiao(url)

        # P2: Douyin - use douyin-tiktok-scraper library (X-Bogus + API)
        if platform == 'douyin':
            return await self._fetch_douyin(url)

        # P3: Bilibili - split into 专栏 (HTML) vs 视频 (API + 字幕)
        if platform == 'bilibili':
            return await self._fetch_bilibili(url)

        # P3.5: Feishu - React SPA, requires Playwright render; publicly-shared
        # docs need no auth but content is loaded after page hydration
        if platform == 'feishu':
            return await self._fetch_feishu(url)

        # P4: Xiaohongshu - follow xhslink redirect → curl_cffi mobile UA →
        # parse __INITIAL_STATE__ inline JSON → Playwright/OG fallback
        if platform == 'xhs':
            return await self._fetch_xhs(url)

        # P5: YouTube - yt-dlp subtitles first, ASR fallback
        if platform == 'youtube':
            return await self._fetch_youtube(url)

        # P5: 通用网页 - trafilatura 优先,内容过短再 Playwright 渲染,最后 BeautifulSoup 兜底
        # 视频号(channels.weixin.qq.com)、CSDN、掘金、Medium、少数派、36氪 等 JS 动态页同走此路
        return await self._fetch_generic(url, platform)

    # ── 飞书文档 ──────────────────────────────────────────────────────
    _FEISHU_GENERIC_TITLES = frozenset({
        "飞书云文档", "飞书文档", "feishu云文档", "lark", "untitled", "无标题",
    })

    @staticmethod
    def _text_len(html_or_text: Optional[str]) -> int:
        if not html_or_text:
            return 0
        return len(BeautifulSoup(html_or_text, 'lxml').get_text(strip=True))

    def _trafilatura_extract(self, html: str, url: str) -> Optional[str]:
        """用 trafilatura 提取正文(输出 HTML,保持与下游 clean_to_markdown 一致)。失败/未装返回 None。"""
        try:
            import trafilatura
        except ImportError:
            return None
        try:
            return trafilatura.extract(
                html, url=url, output_format='html',
                include_images=True, include_links=True, include_tables=True,
                include_formatting=True,
            )
        except Exception as e:
            logger.warning(f"trafilatura extract failed for {url}: {e}")
            return None

    async def _render_with_playwright(self, url: str) -> Optional[str]:
        """复用现成 headless Chromium 渲染 JS 动态页,返回完整 HTML。失败返回 None。"""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return None
        ua = self._get_headers('other', url)['User-Agent']
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-blink-features=AutomationControlled'],
                )
                ctx = await browser.new_context(
                    user_agent=ua, viewport={'width': 1920, 'height': 1080}, locale='zh-CN',
                )
                page = await ctx.new_page()
                try:
                    await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                except Exception as e:
                    logger.warning(f"playwright nav {url}: {e}")
                import asyncio as _a
                await _a.sleep(3)  # 给 CSR 一点渲染时间
                html = await page.content()
                await browser.close()
                return html
        except Exception as e:
            logger.warning(f"playwright render failed for {url}: {e}")
            return None

    # ── 通用网页提取级联 ──────────────────────────────────────────────
    # trafilatura(快、正文质量稳)→ 内容过短则 Playwright 渲染后重试 → BeautifulSoup 兜底。
    _MIN_CONTENT_CHARS = 200  # 正文纯文本短于此值视为提取不足,触发下一级

    def _build_generic_result(self, html: str, url: str, platform: str) -> Dict:
        """从原始 HTML 构建解析结果:trafilatura 优先,BeautifulSoup 兜底;元数据走 OG/soup。"""
        soup = BeautifulSoup(html, 'lxml')
        og_meta = self._extract_og_metadata(soup)

        # 1) trafilatura 优先(正文 HTML)
        content_html = self._trafilatura_extract(html, url)

        # 2) 回退:BeautifulSoup 启发式清洗 + 提取
        if not content_html or self._text_len(content_html) < self._MIN_CONTENT_CHARS:
            for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'iframe', 'noscript']):
                tag.decompose()
            # 精确类名匹配,避免子串误伤(如 'comment' 命中 'comment_feature')
            for cls in ['advertisement', 'comment', 'recommend', 'related', 'sidebar', 'share',
                        'sharing', 'bottom-bar', 'toolbar', 'report', 'copyright']:
                pattern = re.compile(r'(?:^|\s)' + re.escape(cls) + r'(?:\s|$)', re.I)
                for tag in soup.find_all(class_=pattern):
                    tag.decompose()
            content_html = self._extract_content(soup, platform, og_meta)

        title = og_meta.get('title') or self._extract_title(soup, platform)
        author = og_meta.get('author') or self._extract_author(soup, platform)
        cover = og_meta.get('image') or self._extract_cover(soup, platform)

        # WeChat/视频号 封面图走代理(mmbiz.qpic.cn 有 referer 防盗链)
        if cover and 'mmbiz.qpic.cn' in cover:
            from urllib.parse import quote
            cover = f"/api/images/proxy?url={quote(cover, safe='')}"

        return {
            'title': title,
            'raw_html': html,
            'raw_content': content_html,
            'platform': platform,
            'author': author,
            'cover_image': cover,
            'og_meta': og_meta,
        }

    async def _fetch_generic(self, url: str, platform: str) -> Dict:
        """通用网页抓取 + 提取级联。"""
        headers = self._get_headers(platform, url)
        try:
            async with httpx.AsyncClient(
                timeout=_FETCH_HTTP_TIMEOUT, follow_redirects=True,
            ) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                html = resp.text
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = f"HTTP {status}"
            if status in (403, 429):
                detail += "（可能被限流或需验证）"
            raise RuntimeError(f"{detail}: {url}") from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"请求超时 ({_http_error_detail(exc)}): {url}",
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"网络错误 ({_http_error_detail(exc)}): {url}",
            ) from exc

        result = self._build_generic_result(html, url, platform)

        # 内容过短 → 大概率是 JS 动态渲染页(视频号/部分前端框架站),Playwright 渲染后重试,取更长者
        if self._text_len(result['raw_content']) < self._MIN_CONTENT_CHARS:
            rendered = await self._render_with_playwright(url)
            if rendered:
                alt = self._build_generic_result(rendered, url, platform)
                if self._text_len(alt['raw_content']) > self._text_len(result['raw_content']):
                    logger.info(f"generic fetch: playwright render improved content for {url}")
                    result = alt
        return result

    # ── 通用提取辅助(供 _build_generic_result 兜底使用) ──────────────
    def _extract_content(self, soup: BeautifulSoup, platform: str, og_meta: Dict) -> str:
        """Extract main content based on platform-specific selectors."""
        content_html = ""

        # 公众号/视频号(channels.weixin.qq.com → 'wechat')正文容器
        if platform == 'wechat':
            article = soup.find('div', id='js_content') or soup.find('div', class_='rich_media_content')
            if article:
                content_html = str(article)

        # 飞书文档(新版 docx / 旧版 docs / 知识库 wiki)内容区
        elif platform == 'feishu':
            for sel in [
                {'class': 'docx-scene'},
                {'class': 'lake-content'},
                {'id': 'content-scroller'},
                {'class': 'doc-editor'},
                {'class': 'wiki-content'},
            ]:
                node = soup.find('div', sel)
                if node:
                    content_html = str(node)
                    break

        # Generic extraction fallback
        if not content_html:
            article = soup.find('article')
            if article:
                content_html = str(article)
            else:
                for selector in [
                    {'name': 'div', 'attrs': {'class': 'article-content'}},
                    {'name': 'div', 'attrs': {'class': 'post-content'}},
                    {'name': 'div', 'attrs': {'class': 'entry-content'}},
                    {'name': 'div', 'attrs': {'id': 'content'}},
                    {'name': 'main', 'attrs': {}},
                ]:
                    article = soup.find(selector['name'], selector['attrs'])
                    if article:
                        content_html = str(article)
                        break

        # Final fallback: whole body
        if not content_html:
            body = soup.find('body')
            content_html = str(body) if body else str(soup)
        return content_html

    def _extract_title(self, soup: BeautifulSoup, platform: str) -> str:
        """Extract article title."""
        h1 = soup.find('h1')
        if h1 and h1.get_text(strip=True):
            return h1.get_text(strip=True)
        title_tag = soup.find('title')
        if title_tag:
            return title_tag.get_text(strip=True)
        return "Untitled"

    def _extract_author(self, soup: BeautifulSoup, platform: str) -> str:
        """Extract article author."""
        for selector in [
            {'name': 'a', 'attrs': {'class': 'author'}},
            {'name': 'span', 'attrs': {'class': 'author'}},
            {'name': 'div', 'attrs': {'class': 'author'}},
        ]:
            tag = soup.find(selector['name'], selector['attrs'])
            if tag and tag.get_text(strip=True):
                return tag.get_text(strip=True)
        return ""

    def _extract_cover(self, soup: BeautifulSoup, platform: str) -> str:
        """Extract cover image."""
        og_img = soup.find('meta', property='og:image')
        if og_img:
            return og_img.get('content', '')
        return ""

    # CDNs that block hotlink requests without a proper Referer. URLs from these
    # hosts must be rewritten through /api/images/proxy (served with the right Referer).
    _HOTLINK_PROTECTED_CDNS = (
        'mmbiz.qpic.cn', 'mmbiz.qlogo.cn', 'mmecoa.qpic.cn',  # WeChat / 视频号
        'xhscdn.com',                                           # XHS
        'douyinpic.com', 'douyinvod.com',                       # Douyin
    )

    @classmethod
    def _proxy_url(cls, image_url: Optional[str]) -> Optional[str]:
        """Rewrite hotlink-protected image URLs through the backend proxy.

        The proxy endpoint (/api/images/proxy) adds the right Referer per CDN.
        Non-protected URLs are returned unchanged. None / empty pass through.
        """
        if not image_url:
            return image_url
        if image_url.startswith('/api/images/proxy'):
            return image_url  # already rewritten
        if any(d in image_url for d in cls._HOTLINK_PROTECTED_CDNS):
            from urllib.parse import quote
            return f"/api/images/proxy?url={quote(image_url, safe='')}"
        return image_url

    @classmethod
    def _proxy_imgs_in_html(cls, html: str) -> str:
        """Rewrite any <img src=...> referencing a hotlink-protected CDN through proxy."""
        if not html:
            return html
        soup = BeautifulSoup(html, 'lxml')
        for img in soup.find_all('img'):
            src = img.get('src') or ''
            new_src = cls._proxy_url(src)
            if new_src != src:
                img['src'] = new_src
        # BeautifulSoup with lxml wraps content in <html><body>; strip if added.
        body = soup.body
        if body:
            return body.decode_contents()
        return str(soup)

    def clean_to_markdown(self, html_content: str, platform: str = 'other') -> str:
        """Convert cleaned HTML to readable markdown."""
        if not html_content:
            return ""

        # For WeChat, rewrite mmbiz.qpic.cn image URLs to proxy endpoint
        # instead of deleting them, so images display correctly in the browser
        if platform == 'wechat':
            soup = BeautifulSoup(html_content, 'lxml')
            for img in soup.find_all('img'):
                src = img.get('data-src') or img.get('data-original') or img.get('src', '')
                if src and 'mmbiz.qpic.cn' in src:
                    from urllib.parse import quote
                    img['src'] = f"/api/images/proxy?url={quote(src, safe='')}"
                elif not img.get('src'):
                    img.decompose()
            html_content = str(soup)

        # markdownify: when using convert, don't set strip
        markdown = md_convert(
            html_content,
            heading_style='ATX',
            bullets='-',
        )

        # Clean up excessive whitespace
        markdown = re.sub(r'\n{4,}', '\n\n\n', markdown)
        markdown = markdown.strip()

        # If markdown is empty/very short, try extracting text directly
        if len(markdown) < 100:
            soup = BeautifulSoup(html_content, 'lxml')

            # Extract all text, preserving paragraph structure
            paragraphs = []
            for tag in soup.find_all(['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'blockquote']):
                text = tag.get_text(strip=True)
                if text and len(text) > 5:
                    # Rewrite WeChat image URLs to proxy endpoint
                    imgs = tag.find_all('img') if platform == 'wechat' else []
                    for img in imgs:
                        src = img.get('data-src') or img.get('src', '')
                        if src and 'mmbiz.qpic.cn' in src:
                            from urllib.parse import quote
                            src = f"/api/images/proxy?url={quote(src, safe='')}"
                            paragraphs.append(f'![]({src})')
                    if not imgs or text:
                        if tag.name.startswith('h'):
                            paragraphs.append(f"\n## {text}")
                        elif tag.name == 'blockquote':
                            paragraphs.append(f"\n> {text}")
                        elif tag.name == 'li':
                            paragraphs.append(f"- {text}")
                        else:
                            paragraphs.append(text)

            if paragraphs:
                markdown = '\n\n'.join(paragraphs)
            else:
                # Straight text extraction
                text = soup.get_text(separator='\n', strip=True)
                lines = [l.strip() for l in text.split('\n') if l.strip()]
                markdown = '\n\n'.join(lines)

        return markdown

    def count_words(self, text: str) -> int:
        """Count words/characters in text."""
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        english_words = len(re.findall(r'[a-zA-Z]+', text))
        return chinese_chars + english_words

    def estimate_reading_time(self, word_count: int) -> int:
        """Estimate reading time in minutes."""
        return max(1, round(word_count / 300))


# ============================================================
#  Xiaohongshu (小红书) helpers
# ============================================================

_XHS_STATE_PATTERNS = (
    # Most common: a JS object literal assignment, possibly with unquoted keys.
    re.compile(r'window\.__INITIAL_STATE__\s*=\s*({.*?})\s*</script>', re.DOTALL),
    re.compile(r'window\.__INITIAL_SSR_STATE__\s*=\s*({.*?})\s*</script>', re.DOTALL),
    re.compile(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', re.DOTALL),
)


