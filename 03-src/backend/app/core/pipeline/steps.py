"""Shared pipeline step runners.

Each function handles one pipeline step for any content type.  The orchestrator
calls these in sequence according to content_type routing.  Steps are reused
by the retry path (resume_job) with already-computed file paths.
"""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.article import Article
from app.core.pipeline.pipeline_log import PhaseLogger, short_job_id
from app.core.pipeline.state_machine import transition
from app.core.shared.storage import default_storage
from app.core.shared.storage.conventions import (
    display_card_html_path,
    display_card_png_path,
    parse_asr_txt_path,
)

logger = logging.getLogger("trove.pipeline.steps")


async def _notify_wechat_callback(
    db: AsyncSession,
    *,
    job_id: UUID,
) -> None:
    """Flip any pending WeChat callback for this job to 'ready' (log on bot push)."""
    try:
        from sqlalchemy import text as _text
        result = await db.execute(
            _text(
                "UPDATE wechat_callback_queue "
                "SET status = 'ready' "
                "WHERE job_id = :job_id AND status = 'pending'"
            ),
            {"job_id": str(job_id)},
        )
        await db.commit()
    except Exception as exc:
        logger.warning("wechat callback notify skipped for job %s: %s", job_id, exc)


def _extract_plain_text(raw_data: dict) -> str:
    """Extract plain text from RawCapture dict for normalization."""
    raw = raw_data.get("raw") or {}
    text = (raw.get("raw_text") or "").strip()
    if text and len(text) > 100:
        return text

    html = (raw.get("raw_html") or raw.get("raw_content") or "").strip()
    if not html:
        return text

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "nav", "footer", "iframe", "noscript"]):
        tag.decompose()
    extracted = soup.get_text(separator="\n", strip=True)
    return extracted or text


async def run_normalize_text(
    db: AsyncSession,
    *,
    job_id: UUID,
    raw_file_path: str,
    content_type: str = "article",
) -> str | None:
    """图文 text normalization — writes 02_parse/{job_id}_asr.txt only."""
    phase = PhaseLogger(job_id, "normalizing", content_type=content_type)
    txt_path = parse_asr_txt_path(raw_file_path, job_id)
    try:
        if Path(txt_path).is_file() and Path(txt_path).stat().st_size > 0:
            from app.core.models.ingest_job import IngestJob
            job = await db.get(IngestJob, job_id)
            if job and job.status == "captured":
                await transition(
                    db, job_id=job_id, current_status="captured", target_status="normalizing",
                )
                await transition(
                    db, job_id=job_id, current_status="normalizing", target_status="normalized",
                )
            phase.skip(f"复用已有文本 {Path(txt_path).name}")
            return txt_path

        await transition(
            db,
            job_id=job_id,
            current_status="captured",
            target_status="normalizing",
        )
        phase.start()

        raw_data = await default_storage.read_raw(raw_file_path)
        plain = _extract_plain_text(raw_data)
        if not plain:
            raise ValueError("无法从 RawCapture 提取正文")

        out = Path(txt_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(plain, encoding="utf-8")
        phase.detail(f"正文已写入 {out.name}")

        await transition(
            db,
            job_id=job_id,
            current_status="normalizing",
            target_status="normalized",
        )
        phase.end(chars=len(plain), file=out.name)
        return txt_path

    except Exception as exc:
        phase.fail(str(exc)[:200])
        logger.error("Normalize step failed: job=%s error=%s", job_id, exc)
        try:
            await transition(
                db,
                job_id=job_id,
                current_status="normalizing",
                target_status="failed",
                error_stage="normalizing",
                error_message=str(exc)[:500],
            )
        except Exception:
            pass
        return None


async def run_transcribe(
    db: AsyncSession,
    *,
    job_id: UUID,
    raw_file_path: str,
    content_type: str = "audio",
) -> str | None:
    """ASR transcription step (音频 path)."""
    phase = PhaseLogger(job_id, "transcribing", content_type=content_type)
    try:
        await transition(
            db,
            job_id=job_id,
            current_status="captured",
            target_status="transcribing",
        )

        from app.s2_parse.transcriber import transcribe_job
        from app.core.models.ingest_job import append_step_log

        async def _emit_log(msg: str) -> None:
            await append_step_log(job_id=job_id, step="transcribing", msg=msg)

        asr_path = await transcribe_job(
            job_id=job_id,
            raw_file_path=raw_file_path,
            phase=phase,
            emit_log=_emit_log,
        )

        await transition(
            db,
            job_id=job_id,
            current_status="transcribing",
            target_status="transcribed",
            asr_file_path=asr_path,
        )
        return asr_path

    except Exception as exc:
        phase.fail(str(exc)[:200])
        logger.error("Transcribe step failed: job=%s error=%s", job_id, exc)
        try:
            await transition(
                db,
                job_id=job_id,
                current_status="transcribing",
                target_status="failed",
                error_stage="transcribing",
                error_message=str(exc)[:500],
            )
        except Exception:
            pass
        return None


async def run_chapters(
    db: AsyncSession,
    *,
    job_id: UUID,
    raw_file_path: str,
    current_status: str,
    content_type: str = "article",
) -> str | None:
    """Chapter LLM step — non-fatal if skipped."""
    from app.s1_ingest.schema import RawCapture
    from app.s2_parse.chapter_runner import generate_chapters

    phase = PhaseLogger(job_id, "chapters", content_type=content_type)
    try:
        if current_status != "parsing":
            await transition(
                db,
                job_id=job_id,
                current_status=current_status,
                target_status="parsing",
            )

        phase.start()
        raw_data = await default_storage.read_raw(raw_file_path)
        raw = RawCapture.model_validate(raw_data)

        path = await generate_chapters(
            raw=raw,
            job_id=job_id,
            raw_file_path=raw_file_path,
            progress_cb=phase.detail,
        )
        if path:
            from pathlib import Path as _Path
            phase.end(file=_Path(path).name)
        else:
            phase.skip("无可用转写输入")
        return path
    except Exception as exc:
        phase.skip(str(exc)[:120])
        logger.warning("Chapters step non-fatal failure: job=%s error=%s", job_id, exc)
        return None


async def run_parse(
    db: AsyncSession,
    *,
    job_id: UUID,
    raw_file_path: str,
    asr_file_path: str | None = None,
    current_status: str = "captured",
    content_type: str = "article",
) -> str | None:
    """AI parse step (all content types)."""
    phase = PhaseLogger(job_id, "parsing", content_type=content_type)
    try:
        if current_status != "parsing":
            await transition(
                db,
                job_id=job_id,
                current_status=current_status,
                target_status="parsing",
            )

        from app.s2_parse.parser import parse_job

        raw_data = await default_storage.read_raw(raw_file_path)
        title = (raw_data.get("raw") or {}).get("title") or ""
        platform = (raw_data.get("meta") or {}).get("source_platform") or ""
        phase.start(platform=platform, title=title[:40])

        parsed_path = await parse_job(
            job_id=job_id,
            raw_file_path=raw_file_path,
            asr_file_path=asr_file_path,
            skip_chapters=True,
            progress_cb=phase.detail,
        )

        await transition(
            db,
            job_id=job_id,
            current_status="parsing",
            target_status="parsed",
            parsed_file_path=parsed_path,
        )

        parsed_data = await default_storage.read_parsed(parsed_path)
        ai_title = (parsed_data.get("article") or {}).get("title") or title
        phase.end(title=(ai_title or "")[:40])
        return parsed_path

    except Exception as exc:
        phase.fail(str(exc)[:200])
        logger.error("Parse step failed: job=%s error=%s", job_id, exc)
        try:
            await transition(
                db,
                job_id=job_id,
                current_status="parsing",
                target_status="failed",
                error_stage="parsing",
                error_message=str(exc)[:500],
            )
        except Exception:
            pass
        return None


async def run_compose_card(
    db: AsyncSession,
    *,
    job_id: UUID,
    raw_file_path: str,
    parsed_file_path: str,
    asr_file_path: str | None = None,
    source_platform: str | None = None,
    content_type: str = "article",
) -> tuple[str, str] | None:
    """Generate card HTML + PNG (blocks ready per §12.2)."""
    phase = PhaseLogger(job_id, "composing", content_type=content_type)
    html_path = display_card_html_path(raw_file_path, job_id)
    png_path = display_card_png_path(raw_file_path, job_id)
    try:
        await transition(
            db,
            job_id=job_id,
            current_status="parsed",
            target_status="composing",
        )

        from app.s4_compose.card_renderer import render_card_png_for_job

        phase.start(platform=source_platform or "")
        result_png = await render_card_png_for_job(
            str(job_id),
            asr_file_path=asr_file_path,
            parsed_file_path=parsed_file_path,
            source_platform=source_platform,
            progress_cb=phase.detail,
        )

        await transition(
            db,
            job_id=job_id,
            current_status="composing",
            target_status="composed",
        )
        phase.end(png=Path(result_png).name)
        return html_path, result_png

    except Exception as exc:
        phase.fail(str(exc)[:200])
        logger.error("Compose step failed: job=%s error=%s", job_id, exc)
        try:
            await transition(
                db,
                job_id=job_id,
                current_status="composing",
                target_status="failed",
                error_stage="composing",
                error_message=str(exc)[:500],
            )
        except Exception:
            pass
        return None


async def run_index(
    db: AsyncSession,
    *,
    job_id: UUID,
    article_id: UUID,
    user_id: UUID,
    parsed_file_path: str,
    raw_file_path: str,
    source_url: str | None,
    source_platform: str | None,
    content_type: str = "article",
) -> str | None:
    """Semantic index step + article rendering."""
    phase = PhaseLogger(job_id, "indexing", content_type=content_type)
    try:
        await transition(
            db,
            job_id=job_id,
            current_status="composed",
            target_status="indexing",
        )

        phase.start(platform=source_platform or "")

        from app.s3_display.renderer import render_job
        rendered_article_id = await render_job(
            db,
            job_id=job_id,
            user_id=user_id,
            parsed_file_path=parsed_file_path,
            source_url=source_url,
            source_platform=source_platform,
        )

        article = await db.get(Article, rendered_article_id)
        if article:
            phase.detail(
                f"渲染文章入库完成：{(article.title or '')[:30]}"
                # f" | article={short_job_id(rendered_article_id)}"
            )

        index_path: str | None = None
        try:
            from app.s2_parse.wiki_indexer import build_index_with_path
            asr_txt = parse_asr_txt_path(raw_file_path, job_id)
            index_path = await build_index_with_path(
                db,
                job_id=job_id,
                article_id=article_id,
                user_id=user_id,
                parsed_file_path=parsed_file_path,
                asr_txt_path=asr_txt if Path(asr_txt).is_file() else None,
                progress_cb=phase.detail,
            )
        except Exception as exc:
            logger.error(
                "Semantic index failed for job %s (non-fatal): %s", job_id, exc
            )

        await transition(
            db,
            job_id=job_id,
            current_status="indexing",
            target_status="ready",
            index_file_path=index_path,
            article_id=article_id,
        )

        await _notify_wechat_callback(db, job_id=job_id)

        phase.end(status="ready", article=short_job_id(article_id))
        return index_path

    except Exception as exc:
        phase.fail(str(exc)[:200])
        logger.error("Index step failed: job=%s error=%s", job_id, exc)
        try:
            await transition(
                db,
                job_id=job_id,
                current_status="indexing",
                target_status="failed",
                error_stage="indexing",
                error_message=str(exc)[:500],
            )
        except Exception:
            pass
        return None
