"""Chapter generation — input priority and transcript formatting (§12.3)."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Callable
from uuid import UUID

from app.core.shared.storage.conventions import (
    parse_asr_txt_path,
    parse_asr_verbose_path,
    parse_chapters_path,
    parse_transcript_base,
)
from app.s1_ingest.schema import RawCapture
from app.s2_parse.parser import (
    _build_timestamped_transcript,
    _call_llm,
    _get_last_transcript_hms,
    _parse_chapters_from_llm,
    _rel_path,
)

logger = logging.getLogger("inFlow.pipeline.chapters")

_SEGMENT_CHARS = 2000


def resolve_chapter_input_path(raw_file_path: str, job_id: UUID) -> Path | None:
    """Return the best available transcript file for chapter LLM."""
    verbose = Path(parse_asr_verbose_path(raw_file_path, job_id))
    if verbose.is_file() and verbose.stat().st_size > 0:
        return verbose
    asr_json = Path(parse_transcript_base(raw_file_path, job_id))
    if asr_json.is_file() and asr_json.stat().st_size > 0:
        return asr_json
    asr_txt = Path(parse_asr_txt_path(raw_file_path, job_id))
    if asr_txt.is_file() and asr_txt.stat().st_size > 0:
        return asr_txt
    return None


def build_chapter_transcript(input_path: Path) -> str:
    """Format transcript for chapter LLM — timestamps or 第n段 labels."""
    name = input_path.name
    if name.endswith("_verbose.json"):
        text = _build_timestamped_transcript(input_path)
        if text:
            return text

    if name.endswith("_asr.json"):
        try:
            data = json.loads(input_path.read_text(encoding="utf-8"))
            body = (data.get("text") or "").strip()
            if body:
                return _segment_plain_text(body)
        except Exception:
            pass

    if name.endswith("_asr.txt"):
        body = input_path.read_text(encoding="utf-8").strip()
        if body:
            return _segment_plain_text(body)

    return ""


def _segment_plain_text(text: str) -> str:
    """Split plain text into 第一段 / 第二段 / … labeled blocks."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]

    segments: list[str] = []
    buf = ""
    for para in paragraphs:
        if len(buf) + len(para) + 1 > _SEGMENT_CHARS and buf:
            segments.append(buf.strip())
            buf = para
        else:
            buf = f"{buf}\n{para}".strip() if buf else para
    if buf.strip():
        segments.append(buf.strip())

    if not segments:
        return text

    labels = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十")
    lines: list[str] = []
    for i, seg in enumerate(segments, start=1):
        if i <= len(labels):
            label = f"第{labels[i - 1]}段"
        else:
            label = f"第{i}段"
        lines.append(f"\n[{label}]\n{seg}")
    return "".join(lines).strip()


async def generate_chapters(
    *,
    raw: RawCapture,
    job_id: UUID,
    raw_file_path: str,
    progress_cb: Callable[[str], None] | None = None,
) -> str | None:
    """Run chapter LLM and write {job_id}_chapters.json. Returns path or None if skipped."""
    input_path = resolve_chapter_input_path(raw_file_path, job_id)
    if input_path is None:
        logger.debug("No chapter input for job %s — skipping", job_id)
        return None

    timestamped = build_chapter_transcript(input_path)
    if not timestamped:
        logger.warning("Empty chapter transcript for job %s", job_id)
        return None

    extra = raw.raw.extra or {}
    title = raw.raw.title or ""
    author = raw.raw.author or extra.get("show_name", "")
    hosts = extra.get("hosts", [])
    hosts_str = "、".join(hosts) if hosts else author
    duration = extra.get("duration_seconds") or 0

    if not duration and input_path.name.endswith("_verbose.json"):
        try:
            _vdata = json.loads(input_path.read_text(encoding="utf-8"))
            duration = float(_vdata.get("duration") or 0)
        except Exception:
            pass

    duration_min = round(duration / 60) if duration else max(1, len(timestamped) // 800)
    shownotes = extra.get("shownotes") or ""
    target_chapters = max(8, min(20, duration_min // 6)) if duration else 8

    last_ts_hms, last_ts_sec = _get_last_transcript_hms(timestamped)

    from app.prompts import load_prompt

    prompt = load_prompt(
        "xiaoyuzhou_chapters",
        title=title,
        hosts_str=hosts_str,
        duration_min=duration_min,
        duration_sec=int(duration or 0),
        last_timestamp_hms=last_ts_hms,
        last_timestamp_sec=last_ts_sec,
        shownotes=shownotes[:3000],
        timestamped_transcript=timestamped,
        target_chapters=target_chapters,
    )

    chapter_t0 = time.perf_counter()
    try:
        llm_output, _, model_name = await _call_llm(prompt, max_tokens=12000, label="章节")
    except Exception as exc:
        logger.warning("[chapters] FAILED for job %s: %s", job_id, exc)
        if progress_cb:
            progress_cb(f"章节生成失败：{exc}")
        return None

    chapters = _parse_chapters_from_llm(llm_output)
    if not chapters:
        logger.warning("[chapters] no valid chapters parsed | job=%s", job_id)
        if progress_cb:
            progress_cb("章节生成失败：LLM 输出无法解析")
        return None

    chapters_file = Path(parse_chapters_path(raw_file_path, job_id))
    chapters_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "1.0",
        "total_duration": float(duration or 0),
        "chapters": chapters,
    }
    chapters_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    llm_elapsed = time.perf_counter() - chapter_t0
    logger.debug("Saved %d chapters to %s", len(chapters), chapters_file)
    if progress_cb:
        progress_cb(
            f"章节 LLM 完成：{len(chapters)} 章 / {model_name} / {llm_elapsed:.1f}s"
        )
    return str(chapters_file)
