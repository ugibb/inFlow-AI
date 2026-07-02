"""Audio file downloader with resume support.

Ported from 06-src/parser/downloader.py.
Key change: sync requests → async httpx to fit the async service architecture.
Behaviour is otherwise identical: streaming download, resume via Range header,
.part file for incomplete downloads.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.core.shared.utils.retry import async_retry

logger = logging.getLogger("inFlow.services.audio_downloader")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

_CHUNK_SIZE = 1024 * 64          # 64 KB
_CONNECT_TIMEOUT = 30.0
_READ_TIMEOUT = 600.0            # 10 min for large files
_CONTENT_RANGE_RE = re.compile(r"bytes \d+-\d+/(\d+|\*)")


def _parse_total_bytes(content_range: str, resume_from: int, content_length: int) -> int:
    """Infer total file size from Content-Range or Content-Length."""
    if content_range:
        m = _CONTENT_RANGE_RE.match(content_range.strip())
        if m and m.group(1) != "*":
            return int(m.group(1))
    if content_length > 0:
        return resume_from + content_length
    return 0


class AudioDownloader:
    """Async audio downloader. Supports streaming, resume, and auto-retry.

    Ported from 06-src/parser/downloader.py :: AudioDownloader.
    """

    async def download(
        self,
        audio_url: str,
        dest_dir: Path,
        filename: str = "",
        progress_cb: Callable[[str], None] | None = None,
    ) -> Path:
        """Download audio to *dest_dir*.

        Skips if the target file already exists with size > 0.
        Resumes from an existing .part file on the next run.

        Args:
            audio_url: Direct audio file URL.
            dest_dir:  Destination directory (created if missing).
            filename:  Target filename; inferred from URL when empty.

        Returns:
            Path of the completed file.

        Raises:
            RuntimeError: Network failure after retries, or HTTP error.
        """
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        if not filename:
            filename = self._infer_filename(audio_url)

        dest = dest_dir / filename
        part_file = dest_dir / (filename + ".part")

        if dest.is_file() and dest.stat().st_size > 0:
            logger.debug("音频已存在，跳过下载：%s", dest)
            return dest

        if part_file.is_file() and part_file.stat().st_size > 0:
            msg = f"断点续传（已下载 {part_file.stat().st_size / 1024 / 1024:.1f} MB）"
            if progress_cb:
                progress_cb(msg)
            else:
                logger.debug("%s：%s", msg, part_file)

        await self._download_with_retry(audio_url, part_file, progress_cb=progress_cb)
        part_file.rename(dest)
        logger.debug("音频下载完成：%s", dest)
        return dest

    @async_retry(
        max_attempts=5,
        delay=5.0,
        exceptions=(httpx.RequestError, httpx.HTTPStatusError, RuntimeError),
    )
    async def _download_with_retry(
        self,
        url: str,
        part_file: Path,
        *,
        progress_cb: Callable[[str], None] | None = None,
    ) -> None:
        resume_from = part_file.stat().st_size if part_file.is_file() else 0
        headers = dict(_HEADERS)
        if resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"

        timeout = httpx.Timeout(connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=10.0, pool=10.0)

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", url, headers=headers) as resp:
                if resp.status_code == 416:
                    if part_file.is_file() and part_file.stat().st_size > 0:
                        if progress_cb:
                            progress_cb("断点文件已完整，跳过下载")
                        else:
                            logger.debug("断点文件已完整，跳过下载")
                        return
                    raise RuntimeError(f"音频下载失败（HTTP 416）")

                if resume_from > 0 and resp.status_code == 200:
                    if progress_cb:
                        progress_cb("服务器不支持断点续传，重新下载")
                    else:
                        logger.warning("服务器不支持断点续传，重新下载")
                    part_file.unlink(missing_ok=True)
                    resume_from = 0

                resp.raise_for_status()

                content_length = int(resp.headers.get("content-length", 0) or 0)
                total = _parse_total_bytes(
                    resp.headers.get("Content-Range", ""),
                    resume_from,
                    content_length,
                )
                downloaded = resume_from
                mode = "ab" if resume_from > 0 and resp.status_code == 206 else "wb"
                last_progress_pct = -1

                with open(part_file, mode) as f:
                    async for chunk in resp.aiter_bytes(chunk_size=_CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total > 0:
                                milestone = int(downloaded / total * 100) // 25 * 25
                                if milestone > last_progress_pct and milestone > 0:
                                    last_progress_pct = milestone
                                    if progress_cb:
                                        progress_cb(f"下载进度 {milestone}%")
                                    else:
                                        logger.debug("下载进度：%d%%", milestone)

                if total > 0 and downloaded < total:
                    raise RuntimeError(
                        f"下载不完整：{downloaded}/{total} bytes"
                    )

    @staticmethod
    def _infer_filename(url: str) -> str:
        parsed = urlparse(url)
        name = parsed.path.rstrip("/").split("/")[-1]
        if not name or "." not in name:
            name = "audio.m4a"
        return name
