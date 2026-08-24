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

from backend.core.ingest.fetchers.helpers import _get_feishu_cookie, logger, _STEALTH_JS

"""飞书文档抓取。"""

class FeishuParserMixin:
    @classmethod
    def _extract_feishu_doc_title(cls, html: str, fallback: str | None = None) -> str | None:
        """飞书 SPA 的 <title> 常为占位名，从正文 h1 提取真实文档标题。"""

        def _clean(text: str) -> str:
            return re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text).strip()

        def _is_generic(text: str) -> bool:
            normalized = re.sub(r"\s+", "", _clean(text)).lower()
            if not normalized or len(normalized) < 3:
                return True
            if normalized in {t.lower() for t in cls._FEISHU_GENERIC_TITLES}:
                return True
            if re.fullmatch(r"飞书.*文档", normalized):
                return True
            return False

        candidate = _clean(fallback or "")
        if candidate and not _is_generic(candidate):
            return candidate

        soup = BeautifulSoup(html, "lxml")
        for h1 in soup.find_all("h1"):
            text = _clean(h1.get_text(strip=True))
            if text and not _is_generic(text):
                return text
        return candidate or None

    async def _fetch_feishu(self, url: str) -> Dict:
        """Fetch Feishu (飞书) document via Playwright.

        飞书文档是 React SPA，正文由前端 hydration 后注入 DOM，纯 httpx GET 只
        能拿到空壳 HTML。

        反扒特征：
          - navigator.webdriver 检测：用 _STEALTH_JS 消除
          - Wiki 内容懒加载：需要滚动触发块渲染
          - 未授权文档重定向到登录页

        支持路径：
          /docx/<id>  — 新版文档（飞书文档）
          /docs/<id>  — 旧版文档
          /wiki/<id>  — 知识库（Wiki）页面
        """
        import asyncio as _a

        logger.info("Fetching Feishu doc via Playwright: %s", url[:100])

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ValueError("playwright 未安装，无法渲染飞书 SPA，请 pip install playwright")

        cookie = _get_feishu_cookie()
        is_wiki = '/wiki/' in url

        html = ""
        page_title = ""

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage',
                        '--disable-web-security',
                    ],
                )
                ctx = await browser.new_context(
                    user_agent=(
                        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/124.0.0.0 Safari/537.36'
                    ),
                    viewport={'width': 1440, 'height': 900},
                    locale='zh-CN',
                )

                # 注入 Cookie（如果配置了飞书 Cookie）
                if cookie:
                    parsed_domain = re.search(r'https?://([^/]+)', url)
                    domain = parsed_domain.group(1) if parsed_domain else 'feishu.cn'
                    # 解析 cookie 字符串注入
                    pw_cookies = []
                    for part in cookie.split(';'):
                        part = part.strip()
                        if '=' not in part:
                            continue
                        name, value = part.split('=', 1)
                        pw_cookies.append({
                            'name': name.strip(),
                            'value': value.strip(),
                            'domain': '.' + domain.split('.')[-2] + '.' + domain.split('.')[-1],
                            'path': '/',
                        })
                    if pw_cookies:
                        await ctx.add_cookies(pw_cookies)
                        logger.info("Feishu: using configured cookie (%d entries)", len(pw_cookies))

                page = await ctx.new_page()

                # 在页面加载前注入反检测脚本
                await page.add_init_script(_STEALTH_JS)

                try:
                    await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                except Exception as e:
                    logger.warning("Feishu nav partial: %s", e)

                # 初始等待：让 React hydration 和首屏渲染完成
                await _a.sleep(4)

                # 检测是否被重定向到登录页（尽早退出）
                current_url = page.url
                if 'passport.feishu.cn' in current_url or 'passport.larksuite.com' in current_url:
                    await browser.close()
                    tip = (
                        "，可在「设置 → 插件设置」填写飞书 Cookie 后重试"
                        if not cookie else ""
                    )
                    raise ValueError(
                        f"飞书文档需要登录才能访问，请确认文档已开启「互联网可查看」{tip}"
                    )

                # Wiki 页面：内容块懒加载，需要模拟滚动触发渲染
                if is_wiki:
                    scroll_steps = 12
                else:
                    scroll_steps = 6

                for _ in range(scroll_steps):
                    await page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")
                    await _a.sleep(0.8)

                # 滚回顶部，再等内容稳定
                await page.evaluate("window.scrollTo(0, 0)")
                await _a.sleep(2)

                page_title = await page.title()
                html = await page.content()

                # 检查正文长度：内容过短说明仍未渲染，再等一轮
                body_text = await page.evaluate("document.body.innerText")
                if len(body_text.strip()) < 300:
                    logger.info("Feishu: body too short (%d), waiting extra 8s", len(body_text))
                    await _a.sleep(8)
                    html = await page.content()
                    body_text = await page.evaluate("document.body.innerText")

                logger.info("Feishu: captured %d body chars from %s", len(body_text), url[:80])
                await browser.close()
        except ValueError:
            raise
        except Exception as exc:
            logger.warning("Feishu playwright failed: %s", exc)
            raise ValueError(f"飞书文档抓取失败: {exc}") from exc

        if not html:
            raise ValueError("飞书文档内容为空，可能需要登录或文档未开启公开分享")

        result = self._build_generic_result(html, url, 'feishu')

        # 正文过短时给出友好提示（而不是返回空内容）
        if self._text_len(result.get('raw_content')) < 200:
            tip = (
                "，可在「设置 → 插件设置」填写飞书 Cookie 后重试，或使用「粘贴正文」手动导入"
                if not cookie else "，可使用「粘贴正文」手动导入"
            )
            logger.warning("Feishu: content too short for %s", url)
            raise ValueError(
                f"飞书文档内容抓取不完整（可能受反扒机制限制）{tip}"
            )

        # 飞书页面 title 格式：「文档标题 - 飞书文档」，去掉后缀
        candidate = result.get('title') or ''
        if page_title:
            clean_title = re.sub(r'\s*[-–|]\s*(飞书|Lark).*$', '', page_title).strip()
            if clean_title:
                candidate = clean_title
        resolved = self._extract_feishu_doc_title(html, candidate)
        if resolved:
            result['title'] = resolved

        result['platform'] = 'feishu'
        return result
