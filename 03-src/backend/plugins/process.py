"""进程型插件子进程管理 —— subprocess + PID 落 `.server/plugins/{id}.pid`。

与 start-server.sh 双路径兼容：start-server.sh 直跑 wechat-bot 时写
`.server/wechat-bot.pid`，PluginManager 探测到存活即识别为 running，不重复拉起；
PluginManager 启停写 `.server/plugins/{id}.pid`（新命名规范）。
"""
import os
import signal
import subprocess
import time
from datetime import date
from pathlib import Path
from typing import Optional

from backend.core.paths import get_project_root
from backend.plugins.status import pid_file_status, process_is_alive

PROJECT_ROOT = get_project_root()
# backend 包只在 03-src/ 下可见——`python -m backend.plugins.*` 必须以此为 cwd。
BACKEND_PARENT = Path(__file__).resolve().parents[2]
PLUGIN_PID_DIR = PROJECT_ROOT / ".server" / "plugins"


def pid_file_for(plugin_id: str) -> Path:
    return PLUGIN_PID_DIR / f"{plugin_id}.pid"


def legacy_pid_file(plugin_id: str) -> Optional[Path]:
    """start-server.sh 时代的旧 PID 文件（`.server/wechat-bot.pid`），探测时兼容。"""
    legacy = PROJECT_ROOT / ".server" / f"{plugin_id}-bot.pid"
    return legacy if legacy.exists() else None


def resolve_pid_files(plugin_id: str, extra: Optional[list] = None) -> list:
    """候选 PID 文件：新规范 + 旧规范 + 显式 extra。"""
    files = [pid_file_for(plugin_id)]
    legacy = legacy_pid_file(plugin_id)
    if legacy:
        files.append(legacy)
    for f in (extra or []):
        p = Path(f)
        if p.exists() and p not in files:
            files.append(p)
    return files


def find_alive_pid(plugin_id: str, extra: Optional[list] = None) -> tuple[bool, Optional[int]]:
    """在候选 PID 文件中找第一个存活进程 → (存活?, pid)。"""
    for pf in resolve_pid_files(plugin_id, extra):
        alive, pid = pid_file_status(pf)
        if alive and pid:
            return True, pid
    return False, None


def stop_pid(pid: int, timeout_sec: float = 10.0) -> bool:
    """SIGTERM 优雅停止，超时 SIGKILL。进程组（start_new_session 拉起）一并处理。"""
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return False
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if not _group_alive(pid):
            return True
        time.sleep(0.3)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    return not _group_alive(pid)


def _group_alive(pid: int) -> bool:
    """进程组是否仍有存活成员 —— 复用 process_is_alive（含僵尸检测，避免误判）。"""
    return process_is_alive(pid)


def start_bot(plugin_id: str, cmd: list, env: dict, log_dir: Path) -> Optional[int]:
    """后台拉起 bot 子进程，写 PID 文件。返回 pid（失败返回 None）。"""
    PLUGIN_PID_DIR.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{date.today().isoformat()}.log"
    stdout = open(log_path, "ab", buffering=0)
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(BACKEND_PARENT),  # backend 包在 03-src/ 下可见
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stdout,
            start_new_session=True,   # 独立进程组，stop 时整组停止
        )
    except OSError:
        stdout.close()
        return None
    pid_file_for(plugin_id).write_text(f"{proc.pid}\n")
    return proc.pid


def stop_bot(plugin_id: str, extra_pid_files: Optional[list] = None) -> bool:
    """停止插件进程：优先 PID 文件；文件里找不到活进程时按进程名兜底（由调用方传入 cmd）。"""
    alive, pid = find_alive_pid(plugin_id, extra_pid_files)
    if alive and pid:
        stopped = stop_pid(pid)
    else:
        stopped = _stop_by_name(f"-m backend.plugins.{plugin_id}.bot")
    # 清理残留 PID 文件
    for pf in resolve_pid_files(plugin_id, extra_pid_files):
        pf.unlink(missing_ok=True)
    return stopped


def _stop_by_name(match: str) -> bool:
    """pgrep 按命令行匹配杀进程（无 PID 文件时的兜底）。"""
    try:
        import subprocess
        out = subprocess.run(
            ["pgrep", "-f", match], capture_output=True, text=True
        ).stdout.split()
        for pid_str in out:
            stop_pid(int(pid_str))
        return bool(out)
    except Exception:
        return False
