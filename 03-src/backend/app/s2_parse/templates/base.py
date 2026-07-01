"""AbstractTemplate — interface contract for all parse templates.

A template encapsulates the LLM prompt strategy for one platform or content
type.  It takes a RawCapture and produces a ParsedArticle.

Implementing a new template:
1. Subclass AbstractTemplate.
2. Set template_id, platform, version.
3. Implement build_prompt() and parse_response().
4. Register an instance in templates/registry.py.
"""

from __future__ import annotations

import abc
import json
import logging
import re
from typing import Optional

from app.s1_ingest.schema import RawCapture
from app.s2_parse.schema import Chapter, ParsedArticle

logger = logging.getLogger("trove.parse.templates.base")


class AbstractTemplate(abc.ABC):
    """Base class for all parse templates."""

    #: Unique template identifier.  Must match what Adapter.get_parse_template_id() returns.
    template_id: str

    #: Human-readable platform name.
    platform: str

    #: Template version string.  Increment when the prompt changes significantly.
    version: str = "1.0"

    @abc.abstractmethod
    def build_prompt(self, raw: RawCapture) -> str:
        """Build the full LLM prompt for parsing *raw*.

        The prompt should instruct the LLM to output a strict JSON object
        conforming to the ParsedArticle schema.  Include schema fields as a
        reference in the prompt to reduce hallucination.
        """

    @abc.abstractmethod
    def parse_response(self, llm_output: str) -> ParsedArticle:
        """Parse the raw LLM output string into a ParsedArticle.

        Implementations should be robust to:
        - Extra text before/after the JSON block.
        - Missing optional fields.
        - Minor JSON formatting errors (use robust_json_parse from ai_service).
        """

    # ------------------------------------------------------------------ #
    # Shared helpers available to all templates                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def extract_json_block(text: str) -> Optional[str]:
        """Find and return the first ```json ... ``` block, or the raw text."""
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            return m.group(1)
        # No fenced block — look for any leading/trailing JSON object.
        m2 = re.search(r"\{.*\}", text, re.DOTALL)
        if m2:
            return m2.group(0)
        return None

    @staticmethod
    def safe_parse_json(text: str) -> dict:
        """Try strict JSON, then json_repair, then return empty dict."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        try:
            from json_repair import repair_json
            return json.loads(repair_json(text, return_objects=False))
        except Exception:
            pass
        return {}

    def llm_output_to_article(self, llm_output: str) -> ParsedArticle:
        """Common implementation: extract JSON block, parse, map to ParsedArticle."""
        raw_json = self.extract_json_block(llm_output) or llm_output
        data = self.safe_parse_json(raw_json)

        if not data:
            logger.warning(
                "Template %s: JSON parse failed, returning minimal article",
                self.template_id,
            )
            return ParsedArticle(
                title="(解析失败)",
                clean_content=llm_output[:5000],
            )

        chapters: list[Chapter] = []
        for c in data.get("chapters") or []:
            if isinstance(c, dict) and c.get("title"):
                chapters.append(Chapter(
                    start_min=int(c.get("start_min", 0)),
                    title=str(c.get("title", "")),
                    description=str(c.get("description", "")),
                ))

        return ParsedArticle(
            title=str(data.get("title", "")),
            summary=str(data.get("summary", "")),
            key_points=list(data.get("key_points", [])),
            tags=list(data.get("tags", [])),
            author=str(data.get("author", "")),
            clean_content=str(data.get("clean_content", "")),
            reading_time=int(data.get("reading_time", 0)),
            word_count=int(data.get("word_count", 0)),
            chapters=chapters,
        )
