"""Template registry — maps platform/template IDs to AbstractTemplate instances.

Usage:
    from app.s2_parse.templates.registry import template_registry

    template = template_registry.resolve("wechat_article")
    parsed = template.parse_response(llm_output)

Adding a new template:
    1. Implement AbstractTemplate in its own module.
    2. Import and register an instance in _build() below.
    3. The generic template is the fallback and must always be last.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.s2_parse.templates.base import AbstractTemplate

logger = logging.getLogger("inFlow.parse.templates.registry")


class TemplateRegistry:
    """Holds all registered parse templates."""

    def __init__(self) -> None:
        self._templates: dict[str, AbstractTemplate] = {}
        self._built = False

    def _build(self) -> None:
        """Import and register all templates.  Called once on first access."""
        from app.s2_parse.templates.wechat_article import WechatArticleTemplate
        from app.s2_parse.templates.bilibili_video import BilibiliVideoTemplate
        from app.s2_parse.templates.xiaoyuzhou_podcast import XiaoyuzhouPodcastTemplate
        from app.s2_parse.templates.xhs_note import XhsNoteTemplate
        from app.s2_parse.templates.document import DocumentTemplate
        from app.s2_parse.templates.generic import GenericTemplate

        instances: list[AbstractTemplate] = [
            WechatArticleTemplate(),
            BilibiliVideoTemplate(),
            XiaoyuzhouPodcastTemplate(),
            XhsNoteTemplate(),
            DocumentTemplate(),
            GenericTemplate(),
        ]

        for t in instances:
            self._templates[t.template_id] = t
            logger.debug("Registered parse template: %s (v%s)", t.template_id, t.version)

        self._built = True
        logger.debug(
            "Template registry built: %d templates registered",
            len(self._templates),
        )

    def resolve(self, template_id: str) -> AbstractTemplate:
        """Return the template for *template_id*, falling back to generic."""
        if not self._built:
            self._build()

        if template_id in self._templates:
            return self._templates[template_id]

        logger.warning(
            "No template found for %r, falling back to generic", template_id
        )
        return self._templates["generic"]

    def list_template_ids(self) -> list[str]:
        """Return all registered template IDs."""
        if not self._built:
            self._build()
        return list(self._templates.keys())


# Module-level singleton.
template_registry = TemplateRegistry()
