"""Compute fine-grained pipeline step states for PipelineBar (file-driven + job.status)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from app.core.models.ingest_job import IngestJob
from app.core.shared.storage.conventions import (
    display_card_html_path,
    display_card_png_path,
    ingest_media_path,
    parse_asr_txt_path,
    parse_asr_verbose_path,
    parse_chapters_path,
    parse_chunks_path,
    parse_json_path,
    parse_transcript_base,
)

StepState = Literal["pending", "active", "done", "failed"]

_AUDIO_EXTS = {".mp3", ".m4a", ".ogg", ".flac", ".wav", ".aac"}
_VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi"}

# 外部 worker job 的步骤完成判定：按状态排名（云端看不到本地文件，_step_done 全 False）。
# 状态 → 数值排名，单调递增；数值越大表示 pipeline 走得越深。
_EXT_RANK = {
    "pending": 0, "capturing": 1, "captured": 2,
    "normalizing": 3, "normalized": 4,
    "transcribing": 3, "transcribed": 4,
    "parsing": 5, "parsed": 6,
    "composing": 7, "composed": 8,
    "indexing": 9, "ready": 10,
    "failed": 0, "cancelled": 0,
}
# 每个步骤完成所需的排名阈值（rank >= 阈值 → done）
_EXT_STEP_DONE_RANK = {
    "capture": 2, "media_download": 2, "video_download": 2,
    "normalize": 4, "transcribe": 4,
    # chapters 在 parsing 开始即视为完成（rank 5），否则 parsing 期间
    # "章节解析"显示 active 而真正在跑的 "AI 解析"却显示 pending。
    "chapters": 5, "parse": 6,
    "compose_html": 8, "compose_png": 8,
    "index": 10,
}


def _ext_step_done(spec_id: str, status: str) -> bool:
    """外部 worker job 的步骤是否完成（按状态排名，不查本地文件）。"""
    if spec_id == "done":
        return False
    threshold = _EXT_STEP_DONE_RANK.get(spec_id, 99)
    return _EXT_RANK.get(status, 0) >= threshold


@dataclass(frozen=True)
class StepSpec:
    id: str
    label: str
    short_label: str
    retry_from: str
    artifact_path: str | None
    extra_done_check: str | None = None
    active_statuses: frozenset[str] = frozenset()
    error_keys: frozenset[str] = frozenset()


def _file_ok(path: str | None) -> bool:
    if not path:
        return False
    p = Path(path)
    return p.is_file() and p.stat().st_size > 0


def _ingest_media_path(raw_file_path: str, job_id: UUID) -> str | None:
    folder = Path(raw_file_path).parent
    for p in sorted(folder.iterdir()):
        if not p.is_file() or p.suffix.lower() == ".json":
            continue
        if p.name.startswith(f"{job_id}.") and p.suffix.lower() in _AUDIO_EXTS | _VIDEO_EXTS:
            return str(p)
    return None


def _transcribe_done(raw_file_path: str, job_id: UUID) -> bool:
    txt = parse_asr_txt_path(raw_file_path, job_id)
    asr_json = parse_transcript_base(raw_file_path, job_id)
    verbose = parse_asr_verbose_path(raw_file_path, job_id)
    return _file_ok(txt) and _file_ok(asr_json) and _file_ok(verbose)


def _video_screenshot_done(raw_file_path: str, job_id: UUID) -> bool:
    display_dir = Path(display_card_html_path(raw_file_path, job_id)).parent
    if not display_dir.is_dir():
        return False
    pattern = re.compile(rf"^{re.escape(str(job_id))}_(\d{{3}})\.png$")
    indices = sorted(
        int(m.group(1))
        for p in display_dir.iterdir()
        if p.is_file() and (m := pattern.match(p.name))
    )
    if not indices or indices[0] != 1:
        return False
    for i, idx in enumerate(indices, start=1):
        if idx != i:
            return False
    return True


def _build_specs(content_type: str, raw_file_path: str, job_id: UUID) -> list[StepSpec]:
    jid = job_id
    if content_type == "audio":
        media = _ingest_media_path(raw_file_path, jid) or ingest_media_path(raw_file_path, jid, ".m4a")
        return [
            StepSpec("capture", "资源下载", "资源", "capturing", raw_file_path,
                     active_statuses=frozenset({"pending", "capturing"}),
                     error_keys=frozenset({"capturing"})),
            StepSpec("media_download", "音频下载", "音频", "capturing", media,
                     active_statuses=frozenset({"capturing"}),
                     error_keys=frozenset({"capturing"})),
            StepSpec("transcribe", "转录", "转录", "transcribing", parse_asr_verbose_path(raw_file_path, jid),
                     extra_done_check="transcribe_triplet",
                     active_statuses=frozenset({"transcribing"}),
                     error_keys=frozenset({"transcribing"})),
            StepSpec("chapters", "章节解析", "章节", "parsing", parse_chapters_path(raw_file_path, jid),
                     active_statuses=frozenset({"parsing"}),
                     error_keys=frozenset({"chapters", "parsing"})),
            StepSpec("parse", "AI 解析", "解析", "parsing", parse_json_path(raw_file_path, jid),
                     active_statuses=frozenset({"parsing"}),
                     error_keys=frozenset({"parsing"})),
            StepSpec("compose_html", "生成卡片", "卡片", "composing", display_card_html_path(raw_file_path, jid),
                     active_statuses=frozenset({"composing"}),
                     error_keys=frozenset({"composing"})),
            StepSpec("compose_png", "HTML→PNG", "PNG", "composing", display_card_png_path(raw_file_path, jid),
                     active_statuses=frozenset({"composing"}),
                     error_keys=frozenset({"composing"})),
            StepSpec("index", "语义索引", "索引", "indexing", parse_chunks_path(raw_file_path, jid),
                     active_statuses=frozenset({"indexing"}),
                     error_keys=frozenset({"indexing"})),
            StepSpec("done", "完成", "完成", "", None),
        ]

    if content_type == "video":
        media = _ingest_media_path(raw_file_path, jid) or ingest_media_path(raw_file_path, jid, ".mp4")
        audio = _ingest_media_path(raw_file_path, jid)
        return [
            StepSpec("capture", "资源下载", "资源", "capturing", raw_file_path,
                     active_statuses=frozenset({"pending", "capturing"}),
                     error_keys=frozenset({"capturing"})),
            StepSpec("video_download", "视频下载", "视频", "capturing", media,
                     active_statuses=frozenset({"capturing"}),
                     error_keys=frozenset({"capturing"})),
            StepSpec("extract_audio", "抽离音频", "音频", "preprocessing", audio,
                     active_statuses=frozenset({"preprocessing"}),
                     error_keys=frozenset({"preprocessing"})),
            StepSpec("screenshots", "提取截图", "截图", "preprocessing", None,
                     extra_done_check="video_screenshots",
                     active_statuses=frozenset({"preprocessing"}),
                     error_keys=frozenset({"preprocessing"})),
            StepSpec("transcribe", "转录", "转录", "transcribing", parse_asr_verbose_path(raw_file_path, jid),
                     extra_done_check="transcribe_triplet",
                     active_statuses=frozenset({"transcribing"}),
                     error_keys=frozenset({"transcribing"})),
            StepSpec("chapters", "章节解析", "章节", "parsing", parse_chapters_path(raw_file_path, jid),
                     active_statuses=frozenset({"parsing"}),
                     error_keys=frozenset({"chapters", "parsing"})),
            StepSpec("parse", "AI 解析", "解析", "parsing", parse_json_path(raw_file_path, jid),
                     active_statuses=frozenset({"parsing"}),
                     error_keys=frozenset({"parsing"})),
            StepSpec("compose_html", "生成卡片", "卡片", "composing", display_card_html_path(raw_file_path, jid),
                     active_statuses=frozenset({"composing"}),
                     error_keys=frozenset({"composing"})),
            StepSpec("compose_png", "HTML→PNG", "PNG", "composing", display_card_png_path(raw_file_path, jid),
                     active_statuses=frozenset({"composing"}),
                     error_keys=frozenset({"composing"})),
            StepSpec("index", "语义索引", "索引", "indexing", parse_chunks_path(raw_file_path, jid),
                     active_statuses=frozenset({"indexing"}),
                     error_keys=frozenset({"indexing"})),
            StepSpec("done", "完成", "完成", "", None),
        ]

    # article / ebook / report / default
    return [
        StepSpec("capture", "资源下载", "资源", "capturing", raw_file_path,
                 active_statuses=frozenset({"pending", "capturing"}),
                 error_keys=frozenset({"capturing"})),
        StepSpec("normalize", "音频转录", "转录", "normalizing", parse_asr_txt_path(raw_file_path, jid),
                 active_statuses=frozenset({"normalizing"}),
                 error_keys=frozenset({"normalizing"})),
        StepSpec("chapters", "章节解析", "章节", "parsing", parse_chapters_path(raw_file_path, jid),
                 active_statuses=frozenset({"parsing"}),
                 error_keys=frozenset({"chapters", "parsing"})),
        StepSpec("parse", "AI 解析", "解析", "parsing", parse_json_path(raw_file_path, jid),
                 active_statuses=frozenset({"parsing"}),
                 error_keys=frozenset({"parsing"})),
        StepSpec("compose_html", "生成卡片", "卡片", "composing", display_card_html_path(raw_file_path, jid),
                 active_statuses=frozenset({"composing"}),
                 error_keys=frozenset({"composing"})),
        StepSpec("compose_png", "HTML→PNG", "PNG", "composing", display_card_png_path(raw_file_path, jid),
                 active_statuses=frozenset({"composing"}),
                 error_keys=frozenset({"composing"})),
        StepSpec("index", "语义索引", "索引", "indexing", parse_chunks_path(raw_file_path, jid),
                 active_statuses=frozenset({"indexing"}),
                 error_keys=frozenset({"indexing"})),
        StepSpec("done", "完成", "完成", "", None),
    ]


def _step_done(spec: StepSpec, raw_file_path: str, job_id: UUID) -> bool:
    if spec.id == "done":
        return False
    if spec.extra_done_check == "transcribe_triplet":
        return _transcribe_done(raw_file_path, job_id)
    if spec.extra_done_check == "video_screenshots":
        return _video_screenshot_done(raw_file_path, job_id)
    return _file_ok(spec.artifact_path)


def compute_pipeline_steps(
    job: IngestJob,
    *,
    content_type: str,
) -> list[dict]:
    """Return pipeline_steps[] for API responses."""
    if not job.raw_file_path:
        specs = _build_specs(content_type, "", job.id)
        return [
            {
                "id": s.id,
                "label": s.label,
                "short_label": s.short_label,
                "state": "active" if i == 0 and job.status in ("pending", "capturing") else "pending",
                "artifact_path": s.artifact_path,
                "retry_from": s.retry_from or None,
            }
            for i, s in enumerate(specs)
        ]

    raw_file_path = job.raw_file_path
    job_id = job.id
    specs = _build_specs(content_type, raw_file_path, job_id)
    status = job.status
    error_stage = job.error_stage or ""

    # 外部 worker job：云端看不到本地文件，改用状态排名判定各步骤完成度
    done_flags = [
        (_ext_step_done(spec.id, status) if job.external_processing
         else _step_done(spec, raw_file_path, job_id))
        for spec in specs
    ]

    if status == "ready":
        states: list[StepState] = ["done"] * len(specs)
        states[-1] = "done"
        return _pack(specs, states, raw_file_path, job_id)

    if status in ("failed", "cancelled"):
        failed_idx = 0
        for i, spec in enumerate(specs):
            if error_stage in spec.error_keys or error_stage == spec.retry_from:
                failed_idx = i
                break
        else:
            for i, spec in enumerate(specs):
                if not done_flags[i] and spec.id != "done":
                    failed_idx = i
                    break
            else:
                failed_idx = max(0, len(specs) - 2)

        states = []
        for i, spec in enumerate(specs):
            if spec.id == "done":
                states.append("pending")
            elif i < failed_idx:
                states.append("done")
            elif i == failed_idx:
                states.append("failed")
            else:
                states.append("pending")
        return _pack(specs, states, raw_file_path, job_id)
    first_incomplete = next(
        (i for i, s in enumerate(specs) if s.id != "done" and not done_flags[i]),
        len(specs) - 1,
    )

    states = []
    for i, spec in enumerate(specs):
        if spec.id == "done":
            states.append("pending")
        elif done_flags[i]:
            states.append("done")
        elif i == first_incomplete and (
            status in spec.active_statuses
            or (status == "captured" and spec.id in ("media_download", "normalize"))
            or (status == "normalized" and spec.id == "chapters")
            or (status == "transcribed" and spec.id == "chapters")
            or (status == "composed" and spec.id == "index")
        ):
            states.append("active")
        elif i == first_incomplete:
            states.append("active")
        else:
            states.append("pending")

    return _pack(specs, states, raw_file_path, job_id)


def _pack(
    specs: list[StepSpec],
    states: list[StepState],
    raw_file_path: str,
    job_id: UUID,
) -> list[dict]:
    out: list[dict] = []
    for spec, state in zip(specs, states):
        artifact = spec.artifact_path
        if spec.extra_done_check == "transcribe_triplet" and raw_file_path:
            artifact = parse_asr_verbose_path(raw_file_path, job_id)
        out.append({
            "id": spec.id,
            "label": spec.label,
            "short_label": spec.short_label,
            "state": state,
            "artifact_path": artifact,
            "retry_from": spec.retry_from or None,
        })
    return out
