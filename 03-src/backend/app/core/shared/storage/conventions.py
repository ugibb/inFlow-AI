"""Path conventions for the local storage layout.

All pipeline components must derive file paths through these helpers so that
naming stays consistent across steps.

Directory structure under DATA_ROOT:

    data/
    ├── 01_ingest/
    │   └── {platform}/
    │       └── {YYYYMMDD}/
    │           └── {index:03d}-{title_20}/   ← one folder per article
    │               ├── {job_id}.json          ← RawCapture
    │               └── {job_id}.m4a           ← downloaded audio/video (if any)
    │
    ├── 02_parse/
    │   └── {platform}/
    │       └── {YYYYMMDD}/
    │           └── {index:03d}-{title_20}/   ← same folder name as 01_ingest
    │               ├── {job_id}.json          ← ParsedContent
    │               ├── {job_id}_asr.txt       ← ASR transcript plain text (if any)
    │               ├── {job_id}_asr.json      ← ASR compact JSON
    │               └── {job_id}_asr_verbose.json
    │
    └── 03_display/
        └── {platform}/
            └── {YYYYMMDD}/
                └── {index:03d}-{title_20}/
                    └── ...                    ← generated files (png, html, etc.)

Key design:
- 01_ingest folder name is the single source of truth.
- 02_parse and 03_display derive their paths by replacing the step prefix
  in raw_file_path — no extra state needed.
- All files for one article live flat in the article folder with no
  sub-directories, making the data directory human-browsable.
"""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime, timezone
from uuid import UUID

_UNSAFE = re.compile(r'[/\\:*?"<>|]')


def _sanitize(title: str) -> str:
    """Normalize title for folder names: punctuation/symbols → ``_``, max 20 chars."""
    cleaned = _UNSAFE.sub("_", title).strip()
    parts: list[str] = []
    for ch in cleaned:
        cat = unicodedata.category(ch)
        if ch.isspace() or cat.startswith(("P", "S")):
            parts.append("_")
        else:
            parts.append(ch)
    cleaned = re.sub(r"_+", "_", "".join(parts)).strip("_")
    return cleaned[:20]


def _today() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y%m%d")


def _swap_step(path: str, from_step: str, to_step: str) -> str:
    """Replace the step directory segment in *path* (handles both / and os.sep)."""
    return path.replace(f"/{from_step}/", f"/{to_step}/").replace(
        f"{os.sep}{from_step}{os.sep}", f"{os.sep}{to_step}{os.sep}"
    )


# ── 01_ingest ─────────────────────────────────────────────────────────────


def article_folder_name(
    data_root: str,
    platform: str,
    title: str,
    datestamp: str | None = None,
) -> str:
    """Return a new '001-title' folder name, auto-incrementing the index.

    The index counts existing article folders for the given platform + date
    inside 01_ingest/ so each new article gets the next sequential number.

    Example: '001-Vol_121_硅谷AI大转弯_软件正在死'
    """
    date = datestamp or _today()
    base = os.path.join(data_root, "01_ingest", platform, date)
    idx = 1
    if os.path.isdir(base):
        existing = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))]
        idx = len(existing) + 1
    return f"{idx:03d}-{_sanitize(title)}"


def ingest_json_path(
    data_root: str,
    platform: str,
    folder_name: str,
    job_id: UUID,
    datestamp: str | None = None,
) -> str:
    """RawCapture JSON path.

    Example: data/01_ingest/wechat/20260618/001-AI的边界与人类创造力/{uuid}.json
    """
    date = datestamp or _today()
    return os.path.join(data_root, "01_ingest", platform, date, folder_name, f"{job_id}.json")


def ingest_media_path(raw_file_path: str, job_id: UUID, ext: str = ".m4a") -> str:
    """Downloaded audio/video path — same folder as RawCapture JSON.

    Example: data/01_ingest/xiaoyuzhou/20260621/001-title/{uuid}.m4a
    """
    if not ext.startswith("."):
        ext = f".{ext}"
    return os.path.join(os.path.dirname(raw_file_path), f"{job_id}{ext}")


# ── 02_parse ──────────────────────────────────────────────────────────────


def parse_json_path(raw_file_path: str, job_id: UUID) -> str:
    """ParsedContent JSON path — mirrors 01_ingest folder, swaps step prefix.

    Example: data/02_parse/wechat/20260618/001-title/{uuid}.json
    """
    folder = _swap_step(os.path.dirname(raw_file_path), "01_ingest", "02_parse")
    return os.path.join(folder, f"{job_id}.json")


def parse_chapters_path(raw_file_path: str, job_id: UUID) -> str:
    """Path for the LLM-generated chapters JSON file.

    Example: data/02_parse/xiaoyuzhou/20260621/001-title/{uuid}_chapters.json
    """
    folder = _swap_step(os.path.dirname(raw_file_path), "01_ingest", "02_parse")
    return os.path.join(folder, f"{job_id}_chapters.json")


def parse_asr_txt_path(raw_file_path: str, job_id: UUID) -> str:
    """Plain-text transcript / normalized article body path."""
    folder = _swap_step(os.path.dirname(raw_file_path), "01_ingest", "02_parse")
    return os.path.join(folder, f"{job_id}_asr.txt")


def parse_asr_verbose_path(raw_file_path: str, job_id: UUID) -> str:
    """Verbose ASR JSON with timestamped segments."""
    base = parse_transcript_base(raw_file_path, job_id)
    stem = os.path.splitext(os.path.basename(base))[0]
    folder = os.path.dirname(base)
    return os.path.join(folder, f"{stem}_verbose.json")


def parse_chunks_path(raw_file_path: str, job_id: UUID) -> str:
    """Semantic index offline mirror."""
    folder = _swap_step(os.path.dirname(raw_file_path), "01_ingest", "02_parse")
    return os.path.join(folder, f"{job_id}_chunks.json")


def display_card_html_path(raw_file_path: str, job_id: UUID) -> str:
    return display_file_path(raw_file_path, f"{job_id}.html")


def display_card_png_path(raw_file_path: str, job_id: UUID) -> str:
    return display_file_path(raw_file_path, f"{job_id}.png")


def parse_transcript_base(raw_file_path: str, job_id: UUID) -> str:
    """Base path for ASR transcript files (WhisperTranscriber appends suffixes).

    WhisperTranscriber saves three files from this base:
        {job_id}_asr.txt           ← plain transcript
        {job_id}_asr.json          ← compact JSON  (this IS the returned path)
        {job_id}_asr_verbose.json  ← Groq verbose_json with segments

    Example: data/02_parse/xiaoyuzhou/20260621/001-title/{uuid}_asr.json
    """
    folder = _swap_step(os.path.dirname(raw_file_path), "01_ingest", "02_parse")
    return os.path.join(folder, f"{job_id}_asr.json")


# ── 03_display ────────────────────────────────────────────────────────────


def display_file_path(raw_file_path: str, filename: str) -> str:
    """Path for a display-step output file (png, html, etc.).

    Example: data/03_display/wechat/20260618/001-title/mindmap.png
    """
    folder = _swap_step(os.path.dirname(raw_file_path), "01_ingest", "03_display")
    return os.path.join(folder, filename)
