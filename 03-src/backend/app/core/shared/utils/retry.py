"""Async-compatible retry decorator.

Ported from 06-src/utils/retry.py; adapted for asyncio (uses asyncio.sleep
instead of time.sleep so it does not block the event loop).
"""

from __future__ import annotations

import asyncio
import functools
import logging
import re
from collections.abc import Callable
from typing import Tuple, Type, TypeVar

logger = logging.getLogger("inFlow.utils.retry")

T = TypeVar("T")

_PROGRESS_CB_KWARG = "progress_cb"


def format_retry_reason(exc: Exception) -> str:
    """Turn low-level network errors into short Chinese for pipeline logs."""
    text = str(exc).strip()
    if not text:
        return type(exc).__name__

    peer_closed = re.search(
        r"peer closed connection.*?received (\d+) bytes, expected (\d+)",
        text,
        re.IGNORECASE,
    )
    if peer_closed:
        got_mb = int(peer_closed.group(1)) / (1024 * 1024)
        total_mb = int(peer_closed.group(2)) / (1024 * 1024)
        return f"连接中断（已收 {got_mb:.1f}/{total_mb:.1f} MB）"

    incomplete = re.search(r"下载不完整：(\d+)/(\d+) bytes", text)
    if incomplete:
        got_mb = int(incomplete.group(1)) / (1024 * 1024)
        total_mb = int(incomplete.group(2)) / (1024 * 1024)
        return f"下载不完整（{got_mb:.1f}/{total_mb:.1f} MB）"

    if "Connection aborted" in text or "Remote end closed" in text:
        return "API 连接中断"

    if "SDK.HttpError" in text or "HttpError" in type(exc).__name__:
        return "听悟 API 网络异常"

    if len(text) > 100:
        return text[:97] + "…"
    return text


def _emit_retry_log(
    *,
    progress_cb: Callable[[str], None] | None,
    attempt: int,
    max_attempts: int,
    func_name: str,
    exc: Exception,
    delay: float,
) -> None:
    reason = format_retry_reason(exc)
    if progress_cb is not None:
        progress_cb(
            f"网络异常，第 {attempt}/{max_attempts} 次重试（{reason}，{int(delay)}s 后断点续传）"
        )
        logger.debug(
            "%s retry %d/%d: %s",
            func_name,
            attempt,
            max_attempts,
            exc,
        )
        return

    logger.warning(
        "第 %d/%d 次重试 %s：%s",
        attempt,
        max_attempts,
        func_name,
        reason,
    )


def async_retry(
    max_attempts: int = 3,
    delay: float = 3.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """Decorator that retries an async function on specified exceptions.

    If the wrapped call receives ``progress_cb=...`` in kwargs, retry messages
    are routed there (pipeline PhaseLogger) instead of WARNING on utils.retry.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            progress_cb = kwargs.get(_PROGRESS_CB_KWARG)
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        _emit_retry_log(
                            progress_cb=progress_cb,
                            attempt=attempt,
                            max_attempts=max_attempts,
                            func_name=func.__name__,
                            exc=exc,
                            delay=delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        reason = format_retry_reason(exc)
                        if progress_cb is not None:
                            progress_cb(
                                f"下载失败，已重试 {max_attempts} 次（{reason}）"
                            )
                            logger.error(
                                "%s failed after %d attempts: %s",
                                func.__name__,
                                max_attempts,
                                exc,
                            )
                        else:
                            logger.error(
                                "%s 在 %d 次尝试后仍失败：%s",
                                func.__name__,
                                max_attempts,
                                reason,
                            )
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator
