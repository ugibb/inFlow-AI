"""Adapter registry — maps incoming URLs to the correct platform adapter.

The registry is populated lazily on first access so that adapter imports
(which may have heavy dependencies) are deferred until needed.

Usage:
    from backend.core.ingest.adapters.registry import adapter_registry

    adapter = adapter_registry.resolve(url)
    raw = await adapter.fetch(url, user_id=user_id)

Adding a new adapter:
    1. Implement AbstractAdapter in its own module.
    2. Import it in _build_registry() below.
    3. Add an instance to the adapters list (order = priority).
       The generic adapter must always be last.
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.core.ingest.adapters.base import AbstractAdapter, AdapterError

logger = logging.getLogger("inFlow.ingest.registry")


class AdapterRegistry:
    """Holds all registered adapters and routes URLs to the right one."""

    def __init__(self) -> None:
        self._adapters: list[AbstractAdapter] = []
        self._built = False

    def _build(self) -> None:
        """Import and register all adapters.  Called once on first resolve()."""
        from backend.core.ingest.adapters.wechat import WechatAdapter
        from backend.core.ingest.adapters.bilibili import BilibiliAdapter
        from backend.core.ingest.adapters.xiaoyuzhou import XiaoyuzhouAdapter
        from backend.core.ingest.adapters.xhs import XhsAdapter
        from backend.core.ingest.adapters.douyin import DouyinAdapter
        from backend.core.ingest.adapters.youtube import YoutubeAdapter
        from backend.core.ingest.adapters.toutiao import ToutiaoAdapter
        from backend.core.ingest.adapters.juejin import JuejinAdapter
        from backend.core.ingest.adapters.csdn import CsdnAdapter
        from backend.core.ingest.adapters.feishu import FeishuAdapter
        from backend.core.ingest.adapters.generic import GenericAdapter

        self._adapters = [
            WechatAdapter(),
            BilibiliAdapter(),
            XiaoyuzhouAdapter(),
            XhsAdapter(),
            DouyinAdapter(),
            YoutubeAdapter(),
            ToutiaoAdapter(),
            JuejinAdapter(),
            CsdnAdapter(),
            FeishuAdapter(),
            # GenericAdapter must be last — it accepts any URL.
            GenericAdapter(),
        ]
        self._built = True
        logger.info(
            "Adapter registry built: %d adapters registered",
            len(self._adapters),
        )

    def resolve(self, url: str) -> AbstractAdapter:
        """Return the first adapter that can handle *url*.

        The generic adapter always matches, so this never returns None.
        """
        if not self._built:
            self._build()

        for adapter in self._adapters:
            if adapter.can_handle(url):
                logger.debug(
                    "Resolved %r → %s adapter (v%s)",
                    url[:80],
                    adapter.platform,
                    adapter.version,
                )
                return adapter

        # Should never reach here because GenericAdapter.can_handle() is True
        raise AdapterError(
            "No adapter found for URL (this is a bug — generic adapter should catch all)",
            platform="unknown",
            url=url,
        )

    def resolve_by_platform(self, platform: str) -> Optional[AbstractAdapter]:
        """Return the adapter registered for *platform*, or None."""
        if not self._built:
            self._build()
        for adapter in self._adapters:
            if adapter.platform == platform:
                return adapter
        return None

    def list_platforms(self) -> list[str]:
        """Return platform identifiers for all registered adapters."""
        if not self._built:
            self._build()
        return [a.platform for a in self._adapters]


# Module-level singleton used by all pipeline components.
adapter_registry = AdapterRegistry()
