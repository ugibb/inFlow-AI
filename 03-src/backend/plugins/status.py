"""插件状态判定工具 —— 进程存活 / PID 文件 / 配置就绪。"""
import os
import subprocess
from pathlib import Path
from typing import Optional


def _is_zombie(pid: int) -> bool:
    """僵尸进程（stat 含 Z）视为不存活 —— kill -0 对僵尸返回 True，会误判 running。"""
    try:
        out = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            capture_output=True, text=True, timeout=2,
        )
        return "Z" in out.stdout
    except Exception:
        return False


def process_is_alive(pid: int) -> bool:
    """kill -0 探测进程存活。

    - ProcessLookupError → 进程不存在
    - PermissionError → 存在但无信号权限（视为存活）
    - 僵尸进程（已退出、父进程未收割）→ 视为不存活
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return not _is_zombie(pid)


def pid_file_status(pid_file: Path) -> tuple[bool, Optional[int]]:
    """读 PID 文件 → (存活?, pid)。文件不存在 / 内容非法 / 进程不存在均视为未运行。"""
    if not pid_file.exists():
        return False, None
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return False, None
    return process_is_alive(pid), pid
