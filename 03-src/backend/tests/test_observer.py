"""云端观测告警 —— 纯判定/去重/恢复逻辑单测（无 PostgreSQL 依赖）。

覆盖 4 类告警（进度停滞 / 租约超时 / 日失败率 / worker 失联）：
- 首次命中必告警；未恢复前不重复告警（去重）
- 告警对象离开查询结果视为「恢复」→ 重置标记，允许再次告警
- 多新对象同批全部告警
- Observer.run_pass 组合注入查询端到端产出消息
"""
from __future__ import annotations

import asyncio

from backend.core.observer import (
    Observer,
    check_fail_rate,
    check_leases,
    check_stalled,
    check_workers,
)


def test_stall_alerts_once_then_resets() -> None:
    alerted: set[str] = set()
    rows = [{"id": "a", "status": "parsing", "processing_host": "h1", "stale_minutes": 12.0}]

    # 首次命中 → 1 条 WARNING
    msgs = check_stalled(rows, alerted)
    assert len(msgs) == 1
    level, text = msgs[0]
    assert level == "WARNING"
    assert "job=a" in text and "12.0" in text

    # 未恢复前重复巡检 → 不重复告警
    assert check_stalled(rows, alerted) == []

    # job 恢复（不在结果里）→ 标记重置，可再次告警
    assert check_stalled([], alerted) == []
    assert check_stalled(rows, alerted) == msgs


def test_stall_multiple_new_jobs_all_alert() -> None:
    alerted: set[str] = set()
    rows = [
        {"id": "a", "status": "parsing", "processing_host": None, "stale_minutes": 11.0},
        {"id": "b", "status": "indexing", "processing_host": "h2", "stale_minutes": 40.0},
    ]
    msgs = check_stalled(rows, alerted)
    assert len(msgs) == 2
    assert {m[1].split("job=")[1].split(" ")[0] for m in msgs} == {"a", "b"}


def test_lease_dedup_and_reset() -> None:
    alerted: set[str] = set()
    rows = [{"id": "x", "status": "transcribing", "processing_host": "w1", "lease_minutes": 15.0}]
    msgs = check_leases(rows, alerted)
    assert len(msgs) == 1 and msgs[0][0] == "WARNING" and "lease=15.0" in msgs[0][1]
    assert check_leases(rows, alerted) == []
    assert check_leases([], alerted) == []
    assert len(check_leases(rows, alerted)) == 1


def test_fail_rate_dedup_by_day() -> None:
    alerted: set[str] = set()
    rows = [{"day": "2026-08-25", "failed": 5, "ready": 3, "fail_rate": 0.625}]
    msgs = check_fail_rate(rows, alerted)
    assert len(msgs) == 1 and "0.625" in msgs[0][1]
    # 同一天持续命中不重复告警
    assert check_fail_rate(rows, alerted) == []
    # 跨天不冲突
    next_day = [{"day": "2026-08-26", "failed": 2, "ready": 1, "fail_rate": 0.667}]
    assert len(check_fail_rate(next_day, alerted)) == 1


def test_worker_dedup_by_host_and_reset() -> None:
    alerted: set[str] = set()
    rows = [
        {
            "processing_host": "pc-01",
            "last_seen": "2026-08-25 09:00:00+00",
            "gone_minutes": 20.0,
            "in_flight": 2,
        }
    ]
    msgs = check_workers(rows, alerted)
    assert len(msgs) == 1
    level, text = msgs[0]
    assert level == "ERROR"
    assert "host=pc-01" in text and "20.0" in text and "in_flight=2" in text
    assert check_workers(rows, alerted) == []
    assert check_workers([], alerted) == []
    assert len(check_workers(rows, alerted)) == 1


def test_observer_run_pass_combines_injected_queries() -> None:
    async def q_stall() -> list[dict]:
        return [{"id": "s1", "status": "parsing", "processing_host": None, "stale_minutes": 11.0}]

    async def q_lease() -> list[dict]:
        return [{"id": "l1", "status": "transcribing", "processing_host": "w", "lease_minutes": 12.0}]

    async def q_fail_rate() -> list[dict]:
        return [{"day": "2026-08-25", "failed": 4, "ready": 2, "fail_rate": 0.667}]

    async def q_worker() -> list[dict]:
        return [{"processing_host": "pc", "last_seen": "x", "gone_minutes": 30.0, "in_flight": 1}]

    observer = Observer(
        queries={"stall": q_stall, "lease": q_lease, "fail_rate": q_fail_rate, "worker": q_worker}
    )
    alerts = asyncio.run(observer.run_pass())
    assert len(alerts) == 4
    levels = {level for level, _ in alerts}
    assert levels == {"WARNING", "ERROR"}  # 只有 worker 失联是 ERROR

    # 二次巡检：无新对象 → 空（去重生效）
    assert asyncio.run(observer.run_pass()) == []


def test_observer_interval_sec() -> None:
    assert Observer(interval_sec=600).interval_sec == 600
