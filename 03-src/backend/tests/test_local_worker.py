"""本地 worker 核心逻辑单元测试。

覆盖不依赖外部网络/DB 的纯逻辑：
- 外部 job 前端进度状态排名（_ext_step_done）
- SFTP 回传目标相对路径推导（ext_display_card_png_rel）
- _compose_and_continue 的 on_composed 钩子（回传失败 → 停 failed，成功 → 继续 index）
- SFTP 未配置时回传空跑返回 True
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.pipeline.pipeline_steps import _ext_step_done
from app.core.shared.storage.conventions import ext_display_card_png_rel


def _run(coro):
    return asyncio.run(coro)


# ── 外部 job 前端进度：状态排名判定 ───────────────────────────

def test_ext_step_done_rank():
    # captured：capture/media_download 完成，transcribe 未开始
    assert _ext_step_done("capture", "captured") is True
    assert _ext_step_done("media_download", "captured") is True
    assert _ext_step_done("transcribe", "captured") is False
    # 图文 normalize 在 normalized 才完成
    assert _ext_step_done("normalize", "captured") is False
    assert _ext_step_done("normalize", "normalized") is True
    # chapters 在 parsing 开始即视为完成；parse 在 parsed 完成
    assert _ext_step_done("chapters", "parsing") is True
    assert _ext_step_done("chapters", "parsed") is True
    assert _ext_step_done("parse", "parsing") is False
    assert _ext_step_done("parse", "parsed") is True
    # compose 在 composed 完成
    assert _ext_step_done("compose_html", "composing") is False
    assert _ext_step_done("compose_png", "composed") is True
    # index 在 ready 完成
    assert _ext_step_done("index", "indexing") is False
    assert _ext_step_done("index", "ready") is True
    # done 步骤永远不算"完成"
    assert _ext_step_done("done", "ready") is False


# ── SFTP 回传目标相对路径 ─────────────────────────────────────

def test_ext_display_card_png_rel_strips_data_prefix():
    rel = ext_display_card_png_rel(
        "data/01_ingest/xiaoyuzhou/20260820/001-title/abc-123.json",
        uuid.UUID("12345678-1234-5678-1234-567812345678"),
    )
    assert rel == (
        "03_display/xiaoyuzhou/20260820/001-title/"
        "12345678-1234-5678-1234-567812345678.png"
    )
    assert not rel.startswith("data/")


# ── _compose_and_continue 钩子 ────────────────────────────────

def test_compose_and_continue_upload_failure_stops_before_index():
    import app.s1_ingest.orchestrator as orch

    jid = uuid.uuid4()
    db = MagicMock()
    on_composed = AsyncMock(return_value=False)

    with (
        patch.object(
            orch, "run_compose_card",
            new=AsyncMock(return_value=("/tmp/x.html", "/tmp/x.png")),
        ),
        patch.object(orch, "transition", new=AsyncMock()) as trans,
        patch.object(orch, "run_index", new=AsyncMock()) as index,
    ):
        _run(orch._compose_and_continue(
            db,
            job_id=jid,
            article_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            raw_file_path="data/01_ingest/x/20260820/001-t/u.json",
            parsed_file_path="data/02_parse/x/20260820/001-t/u.json",
            asr_file_path=None,
            source_platform="x",
            content_type="article",
            source_url=None,
            on_composed=on_composed,
        ))

    on_composed.assert_awaited_once()
    # 回传失败 → composed→failed（error_stage=composing），不再 index
    trans.assert_awaited_once()
    args = trans.await_args.kwargs
    assert args["target_status"] == "failed"
    assert args["error_stage"] == "composing"
    index.assert_not_awaited()


def test_compose_and_continue_upload_ok_continues_index():
    import app.s1_ingest.orchestrator as orch

    jid = uuid.uuid4()
    db = MagicMock()
    on_composed = AsyncMock(return_value=True)

    with (
        patch.object(
            orch, "run_compose_card",
            new=AsyncMock(return_value=("/tmp/x.html", "/tmp/x.png")),
        ),
        patch.object(orch, "transition", new=AsyncMock()),
        patch.object(orch, "run_index", new=AsyncMock()) as index,
    ):
        _run(orch._compose_and_continue(
            db,
            job_id=jid,
            article_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            raw_file_path="data/01_ingest/x/20260820/001-t/u.json",
            parsed_file_path="data/02_parse/x/20260820/001-t/u.json",
            asr_file_path=None,
            source_platform="x",
            content_type="article",
            source_url=None,
            on_composed=on_composed,
        ))

    on_composed.assert_awaited_once()
    index.assert_awaited_once()


def test_compose_and_continue_cloud_no_hook_still_indexes():
    """云端路径（on_composed=None）行为零变化：compose 后照常 index。"""
    import app.s1_ingest.orchestrator as orch

    jid = uuid.uuid4()
    db = MagicMock()

    with (
        patch.object(
            orch, "run_compose_card",
            new=AsyncMock(return_value=("/tmp/x.html", "/tmp/x.png")),
        ),
        patch.object(orch, "transition", new=AsyncMock()),
        patch.object(orch, "run_index", new=AsyncMock()) as index,
    ):
        _run(orch._compose_and_continue(
            db,
            job_id=jid,
            article_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            raw_file_path="data/01_ingest/x/20260820/001-t/u.json",
            parsed_file_path="data/02_parse/x/20260820/001-t/u.json",
            asr_file_path=None,
            source_platform="x",
            content_type="article",
            source_url=None,
            on_composed=None,
        ))

    index.assert_awaited_once()


# ── SFTP 未配置时回传空跑 ─────────────────────────────────────

def test_upload_png_skipped_when_sftp_disabled():
    from types import SimpleNamespace

    from app.local_worker.runner import _upload_card_png_via_sftp

    with patch(
        "app.local_worker.runner.worker_settings",
        SimpleNamespace(sftp_enabled=False),
    ):
        ok = _run(_upload_card_png_via_sftp(uuid.uuid4(), "/tmp/x.png"))
    assert ok is True


# ── _upload_png_or_fail（HIGH-1 修复）：composed 后 PNG 回传 ────

def test_upload_png_or_fail_ok_keeps_job():
    import app.s1_ingest.orchestrator as orch

    with patch.object(orch, "transition", new=AsyncMock()) as trans:
        ok = _run(orch._upload_png_or_fail(
            AsyncMock(),
            job_id=uuid.uuid4(),
            png_path="/tmp/x.png",
            on_composed=AsyncMock(return_value=True),
        ))
    assert ok is True
    trans.assert_not_awaited()


def test_upload_png_or_fail_failure_marks_composed_failed():
    import app.s1_ingest.orchestrator as orch

    with patch.object(orch, "transition", new=AsyncMock()) as trans:
        ok = _run(orch._upload_png_or_fail(
            AsyncMock(),
            job_id=uuid.uuid4(),
            png_path="/tmp/x.png",
            on_composed=AsyncMock(return_value=False),
        ))
    assert ok is False
    trans.assert_awaited_once()
    assert trans.await_args.kwargs["target_status"] == "failed"
    assert trans.await_args.kwargs["error_stage"] == "composing"


def test_upload_png_or_fail_exception_marks_composed_failed():
    """on_composed 抛异常 → 同样转 composed→failed（不再静默吞掉）。"""
    import app.s1_ingest.orchestrator as orch

    async def boom(*_a, **_k):
        raise RuntimeError("sftp gone")

    with patch.object(orch, "transition", new=AsyncMock()) as trans:
        ok = _run(orch._upload_png_or_fail(
            AsyncMock(),
            job_id=uuid.uuid4(),
            png_path="/tmp/x.png",
            on_composed=boom,
        ))
    assert ok is False
    trans.assert_awaited_once()


# ── transition 原子 CAS（HIGH-2 修复）─────────────────────────

def test_transition_atomic_stale_current_raises():
    import pytest

    from app.core.pipeline.state_machine import transition

    db = AsyncMock()
    db.execute.return_value = MagicMock(rowcount=0)
    with pytest.raises(RuntimeError):
        _run(transition(
            db,
            job_id=uuid.uuid4(),
            current_status="pending",
            target_status="capturing",
        ))
    # 失败时不提交
    assert db.commit.await_count == 0


def test_transition_atomic_ok_commits():
    from app.core.pipeline.state_machine import transition

    db = AsyncMock()
    db.execute.return_value = MagicMock(rowcount=1)
    _run(transition(
        db,
        job_id=uuid.uuid4(),
        current_status="pending",
        target_status="capturing",
    ))
    assert db.commit.await_count == 1


# ── mark_failed_guarded 所有权 + 状态机（HIGH-3 / MEDIUM-7）────

def _job_cm(status, processing_host):
    """构造 async_session 上下文管理器 mock，返回给定 job。"""
    job = MagicMock(status=status, processing_host=processing_host)
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=lambda: job)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=db)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def test_mark_failed_guarded_skips_non_owner():
    from types import SimpleNamespace

    from app.local_worker.runner import mark_failed_guarded

    cm = _job_cm(status="parsing", processing_host="other-host")
    with (
        patch("app.local_worker.runner.async_session", return_value=cm),
        patch("app.local_worker.runner.worker_settings", SimpleNamespace(worker_host="my-host-1")),
        patch("app.s1_ingest.orchestrator.transition", new=AsyncMock()) as trans,
    ):
        _run(mark_failed_guarded(uuid.uuid4(), "boom"))
    trans.assert_not_awaited()


def test_mark_failed_guarded_owner_uses_transition():
    from types import SimpleNamespace

    from app.local_worker.runner import mark_failed_guarded

    cm = _job_cm(status="parsing", processing_host="my-host-1")
    with (
        patch("app.local_worker.runner.async_session", return_value=cm),
        patch("app.local_worker.runner.worker_settings", SimpleNamespace(worker_host="my-host-1")),
        patch("app.s1_ingest.orchestrator.transition", new=AsyncMock()) as trans,
    ):
        _run(mark_failed_guarded(uuid.uuid4(), "boom"))
    trans.assert_awaited_once()
    assert trans.await_args.kwargs["target_status"] == "failed"
    assert trans.await_args.kwargs["error_stage"] == "worker"


def test_mark_failed_guarded_skips_terminal_ready():
    from types import SimpleNamespace

    from app.local_worker.runner import mark_failed_guarded

    cm = _job_cm(status="ready", processing_host="my-host-1")
    with (
        patch("app.local_worker.runner.async_session", return_value=cm),
        patch("app.local_worker.runner.worker_settings", SimpleNamespace(worker_host="my-host-1")),
        patch("app.s1_ingest.orchestrator.transition", new=AsyncMock()) as trans,
    ):
        _run(mark_failed_guarded(uuid.uuid4(), "boom"))
    trans.assert_not_awaited()
