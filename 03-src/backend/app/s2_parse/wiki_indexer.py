"""Wiki indexer — builds semantic embeddings and knowledge graph edges.

Called after the parse step completes for an article.  Runs two operations:

1. Embedding:    Generate a 512-dim vector for the article (title + summary +
                 first 2000 chars of clean content) and write it to
                 articles.embedding.

2. Knowledge edges: Find the top-5 semantically similar articles already in
                    the user's library and create knowledge_edges rows where
                    cosine distance is below the threshold.

Both operations are idempotent (safe to re-run) and non-blocking (errors are
logged but do not fail the pipeline).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.article import Article, KnowledgeEdge

logger = logging.getLogger("trove.parse.wiki_indexer")

# Cosine distance threshold below which we create a knowledge edge.
# pgvector <=> operator: 0 = identical, 2 = maximally dissimilar.
SIMILARITY_THRESHOLD = 0.45
MAX_EDGES_PER_ARTICLE = 5


async def build_index(
    db: AsyncSession,
    *,
    article_id: UUID,
    user_id: UUID,
    asr_txt_path: str | None = None,
) -> None:
    """Generate embedding and knowledge edges for *article_id*.

    Args:
        db:          Active async database session.
        article_id:  UUID of the newly created article.
        user_id:     UUID of the article owner (for scoping similarity search).
    """
    article = await db.get(Article, article_id)
    if article is None:
        logger.warning("wiki_indexer: article %s not found, skipping", article_id)
        return

    # ── 1. Generate and store embedding ──────────────────────────────────
    await _ensure_embedding(db, article, asr_txt_path=asr_txt_path)

    # ── 2. Build knowledge edges ──────────────────────────────────────────
    if article.embedding is not None:
        await _build_knowledge_edges(db, article=article, user_id=user_id)

    await db.commit()
    logger.debug("wiki_indexer: index built for article %s", article_id)


def _rel_path(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(path).replace("\\", "/")


async def build_index_with_path(
    db: AsyncSession,
    *,
    job_id: UUID,
    article_id: UUID,
    user_id: UUID,
    parsed_file_path: str,
    asr_txt_path: str | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> str | None:
    """Build semantic index and write chunks file to data/02_parse/.

    Calls build_index() for DB embedding + knowledge edges, then writes
    a {job_id}_chunks.json file alongside the parsed file for offline use.

    Returns the chunks file path, or None if writing fails.
    """
    await build_index(db, article_id=article_id, user_id=user_id, asr_txt_path=asr_txt_path)

    # Write chunks file alongside the parsed file in data/02_parse/
    try:
        import json as _json
        from pathlib import Path

        article = await db.get(Article, article_id)
        if article is None:
            return None

        parsed_dir = Path(parsed_file_path).parent
        chunks_path = parsed_dir / f"{job_id}_chunks.json"

        chunks_data = {
            "article_id": str(article_id),
            "job_id": str(job_id),
            "chunks": [
                {
                    "chunk_id": 0,
                    "text": _resolve_index_text(article, asr_txt_path),
                    "embedding": article.embedding if article.embedding is not None else None,
                }
            ],
        }

        chunks_path.write_text(
            _json.dumps(chunks_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.debug("wiki_indexer: chunks file written to %s", chunks_path)
        if progress_cb:
            embed_note = (
                "有向量"
                if article.embedding is not None
                else "无向量（本地 embedding 不可用，已跳过）"
            )
            progress_cb(
                f"构建语义索引完成： {embed_note}"
            )
        return str(chunks_path)

    except Exception as exc:
        logger.error("wiki_indexer: failed to write chunks file for job %s: %s", job_id, exc)
        if progress_cb:
            progress_cb(f"语义索引失败：{exc}")
        return None


async def _ensure_embedding(
    db: AsyncSession,
    article: Article,
    *,
    asr_txt_path: str | None = None,
) -> None:
    """Generate and persist the article embedding if not already present.

    Routes to the API provider (Siliconflow etc.) when configured, falls back
    to the local fastembed model otherwise.
    """
    if article.embedding is not None:
        return  # Already indexed; idempotent skip.

    try:
        from app.core.config_manager import get_embedding_config
        from app.core.shared.ai_service import generate_local_embedding, AIService

        text = _resolve_index_text(article, asr_txt_path)
        cfg = get_embedding_config()
        provider = cfg.get("provider", "local")

        if provider == "local":
            embedding = await _run_in_executor(generate_local_embedding, text)
        else:
            embedding = await AIService().get_embedding(text)

        article.embedding = embedding
        logger.debug(
            "wiki_indexer: generated embedding for article %s via %s (%d dims)",
            article.id,
            provider,
            len(embedding),
        )
    except Exception as exc:
        logger.debug(
            "wiki_indexer: embedding skipped for article %s: %s",
            article.id,
            exc,
        )


async def _build_knowledge_edges(
    db: AsyncSession,
    *,
    article: Article,
    user_id: UUID,
) -> None:
    """Find similar articles and create knowledge_edges rows."""
    emb_str = "[" + ",".join(str(v) for v in article.embedding) + "]"

    sim_sql = sql_text(f"""
        SELECT id, (embedding <=> '{emb_str}'::vector) AS distance
        FROM   articles
        WHERE  embedding IS NOT NULL
          AND  user_id   = :uid
          AND  id        != :aid
        ORDER  BY embedding <=> '{emb_str}'::vector
        LIMIT  :limit
    """)

    result = await db.execute(
        sim_sql,
        {"uid": user_id, "aid": article.id, "limit": MAX_EDGES_PER_ARTICLE},
    )
    rows = result.fetchall()

    edges_created = 0
    for row in rows:
        sibling_id, distance = row
        if float(distance) >= SIMILARITY_THRESHOLD:
            break  # rows are ordered by distance; no closer siblings remain

        # Avoid duplicate edges (check both directions).
        existing = await db.execute(
            select(KnowledgeEdge).where(
                (
                    (KnowledgeEdge.source_article_id == article.id)
                    & (KnowledgeEdge.target_article_id == sibling_id)
                )
                | (
                    (KnowledgeEdge.source_article_id == sibling_id)
                    & (KnowledgeEdge.target_article_id == article.id)
                )
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue

        edge = KnowledgeEdge(
            source_article_id=article.id,
            target_article_id=sibling_id,
            relation_type="related",
            weight=round(1.0 - float(distance), 4),
            user_id=user_id,
        )
        db.add(edge)
        edges_created += 1

    if edges_created:
        logger.info(
            "wiki_indexer: created %d knowledge edge(s) for article %s",
            edges_created,
            article.id,
        )


def _build_embedding_input(article: Article) -> str:
    """Build the text string used as input to the embedding model."""
    parts = [
        article.title or "",
        article.summary or "",
        (article.clean_content or article.plain_text or "")[:2000],
    ]
    return ". ".join(p for p in parts if p)


def _resolve_index_text(article: Article, asr_txt_path: str | None) -> str:
    """Prefer normalized/transcript plain text for semantic index (§10)."""
    if asr_txt_path:
        p = Path(asr_txt_path)
        if p.is_file() and p.stat().st_size > 0:
            return p.read_text(encoding="utf-8")[:8000]
    return _build_embedding_input(article)


async def _run_in_executor(fn, *args):
    """Run a synchronous function in a thread pool to avoid blocking the event loop."""
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)
