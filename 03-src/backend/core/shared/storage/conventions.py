"""Path conventions for the local storage layout.

All pipeline components must derive file paths through these helpers so that
naming stays consistent across steps.

Directory structure under DATA_ROOT:

    data/
    ├── 00_staging/
    │   └── {job_id}/
    │       └── {filename}               ← upload/paste 分流暂存（云端收件，worker 拉取）
    │
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
    │               ├── {job_id}_asr_verbose.json
    │               └── {job_id}_tingwu.json   ← 听悟原始转写 JSON（ASR_PROVIDER=tingwu）
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
    """Replace the step directory segment in *path* (handles both / and os.sep).

    两种匹配形态（优先级从高到低）：
    1. 步骤段为路径**末段**——新布局标准形态：``{platform}/{date}-{folder}/01_ingest``
       （调用方传入 dirname(raw)，步骤段无尾随分隔符）；
    2. 步骤段居中（``/{step}/``）——旧布局防御 + 标题段含步骤字面量时
       rfind 只替换最后一次出现，不误伤前缀。
    """
    for sep in ("/", os.sep):
        suffix = f"{sep}{from_step}"
        if path.endswith(suffix):
            return path[: -len(from_step)] + to_step
        needle = f"{sep}{from_step}{sep}"
        idx = path.rfind(needle)
        if idx != -1:
            return path[:idx] + f"{sep}{to_step}{sep}" + path[idx + len(needle):]
    return path


# ── 00_staging ────────────────────────────────────────────────────────────


def staging_file_path(data_root: str, job_id: UUID, filename: str) -> str:
    """云端收件暂存路径（upload/paste 全量分流）。

    云端把上传文件/粘贴正文落盘到 ``data/00_staging/{job_id}/`` 并登记到
    ``ingest_jobs.staging_file_path``；worker 认领后经 SFTP 拉取完成 capture。

    Example: data/00_staging/{uuid}/notes.md
    """
    stem, ext = os.path.splitext(filename)
    safe = _sanitize(stem) or "file"
    return os.path.join(data_root, "00_staging", str(job_id), f"{safe}{ext.lower()}")


def ext_staging_file_rel(staging_path: str) -> str:
    """worker SFTP 拉取暂存文件用的云端侧路径（相对 $INFLOW_PIPELINE_DATA_DIR）。

    镜像 ``ext_display_card_png_rel``：剥掉 ``data/`` 前缀。若云端 DATA_ROOT 为
    绝对路径（生产直跑形态），登记值本就是云端绝对路径，原样返回——由 worker
    侧按「/ 开头=云端绝对路径，否则拼 SFTP 根」归一。

    Example: 00_staging/{uuid}/notes.md
    """
    return staging_path.removeprefix("data/")


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


def parse_tingwu_json_path(raw_file_path: str, job_id: UUID) -> str:
    """Raw Tingwu API transcription JSON (offline task result)."""
    folder = _swap_step(os.path.dirname(raw_file_path), "01_ingest", "02_parse")
    return os.path.join(folder, f"{job_id}_tingwu.json")


def parse_chunks_path(raw_file_path: str, job_id: UUID) -> str:
    """Semantic index offline mirror."""
    folder = _swap_step(os.path.dirname(raw_file_path), "01_ingest", "02_parse")
    return os.path.join(folder, f"{job_id}_chunks.json")


def display_card_html_path(raw_file_path: str, job_id: UUID) -> str:
    return display_file_path(raw_file_path, f"{job_id}.html")


def display_card_png_path(raw_file_path: str, job_id: UUID) -> str:
    return display_file_path(raw_file_path, f"{job_id}.png")


def ext_display_card_png_rel(raw_file_path: str, job_id: UUID) -> str:
    """本地 worker 回传 PNG 的云端相对路径（相对 $INFLOW_PIPELINE_DATA_DIR）。

    与 bot 读取路径同源：``display_card_png_path`` 得到 ``data/03_display/...``，
    剥掉 ``data/`` 前缀后在云端拼 ``{INFLOW_PIPELINE_DATA_DIR}/{rel}``。

    Example: 03_display/xiaoyuzhou/20260621/001-title/{uuid}.png
    """
    return display_card_png_path(raw_file_path, job_id).removeprefix("data/")


def card_png_candidates(
    raw_file_path: str, job_id: UUID, pipeline_data_dir: str = ""
) -> list[str]:
    """卡片 PNG 在云端的候选路径（兼容新旧管线的 raw_file_path 登记形态）。

    - 云端绝对形态（旧云端管线，登记 ``/www/.../01_ingest/...``）：
      换段路径即真实位置，首个候选直接命中
    - worker 相对形态（本地 worker 登记 ``04-output/01_ingest/...``，
      或云端 ``data/01_ingest/...``）：剥掉本地 data_root 前缀后拼
      ``{pipeline_data_dir}`` —— worker 的 SFTP 回传落盘根（SFTP_PIPELINE_DIR
      须与云端 INFLOW_PIPELINE_DATA_DIR 指向同一目录）

    调用方按序 stat，取第一个存在且非空的候选。
    """
    direct = display_card_png_path(raw_file_path, job_id)
    candidates = [direct]
    rel = direct.removeprefix("data/").removeprefix("04-output/")
    if pipeline_data_dir and rel != direct:
        candidates.append(f"{pipeline_data_dir.rstrip('/')}/{rel}")
    return candidates


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
