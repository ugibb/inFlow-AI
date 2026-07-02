"""
inFlow AI 统一日志模块。

- 仅写入按日文件：LOG_DIR/YYYY-MM-DD.log（DEBUG 及以上）
- 格式：时间戳 | 级别 | 模块名 | 消息
- 进程 stdout/stderr（uvicorn 启动信息等）由 start-local.sh 追加到同一按日文件
"""
from __future__ import annotations

import datetime
import logging
import os
import sys
from pathlib import Path
from typing import Iterable

from app.core.paths import get_project_root

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_ROOT_LOGGER_NAME = "inFlow"
_NAME_PREFIX = f"{_ROOT_LOGGER_NAME}."

_PROJECT_ROOT = get_project_root()

_LEVEL_MAP: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

_configured = False
_warnings_configured = False


def configure_python_warnings() -> None:
    """屏蔽阿里云 vendored urllib3 的 SNIMissingWarning（听悟 HTTPS 调用，可安全忽略）。"""
    global _warnings_configured
    if _warnings_configured:
        return
    import warnings

    warnings.filterwarnings(
        "ignore",
        message=r".*SNI \(Server Name Indication\).*",
    )
    warnings.filterwarnings(
        "ignore",
        message=r".*SNI.*",
        category=UserWarning,
    )
    _warnings_configured = True


def _use_stdout_logging() -> bool:
    flag = os.environ.get("LOG_TO_STDOUT", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    return os.environ.get("inFlow_ENV", "").strip().lower() == "production"


class _inFlowFormatter(logging.Formatter):
    """输出时去掉 logger 名中的 inFlow. 前缀。"""

    def format(self, record: logging.LogRecord) -> str:
        name = record.name
        if name.startswith(_NAME_PREFIX):
            record.name = name[len(_NAME_PREFIX) :]
        elif name == _ROOT_LOGGER_NAME:
            record.name = "root"
        return super().format(record)


class _AccessPathSkipFilter(logging.Filter):
    """跳过高频轮询路径的 uvicorn access 日志。"""

    def __init__(self, skip_paths: Iterable[str]) -> None:
        super().__init__()
        self._skip_paths = tuple(p.strip() for p in skip_paths if p.strip())

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(path in msg for path in self._skip_paths)


def resolve_log_dir(log_dir: str | Path) -> Path:
    """将 LOG_DIR 解析为绝对路径（相对路径基于项目根目录）。"""
    path = Path(log_dir)
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def parse_log_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    return _LEVEL_MAP.get(level.upper().strip(), logging.INFO)


def setup_logging(
    log_dir: str | Path | None = None,
    file_level: str | int = logging.DEBUG,
    name: str = _ROOT_LOGGER_NAME,
) -> logging.Logger:
    """
    初始化并返回项目根 logger（仅文件输出）。
    可多次调用；重复调用时先清空已有 handler（pytest 场景）。
    """
    global _configured

    configure_python_warnings()

    if log_dir is None:
        from app.core.config import get_settings

        log_dir = get_settings().get_log_dir_path()
    else:
        log_dir = resolve_log_dir(log_dir)

    file_level = parse_log_level(file_level)

    today = datetime.date.today().strftime("%Y-%m-%d")
    log_file = log_dir / f"{today}.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        logger.handlers.clear()

    formatter = _inFlowFormatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    handlers: list[logging.Handler] = []
    try:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(file_level)
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    except OSError as exc:
        logging.basicConfig(level=file_level, stream=sys.stderr)
        logging.getLogger(name).warning("File logging disabled (%s): %s", log_file, exc)

    if _use_stdout_logging():
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setLevel(file_level)
        stream_handler.setFormatter(formatter)
        handlers.append(stream_handler)

    for handler in handlers:
        logger.addHandler(handler)

    logger.propagate = False
    _configured = True
    return logger


def get_logger(module_name: str) -> logging.Logger:
    """获取子模块 logger，命名格式：inFlow.<module_name>"""
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{module_name}")


def configure_quiet_module_loggers() -> None:
    """压低已由 PhaseLogger 覆盖的子模块 DEBUG/INFO，避免 pipeline 日志被刷屏。"""
    for name in (
        "inFlow.ingest.adapters",
        "inFlow.storage.local",
        "inFlow.services.audio_downloader",
        "inFlow.pipeline.state_machine",
        "inFlow.parse.templates.registry",
        "inFlow.parse.parser",
        "inFlow.display.renderer",
        "inFlow.parse.wiki_indexer",
        "inFlow.parse.transcriber",
        "inFlow.s4.card_renderer",
        "inFlow.pipeline.steps",
        "inFlow.core.shared.ai_service",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)


def configure_third_party_loggers(
    log_sql: bool = False,
    log_access: bool = False,
    access_skip_paths: Iterable[str] | None = None,
) -> None:
    """压制 SQLAlchemy / httpx / uvicorn 等第三方噪音。"""
    if log_sql:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
    else:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    logging.getLogger("httpx").setLevel(logging.WARNING)

    access_logger = logging.getLogger("uvicorn.access")
    if log_access:
        access_logger.setLevel(logging.INFO)
        skip_paths = list(access_skip_paths or ())
        if skip_paths:
            for handler in access_logger.handlers:
                handler.addFilter(_AccessPathSkipFilter(skip_paths))
            if not access_logger.handlers:
                access_logger.addFilter(_AccessPathSkipFilter(skip_paths))
    else:
        access_logger.setLevel(logging.WARNING)
        access_logger.disabled = True

    _attach_inFlow_handlers_to(("uvicorn", "uvicorn.error"))


def _attach_inFlow_handlers_to(logger_names: Iterable[str]) -> None:
    """让第三方 logger 复用 inFlow 的 handler，统一时间戳格式。"""
    inFlow = logging.getLogger(_ROOT_LOGGER_NAME)
    if not inFlow.handlers:
        return
    for name in logger_names:
        ext = logging.getLogger(name)
        ext.handlers.clear()
        for handler in inFlow.handlers:
            ext.addHandler(handler)
        ext.propagate = False
