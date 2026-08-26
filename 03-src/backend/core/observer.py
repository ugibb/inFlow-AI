"""云端观测告警 —— 兜住「worker 长时间失联无人知」。

口径对齐 worker 仓库 deploy/cloud/alerts.sql（framework/scheduler/observer.py
的云端聚合侧）：
    - 进度停滞 >10min（进行中 job 的 updated_at 陈旧）
    - 租约超时   >10min（claimed_at 陈旧，lease=600s）
    - 日失败率   >30%  （failed/(ready+failed)，按天）
    - worker 失联      （processing_host 最后活跃 >10min）

轻量巡检：每 OBSERVER_INTERVAL_SEC（默认 300s）跑 4 条 SELECT，命中写
WARNING/ERROR 日志。同一告警对象只报一次，恢复后重置可再报。
单次巡检异常仅告警不崩——观测循环本身不是故障点。
"""
from __future__ import annotations

import asyncio
from typing import Callable, Dict, List, Tuple

from sqlalchemy import text

from backend.core.config import get_settings
from backend.core.utils.logger import get_logger

# 进行中状态（与 worker settings 一致；租约/停滞只盯这些）
_ACTIVE_STATUSES = (
    "capturing", "captured",
    "normalizing", "normalized",
    "transcribing", "transcribed",
    "parsing", "parsed",
    "composing", "composed",
    "indexing",
)

# 告警消息 = (level, text)；level 用于日志级别区分
Alert = Tuple[str, str]

# 查询函数签名：async () -> list[dict]（每行是告警候选，字段由 check_* 消费）
Query = Callable[[], "list[dict]"]


def _in(values: tuple[str, ...]) -> str:
    """把常量状态列表拼进 SQL IN 子句（非用户输入，无注入风险）。"""
    return ", ".join(f"'{v}'" for v in values)


# ── 真实查询（默认注入）──────────────────────────────────────────
async def _fetch(sql: str) -> list[dict]:
    """在 async engine 上执行 SELECT，返回 dict 行列表。"""
    from backend.core.database import async_session

    async with async_session() as session:
        result = await session.execute(text(sql))
        return [dict(r) for r in result.mappings().all()]


async def _q_stall() -> list[dict]:
    sql = f"""
        SELECT id, status, processing_host,
               ROUND(EXTRACT(EPOCH FROM (now() - updated_at)) / 60, 1) AS stale_minutes
        FROM ingest_jobs
        WHERE status IN ({_in(_ACTIVE_STATUSES)})
          AND claimed_at IS NOT NULL
          AND updated_at < now() - interval '10 minutes'
        ORDER BY stale_minutes DESC
    """
    return await _fetch(sql)


async def _q_lease() -> list[dict]:
    sql = f"""
        SELECT id, status, processing_host,
               ROUND(EXTRACT(EPOCH FROM (now() - claimed_at)) / 60, 1) AS lease_minutes
        FROM ingest_jobs
        WHERE status IN ({_in(_ACTIVE_STATUSES)})
          AND claimed_at IS NOT NULL
          AND claimed_at < now() - interval '10 minutes'
        ORDER BY lease_minutes DESC
    """
    return await _fetch(sql)


async def _q_fail_rate() -> list[dict]:
    sql = """
        SELECT date_trunc('day', created_at)::date AS day,
               COUNT(*) FILTER (WHERE status = 'failed') AS failed,
               COUNT(*) FILTER (WHERE status = 'ready')  AS ready,
               ROUND(
                   COUNT(*) FILTER (WHERE status = 'failed')::numeric
                   / NULLIF(COUNT(*) FILTER (WHERE status IN ('ready','failed')), 0),
                   3
               ) AS fail_rate
        FROM ingest_jobs
        WHERE created_at >= date_trunc('day', now())
          AND status IN ('ready', 'failed')
        GROUP BY 1
        HAVING COUNT(*) FILTER (WHERE status = 'failed') > 0
           AND COUNT(*) FILTER (WHERE status = 'failed')::numeric
               / NULLIF(COUNT(*) FILTER (WHERE status IN ('ready','failed')), 0) > 0.3
        ORDER BY day DESC
    """
    return await _fetch(sql)


async def _q_worker() -> list[dict]:
    sql = """
        SELECT processing_host,
               MAX(claimed_at) AS last_seen,
               ROUND(EXTRACT(EPOCH FROM (now() - MAX(claimed_at))) / 60, 1) AS gone_minutes,
               COUNT(*) FILTER (WHERE status NOT IN ('ready','failed','cancelled')) AS in_flight
        FROM ingest_jobs
        WHERE processing_host IS NOT NULL
        GROUP BY processing_host
        HAVING MAX(claimed_at) < now() - interval '10 minutes'
        ORDER BY gone_minutes DESC
    """
    return await _fetch(sql)


# ── 纯判定逻辑（无 DB 依赖，可单测）──────────────────────────────
# 约定：alerted 是调用方持有的 set（按类别各自一个）；命中即写入防重复；
#      行不再出现在查询结果里视为「恢复」，intersection_update 重置标记。


def check_stalled(rows: list[dict], alerted: set[str]) -> list[Alert]:
    """进度停滞 >10min：按 job_id 去重，恢复后重置。"""
    messages: list[Alert] = []
    seen = {str(r["id"]) for r in rows}
    for r in rows:
        jid = str(r["id"])
        if jid in alerted:
            continue
        alerted.add(jid)
        messages.append((
            "WARNING",
            f"[云端观测] 进度停滞>10min job={jid} status={r['status']} "
            f"host={r.get('processing_host')} stale={r['stale_minutes']}min",
        ))
    alerted.intersection_update(seen)
    return messages


def check_leases(rows: list[dict], alerted: set[str]) -> list[Alert]:
    """租约超时 >10min：按 job_id 去重，恢复后重置。"""
    messages: list[Alert] = []
    seen = {str(r["id"]) for r in rows}
    for r in rows:
        jid = str(r["id"])
        if jid in alerted:
            continue
        alerted.add(jid)
        messages.append((
            "WARNING",
            f"[云端观测] 租约超时>10min job={jid} status={r['status']} "
            f"host={r.get('processing_host')} lease={r['lease_minutes']}min",
        ))
    alerted.intersection_update(seen)
    return messages


def check_fail_rate(rows: list[dict], alerted: set[str]) -> list[Alert]:
    """日失败率 >30%：按天去重，该天有数据则持续告警直到不再命中。"""
    messages: list[Alert] = []
    seen = {str(r["day"]) for r in rows}
    for r in rows:
        day = str(r["day"])
        if day in alerted:
            continue
        alerted.add(day)
        messages.append((
            "WARNING",
            f"[云端观测] 日失败率>30% day={day} failed={r['failed']} "
            f"ready={r['ready']} rate={r['fail_rate']}",
        ))
    alerted.intersection_update(seen)
    return messages


def check_workers(rows: list[dict], alerted: set[str]) -> list[Alert]:
    """worker 失联 >10min：按 processing_host 去重，恢复后重置。"""
    messages: list[Alert] = []
    seen = {str(r["processing_host"]) for r in rows}
    for r in rows:
        host = str(r["processing_host"])
        if host in alerted:
            continue
        alerted.add(host)
        messages.append((
            "ERROR",
            f"[云端观测] worker 失联>10min host={host} "
            f"last_seen={r['last_seen']} gone={r['gone_minutes']}min "
            f"in_flight={r['in_flight']}",
        ))
    alerted.intersection_update(seen)
    return messages


# ── 巡检编排 ─────────────────────────────────────────────────────
_DEFAULT_QUERIES: Dict[str, Query] = {
    "stall": _q_stall,
    "lease": _q_lease,
    "fail_rate": _q_fail_rate,
    "worker": _q_worker,
}


class Observer:
    """一次巡检 = 并行跑 4 类查询 → 纯判定 → 日志告警。

    queries 可注入（测试用假数据），默认真实 SQL。
    """

    def __init__(
        self,
        queries: Dict[str, Query] | None = None,
        interval_sec: int = 300,
    ) -> None:
        self._queries = queries or _DEFAULT_QUERIES
        self._interval_sec = interval_sec
        self._stall_alerted: set[str] = set()
        self._lease_alerted: set[str] = set()
        self._fail_rate_alerted: set[str] = set()
        self._worker_alerted: set[str] = set()

    @property
    def interval_sec(self) -> int:
        return self._interval_sec

    async def run_pass(self) -> list[Alert]:
        """跑一次巡检，返回命中的告警消息（由调用方负责落日志）。"""
        results = await asyncio.gather(
            self._queries["stall"](),
            self._queries["lease"](),
            self._queries["fail_rate"](),
            self._queries["worker"](),
        )
        messages: list[Alert] = []
        messages += check_stalled(results[0], self._stall_alerted)
        messages += check_leases(results[1], self._lease_alerted)
        messages += check_fail_rate(results[2], self._fail_rate_alerted)
        messages += check_workers(results[3], self._worker_alerted)
        return messages


async def observer_loop() -> None:
    """常驻巡检循环：命中写日志，单次异常不崩。main.py lifespan 中启动。"""
    observer = Observer(interval_sec=get_settings().observer_interval_sec)
    logger = get_logger("observer")
    logger.info("云端观测告警已启动（间隔 %ss）", observer.interval_sec)
    while True:
        try:
            alerts = await observer.run_pass()
            for level, message in alerts:
                if level == "ERROR":
                    logger.error(message)
                else:
                    logger.warning(message)
        except Exception:
            logger.exception("观测巡检异常（本次跳过，循环继续）")
        await asyncio.sleep(observer.interval_sec)
