"""Core parse logic.

parse_job() is the main entry point:
1. Load RawCapture from storage.
2. If content_type == "audio" and media_urls is non-empty:
   a. Download the audio file (AudioDownloader) → data/audio/…
   b. Transcribe (WhisperTranscriber) → data/transcripts/… (.txt/.json/_verbose.json)
   c. Inject transcript text into raw.raw.raw_text so the template sees it.
3. Select the parse template via the registry.
4. Call the LLM (ai_service).
5. Build a ParsedContent object.
6. Write it to storage.
7. Return the path.

The parse orchestrator (orchestrator.py) calls this function and handles
ingest_job state transitions.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from inflow_core.ingest.schema import RawCapture
from inflow_core.parse.schema import ParsedContent, AIMeta
from inflow_core.parse.templates.registry import template_registry
from inflow_core.core.shared.storage import default_storage
from inflow_core.core.shared.storage.conventions import ingest_media_path, parse_transcript_base, parse_chapters_path

logger = logging.getLogger("inFlow.parse.parser")


async def parse_job(
    *,
    job_id: UUID,
    raw_file_path: str,
    asr_file_path: str | None = None,
    skip_chapters: bool = False,
    _t0: float | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> str:
    """Parse a raw capture file and produce a ParsedContent file.

    Args:
        job_id:         UUID of the ingest_jobs row (used as output file ID).
        raw_file_path:  Path to the RawCapture JSON file.
        asr_file_path:  Path to the _asr_verbose.json from a prior transcribe step.
                        If provided, skips download + transcription (file reuse).

    Returns:
        Path to the written ParsedContent JSON file.

    Raises:
        Exception: Any error during LLM call or file I/O (caller must handle).
    """
    t0 = _t0 if _t0 is not None else time.perf_counter()

    # ── 1. Load RawCapture ──────────────────────────────────────────────
    raw_data = await default_storage.read_raw(raw_file_path)
    raw = RawCapture.model_validate(raw_data)

    logger.debug(
        "[parse_job] START | job=%s | platform=%s | title=%s",
        job_id,
        raw.meta.source_platform,
        (raw.raw.title or "")[:60],
    )

    # ── 2. Audio pre-processing (download + transcribe) ─────────────────
    if raw.raw.content_type == "audio" and raw.raw.media_urls:
        if asr_file_path:
            # Transcription already done by the dedicated transcribe step — load from file
            if progress_cb:
                progress_cb(_format_transcript_load_message())
            raw = _inject_transcript_from_file(raw, asr_file_path)
        else:
            # Legacy path: transcription inline (no prior transcribe step)
            verbose_path = _transcript_verbose_path(raw_file_path, job_id)
            if progress_cb:
                progress_cb(_format_transcript_load_message())
            raw = await _preprocess_audio(raw, job_id, raw_file_path)

    # ── 3. Select template ──────────────────────────────────────────────
    template_id = _resolve_template_id(raw)
    template = template_registry.resolve(template_id)
    if progress_cb:
        progress_cb(f"解析模板：{template.template_id} v{template.version}")

    logger.debug("Using template: %s (v%s)", template.template_id, template.version)

    # ── 4a. Chapter generation (optional; skip when run_chapters already ran) ──
    if raw.raw.content_type == "audio" and not skip_chapters:
        await _generate_and_save_chapters(
            raw, job_id, raw_file_path, progress_cb=progress_cb,
        )

    # ── 4b. Main analysis LLM call ──────────────────────────────────────
    analysis_t0 = time.perf_counter()
    prompt = template.build_prompt(raw)
    llm_output, tokens_used, model_name = await _call_llm(prompt, label="主内容")
    if progress_cb:
        progress_cb(
            f"主内容解析完成：{model_name} | {time.perf_counter() - analysis_t0:.1f}s"
            f" | 响应 {len(llm_output)} 字"
        )

    # ── 5. Parse LLM output into ParsedArticle ──────────────────────────
    article = template.parse_response(llm_output)

    if not article.word_count and article.clean_content:
        article = article.model_copy(
            update={"word_count": len(article.clean_content)}
        )
    if not article.reading_time and article.word_count:
        article = article.model_copy(
            update={"reading_time": max(1, article.word_count // 300)}
        )

    # ── 6. Build and persist ParsedContent ──────────────────────────────
    parsed = ParsedContent(
        id=job_id,
        raw_file=raw_file_path,
        template_used=template.template_id,
        article=article,
        ai_meta=AIMeta(
            model=model_name,
            tokens_used=tokens_used,
            template_version=template.version,
        ),
    )

    parsed_path = await default_storage.write_parsed(
        job_id=job_id,
        data=parsed.to_dict(),
        raw_file_path=raw_file_path,
    )

    elapsed = time.perf_counter() - t0
    logger.debug(
        "[parse_job] DONE | job=%s | elapsed=%.1fs | title=%s",
        job_id,
        elapsed,
        article.title[:60],
    )
    return parsed_path


# ------------------------------------------------------------------ #
# Audio pre-processing                                                #
# ------------------------------------------------------------------ #

def _transcript_verbose_path(raw_file_path: str, job_id: UUID) -> Path:
    """Path to _asr_verbose.json beside the parse transcript base."""
    base = Path(parse_transcript_base(raw_file_path, job_id))
    return base.parent / f"{base.stem}_verbose.json"


def _rel_path(path: str | Path) -> str:
    """Path relative to backend cwd for pipeline logs."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(path).replace("\\", "/")


_TRANSCRIPT_LOAD_MSG = "将待解析数据喂给LLM：ASR 转录文本+原始文本内容"


def _format_transcript_load_message() -> str:
    """Pipeline log: LLM input sources (no file paths)."""
    return _TRANSCRIPT_LOAD_MSG


 
async def _preprocess_audio(raw: RawCapture, job_id: UUID, raw_file_path: str) -> RawCapture:
    """Download audio and transcribe; inject transcript into raw.raw.raw_text.

    Files are persisted alongside the RawCapture in 01_ingest/ (audio) and
    02_parse/ (transcript), both derived from raw_file_path.

    Returns a new RawCapture with raw_text set to the transcript.
    """
    from inflow_core.parse.audio.downloader import AudioDownloader
    from inflow_core.parse.audio.transcriber import WhisperTranscriber

    audio_url = raw.raw.media_urls[0]

    # -- Resolve persistent file paths ----------------------------------
    ext = _ext_from_url(audio_url)
    audio_dest = Path(ingest_media_path(raw_file_path, job_id, ext))
    transcript_base = Path(parse_transcript_base(raw_file_path, job_id))

    # -- Step 2: Download audio (cached by file presence) ---------------
    # ASR is always re-run to keep _asr_verbose.json fresh and accurate.
    # Only the audio download is cached — re-downloading 100+ MB every time is wasteful.
    if audio_dest.is_file() and audio_dest.stat().st_size > 0:
        audio_path = audio_dest
        logger.info("Audio cache hit, skipping download: %s", audio_dest.name)
    else:
        logger.info("Downloading audio for job %s: %s", job_id, audio_url[:100])
        downloader = AudioDownloader()
        audio_path = await downloader.download(
            audio_url,
            dest_dir=audio_dest.parent,
            filename=audio_dest.name,
        )

    # -- Step 3: Transcribe (sync, run in thread pool) ------------------
    # Always runs — generates fresh _asr.txt / _asr.json / _asr_verbose.json
    logger.info("Transcribing audio for job %s: %s", job_id, audio_path.name)
    transcriber = _build_transcriber()

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: transcriber.transcribe(audio_path, json_save_path=transcript_base),
        )
        logger.info(
            "Transcription complete: job=%s, lang=%s, chars=%d",
            job_id, result.language, len(result.text),
        )
        return _inject_transcript(raw, result.text)
    except Exception as exc:
        fallback_text = (raw.raw.raw_text or "").strip()
        if fallback_text:
            logger.error(
                "ASR FAILED for job %s — %s: %s — falling back to show notes (%d chars)",
                job_id, type(exc).__name__, exc, len(fallback_text),
            )
            return raw  # raw_text already present — LLM will use it directly
        raise


def _inject_transcript(raw: RawCapture, transcript: str) -> RawCapture:
    """Return a new RawCapture with raw_text replaced by the transcript.
    Preserves original raw_text (shownotes) in extra['shownotes'] for prompt use.
    """
    original_shownotes = (raw.raw.raw_text or "").strip()
    updated_extra = {**(raw.raw.extra or {}), "shownotes": original_shownotes}
    updated_content = raw.raw.model_copy(update={"raw_text": transcript, "extra": updated_extra})
    return raw.model_copy(update={"raw": updated_content})


def _inject_transcript_from_file(raw: RawCapture, asr_verbose_path: str) -> RawCapture:
    """Load transcript text from _asr_verbose.json and inject into RawCapture.

    Used when transcription was done as a prior pipeline step (file reuse path).
    Falls back to existing raw_text if the file is missing or unreadable.
    """
    import json as _json
    try:
        data = _json.loads(Path(asr_verbose_path).read_text(encoding="utf-8"))
        # Groq/Whisper verbose JSON format: {"text": "...", "segments": [...], ...}
        transcript = (data.get("text") or "").strip()
        if transcript:
            return _inject_transcript(raw, transcript)
    except Exception as exc:
        logger.warning(
            "Failed to load asr_verbose from %s: %s — using existing raw_text",
            asr_verbose_path, exc,
        )
    return raw


def _build_transcriber():
    """Instantiate ASR transcriber from Settings (Groq / 听悟)."""
    from inflow_core.parse.audio.transcriber_factory import build_transcriber

    return build_transcriber()


def _ext_from_url(url: str) -> str:
    """Extract file extension from URL path; default to .m4a."""
    path = urlparse(url).path.rstrip("/")
    name = path.split("/")[-1]
    ext = os.path.splitext(name)[1]
    return ext if ext else ".m4a"


# ------------------------------------------------------------------ #
# Template routing                                                    #
# ------------------------------------------------------------------ #

def _resolve_template_id(raw: RawCapture) -> str:
    platform = raw.meta.source_platform

    platform_template_map = {
        "wechat":      "wechat_article",
        "bilibili":    "bilibili_video",
        "xiaoyuzhou":  "xiaoyuzhou_podcast",
        "xhs":         "xhs_note",
        "upload":      "document",
        "generic":     "generic",
        "douyin":      "generic",
        "youtube":     "generic",
        "toutiao":     "generic",
        "juejin":      "generic",
        "csdn":        "generic",
    }

    return platform_template_map.get(platform, "generic")


# ------------------------------------------------------------------ #
# LLM call                                                           #
# ------------------------------------------------------------------ #

async def _call_llm(
    prompt: str,
    max_tokens: int = 4096,
    label: str = "LLM",
    *,
    progress_cb: Callable[[str], None] | None = None,
) -> tuple[str, int, str]:
    try:
        from inflow_core.core.shared.ai_service import llm_service
        from inflow_core.core.config_manager import get_llm_config
        cfg = get_llm_config()
        model_name = cfg.get("model", "deepseek-chat")
        logger.debug(
            "[%s] START | model=%s | prompt=%d chars | max_tokens=%d",
            label, model_name, len(prompt), max_tokens,
        )
        t0 = time.perf_counter()
        text = await llm_service._chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=max_tokens,
        )
        elapsed = time.perf_counter() - t0
        logger.debug(
            "[%s] DONE | elapsed=%.1fs | response=%d chars",
            label, elapsed, len(text),
        )
        if progress_cb:
            progress_cb(
                f"LLM {label}完成：{model_name} | {elapsed:.1f}s | 响应 {len(text)} 字"
            )
        return text, 0, model_name
    except Exception as exc:
        logger.error("[%s] FAILED | %s", label, exc)
        raise


# ------------------------------------------------------------------ #
# Chapter generation (dedicated LLM call for audio)                  #
# ------------------------------------------------------------------ #

def _get_last_transcript_hms(timestamped: str) -> tuple[str, int]:
    """Return (HH:MM:SS string, total_seconds) of the last timestamp in a timestamped transcript."""
    import re
    matches = re.findall(r'\[(\d{2}):(\d{2}):(\d{2})\]', timestamped)
    if not matches:
        return ("00:00:00", 0)
    hh, mm, ss = matches[-1]
    sec = int(hh) * 3600 + int(mm) * 60 + int(ss)
    return (f"{hh}:{mm}:{ss}", sec)


def _build_timestamped_transcript(verbose_path: Path) -> str:
    """Build a transcript with [HH:MM:SS] markers injected every 30 seconds."""
    import json as _json
    try:
        data = _json.loads(verbose_path.read_text(encoding="utf-8"))
        segments = data.get("segments", [])
    except Exception:
        return ""

    lines: list[str] = []
    last_ts_at = -30.0
    for seg in segments:
        start = float(seg.get("start", 0))
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if start - last_ts_at >= 30:
            hh = int(start // 3600)
            mm = int((start % 3600) // 60)
            ss = int(start % 60)
            lines.append(f"\n[{hh:02d}:{mm:02d}:{ss:02d}]")
            last_ts_at = start
        lines.append(text)
    return " ".join(lines).strip()


def _parse_chapters_from_llm(llm_output: str) -> list[dict]:
    """Extract and validate a chapters JSON array from LLM output."""
    import json as _json
    import re
    # Try to find a JSON array in the output
    m = re.search(r"\[.*\]", llm_output, re.DOTALL)
    raw = m.group(0) if m else llm_output
    try:
        items = _json.loads(raw)
    except Exception:
        try:
            from json_repair import repair_json  # type: ignore
            items = _json.loads(repair_json(raw))
        except Exception:
            return []
    if not isinstance(items, list):
        return []
    chapters = []
    for item in items:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        chapters.append({
            "index": int(item.get("index") or len(chapters) + 1),
            "title": str(item.get("title") or "")[:30],
            "start_time": float(item.get("start_time") or 0),
            "end_time": float(item.get("end_time") or 0),
            "summary": str(item.get("summary") or ""),
        })
    return chapters


async def _generate_and_save_chapters(
    raw: RawCapture,
    job_id: UUID,
    raw_file_path: str,
    *,
    progress_cb: Callable[[str], None] | None = None,
) -> None:
    """Run a dedicated LLM call to generate chapters; save to {job_id}_chapters.json."""
    import json as _json

    transcript_base = Path(parse_transcript_base(raw_file_path, job_id))
    verbose_path = transcript_base.parent / (transcript_base.stem + "_verbose.json")
    if not verbose_path.is_file():
        logger.debug("No verbose transcript for job %s — skipping chapter generation", job_id)
        return

    timestamped = _build_timestamped_transcript(verbose_path)
    if not timestamped:
        logger.warning("Empty timestamped transcript for job %s", job_id)
        return

    extra = raw.raw.extra or {}
    title = raw.raw.title or ""
    author = raw.raw.author or extra.get("show_name", "")
    hosts = extra.get("hosts", [])
    hosts_str = "、".join(hosts) if hosts else author
    duration = extra.get("duration_seconds") or 0
    # Fallback: read accurate duration from ASR verbose JSON (Whisper always records it)
    if not duration and verbose_path.is_file():
        try:
            import json as _json_dur
            _vdata = _json_dur.loads(verbose_path.read_text(encoding="utf-8"))
            duration = float(_vdata.get("duration") or 0)
            logger.debug("[chapters] duration fallback from ASR verbose: %.0fs", duration)
        except Exception:
            pass
    duration_min = round(duration / 60) if duration else 0
    # Shownotes stored by _inject_transcript; fall back to current raw_text if not injected yet
    shownotes = extra.get("shownotes") or ""
    target_chapters = max(8, min(20, duration_min // 6))

    logger.debug(
        "[chapters] PREPARE | job=%s | duration=%dmin | target_chapters=%d | transcript=%d chars",
        job_id, duration_min, target_chapters, len(timestamped),
    )

    last_ts_hms, last_ts_sec = _get_last_transcript_hms(timestamped)

    from inflow_core.prompts import load_prompt
    prompt = load_prompt(
        "xiaoyuzhou_chapters",
        title=title,
        hosts_str=hosts_str,
        duration_min=duration_min,
        duration_sec=int(duration),
        last_timestamp_hms=last_ts_hms,
        last_timestamp_sec=last_ts_sec,
        shownotes=shownotes[:3000],
        timestamped_transcript=timestamped,
        target_chapters=target_chapters,
    )

    chapter_t0 = time.perf_counter()
    try:
        llm_output, _, model_name = await _call_llm(
            prompt, max_tokens=12000, label="章节",
        )
        llm_elapsed = time.perf_counter() - chapter_t0
    except Exception as exc:
        logger.warning("[chapters] FAILED for job %s: %s", job_id, exc)
        if progress_cb:
            progress_cb(f"章节生成失败：{exc}")
        return

    chapters = _parse_chapters_from_llm(llm_output)
    if not chapters:
        logger.warning("[chapters] no valid chapters parsed | job=%s", job_id)
        if progress_cb:
            progress_cb("章节生成失败：LLM 输出无法解析")
        return

    chapters_file = Path(parse_chapters_path(raw_file_path, job_id))
    chapters_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "1.0",
        "total_duration": float(duration or 0),
        "chapters": chapters,
    }
    chapters_file.write_text(_json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.debug("Saved %d chapters to %s", len(chapters), chapters_file)
    if progress_cb:
        if len(chapters) == target_chapters:
            chapters_part = f"目标 {target_chapters} 章"
        else:
            chapters_part = f"{len(chapters)} 章（目标 {target_chapters}）"
        progress_cb(
            f"章节生成完成：{chapters_part} | 时长 {duration_min}min"
            f" | {model_name} | {llm_elapsed:.1f}s"
            f" | 响应 {len(llm_output)} 字 | {_rel_path(chapters_file)}"
        )
