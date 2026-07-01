"""Async-compatible retry decorator.

Ported from 06-src/utils/retry.py; adapted for asyncio (uses asyncio.sleep
instead of time.sleep so it does not block the event loop).
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Tuple, Type, TypeVar

logger = logging.getLogger("trove.utils.retry")

T = TypeVar("T")


def async_retry(
    max_attempts: int = 3,
    delay: float = 3.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """Decorator that retries an async function on specified exceptions.

    Args:
        max_attempts: Total attempts including the first try.
        delay:        Seconds to wait between attempts (async sleep).
        exceptions:   Exception types that trigger a retry; others propagate immediately.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        logger.warning(
                            "第 %d 次重试 %s，错误：%s",
                            attempt,
                            func.__name__,
                            exc,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "%s 在 %d 次尝试后仍失败，错误：%s",
                            func.__name__,
                            max_attempts,
                            exc,
                        )
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator
