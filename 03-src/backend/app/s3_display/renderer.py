"""Renderer — converts ParsedContent into an articles DB record.

render_job() is the main entry point:
1. Load ParsedContent from storage.
2. Find or create the Article row (upsert by user_id + url).
3. Populate all fields from ParsedContent.
4. Mark processing_stage = 'ready'.
5. Trigger wiki_indexer to build semantic index.
6. Return the article UUID.
"""

from __future__ import annotations

import json as _json
import logging
import os
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.models.article import Article
from app.s2_parse.schema import ParsedContent
from app.core.shared.storage import default_storage

logger = logging.getLogger("inFlow.display.renderer")


async def render_job(
    db: AsyncSession,
    *,
    job_id: UUID,
    user_id: UUID,
    parsed_file_path: str,
    source_url: str | None = None,
    source_platform: str | None = None,
) -> UUID:
    """Write or update an Article row from a ParsedContent file.

    Args:
        db:                  Active async database session.
        job_id:              UUID of the ingest_job (used for idempotency key).
        user_id:             UUID of the article owner.
        parsed_file_path:    Path to the ParsedContent JSON file.
        source_url:          Original source URL (may be None for uploads).
        source_platform:     Platform identifier (wechat, bilibili, …).

    Returns:
        UUID of the created or updated Article.
    """
    # ── 1. Load ParsedContent ────────────────────────────────────────────
    parsed_data = await default_storage.read_parsed(parsed_file_path)
    parsed = ParsedContent.model_validate(parsed_data)
    art = parsed.article

    logger.debug(
        "Rendering job %s: title=%s, platform=%s",
        job_id,
        art.title[:60],
        source_platform,
    )

    # ── 2. Resolve Article — prefer the stub created at job creation time ──
    article = None

    # New jobs always have article_id pre-set; use that.
    from app.core.models.ingest_job import IngestJob
    job = await db.get(IngestJob, job_id)
    if job and job.article_id:
        article = await db.get(Article, job.article_id)

    # Fallback for legacy jobs (article_id was None before this architecture change).
    if article is None and source_url:
        result = await db.execute(
            select(Article).where(
                Article.user_id == user_id,
                Article.url == source_url,
            )
        )
        article = result.scalar_one_or_none()

    if article is None:
        article = Article(user_id=user_id)
        db.add(article)

    # ── 3. Populate fields ───────────────────────────────────────────────
    article.title = art.title or "Untitled"
    article.url = source_url
    article.source_platform = source_platform
    article.author = art.author or None

    ingest_raw = _read_ingest_fields(parsed.raw_file)
    article.raw_content = ingest_raw.get("raw_text") or None
    article.cover_image = article.cover_image or ingest_raw.get("cover_image") or None
    if ingest_raw.get("content_type"):
        article.content_type = ingest_raw["content_type"]
    article.clean_content = art.clean_content or None
    article.plain_text = _strip_markdown(art.clean_content) if art.clean_content else None
    article.summary = art.summary or None
    article.key_points = art.key_points or []

    article.reading_time = art.reading_time or 0
    article.word_count = art.word_count or 0
    article.chapters = [c.model_dump() for c in art.chapters] if art.chapters else None

    article.processing_stage = "ready"
    article.processing_error = None
    article.fetch_status = "completed"

    # ── 4. Flush to get article.id ────────────────────────────────────────
    await db.flush()
    article_id = article.id

    # ── 5. Auto-save AI-extracted tags ───────────────────────────────────
    if art.tags:
        from app.core.models.article import Tag, article_tags as article_tags_table  # noqa: PLC0415
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        for raw_name in art.tags[:10]:
            tag_name = raw_name.strip()[:100]
            if not tag_name:
                continue
            tag_result = await db.execute(select(Tag).where(Tag.name == tag_name))
            tag = tag_result.scalar_one_or_none()
            if tag is None:
                tag = Tag(name=tag_name, is_ai_generated=True, user_id=user_id)
                db.add(tag)
                await db.flush()
            await db.execute(
                pg_insert(article_tags_table)
                .values(article_id=article_id, tag_id=tag.id)
                .on_conflict_do_nothing()
            )

    await db.commit()

    logger.debug(
        "Render complete: article_id=%s, title=%s",
        article_id,
        art.title[:60],
    )
    return article_id
    # Note: semantic index (wiki_indexer) is called by the pipeline steps layer
    # (core/pipeline/steps.py run_index) after render_job() returns.


def _read_ingest_fields(raw_file_path: str) -> dict:
    """Read raw section fields from the ingest JSON file.

    Returns a dict with 'raw_text', 'cover_image', and 'content_type' keys.
    Returns an empty dict on any error.
    """
    if not raw_file_path or not os.path.exists(raw_file_path):
        return {}
    try:
        with open(raw_file_path, encoding="utf-8") as f:
            data = _json.load(f)
        raw = data.get("raw", {})
        return {
            "raw_text": raw.get("raw_text") or None,
            "cover_image": raw.get("cover_image") or None,
            "content_type": raw.get("content_type") or None,
        }
    except Exception:
        return {}


def _strip_markdown(md: str) -> str:
    """Rough Markdown → plain text conversion for plain_text field.

    Removes headers (#), bold/italic (**/*), links, code fences, and
    horizontal rules.  Not perfect — good enough for keyword search.
    """
    import re
    text = re.sub(r"```.*?```", "", md, flags=re.DOTALL)    # code blocks
    text = re.sub(r"`[^`]+`", "", text)                      # inline code
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)              # images
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)    # links → text
    text = re.sub(r"#+\s*", "", text)                        # headers
    text = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", text)  # bold/italic
    text = re.sub(r"^[-*]{3,}$", "", text, flags=re.MULTILINE)  # HR
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)  # bullets
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
