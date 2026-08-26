"""upload/paste 全量分流登记 + 配额检查的单元测试（无 PostgreSQL 依赖）。

验证 external_processing=True 时 ingest_upload / ingest_text 只做
「收件落盘 data/00_staging/ + 登记 job 字段」，不调度任何后台任务：
- staging 文件原子写入且内容一致
- job.external_processing / staging_file_path 已登记
- job 停在 pending（等 worker 认领），BackgroundTasks 为空
- 免费额度（FREE_QUOTA_PER_DAY，worker 契约 quota_check.sql）登记前检查：
  当日 ready 数 >= 上限 → 429 拒绝，未超限正常登记，0=不限制
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from fastapi import BackgroundTasks, HTTPException

from backend.core.ingest import orchestrator


class _FakeResult:
    """COUNT 查询替身：只实现 scalar_one()。"""

    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class FakeSession:
    """最小 AsyncSession 替身：add/flush/commit/execute，flush 时补默认主键。"""

    def __init__(self, ready_count: int = 0) -> None:
        self.added: list = []
        self.committed = False
        # 配额检查的 COUNT 返回值：当日 ready 数（默认 0=未超限）
        self._ready_count = ready_count

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            if getattr(obj, "status", None) is None:
                obj.status = "pending"  # 模拟 SQLAlchemy flush 应用列默认值

    async def commit(self) -> None:
        self.committed = True

    async def execute(self, stmt) -> _FakeResult:
        # 配额检查的 COUNT 查询：返回注入的 ready_count
        return _FakeResult(self._ready_count)


def _setup(tmp_path: Path, monkeypatch) -> FakeSession:
    # data_root 用绝对路径（生产直跑形态）：同时覆盖绝对路径登记场景
    monkeypatch.setattr(orchestrator.settings, "data_root", str(tmp_path))
    monkeypatch.setattr(orchestrator.settings, "external_processing", True)
    return FakeSession()


def test_ingest_upload_external_branch(tmp_path: Path, monkeypatch) -> None:
    db = _setup(tmp_path, monkeypatch)
    bg = BackgroundTasks()

    job_id = asyncio.run(
        orchestrator.ingest_upload(
            db, bg, filename="笔记.md", content="# 摘要\n正文".encode("utf-8"),
            user_id=uuid.uuid4(),
        )
    )

    job = db.added[-1]
    assert db.committed is True
    assert job.external_processing is True
    assert job.staging_file_path is not None
    assert job.status == "pending"  # 未 transition，等 worker 认领
    assert bg.tasks == []  # 云端不调度任何后台 pipeline

    # 收件落盘（绝对 data_root 形态：登记值即云端绝对路径）
    staging = Path(job.staging_file_path)
    assert staging.is_file()
    assert staging.read_bytes() == "# 摘要\n正文".encode("utf-8")
    assert staging.parent.name == str(job_id)
    assert staging.name == "笔记.md"

    # 无 .tmp 残留（原子写）
    assert not Path(f"{job.staging_file_path}.tmp").exists()


def test_ingest_text_external_branch(tmp_path: Path, monkeypatch) -> None:
    db = _setup(tmp_path, monkeypatch)
    bg = BackgroundTasks()

    job_id = asyncio.run(
        orchestrator.ingest_text(
            db, bg, text="粘贴的正文内容", title="我的便签", user_id=uuid.uuid4(),
        )
    )

    job = db.added[-1]
    assert db.committed is True
    assert job.external_processing is True
    assert job.status == "pending"
    assert bg.tasks == []

    staging = Path(job.staging_file_path)
    assert staging.is_file()
    assert staging.read_text(encoding="utf-8") == "粘贴的正文内容"
    assert staging.name == "note.md"  # paste 固定文件名
    assert staging.parent.name == str(job_id)


def test_external_disabled_still_registers_external(tmp_path: Path, monkeypatch) -> None:
    """EXTERNAL_PROCESSING=false 也已无法回退云端本地管道（venv 已瘦身）。

    单包收敛/依赖瘦身后，云端不再有自跑管道（orchestrator.transition 已随
    旧架构删除）：无论配置如何，upload/paste 都按外部分流登记收件到
    00_staging，由本地 worker 承接。本测试即回归此行为。
    """
    db = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(orchestrator.settings, "external_processing", False)
    bg = BackgroundTasks()

    asyncio.run(
        orchestrator.ingest_upload(
            db, bg, filename="a.md", content=b"x", user_id=uuid.uuid4(),
        )
    )

    job = db.added[-1]
    assert job.external_processing is True
    assert job.staging_file_path is not None
    assert bg.tasks == []  # 云端不调度任何后台 pipeline
    assert (tmp_path / "00_staging").exists()


# ── 免费额度配额（worker 契约 quota_check.sql）────────────────────

def test_quota_exceeded_rejects_new_job(tmp_path: Path, monkeypatch) -> None:
    db = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(orchestrator.settings, "free_quota_per_day", 10)
    db._ready_count = 10  # 当日 ready 已达上限
    bg = BackgroundTasks()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            orchestrator.ingest_upload(
                db, bg, filename="a.md", content=b"x", user_id=uuid.uuid4(),
            )
        )
    assert exc.value.status_code == 429
    assert "10" in exc.value.detail
    assert db.added == []  # 未创建任何 Article/Job


def test_quota_under_limit_allows_registration(tmp_path: Path, monkeypatch) -> None:
    db = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(orchestrator.settings, "free_quota_per_day", 10)
    db._ready_count = 9  # 未超限
    bg = BackgroundTasks()

    job_id = asyncio.run(
        orchestrator.ingest_upload(
            db, bg, filename="b.md", content=b"y", user_id=uuid.uuid4(),
        )
    )
    assert job_id is not None
    assert db.added[-1].external_processing is True


def test_quota_disabled_when_zero(tmp_path: Path, monkeypatch) -> None:
    """FREE_QUOTA_PER_DAY=0：不限制（自托管全放开）。"""
    db = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(orchestrator.settings, "free_quota_per_day", 0)
    db._ready_count = 100
    bg = BackgroundTasks()

    job_id = asyncio.run(
        orchestrator.ingest_upload(
            db, bg, filename="c.md", content=b"z", user_id=uuid.uuid4(),
        )
    )
    assert job_id is not None
