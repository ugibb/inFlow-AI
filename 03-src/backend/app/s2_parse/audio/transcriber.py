"""Whisper transcription service.

Ported from 06-src/transcriber/whisper_transcriber.py.
Changes from the original:
  - Removed 06-src utils imports (utils.exceptions / utils.logger).
  - Uses standard logging and plain RuntimeError / ValueError.
  - transcribe() is synchronous (faster-whisper is sync); callers in async
    context should wrap with asyncio.get_event_loop().run_in_executor().
  - _save_response_files() / _merge_groq_responses() preserved verbatim.

Priority:
  1. Groq API  (GROQ_API_KEY set, file ≤ 25 MB — chunked for larger files)
  2. faster-whisper local model  (fallback)
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import av

from app.core.utils.logger import get_logger

logger = get_logger("parse.transcriber")

try:
    from groq import Groq  # type: ignore
    _GROQ_AVAILABLE = True
except ImportError:
    Groq = None  # type: ignore
    _GROQ_AVAILABLE = False

try:
    from faster_whisper import WhisperModel  # type: ignore
    _FASTER_WHISPER_AVAILABLE = True
except ImportError:
    WhisperModel = None  # type: ignore
    _FASTER_WHISPER_AVAILABLE = False

_GROQ_MAX_BYTES = 25 * 1024 * 1024          # 25 MB hard limit per Groq request
_GROQ_MP3_CHUNK_DURATION_SEC = 300           # 5 min per chunk
# Always chunk when audio exceeds one chunk length — gives progress visibility
# and per-segment retry even for small-bitrate files that are under 25 MB.
_GROQ_CHUNK_IF_LONGER_SEC = _GROQ_MP3_CHUNK_DURATION_SEC  # > 5 min → chunk
_GROQ_SEGMENT_MAX_ATTEMPTS = 3
_GROQ_SEGMENT_RETRY_DELAY_SEC = 5.0
_GROQ_HEARTBEAT_INTERVAL_SEC = 60.0
_LOCAL_PROGRESS_INTERVAL_SEC = 15.0
_FFMPEG_CLI_USABLE: Optional[bool] = None


def _is_ffmpeg_cli_usable() -> bool:
    global _FFMPEG_CLI_USABLE
    if _FFMPEG_CLI_USABLE is not None:
        return _FFMPEG_CLI_USABLE
    if not shutil.which("ffmpeg"):
        _FFMPEG_CLI_USABLE = False
        return False
    proc = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10)
    _FFMPEG_CLI_USABLE = proc.returncode == 0
    return _FFMPEG_CLI_USABLE


def _format_segment_label(idx: int, total: int) -> str:
    """e.g. 分段[01/12] — zero-pad width follows total segment count."""
    width = max(2, len(str(total)))
    return f"分段[{idx:0{width}d}/{total:0{width}d}]"


def _start_groq_heartbeat(
    label: str,
    emit_log: Optional[Callable[[str], None]],
    interval: float = _GROQ_HEARTBEAT_INTERVAL_SEC,
) -> tuple[threading.Event, threading.Thread]:
    """Emit periodic logs while a blocking Groq API call is in flight."""
    stop = threading.Event()

    def _loop() -> None:
        waited = 0.0
        while not stop.wait(interval):
            waited += interval
            msg = f"Groq 仍在转录 {label}，已等待 {waited:.0f}s"
            if emit_log:
                emit_log(msg)
            else:
                logger.info(msg)

    thread = threading.Thread(target=_loop, daemon=True, name="groq-heartbeat")
    thread.start()
    return stop, thread


@dataclass
class TranscriptionResult:
    text: str
    language: str


class WhisperTranscriber:
    """Whisper transcription wrapper.

    Priority:
      1. Groq API (groq_api_key set; large files chunked automatically)
      2. faster-whisper local inference (fallback)

    Ported verbatim from 06-src/transcriber/whisper_transcriber.py.
    """

    def __init__(
        self,
        model_name: str = "large-v3",
        checkpoint_path: Optional[str] = None,
        groq_api_key: Optional[str] = None,
    ) -> None:
        self._groq_api_key = groq_api_key or ""
        self._groq_client: Optional["Groq"] = None

        if checkpoint_path and checkpoint_path.strip():
            resolved = Path(checkpoint_path.strip()).expanduser()
            if not resolved.is_absolute():
                resolved = Path.home() / resolved
            self._local_model_path = str(resolved.resolve())
        else:
            self._local_model_path = model_name

        self.model_name = model_name
        self._fw_model: Optional["WhisperModel"] = None
        self._emit_log: Optional[Callable[[str], None]] = None

    def backend_label(self) -> str:
        """Human-readable ASR backend for logs."""
        if self._groq_api_key and _GROQ_AVAILABLE:
            return "Groq Whisper 转录 (whisper-large-v3-turbo)"
        if self._groq_api_key and not _GROQ_AVAILABLE:
            return "faster-whisper 本地（groq 包未安装）"
        return f"faster-whisper 本地 ({self._local_model_path})"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transcribe(
        self,
        audio_path: Path,
        json_save_path: Optional[Path] = None,
        emit_log: Optional[Callable[[str], None]] = None,
    ) -> TranscriptionResult:
        """Transcribe *audio_path*.

        When *json_save_path* is given, Groq verbose_json responses are saved
        as three files beside it: .txt, .json, _verbose.json — mirroring the
        06-src behaviour.

        Raises:
            RuntimeError: No backend available, or model failed to load.
            ValueError: Transcription returned empty text.
        """
        self._emit_log = emit_log
        file_size = audio_path.stat().st_size
        mb = file_size / (1024 * 1024)

        if self._groq_api_key and _GROQ_AVAILABLE:
            duration_sec = self._get_audio_duration_sec(audio_path)
            needs_chunk = file_size > _GROQ_MAX_BYTES or duration_sec > _GROQ_CHUNK_IF_LONGER_SEC

            if not needs_chunk:
                dur_min = duration_sec / 60
                if self._emit_log:
                    self._emit_log(
                        f"单文件直传 Groq Whisper {mb:.1f} MB / {dur_min:.1f} min（≤ 25 MB 且 ≤ 5 min）"
                    )
                last_exc: Optional[Exception] = None
                for attempt in range(1, _GROQ_SEGMENT_MAX_ATTEMPTS + 1):
                    try:
                        return self._transcribe_groq(
                            audio_path,
                            json_save_path=json_save_path,
                            attempt=attempt,
                            max_attempts=_GROQ_SEGMENT_MAX_ATTEMPTS,
                        )
                    except (RuntimeError, ValueError) as exc:
                        last_exc = exc
                        if attempt < _GROQ_SEGMENT_MAX_ATTEMPTS:
                            retry_msg = (
                                f"单文件转录第 {attempt} 次失败，"
                                f"{int(_GROQ_SEGMENT_RETRY_DELAY_SEC)}s 后重试：{exc}"
                            )
                            if self._emit_log:
                                self._emit_log(retry_msg)
                            else:
                                logger.warning(
                                    "单文件转录第 %d 次失败（%s），%ds 后重试",
                                    attempt, exc, int(_GROQ_SEGMENT_RETRY_DELAY_SEC),
                                )
                            time.sleep(_GROQ_SEGMENT_RETRY_DELAY_SEC)
                raise last_exc  # type: ignore[misc]

            dur_min = duration_sec / 60
            reason = f"{mb:.1f} MB > 25 MB" if file_size > _GROQ_MAX_BYTES else f"{dur_min:.1f} min > 5 min"
            if not self._emit_log:
                logger.info(
                    "Groq Whisper 分段转录：%s（%s）",
                    audio_path.name, reason,
                )
            try:
                return self._transcribe_groq_chunked(
                    audio_path,
                    json_save_path=json_save_path,
                    chunk_reason=reason,
                )
            except Exception as exc:
                logger.warning(
                    "文件 %.1f MB，Groq 分段转录失败（%s），回退到本地 faster-whisper", mb, exc
                )
        elif self._groq_api_key and not _GROQ_AVAILABLE:
            logger.warning("已配置 GROQ_API_KEY 但 groq 包未安装，回退到本地 faster-whisper")

        return self._transcribe_local(audio_path, json_save_path=json_save_path)

    # ------------------------------------------------------------------
    # Groq backend  (ported verbatim from 06-src)
    # ------------------------------------------------------------------

    def _transcribe_groq(
        self,
        audio_path: Path,
        json_save_path: Optional[Path] = None,
        segment_idx: Optional[int] = None,
        segment_total: Optional[int] = None,
        collect_response: Optional[List[Any]] = None,
        attempt: int = 1,
        max_attempts: int = 1,
    ) -> TranscriptionResult:
        client = self._get_groq_client()
        size_mb = audio_path.stat().st_size / (1024 * 1024)
        if segment_idx is not None and segment_total is not None:
            label = _format_segment_label(segment_idx, segment_total)
            subject = f"{label} {size_mb:.1f} MB"
        else:
            label = f"单文件 {size_mb:.1f} MB"
            subject = f"{size_mb:.1f} MB"
        started = time.monotonic()

        stop_hb, hb_thread = _start_groq_heartbeat(label, self._emit_log)
        try:
            with open(audio_path, "rb") as f:
                response = client.audio.transcriptions.create(
                    file=(audio_path.name, f.read()),
                    model="whisper-large-v3-turbo",
                    response_format="verbose_json",
                )
            text = (response.text or "").strip()
            language = getattr(response, "language", None) or "unknown"
        except Exception as exc:
            elapsed = time.monotonic() - started
            err_msg = (
                f"Groq ASR 失败：{subject}（{elapsed:.0f}s）"
                f" | {type(exc).__name__}: {exc}"
            )
            if self._emit_log:
                self._emit_log(err_msg)
            logger.error(
                "Groq ASR 失败 [%s] %.1f MB（%.0fs）: %s: %s",
                label, size_mb, elapsed, type(exc).__name__, exc,
            )
            raise RuntimeError(f"Groq 转录失败：{type(exc).__name__}: {exc}") from exc
        finally:
            stop_hb.set()
            hb_thread.join(timeout=1.0)

        if not text:
            raise ValueError("未检测到有效语音内容，请确认音频文件包含人声。")

        if collect_response is not None:
            collect_response.append(response)

        if json_save_path is not None and segment_idx is None:
            _save_response_files(response, json_save_path)

        elapsed = time.monotonic() - started
        seg_count = len(getattr(response, "segments", None) or [])
        attempt_part = f" | 第 {attempt}/{max_attempts} 次" if max_attempts > 1 else ""
        msg = (
            f"ASR 转录完成：{subject}"
            f" | {elapsed:.0f}s{attempt_part}"
            f" | 字数：{len(text)} "
        )
        if self._emit_log:
            self._emit_log(msg)
        else:
            logger.info(msg)
        return TranscriptionResult(text=text, language=language)

    def _get_groq_client(self) -> "Groq":
        if self._groq_client is None:
            # 音频转录通常需要 1-3 分钟；设置宽松超时避免大文件被截断
            self._groq_client = Groq(api_key=self._groq_api_key, timeout=600.0)
        return self._groq_client

    def _transcribe_groq_chunked(
        self,
        audio_path: Path,
        json_save_path: Optional[Path] = None,
        *,
        chunk_reason: str = "",
    ) -> TranscriptionResult:
        size_mb = audio_path.stat().st_size / (1024 * 1024)
        if not self._emit_log:
            logger.debug(
                "文件 %.1f MB，转 MP3 并按 %d 秒/段分段转录",
                size_mb,
                _GROQ_MP3_CHUNK_DURATION_SEC,
            )

        with tempfile.TemporaryDirectory(prefix="trove_chunks_") as tmp:
            split_started = time.monotonic()
            chunk_pairs = self._split_audio_chunks(
                audio_path, _GROQ_MP3_CHUNK_DURATION_SEC, Path(tmp)
            )
            split_elapsed = time.monotonic() - split_started
            texts: List[str] = []
            raw_responses: List[Any] = []
            chunk_offsets: List[float] = []
            language = "unknown"
            total = len(chunk_pairs)
            reason_part = f"（{chunk_reason}）" if chunk_reason else ""
            if self._emit_log:
                self._emit_log(
                    f"Groq 分段转录：{size_mb:.1f} MB{reason_part}"
                    f" | 共 {total} 段 | {_GROQ_MP3_CHUNK_DURATION_SEC}s/段"
                    f" | PyAV： {split_elapsed:.0f}s"
                )

            for idx, (chunk, chunk_start) in enumerate(chunk_pairs, start=1):
                chunk_mb = chunk.stat().st_size / (1024 * 1024)
                if chunk.stat().st_size > _GROQ_MAX_BYTES:
                    raise RuntimeError(
                        f"分段 {chunk.name} 仍超过 Groq 25 MB（{chunk_mb:.1f} MB）。"
                        "请缩短分段时长或改用本地转录。"
                    )
                part = self._transcribe_groq_segment_with_retry(
                    chunk, idx=idx, total=total, chunk_mb=chunk_mb,
                    collect_response=raw_responses,
                )
                texts.append(part.text)
                chunk_offsets.append(chunk_start)
                if idx == 1:
                    language = part.language

        text = " ".join(texts).strip()
        if not text:
            raise ValueError("未检测到有效语音内容，请确认音频文件包含人声。")

        if json_save_path is not None and raw_responses:
            merged = _merge_groq_responses(raw_responses, offsets=chunk_offsets)
            _save_response_files(merged, json_save_path)

        return TranscriptionResult(text=text, language=language)

    def _transcribe_groq_segment_with_retry(
        self,
        chunk: Path,
        idx: int,
        total: int,
        chunk_mb: float,
        collect_response: Optional[List[Any]] = None,
    ) -> TranscriptionResult:
        label = _format_segment_label(idx, total)
        last_exc: Optional[Exception] = None

        for attempt in range(1, _GROQ_SEGMENT_MAX_ATTEMPTS + 1):
            try:
                return self._transcribe_groq(
                    chunk,
                    segment_idx=idx,
                    segment_total=total,
                    collect_response=collect_response,
                    attempt=attempt,
                    max_attempts=_GROQ_SEGMENT_MAX_ATTEMPTS,
                )
            except (RuntimeError, ValueError) as exc:
                last_exc = exc
                if attempt < _GROQ_SEGMENT_MAX_ATTEMPTS:
                    retry_msg = (
                        f"{label} 第 {attempt} 次失败，"
                        f"{int(_GROQ_SEGMENT_RETRY_DELAY_SEC)}s 后重试：{exc}"
                    )
                    if self._emit_log:
                        self._emit_log(retry_msg)
                    else:
                        logger.warning(
                            "%s 第 %d 次失败（%s），%ds 后重试",
                            label, attempt, exc, int(_GROQ_SEGMENT_RETRY_DELAY_SEC),
                        )
                    time.sleep(_GROQ_SEGMENT_RETRY_DELAY_SEC)

        raise last_exc  # type: ignore[misc]

    def _split_audio_chunks(
        self, audio_path: Path, segment_sec: int, tmp_dir: Path
    ) -> List[tuple[Path, float]]:
        """Return (chunk_path, chunk_start_sec) pairs with accurate start times from PyAV."""
        chunks = self._split_audio_pyav(audio_path, segment_sec, tmp_dir)
        if not self._emit_log:
            logger.debug("PyAV 分段完成，共 %d 段", len(chunks))
        return chunks

    def _split_audio_pyav(
        self, audio_path: Path, segment_sec: int, tmp_dir: Path
    ) -> List[tuple[Path, float]]:
        """Convert to mono 16 kHz MP3 chunks via PyAV.

        Returns (chunk_path, chunk_start_sec) — the exact start offset in the
        original audio for each chunk.  Using PyAV frame boundaries rather than
        Groq-reported durations eliminates the cumulative timestamp drift that
        occurs when Groq consistently under-reports chunk duration by ~0.25 s.
        """
        chunks: List[tuple[Path, float]] = []

        with av.open(str(audio_path)) as inp:
            in_stream = inp.streams.audio[0]
            total_duration = self._get_audio_duration_sec(audio_path, in_stream)
            if total_duration <= 0:
                raise RuntimeError("无法获取音频时长，无法分段。")

            start = 0.0
            chunk_idx = 0
            while start < total_duration:
                end = min(start + segment_sec, total_duration)
                chunk_path = tmp_dir / f"chunk_{chunk_idx:03d}.mp3"
                chunk_idx += 1

                # Fresh resampler per chunk — prevents stale buffer leaking across seek boundaries
                resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
                inp.seek(int(start / in_stream.time_base), stream=in_stream)
                with av.open(str(chunk_path), "w", format="mp3") as out:
                    out_stream = out.add_stream("mp3", rate=16000)
                    out_stream.layout = "mono"
                    for frame in inp.decode(audio=0):
                        if frame.time is not None and frame.time < start:
                            continue
                        if frame.time is not None and frame.time >= end:
                            break
                        for resampled in resampler.resample(frame):
                            resampled.pts = None
                            for packet in out_stream.encode(resampled):
                                out.mux(packet)
                    for packet in out_stream.encode(None):
                        out.mux(packet)

                if not chunk_path.is_file() or chunk_path.stat().st_size == 0:
                    raise RuntimeError(f"PyAV 分段失败：{chunk_path.name} 为空。")
                chunks.append((chunk_path, start))  # record exact start offset
                start = end

        if not chunks:
            raise RuntimeError("PyAV 分段后未生成任何音频片段。")
        return chunks

    def _get_audio_duration_sec(self, audio_path: Path, in_stream=None) -> float:
        if _is_ffmpeg_cli_usable() and shutil.which("ffprobe"):
            proc = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
                capture_output=True, text=True,
            )
            if proc.returncode == 0:
                try:
                    d = float(proc.stdout.strip())
                    if d > 0:
                        return d
                except ValueError:
                    pass

        if in_stream is not None and in_stream.duration:
            return float(in_stream.duration * in_stream.time_base)

        with av.open(str(audio_path)) as inp:
            stream = inp.streams.audio[0]
            if stream.duration:
                return float(stream.duration * stream.time_base)
        return 0.0

    # ------------------------------------------------------------------
    # faster-whisper local backend  (ported verbatim from 06-src)
    # ------------------------------------------------------------------

    def _transcribe_local(
        self, audio_path: Path, json_save_path: Optional[Path] = None
    ) -> TranscriptionResult:
        if not _FASTER_WHISPER_AVAILABLE:
            raise RuntimeError(
                "faster-whisper 未安装，且未配置 GROQ_API_KEY。\n"
                "请二选一：\n"
                "  1. 在 .env 中设置 GROQ_API_KEY（推荐）\n"
                "  2. pip install faster-whisper"
            )

        model = self._load_local_model()
        size_mb = audio_path.stat().st_size / (1024 * 1024)
        start_msg = (
            f"使用 faster-whisper 本地转录：{audio_path.name}"
            f"（{size_mb:.1f} MB，模型：{self._local_model_path}）"
        )
        if self._emit_log:
            self._emit_log(start_msg)
        else:
            logger.info(start_msg)

        try:
            segments_iter, info = model.transcribe(
                str(audio_path),
                beam_size=5,
                language=None,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
            )
            text_parts: list[str] = []
            segment_dicts: list[dict] = []
            segment_count = 0
            last_log = time.monotonic()
            for seg in segments_iter:
                text_parts.append(seg.text)
                segment_dicts.append({
                    "id": segment_count,
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text,
                })
                segment_count += 1
                now = time.monotonic()
                if now - last_log >= _LOCAL_PROGRESS_INTERVAL_SEC:
                    progress_msg = (
                        f"转录进行中… 已识别 {segment_count} 段，进度至 {seg.end:.0f} 秒"
                    )
                    if self._emit_log:
                        self._emit_log(progress_msg)
                    else:
                        logger.info(progress_msg)
                    last_log = now
            text = " ".join(text_parts).strip()
        except Exception as exc:
            raise RuntimeError(f"faster-whisper 转录失败：{exc}") from exc

        if not text:
            raise ValueError("未检测到有效语音内容，请确认音频文件包含人声。")

        language = info.language or "unknown"
        logger.info("本地转录完成，语言：%s，字数：%d", language, len(text))

        if json_save_path is not None:
            verbose_response = {
                "text": text,
                "language": language,
                "task": "transcribe",
                "duration": segment_dicts[-1]["end"] if segment_dicts else None,
                "segments": segment_dicts,
            }
            _save_response_files(verbose_response, json_save_path)

        return TranscriptionResult(text=text, language=language)

    def _load_local_model(self) -> "WhisperModel":
        if self._fw_model is not None:
            return self._fw_model

        local_path = Path(self._local_model_path).expanduser()
        if local_path.suffix.lower() == ".pt":
            raise RuntimeError(
                "WHISPER_MODEL_PATH 指向了 .pt 文件；faster-whisper 需要 CTranslate2 模型目录。"
            )
        if local_path.is_file():
            raise RuntimeError(
                f"WHISPER_MODEL_PATH 指向了单个文件（{self._local_model_path}），需要目录。"
            )

        logger.info("加载本地 Whisper 模型：%s", self._local_model_path)
        if self._emit_log:
            self._emit_log(f"加载本地 Whisper 模型：{self._local_model_path}")
        try:
            self._fw_model = WhisperModel(
                self._local_model_path, device="auto", compute_type="auto"
            )
        except Exception as exc:
            raise RuntimeError(
                f"Whisper 模型加载失败（{self._local_model_path}）：{exc}"
            ) from exc

        return self._fw_model


# ------------------------------------------------------------------
# File helpers  (ported verbatim from 06-src)
# ------------------------------------------------------------------

def _response_to_dict(response: Any) -> Dict[str, Any]:
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


def _merge_groq_responses(
    responses: List[Any],
    offsets: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Merge multiple Groq verbose_json chunks with accurate timestamps.

    When *offsets* is provided (list of PyAV chunk start times in seconds),
    each chunk's segments are shifted by the corresponding exact offset instead
    of accumulating Groq-reported durations.  Groq consistently under-reports
    chunk duration by ~0.25 s per chunk, which would cause ~6 s of drift across
    a 2-hour podcast.  Using PyAV-derived offsets eliminates this.
    """
    texts: List[str] = []
    all_segments: List[Dict[str, Any]] = []
    language = "unknown"
    cumulative_offset = 0.0
    total_duration = 0.0

    for chunk_idx, raw_resp in enumerate(responses):
        raw = _response_to_dict(raw_resp)
        text = (raw.get("text") or "").strip()
        if text:
            texts.append(text)
        if language == "unknown":
            language = raw.get("language") or "unknown"

        # Use the exact PyAV start time when available; fall back to cumulative Groq durations
        if offsets is not None and chunk_idx < len(offsets):
            offset = offsets[chunk_idx]
        else:
            offset = cumulative_offset

        for seg in raw.get("segments") or []:
            merged = dict(seg)
            merged["start"] = float(seg.get("start", 0) or 0) + offset
            merged["end"] = float(seg.get("end", 0) or 0) + offset
            if merged.get("words"):
                merged["words"] = [
                    {**w,
                     "start": float(w.get("start", 0) or 0) + offset,
                     "end": float(w.get("end", 0) or 0) + offset}
                    for w in merged["words"]
                ]
            all_segments.append(merged)

        # Accumulate fallback offset from Groq-reported duration (only used when offsets=None)
        segs = raw.get("segments") or []
        chunk_dur = float(raw.get("duration") or 0)
        if chunk_dur <= 0 and segs:
            chunk_dur = max(float(s.get("end", 0) or 0) for s in segs)
        cumulative_offset += chunk_dur
        total_duration += chunk_dur

    # When using PyAV offsets, compute total_duration from last chunk's Groq content
    if offsets and responses:
        last_raw = _response_to_dict(responses[-1])
        last_segs = last_raw.get("segments") or []
        last_offset = offsets[-1] if offsets else 0.0
        last_chunk_dur = float(last_raw.get("duration") or 0)
        if last_chunk_dur <= 0 and last_segs:
            last_chunk_dur = max(float(s.get("end", 0) or 0) for s in last_segs)
        total_duration = last_offset + last_chunk_dur

    return {
        "text": " ".join(texts).strip(),
        "language": language,
        "task": "transcribe",
        "duration": total_duration,
        "segments": all_segments,
    }


def _save_response_files(response: Any, base_json_path: Path) -> None:
    """Save Groq response in three formats beside *base_json_path*.

    Mirrors 06-src behaviour:
      {stem}.txt           — plain text
      {stem}.json          — compact JSON
      {stem}_verbose.json  — full verbose_json with segments
    """
    base_json_path.parent.mkdir(parents=True, exist_ok=True)

    raw = _response_to_dict(response)
    text = (raw.get("text") or "").strip()
    language = raw.get("language") or ""

    txt_path     = base_json_path.with_suffix(".txt")
    json_path    = base_json_path
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
