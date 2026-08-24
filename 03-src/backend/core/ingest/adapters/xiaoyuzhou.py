"""Xiaoyuzhou (小宇宙) podcast adapter.

Parsing strategy (three layers, ported from 06-src/parser/xiaoyuzhou.py):

  1. JSON-LD  <script type="application/ld+json"> PodcastEpisode
     — SEO-standard structured data; most stable across page redesigns.
  2. __NEXT_DATA__  <script id="__NEXT_DATA__">
     — Next.js server-side embedded JSON; kept as fallback.
  3. Open Graph / <meta> tags
     — Last resort; always present, but lacks audio URL.

Supported URL patterns:
    https://www.xiaoyuzhoufm.com/episode/<id>

ASR note: audio URL is recorded in media_urls; transcription happens in the
parse step to keep Step 1 (ingest) fast.
"""

from __future__ import annotations

import json
import logging
import re
from typing import List, Optional
from uuid import UUID

import httpx
from bs4 import BeautifulSoup

from backend.core.ingest.adapters.base import AbstractAdapter, AdapterError
from backend.core.ingest.schema import RawCapture, RawMeta, RawContent
from backend.core.shared.utils.retry import async_retry

logger = logging.getLogger("inFlow.ingest.adapters.xiaoyuzhou")

# 域名匹配（xiaoyuzhoufm.com 和旧域名 xiaoyuzhou.fm 均支持）
_XYZ_URL_RE = re.compile(
    r"https?://(?:www\.)?xiaoyuzhou(?:fm)?\.(?:com|fm)/",
    re.IGNORECASE,
)
# episode 路径校验（对齐 06-src：必须含 /episode/）
_XYZ_EPISODE_RE = re.compile(r"/episode/", re.IGNORECASE)

_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class XiaoyuzhouAdapter(AbstractAdapter):
    platform = "xiaoyuzhou"
    version = "2.0.0"  # bumped: three-layer parsing strategy

    def can_handle(self, url: str) -> bool:
        return bool(_XYZ_URL_RE.search(url)) and bool(_XYZ_EPISODE_RE.search(url))

    async def fetch(
        self,
        url: str,
        *,
        user_id: UUID,
        capture_method: str = "url",
        extra_context: Optional[dict] = None,
    ) -> RawCapture:
        logger.debug("XiaoyuzhouAdapter.fetch: %s", url[:100])

        try:
            html = await self._get_html(url)
            episode = self._extract_episode(html, url)
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(
                f"Xiaoyuzhou fetch failed: {exc}",
                platform=self.platform,
                url=url,
            ) from exc

        meta = RawMeta(
            source_platform=self.platform,
            capture_method=capture_method,
            original_url=url,
            adapter_version=self.version,
            user_id=user_id,
        )

        raw = RawContent(
            title=episode.get("title"),
            author=episode.get("show_name"),
            content_type="audio",
            raw_text=episode.get("description"),
            cover_image=episode.get("cover"),
            media_urls=[episode["audio_url"]] if episode.get("audio_url") else [],
            extra={
                "show_name": episode.get("show_name"),
                "hosts": episode.get("hosts", []),
                "duration_seconds": episode.get("duration"),
                "episode_id": episode.get("episode_id"),
                "parse_strategy": episode.get("_strategy"),
            },
        )

        return RawCapture(meta=meta, raw=raw)

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    @async_retry(max_attempts=3, delay=3.0, exceptions=(httpx.RequestError, httpx.HTTPStatusError))
    async def _get_html(self, url: str) -> str:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers=_HEADERS,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text

    # ------------------------------------------------------------------
    # Three-layer parsing (ported from 06-src/parser/xiaoyuzhou.py)
    # ------------------------------------------------------------------

    def _extract_episode(self, html: str, url: str) -> dict:
        soup = BeautifulSoup(html, "lxml")

        # Layer 1: JSON-LD structured data (most stable)
        result = self._from_json_ld(soup, url)
        if result:
            episode = {**result, "_strategy": "json_ld"}
        else:
            # Layer 2: __NEXT_DATA__ (Next.js embedded JSON)
            result = self._from_next_data(html, url)
            if result:
                episode = {**result, "_strategy": "next_data"}
            else:
                # Layer 3: Open Graph / meta tags (last resort)
                result = self._from_meta_tags(soup, url)
                if result:
                    episode = {**result, "_strategy": "meta_tags"}
                else:
                    raise AdapterError(
                        "Could not extract episode data from Xiaoyuzhou page (all strategies failed)",
                        platform=self.platform,
                        url=url,
                    )

        # Cover image fallback: if primary strategy found no cover, try __NEXT_DATA__ then og:image
        if not episode.get("cover"):
            fallback = self._extract_cover_fallback(html, soup)
            if fallback:
                episode["cover"] = fallback
                logger.debug("封面补填：%s", fallback)

        return episode

    def _extract_cover_fallback(self, html: str, soup: BeautifulSoup) -> str:
        """Extract cover image from __NEXT_DATA__ episode object (preferred) or og:image."""
        m = _NEXT_DATA_RE.search(html)
        if m:
            try:
                data = json.loads(m.group(1))
                props = data.get("props", {}).get("pageProps", {})
                episode_data = (
                    props.get("episode")
                    or props.get("data", {}).get("episode")
                    or {}
                )
                url = self._pick_image_url(episode_data.get("image"))
                if url:
                    return url
            except Exception:
                pass

        og_image = soup.find("meta", property="og:image")
        if og_image:
            return og_image.get("content", "").strip()

        return ""

    def _from_json_ld(self, soup: BeautifulSoup, url: str) -> Optional[dict]:
        """Strategy 1: <script type="application/ld+json"> PodcastEpisode.

        Ported from 06-src/parser/xiaoyuzhou.py :: XiaoyuzhouParser._from_json_ld
        """
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, AttributeError):
                continue

            if isinstance(data, list):
                data = next(
                    (d for d in data if d.get("@type") == "PodcastEpisode"), {}
                )
            if data.get("@type") != "PodcastEpisode":
                continue

            title = data.get("name", "").strip()
            if not title:
                continue

            # audio URL: associatedMedia > audio > url
            media = data.get("associatedMedia") or data.get("audio") or {}
            audio_url = media.get("contentUrl", "").strip()
            if not audio_url:
                audio_url = data.get("url", "").strip()

            # hosts (author array)
            authors = data.get("author", [])
            if isinstance(authors, dict):
                authors = [authors]
            hosts: List[str] = [a.get("name", "") for a in authors if a.get("name")]

            # show name from partOfSeries / isPartOf
            series = data.get("partOfSeries") or data.get("isPartOf") or {}
            show_name = series.get("name", "").strip() if isinstance(series, dict) else ""

            description = data.get("description", "").strip()

            # cover image: episode level first, then show/series level
            cover = ""
            image = data.get("image")
            if isinstance(image, dict):
                cover = image.get("url", "").strip()
            elif isinstance(image, str):
                cover = image.strip()
            if not cover and isinstance(series, dict):
                series_image = series.get("image")
                if isinstance(series_image, dict):
                    cover = series_image.get("url", "").strip()
                elif isinstance(series_image, str):
                    cover = series_image.strip()

            episode_id = url.rstrip("/").split("/")[-1].split("?")[0]

            logger.debug("JSON-LD 解析成功：%s", title)
            return {
                "title": title,
                "description": description,
                "show_name": show_name,
                "hosts": hosts,
                "cover": cover,
                "audio_url": audio_url,
                "duration": data.get("duration"),
                "episode_id": episode_id,
            }

        return None

    @staticmethod
    def _pick_image_url(image_obj) -> str:
        """Extract best URL from xiaoyuzhou image object or plain string."""
        if isinstance(image_obj, str):
            return image_obj.strip()
        if isinstance(image_obj, dict):
            return (
                image_obj.get("largePicUrl")
                or image_obj.get("picUrl")
                or image_obj.get("middlePicUrl")
                or ""
            ).strip()
        return ""

    def _from_next_data(self, html: str, url: str) -> Optional[dict]:
        """Strategy 2: __NEXT_DATA__ embedded JSON (original implementation)."""
        m = _NEXT_DATA_RE.search(html)
        if not m:
            return None

        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return None

        props = data.get("props", {}).get("pageProps", {})
        episode_data = (
            props.get("episode")
            or props.get("data", {}).get("episode")
            or {}
        )
        if not episode_data:
            return None

        show = episode_data.get("podcast") or {}
        episode_id = episode_data.get("id", "")

        cover = self._pick_image_url(episode_data.get("image")) or self._pick_image_url(show.get("image"))

        # shownotes 字段通常是富文本 HTML（含嘉宾图片、章节时间戳等）
        # description 是纯文本简介。优先使用 shownotes，以保留原始格式。
        shownotes = (episode_data.get("shownotes") or "").strip()
        description = (episode_data.get("description") or "").strip()
        content = shownotes if (shownotes and "<" in shownotes) else (description or shownotes)

        logger.debug("__NEXT_DATA__ 解析成功：%s (shownotes=%s)", episode_data.get("title", ""), bool(shownotes))
        return {
            "title": episode_data.get("title", ""),
            "description": content,
            "show_name": show.get("title", ""),
            "hosts": [],
            "cover": cover,
            "audio_url": episode_data.get("enclosure", {}).get("url", ""),
            "duration": episode_data.get("duration"),
            "episode_id": episode_id,
        }

    def _from_meta_tags(self, soup: BeautifulSoup, url: str) -> Optional[dict]:
        """Strategy 3: Open Graph / <meta> tags (ported from 06-src).

        Audio URL is unavailable at this level; recorded as empty string.
        """
        title = ""
        og_title = soup.find("meta", property="og:title")
        if og_title:
            title = og_title.get("content", "").strip()
        if not title:
            title_tag = soup.find("title")
            title = title_tag.get_text(strip=True) if title_tag else ""

        if not title:
            return None

        description = ""
        og_desc = soup.find("meta", property="og:description")
        if og_desc:
            description = og_desc.get("content", "").strip()

        cover = ""
        og_image = soup.find("meta", property="og:image")
        if og_image:
            cover = og_image.get("content", "").strip()

        episode_id = url.rstrip("/").split("/")[-1].split("?")[0]

        logger.debug("Open Graph 解析成功（无音频 URL）：%s", title)
        return {
            "title": title,
            "description": description,
            "show_name": "",
            "hosts": [],
            "cover": cover,
            "audio_url": "",
            "duration": None,
            "episode_id": episode_id,
        }

    def get_parse_template_id(self) -> str:
        return "xiaoyuzhou_podcast"
