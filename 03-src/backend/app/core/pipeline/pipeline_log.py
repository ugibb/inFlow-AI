"""Structured pipeline phase logging for ingest jobs.

Unified line format::
    2026-06-28 19:48:33 | INFO | pipeline | │ 01-采集 | job=eec9650a | ▶ 任务开始：... | ...
    2026-06-28 19:48:33 | INFO | pipeline | │ 00-发起 | job=eec9650a | method=URL | url=...
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from app.core.utils.logger import get_logger

logger = get_logger("pipeline")

# 按内容类型区分步骤：(日志标签, 任务开始名) — 与 PipelineBar 细步一致
# 任务开始日志：▶ 任务开始：{任务名}
_AUDIO_PHASES: dict[str, tuple[str, str]] = {
    "capturing": ("01-采集", "原始信息采集，xxx.json + 音频文件"),
    "transcribing": ("02-转录", "音频 ASR 转录（Groq Whisper），音频文件 --> _asr_verbose.json + _asr.json + _asr.txt"),
    "chapters": ("03-章节", "章节生成，_asr_verbose.json --> _chapters.json"),
    "parsing": ("04-解析", "AI 内容解析，_asr.txt --> xxx.json"),
    "composing": ("05-卡片", "精华卡片合成，_asr.json --> html + png"),
    "indexing": ("06-索引", "语义索引构建，_asr.txt --> _chunks.json"),
    "wechat_push": ("07-推送", "微信Bot精华卡PNG推送"),
}

_ARTICLE_PHASES: dict[str, tuple[str, str]] = {
    "capturing": ("01-采集", "原始信息采集，xxx.json"),
    "normalizing": ("02-提取", "提取正文文本，_asr.txt --> _asr.txt"),
    "chapters": ("03-章节", "章节生成，_asr.txt --> _chapters.json"),
    "parsing": ("04-解析", "AI 内容解析，_asr.txt --> xxx.json"),
    "composing": ("05-卡片", "精华卡片合成，_asr.json --> html + png"),
    "indexing": ("06-索引", "语义索引构建，_asr.txt --> _chunks.json"),
    "wechat_push": ("07-推送", "微信Bot精华卡PNG推送"),
}

_VIDEO_PHASES: dict[str, tuple[str, str]] = {
    "capturing": ("01-采集", "原始信息采集，xxx.json + 视频文件"),
    "preprocessing": ("02-抽离", "音视频抽离，视频文件 --> 音频文件 + 视频截图"),
    "transcribing": ("03-转录", "音频 ASR 转录（Groq Whisper），音频文件 --> _asr_verbose.json + _asr.json + _asr.txt"),
    "chapters": ("04-章节", "章节生成，_asr_verbose.json --> _chapters.json"),
    "parsing": ("05-解析", "AI 内容解析，_asr.txt --> xxx.json"),
    "composing": ("06-卡片", "精华卡片合成，_asr.json --> html + png"),
    "indexing": ("07-索引", "语义索引构建，_asr.txt --> _chunks.json"),
    "wechat_push": ("08-推送", "微信Bot精华卡PNG推送"),
}

_PHASES_BY_TYPE: dict[str, dict[str, tuple[str, str]]] = {
    "audio": _AUDIO_PHASES,
    "video": _VIDEO_PHASES,
    "article": _ARTICLE_PHASES,
}

METHOD_ZH: dict[str, str] = {
    "url": "URL",
    "upload": "上传",
    "paste": "粘贴",
}

# 源 URL 只在 00-发起 行输出，后续阶段不再重复
_PHASE_SUPPRESS_KEYS = frozenset({"url"})


def short_job_id(job_id: UUID | str) -> str:
    return str(job_id).split("-")[0]


def sanitize_log_text(text: Any) -> str:
    """Avoid embedded ' | ' breaking the unified log layout."""
    return str(text).replace(" | ", " / ").replace("\n", " ").strip()


def _phase_table(content_type: str) -> dict[str, tuple[str, str]]:
    return _PHASES_BY_TYPE.get(content_type) or _ARTICLE_PHASES


def resolve_phase_label(phase: str, content_type: str = "article") -> str:
    """Map internal phase key → numbered Chinese label for logs."""
    entry = _phase_table(content_type).get(phase)
    return entry[0] if entry else phase


def resolve_phase_task_name(phase: str, content_type: str = "article") -> str:
    """Map internal phase key → human-readable task name for start logs."""
    entry = _phase_table(content_type).get(phase)
    return entry[1] if entry else phase


def log_job_event(
    job_id: UUID | str,
    label: str,
    *segments: str,
) -> None:
    """One-off pipeline-style line (e.g. wechat push, task queued)."""
    tail = " | ".join(sanitize_log_text(s) for s in segments if s)
    logger.info(f"│ {label} | job={short_job_id(job_id)} | {tail}")


def log_wechat_url_submitted(
    job_id: UUID | str,
    *,
    ok: bool,
    api_status: str = "",
    callback_status: str = "",
) -> None:
    """WeChat bot: URL submitted + push callback registered (one line)."""
    segments = [f"ok={ok}"]
    if api_status:
        segments.append(f"status={sanitize_log_text(api_status)}")
    if callback_status:
        segments.append(f"callback={sanitize_log_text(callback_status)}")
    # log_job_event(job_id, "Bot-入链", *segments)


def log_task_start(
    *,
    job_id: UUID,
    article_id: UUID,
    method: str,
    platform: str,
    url: str | None = None,
    **context: Any,
) -> None:
    """Distinctive line when a new ingest task is queued (before 01-采集)."""
    method_label = METHOD_ZH.get(method, method)
    parts = [
        f"job={short_job_id(job_id)}",
        # f"article={short_job_id(article_id)}",
        f"method={method_label}",
        # f"platform={sanitize_log_text(platform)}",
    ]
    if url:
        parts.append(f"url={sanitize_log_text(url)}")
    parts.extend(
        f"{key}={sanitize_log_text(value)}"
        for key, value in context.items()
        if key not in _PHASE_SUPPRESS_KEYS and value is not None and value != ""
    )
    logger.info(f"│ 00-发起 | {' | '.join(parts)}")


class PhaseLogger:
    """One pipeline stage: start → detail* → end / fail."""

    def __init__(
        self,
        job_id: UUID,
        phase: str,
        content_type: str = "article",
    ) -> None:
        self.job_id = job_id
        self.phase = phase
        self.content_type = content_type
        self.label = resolve_phase_label(phase, content_type)
        self.task_name = resolve_phase_task_name(phase, content_type)
        self._t0 = time.monotonic()
        self._started = False

    def _line(self, *segments: str) -> str:
        tail = " | ".join(s for s in segments if s)
        return f"│ {self.label} | job={short_job_id(self.job_id)} | {tail}"

    def start(self, **_details: Any) -> None:
        self._started = True
        segments = [f"▶ 任务开始：{self.task_name}"]
        for key, value in _details.items():
            if value is not None and value != "":
                segments.append(f"{key}={sanitize_log_text(value)}")
        logger.info(self._line(*segments))

    def detail(self, message: str) -> None:
        logger.info(self._line(sanitize_log_text(message)))

    def end(self, **_details: Any) -> None:
        elapsed = time.monotonic() - self._t0
        segments = ["■ 任务完成", f"{elapsed:.1f}s, {self.task_name}"]
        for key, value in _details.items():
            if value is not None and value != "":
                segments.append(f"{key}={sanitize_log_text(value)}")
        logger.info(self._line(*segments))

    def skip(self, reason: str) -> None:
        """Non-fatal skip (e.g. optional chapters)."""
        logger.info(self._line("○ 任务跳过", sanitize_log_text(reason)))

    def fail(self, error: str) -> None:
        elapsed = time.monotonic() - self._t0
        logger.error(self._line("✗ 任务失败", f"{elapsed:.1f}s", sanitize_log_text(error)))
