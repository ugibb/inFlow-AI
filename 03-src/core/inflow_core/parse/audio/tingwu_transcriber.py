"""通义听悟离线转写 ASR backend."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from inflow_core.core.utils.logger import configure_python_warnings, get_logger
from inflow_core.core.shared.utils.retry import format_retry_reason
from inflow_core.parse.audio.asr_common import TranscriptionResult, save_asr_response_files

configure_python_warnings()

logger = get_logger("parse.tingwu")


def tingwu_json_path_from_transcript_base(transcript_base: Path) -> Path:
    """Derive {job_id}_tingwu.json beside {job_id}_asr.json."""
    stem = transcript_base.stem
    job_stem = stem[: -len("_asr")] if stem.endswith("_asr") else stem
    return transcript_base.parent / f"{job_stem}_tingwu.json"


def save_tingwu_raw_json(payload: dict, transcript_base: Path) -> Path:
    """Persist raw Tingwu transcription JSON next to ASR artifacts."""
    out = tingwu_json_path_from_transcript_base(transcript_base)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out

_TINGWU_DOMAIN = "tingwu.cn-beijing.aliyuncs.com"
_TINGWU_VERSION = "2023-09-30"
_TINGWU_REGION = "cn-beijing"
_OSS_URL_EXPIRE_SEC = 4 * 3600  # 听悟要求预签名 URL ≥3 小时
_SDK_MAX_ATTEMPTS = 3
_SDK_RETRY_DELAY_SEC = 5.0
_OSS_MAX_ATTEMPTS = 3

try:
    import oss2  # type: ignore

    _OSS2_AVAILABLE = True
except ImportError:
    oss2 = None  # type: ignore
    _OSS2_AVAILABLE = False

try:
    from aliyunsdkcore.auth.credentials import AccessKeyCredential  # type: ignore
    from aliyunsdkcore.client import AcsClient  # type: ignore
    from aliyunsdkcore.request import CommonRequest  # type: ignore

    _ALIYUN_SDK_AVAILABLE = True
except ImportError:
    AccessKeyCredential = None  # type: ignore
    AcsClient = None  # type: ignore
    CommonRequest = None  # type: ignore
    _ALIYUN_SDK_AVAILABLE = False


def _is_transient_network_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}"
    markers = (
        "Connection aborted",
        "Remote end closed",
        "RemoteDisconnected",
        "timed out",
        "Timeout",
        "Connection reset",
        "SSLError",
        "HttpError",
    )
    return any(m in text for m in markers)


class TingwuTranscriber:
    """通义听悟离线转写 — 上传 OSS → 提交任务 → 轮询 → 转换 verbose JSON。"""

    def __init__(
        self,
        *,
        app_key: str,
        access_key_id: str,
        access_key_secret: str,
        oss_bucket: str,
        oss_endpoint: str,
        source_language: str = "cn",
        poll_interval_sec: float = 30.0,
        max_wait_sec: float = 10800.0,
    ) -> None:
        self._app_key = (app_key or "").strip()
        self._access_key_id = (access_key_id or "").strip()
        self._access_key_secret = (access_key_secret or "").strip()
        self._oss_bucket = (oss_bucket or "").strip()
        self._oss_endpoint = (oss_endpoint or "oss-cn-beijing.aliyuncs.com").strip()
        self._source_language = (source_language or "cn").strip()
        self._poll_interval_sec = max(5.0, float(poll_interval_sec))
        self._max_wait_sec = max(60.0, float(max_wait_sec))
        self._emit_log: Optional[Callable[[str], None]] = None
        self._acs_client: Optional[Any] = None

    def backend_label(self) -> str:
        if not self._is_configured():
            return "通义听悟 ASR（配置不完整）"
        if not _ALIYUN_SDK_AVAILABLE:
            return "通义听悟 ASR（aliyun SDK 未安装）"
        if not _OSS2_AVAILABLE:
            return "通义听悟 ASR（oss2 未安装）"
        return "通义听悟 ASR（离线转写）"

    def transcribe(
        self,
        audio_path: Path,
        json_save_path: Optional[Path] = None,
        emit_log: Optional[Callable[[str], None]] = None,
    ) -> TranscriptionResult:
        self._emit_log = emit_log
        self._validate_config()

        audio_path = Path(audio_path)
        size_mb = audio_path.stat().st_size / (1024 * 1024)
        self._log(f"听悟转录开始 | {audio_path.name} | {size_mb:.1f} MB")

        started = time.monotonic()
        file_url = self._upload_to_oss(audio_path)
        # self._log(f"音频已上传 OSS，提交听悟离线任务")

        task_id = self._create_offline_task(file_url)
        self._log(f"音频已上传 OSS，听悟离线任务已提交 | TaskId={task_id}")

        transcription_url = self._poll_until_done(task_id, started=started)
        # self._log("听悟转录完成，下载结果 JSON")

        tingwu_payload = self._download_json(transcription_url)
        verbose = tingwu_to_verbose(tingwu_payload)
        text = (verbose.get("text") or "").strip()
        if not text:
            raise ValueError("听悟未返回有效转写文本，请确认音频包含人声。")

        if json_save_path is not None:
            tingwu_path = save_tingwu_raw_json(tingwu_payload, Path(json_save_path))
            self._log(f"听悟原始 JSON 已保存 | {tingwu_path.name}")
            save_asr_response_files(verbose, json_save_path)

        elapsed = time.monotonic() - started
        language = verbose.get("language") or "zh"
        seg_count = len(verbose.get("segments") or [])
        self._log(
            f"听悟 ASR 完成 | {size_mb:.1f} MB | {elapsed:.0f}s"
            f" | 字数 {len(text)} | 句段 {seg_count}"
        )
        return TranscriptionResult(text=text, language=language)

    def _is_configured(self) -> bool:
        return bool(
            self._app_key
            and self._access_key_id
            and self._access_key_secret
            and self._oss_bucket
            and self._oss_endpoint
        )

    def _validate_config(self) -> None:
        missing = []
        if not self._app_key:
            missing.append("TINGWU_APP_KEY")
        if not self._access_key_id:
            missing.append("ALIBABA_CLOUD_ACCESS_KEY_ID")
        if not self._access_key_secret:
            missing.append("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
        if not self._oss_bucket:
            missing.append("TINGWU_OSS_BUCKET")
        if not self._oss_endpoint:
            missing.append("TINGWU_OSS_ENDPOINT")
        if missing:
            raise RuntimeError(
                "听悟 ASR 配置不完整，请在 .env 中设置："
                + "、".join(missing)
            )
        if not _ALIYUN_SDK_AVAILABLE:
            raise RuntimeError(
                "听悟 ASR 需要 aliyun-python-sdk-core，请确认 backend 依赖已安装。"
            )
        if not _OSS2_AVAILABLE:
            raise RuntimeError(
                "听悟 ASR 需要 oss2，请确认 backend 依赖已安装。"
            )

    def _log(self, message: str) -> None:
        if self._emit_log:
            self._emit_log(message)
        else:
            logger.info(message)

    def _get_acs_client(self) -> Any:
        if self._acs_client is None:
            credentials = AccessKeyCredential(self._access_key_id, self._access_key_secret)
            self._acs_client = AcsClient(region_id=_TINGWU_REGION, credential=credentials)
        return self._acs_client

    def _reset_acs_client(self) -> None:
        self._acs_client = None

    def _do_action_with_retry(self, request: Any, *, action: str) -> bytes:
        last_exc: Exception | None = None
        for attempt in range(1, _SDK_MAX_ATTEMPTS + 1):
            try:
                return self._get_acs_client().do_action_with_exception(request)
            except Exception as exc:
                last_exc = exc
                if attempt < _SDK_MAX_ATTEMPTS and _is_transient_network_error(exc):
                    reason = format_retry_reason(exc)
                    self._log(
                        f"听悟 {action} 网络异常，第 {attempt}/{_SDK_MAX_ATTEMPTS} 次重试"
                        f"（{reason}，{_SDK_RETRY_DELAY_SEC:.0f}s 后）"
                    )
                    self._reset_acs_client()
                    time.sleep(_SDK_RETRY_DELAY_SEC)
                    continue
                raise RuntimeError(
                    f"听悟 {action} 失败：{format_retry_reason(exc)}"
                ) from exc
        raise RuntimeError(f"听悟 {action} 失败：{format_retry_reason(last_exc)}") from last_exc

    def _make_request(
        self,
        method: str,
        uri: str,
        body: Optional[dict] = None,
        *,
        query: Optional[dict[str, str]] = None,
        action: str = "API 请求",
    ) -> dict:
        request = CommonRequest()
        request.set_accept_format("json")
        request.set_domain(_TINGWU_DOMAIN)
        request.set_version(_TINGWU_VERSION)
        request.set_protocol_type("https")
        request.set_method(method)
        request.set_uri_pattern(uri)
        request.add_header("Content-Type", "application/json")
        if query:
            for key, value in query.items():
                request.add_query_param(key, value)
        if body is not None:
            request.set_content(json.dumps(body, ensure_ascii=False).encode("utf-8"))
        raw = self._do_action_with_retry(request, action=action)
        payload = json.loads(raw)
        if str(payload.get("Code")) != "0":
            raise RuntimeError(
                f"听悟 API 错误：{payload.get('Message') or payload}"
            )
        return payload

    def _upload_to_oss(self, audio_path: Path) -> str:
        auth = oss2.Auth(self._access_key_id, self._access_key_secret)
        bucket = oss2.Bucket(auth, self._oss_endpoint, self._oss_bucket)
        object_key = f"tingwu-asr/{uuid.uuid4().hex}/{audio_path.name}"
        last_exc: Exception | None = None
        for attempt in range(1, _OSS_MAX_ATTEMPTS + 1):
            try:
                bucket.put_object_from_file(object_key, str(audio_path))
                last_exc = None
                break
            except oss2.exceptions.NoSuchBucket:
                raise RuntimeError(
                    f"OSS Bucket 不存在：{self._oss_bucket!r}（endpoint={self._oss_endpoint}）。"
                    "请在阿里云 OSS 控制台创建该 Bucket（地域需与 TINGWU_OSS_ENDPOINT 一致，如华北2-北京），"
                    "或将 TINGWU_OSS_BUCKET 改为你已有的 Bucket 名称。"
                ) from None
            except oss2.exceptions.AccessDenied:
                raise RuntimeError(
                    f"OSS 上传被拒绝：AccessKey 对 Bucket {self._oss_bucket!r} 无 PutObject 权限。"
                    "请为该 RAM 用户/AccessKey 授予 oss:PutObject、oss:GetObject 权限。"
                ) from None
            except Exception as exc:
                last_exc = exc
                if attempt < _OSS_MAX_ATTEMPTS and _is_transient_network_error(exc):
                    reason = format_retry_reason(exc)
                    self._log(
                        f"OSS 上传网络异常，第 {attempt}/{_OSS_MAX_ATTEMPTS} 次重试"
                        f"（{reason}，{_SDK_RETRY_DELAY_SEC:.0f}s 后）"
                    )
                    time.sleep(_SDK_RETRY_DELAY_SEC)
                    continue
                raise RuntimeError(
                    f"OSS 上传失败（bucket={self._oss_bucket}, endpoint={self._oss_endpoint}）："
                    f"{format_retry_reason(exc)}"
                ) from exc
        if last_exc is not None:
            raise RuntimeError(f"OSS 上传失败：{format_retry_reason(last_exc)}") from last_exc
        url = bucket.sign_url("GET", object_key, _OSS_URL_EXPIRE_SEC)
        if url.startswith("http://"):
            url = "https://" + url[len("http://") :]
        host = urlparse(url).hostname or ""
        if host and host[0].isdigit():
            raise RuntimeError(
                "OSS 预签名 URL 含 IP 地址，听悟不接受；请为 TINGWU_OSS_ENDPOINT 配置域名。"
            )
        return url

    def _create_offline_task(self, file_url: str) -> str:
        task_key = f"inFlow-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        body = {
            "AppKey": self._app_key,
            "Input": {
                "SourceLanguage": self._source_language,
                "TaskKey": task_key,
                "FileUrl": file_url,
            },
            "Parameters": {},
        }
        payload = self._make_request(
            "PUT",
            "/openapi/tingwu/v2/tasks",
            body,
            query={"type": "offline"},
            action="提交离线任务",
        )
        data = payload.get("Data") or {}
        task_id = data.get("TaskId")
        if not task_id:
            raise RuntimeError(f"听悟创建任务未返回 TaskId：{payload}")
        return str(task_id)

    def _poll_until_done(self, task_id: str, *, started: float) -> str:
        deadline = started + self._max_wait_sec
        last_status = ""
        while time.monotonic() < deadline:
            payload = self._make_request(
                "GET",
                f"/openapi/tingwu/v2/tasks/{task_id}",
                action="查询任务状态",
            )
            data = payload.get("Data") or {}
            status = str(data.get("TaskStatus") or "").upper()
            if status != last_status:
                waited = time.monotonic() - started
                self._log(f"听悟任务状态 {status} | 已等待 {waited:.0f}s")
                last_status = status

            if status == "COMPLETED":
                result = data.get("Result") or {}
                url = result.get("Transcription")
                if not url:
                    raise RuntimeError("听悟任务完成但未返回 Transcription URL")
                return str(url)

            if status == "FAILED":
                err = data.get("ErrorMessage") or data.get("ErrorCode") or data
                raise RuntimeError(f"听悟转录失败：{err}")

            time.sleep(self._poll_interval_sec)

        raise RuntimeError(
            f"听悟转录超时（>{int(self._max_wait_sec)}s），TaskId={task_id}"
        )

    def _download_json(self, url: str) -> dict:
        last_exc: Exception | None = None
        for attempt in range(1, _SDK_MAX_ATTEMPTS + 1):
            try:
                with httpx.Client(timeout=120.0, follow_redirects=True) as client:
                    resp = client.get(url)
                    resp.raise_for_status()
                    return resp.json()
            except Exception as exc:
                last_exc = exc
                if attempt < _SDK_MAX_ATTEMPTS and _is_transient_network_error(exc):
                    reason = format_retry_reason(exc)
                    self._log(
                        f"听悟结果下载网络异常，第 {attempt}/{_SDK_MAX_ATTEMPTS} 次重试"
                        f"（{reason}，{_SDK_RETRY_DELAY_SEC:.0f}s 后）"
                    )
                    time.sleep(_SDK_RETRY_DELAY_SEC)
                    continue
                raise RuntimeError(
                    f"听悟结果下载失败：{format_retry_reason(exc)}"
                ) from exc
        raise RuntimeError(f"听悟结果下载失败：{format_retry_reason(last_exc)}") from last_exc


def tingwu_to_verbose(tingwu_payload: dict) -> dict:
    """Convert Tingwu Transcription JSON → Groq-compatible verbose_json."""
    transcription = tingwu_payload.get("Transcription") or tingwu_payload
    if not isinstance(transcription, dict):
        raise ValueError("听悟结果格式异常：缺少 Transcription 对象")

    audio_info = transcription.get("AudioInfo") or {}
    paragraphs = transcription.get("Paragraphs") or []

    sentences: Dict[int, Dict[str, Any]] = {}
    for para in paragraphs:
        for word in para.get("Words") or []:
            sid = int(word.get("SentenceId") or 0)
            start_ms = int(word.get("Start") or 0)
            end_ms = int(word.get("End") or start_ms)
            text = str(word.get("Text") or "")
            if sid not in sentences:
                sentences[sid] = {"start_ms": start_ms, "end_ms": end_ms, "parts": []}
            entry = sentences[sid]
            entry["start_ms"] = min(entry["start_ms"], start_ms)
            entry["end_ms"] = max(entry["end_ms"], end_ms)
            if text:
                entry["parts"].append(text)

    segments: List[dict] = []
    texts: List[str] = []
    for sid in sorted(sentences):
        entry = sentences[sid]
        sentence_text = "".join(entry["parts"]).strip()
        if not sentence_text:
            continue
        texts.append(sentence_text)
        segments.append({
            "start": entry["start_ms"] / 1000.0,
            "end": entry["end_ms"] / 1000.0,
            "text": sentence_text,
        })

    duration_ms = audio_info.get("Duration")
    if duration_ms is None and segments:
        duration_ms = int(segments[-1]["end"] * 1000)

    lang_raw = str(audio_info.get("Language") or "cn")
    language = {"cn": "zh", "en": "en"}.get(lang_raw, lang_raw)

    return {
        "text": "".join(texts).strip(),
        "language": language,
        "task": "transcribe",
        "duration": (duration_ms / 1000.0) if duration_ms else None,
        "segments": segments,
    }
