"""Shared ASR types and file output helpers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from inflow_core.core.utils.logger import get_logger

logger = get_logger("parse.transcriber")

ASR_PROVIDER_GROQ = "groq"
ASR_PROVIDER_TINGWU = "tingwu"
VALID_ASR_PROVIDERS = frozenset({ASR_PROVIDER_GROQ, ASR_PROVIDER_TINGWU})


@dataclass
class TranscriptionResult:
    text: str
    language: str


def response_to_dict(response: Any) -> Dict[str, Any]:
    if isinstance(response, dict):
        return response
    try:
        return response.model_dump() if hasattr(response, "model_dump") else dict(vars(response))
    except Exception:
        return {
            "text": getattr(response, "text", ""),
            "language": getattr(response, "language", ""),
            "task": getattr(response, "task", "transcribe"),
            "duration": getattr(response, "duration", None),
            "segments": getattr(response, "segments", []),
        }


def save_asr_response_files(response: Any, base_json_path: Path) -> None:
    """Save ASR response in three formats beside *base_json_path*.

    Outputs:
      {stem}.txt           — plain text
      {stem}.json          — compact JSON
      {stem}_verbose.json  — full verbose JSON with segments
    """
    base_json_path.parent.mkdir(parents=True, exist_ok=True)

    raw = response_to_dict(response)
    text = (raw.get("text") or "").strip()
    language = raw.get("language") or ""

    txt_path = base_json_path.with_suffix(".txt")
    json_path = base_json_path
    verbose_path = base_json_path.parent / (base_json_path.stem + "_verbose.json")

    txt_path.write_text(text, encoding="utf-8")

    simple = {
        "text": text,
        "language": language,
        "task": raw.get("task", "transcribe"),
        "duration": raw.get("duration"),
    }
    json_path.write_text(json.dumps(simple, ensure_ascii=False, indent=2), encoding="utf-8")
    verbose_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.debug("转录响应文件已保存至 %s", base_json_path.parent)
