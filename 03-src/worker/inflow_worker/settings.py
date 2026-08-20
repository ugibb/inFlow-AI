"""本地 worker 配置。

不经 repo 根 .env（那是云端/本地开发后端用的），由 start-worker.sh 从
`.env.local-worker` 安全注入环境变量（python-dotenv export），pydantic-settings
环境变量优先级高于 .env 文件。

关键约定：
- DATABASE_URL 指向云端 PostgreSQL（5432 白名单），worker 不调用 init_db()
- SFTP_HOST / SFTP_PIPELINE_DIR 为空时跳过 PNG 回传（阶段 2 空跑）
- SFTP_PIPELINE_DIR 必须与云端 INFLOW_PIPELINE_DATA_DIR 一致
"""

from __future__ import annotations

import os
import socket
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


def _hostname() -> str:
    """短主机名（不带域、不带 PID）。"""
    return socket.gethostname().split(".")[0] or "worker"


def _current_host() -> str:
    """worker 身份标识：hostname-pid，用于认领审计与并发所有权判定。"""
    return f"{_hostname()}-{os.getpid()}"


class WorkerSettings(BaseSettings):
    """本地 worker 专属配置（仅环境变量，无 .env 文件）。"""

    model_config = SettingsConfigDict(extra="ignore")

    # ── 调度 ─────────────────────────────────────────────
    scan_interval_s: float = 10.0        # 空闲轮询间隔
    lease_seconds: int = 600             # 租约有效期；超时后其他 worker 可重新认领
    heartbeat_interval_s: float = 120.0  # 长任务心跳刷新 claimed_at，防被抢

    # ── SFTP PNG 回传 ────────────────────────────────────
    # SFTP_HOST / SFTP_PIPELINE_DIR 为空 → 跳过回传（阶段 2 空跑）
    sftp_host: str = ""
    sftp_user: str = "inFlow_worker"
    sftp_port: int = 22
    sftp_pipeline_dir: str = ""          # 云端 $INFLOW_PIPELINE_DATA_DIR（绝对路径）

    @property
    def worker_host(self) -> str:
        """完整身份 hostname-pid（写入 processing_host，含重启 PID 审计信息）。"""
        return _current_host()

    @property
    def host_prefix(self) -> str:
        """短主机名。reclaim_own_host 用它前缀匹配本机遗留租约
        （重启后 PID 变化，hostname 保持不变）。"""
        return _hostname()

    @property
    def sftp_enabled(self) -> bool:
        return bool(self.sftp_host and self.sftp_pipeline_dir)


@lru_cache()
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()


worker_settings = get_worker_settings()
