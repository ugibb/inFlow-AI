"""本地独立 worker —— 承接 inFlow 完整 pipeline（采集→转录→parse→compose→index）。

云端只保留入口/存储/展示/推送；本地 worker 直连云端 PostgreSQL 作为任务总线，
经 SFTP 把卡片 PNG 回传云端（无需新开 API）。

模块：
    settings — 调度/回传配置（SCAN_INTERVAL_S / LEASE_SECONDS / SFTP_HOST …）
    claims   — 原子认领 / 租约 / 心跳回收
    runner   — 每 job 执行（复用云端 run_job_resume 断点续跑）+ SFTP PNG 回传
    __main__ — 主循环入口（python -m inflow_worker）
"""
