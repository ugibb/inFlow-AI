"""upload/paste 全量分流登记的单元测试（无 PostgreSQL 依赖）。

验证 external_processing=True 时 ingest_upload / ingest_text 只做
「收件落盘 data/00_staging/ + 登记 job 字段」，不调度任何后台任务：
- staging 文件原子写入且内容一致
- job.external_processing / staging_file_path 已登记
- job 停在 pending（等 worker 认领），BackgroundTasks 为空
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import BackgroundTasks

from backend.core.ingest import orchestrator


class FakeSession:
    """最小 AsyncSession 替身：add/flush/commit，flush 时补 Python 侧默认主键。"""

    def __init__(self) -> None:
        self.added: list = []
        self.committed = False

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


def test_external_disabled_keeps_local_path(tmp_path: Path, monkeypatch) -> None:
    """EXTERNAL_PROCESSING=false（云端调试）：保持原云端执行路径，不写 staging。"""
    db = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(orchestrator.settings, "external_processing", False)
    bg = BackgroundTasks()

    async def fake_transition(db, *, job_id, current_status, target_status):
        job = db.added[-1]
        job.status = target_status

    monkeypatch.setattr(orchestrator, "transition", fake_transition)

    asyncio.run(
        orchestrator.ingest_upload(
            db, bg, filename="a.md", content=b"x", user_id=uuid.uuid4(),
        )
    )

    job = db.added[-1]
    assert job.external_processing is not True
    assert job.staging_file_path is None
    assert not (tmp_path / "00_staging").exists()  # 未落盘收件
    assert len(bg.tasks) == 1  # 原后台任务仍调度
