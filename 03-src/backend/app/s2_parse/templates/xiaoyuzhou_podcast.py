"""Xiaoyuzhou podcast parse template.

raw.raw.raw_text after the parse pre-processing step contains either:
  - Full ASR transcript  (when audio was downloaded and transcribed)
  - Episode description  (fallback when audio URL was unavailable or transcription failed)

Prompts are stored in prompts/xiaoyuzhou_podcast_*.md.
"""

from __future__ import annotations

import logging
from app.s1_ingest.schema import RawCapture
from app.s2_parse.schema import ParsedArticle
from app.s2_parse.templates.base import AbstractTemplate
from app.prompts import load_prompt

logger = logging.getLogger("trove.parse.templates.xiaoyuzhou_podcast")

_TRANSCRIPT_MIN_CHARS = 500


class XiaoyuzhouPodcastTemplate(AbstractTemplate):
    template_id = "xiaoyuzhou_podcast"
    platform = "xiaoyuzhou"
    version = "2.1"

    def build_prompt(self, raw: RawCapture) -> str:
        title = raw.raw.title or ""
        author = raw.raw.author or raw.raw.extra.get("show_name", "")
        raw_text = raw.raw.raw_text or ""
        extra = raw.raw.extra or {}

        duration = extra.get("duration_seconds", 0)
        duration_min = round(duration / 60) if duration else 0
        hosts = extra.get("hosts", [])
        hosts_str = "、".join(hosts) if hosts else author

        # Original shownotes preserved in extra["shownotes"] by _inject_transcript
        shownotes = extra.get("shownotes", "") or ""

        has_transcript = len(raw_text) >= _TRANSCRIPT_MIN_CHARS

        if has_transcript:
            return load_prompt(
                "xiaoyuzhou_podcast_transcript",
                title=title,
                hosts_str=hosts_str,
                duration_min=duration_min,
                shownotes=shownotes[:3000],
                transcript=raw_text[:20000],
                reading_time=max(duration_min, 5),
                word_count=max(len(raw_text), 500),
            )
        else:
            return load_prompt(
                "xiaoyuzhou_podcast_description",
                title=title,
                hosts_str=hosts_str,
                duration_min=duration_min,
                description=raw_text[:6000],
                reading_time=max(duration_min, 5),
                word_count=max(len(raw_text), 200),
            )

    def parse_response(self, llm_output: str) -> ParsedArticle:
        return self.llm_output_to_article(llm_output)
