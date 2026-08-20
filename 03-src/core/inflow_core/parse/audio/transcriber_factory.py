"""ASR backend factory — Groq / 听悟 可切换。"""

from __future__ import annotations

from typing import Protocol

from inflow_core.core.config import get_settings
from inflow_core.parse.audio.asr_common import (
    ASR_PROVIDER_GROQ,
    ASR_PROVIDER_TINGWU,
    VALID_ASR_PROVIDERS,
    TranscriptionResult,
)
from inflow_core.parse.audio.transcriber import WhisperTranscriber
from inflow_core.parse.audio.tingwu_transcriber import TingwuTranscriber


class AsrTranscriber(Protocol):
    def backend_label(self) -> str: ...

    def transcribe(self, audio_path, json_save_path=None, emit_log=None) -> TranscriptionResult: ...


def resolve_asr_provider() -> str:
    provider = (get_settings().asr_provider or ASR_PROVIDER_TINGWU).strip().lower()
    if provider not in VALID_ASR_PROVIDERS:
        raise ValueError(
            f"无效的 ASR_PROVIDER={provider!r}，可选：{', '.join(sorted(VALID_ASR_PROVIDERS))}"
        )
    return provider


def build_transcriber() -> AsrTranscriber:
    """根据 ASR_PROVIDER 实例化 Groq 或听悟转写器。"""
    s = get_settings()
    provider = resolve_asr_provider()

    if provider == ASR_PROVIDER_GROQ:
        return WhisperTranscriber(
            model_name=s.whisper_model,
            checkpoint_path=s.whisper_model_path or None,
            groq_api_key=s.groq_api_key or None,
        )

    return TingwuTranscriber(
        app_key=s.tingwu_app_key,
        access_key_id=s.alibaba_cloud_access_key_id,
        access_key_secret=s.alibaba_cloud_access_key_secret,
        oss_bucket=s.tingwu_oss_bucket,
        oss_endpoint=s.tingwu_oss_endpoint,
        source_language=s.tingwu_source_language,
        poll_interval_sec=float(s.tingwu_poll_interval_sec),
        max_wait_sec=float(s.tingwu_max_wait_sec),
    )
