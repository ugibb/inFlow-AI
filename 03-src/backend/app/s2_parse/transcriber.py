"""Transcriber — standalone audio download + ASR step.

transcribe_job() is called by the pipeline as a separate step before parse_job()
for audio content.  It downloads the audio file and runs Whisper/Groq ASR,
writing the verbose JSON transcript alongside the raw capture file.

Returns the path to the _asr_verbose.json file, which parse_job() then uses
to inject the transcript text (skipping re-transcription).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable, Coroutine, Optional
from urllib.parse import urlparse
from uuid import UUID

from app.s1_ingest.schema import RawCapture
from app.core.pipeline.pipeline_log import PhaseLogger
from app.core.shared.storage import default_storage
from app.core.shared.storage.conventions import ingest_media_path, parse_transcript_base

logger = logging.getLogger("trove.parse.transcriber")


async def transcribe_job(
    *,
    job_id: UUID,
    raw_file_path: str,
    phase: PhaseLogger | None = None,
    emit_log: Optional[Callable[[str], Coroutine]] = None,
) -> str:
    """Download audio and run ASR for a given ingest job."""
    raw_data = await default_storage.read_raw(raw_file_path)
    raw = RawCapture.model_validate(raw_data)

    if not raw.raw.media_urls:
        raise ValueError(f"No media_urls found in raw capture for job {job_id}")

    audio_url = raw.raw.media_urls[0]
    ext = _ext_from_url(audio_url)
    audio_dest = Path(ingest_media_path(raw_file_path, job_id, ext))
    transcript_base = Path(parse_transcript_base(raw_file_path, job_id))
    verbose_path = transcript_base.parent / (transcript_base.stem + "_verbose.json")

    transcriber = _build_transcriber()
    from app.s2_parse.audio.service import TranscriptionService

    sf_service = TranscriptionService()
    size_mb = audio_dest.stat().st_size / 1024 / 1024 if audio_dest.is_file() else 0.0
    if sf_service.has_siliconflow:
        backend_label = "硅基流动 SenseVoice（国内）→ Groq / 本地 Whisper 备选"
    else:
        backend_label = transcriber.backend_label()
    if phase:
        phase.start(backend=backend_label)

    if audio_dest.is_file() and audio_dest.stat().st_size > 0:
        audio_path = audio_dest
        size_mb = audio_path.stat().st_size / 1024 / 1024
        # if phase:
        #     phase.detail(f"音频已缓存 {size_mb:.1f} MB，跳过下载")
    else:
        if phase:
            phase.detail("下载音频")
        logger.debug("Downloading audio for job %s: %s", job_id, audio_url[:100])
        from app.s2_parse.audio.downloader import AudioDownloader
        downloader = AudioDownloader()
        audio_path = await downloader.download(
            audio_url,
            dest_dir=audio_dest.parent,
            filename=audio_dest.name,
        )
        size_mb = audio_path.stat().st_size / 1024 / 1024
        if phase:
            phase.detail(f"音频下载完成 {size_mb:.1f} MB")

    loop = asyncio.get_running_loop()

    def _emit_sync(msg: str) -> None:
        if phase:
            phase.detail(msg)
        if emit_log is not None:
            asyncio.run_coroutine_threadsafe(emit_log(msg), loop)

    if sf_service.has_siliconflow:
        sf_text = await sf_service.transcribe_file(audio_path, progress_cb=_emit_sync)
        if sf_text:
            _save_plain_transcript(sf_text, transcript_base, language="zh")
            if phase:
                phase.end(lang="zh", audio=f"{size_mb:.1f}MB")
            return str(verbose_path)
        _emit_sync("硅基流动转录失败，回退 Groq / 本地 Whisper")

    result = await loop.run_in_executor(
        None,
        lambda: transcriber.transcribe(
            audio_path,
            json_save_path=transcript_base,
            emit_log=_emit_sync,
        ),
    )

    if phase:
        phase.end(
            lang=result.language,
            audio=f"{size_mb:.1f}MB",
            # chars=len(result.text),
        )

    return str(verbose_path)


def _build_transcriber():
    """Instantiate WhisperTranscriber from Settings."""
    from app.core.config import get_settings
    from app.s2_parse.audio.transcriber import WhisperTranscriber

    s = get_settings()
    return WhisperTranscriber(
        model_name=s.whisper_model,
        checkpoint_path=s.whisper_model_path or None,
        groq_api_key=s.groq_api_key or None,
    )


def _ext_from_url(url: str) -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    return suffix if suffix in {".mp3", ".m4a", ".ogg", ".flac", ".wav", ".aac"} else ".mp3"


def _save_plain_transcript(text: str, transcript_base: Path, *, language: str = "zh") -> None:
    """Write _asr.txt / _asr.json / _asr_verbose.json from plain transcript text."""
    from app.s2_parse.audio.transcriber import _save_response_files

    _save_response_files(
        {
            "text": text,
            "language": language,
            "task": "transcribe",
            "duration": None,
            "segments": [],
        },
        transcript_base,
    )
