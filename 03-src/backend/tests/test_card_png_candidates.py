"""card_png_candidates —— 卡片 PNG 云端候选路径（新旧管线登记形态兼容）单测。

覆盖（纯路径函数，无 IO / 无 DB）：
- worker 相对形态 ``04-output/01_ingest/...`` → 剥前缀拼 pipeline_data_dir
- 云端 ``data/01_ingest/...`` 形态 → 剥 ``data/`` 前缀拼根
- 旧云端管线绝对形态 → 单候选（换段即真实位置）
- pipeline_data_dir 为空 → 仅保留换段候选（行为与旧 display_card_png_path 一致）
"""

from __future__ import annotations

import uuid

from backend.core.shared.storage.conventions import card_png_candidates

JOB_ID = uuid.UUID("ffbd2813-5d3b-412d-bb3b-e3cef05c620d")
PIPELINE_DIR = "/www/data/inflow/pipeline"


def test_worker_relative_form_appends_pipeline_root():
    raw = f"04-output/01_ingest/wechat/20260830/002-标题/{JOB_ID}.json"

    got = card_png_candidates(raw, JOB_ID, pipeline_data_dir=PIPELINE_DIR)

    assert got == [
        f"04-output/03_display/wechat/20260830/002-标题/{JOB_ID}.png",  # 换段原样
        f"{PIPELINE_DIR}/03_display/wechat/20260830/002-标题/{JOB_ID}.png",  # SFTP 落盘位
    ]


def test_data_prefix_form_strips_data_root():
    raw = f"data/01_ingest/xiaoyuzhou/20260621/001-标题/{JOB_ID}.json"

    got = card_png_candidates(raw, JOB_ID, pipeline_data_dir=PIPELINE_DIR)

    assert got[1] == f"{PIPELINE_DIR}/03_display/xiaoyuzhou/20260621/001-标题/{JOB_ID}.png"


def test_absolute_cloud_form_keeps_single_candidate():
    raw = f"/www/data/inflow/pipeline/01_ingest/wechat/20260618/001-标题/{JOB_ID}.json"

    got = card_png_candidates(raw, JOB_ID, pipeline_data_dir=PIPELINE_DIR)

    # 绝对路径换段后已是真实位置；无前缀可剥，不追加候选
    assert got == [f"/www/data/inflow/pipeline/03_display/wechat/20260618/001-标题/{JOB_ID}.png"]


def test_empty_pipeline_dir_returns_direct_only():
    raw = f"04-output/01_ingest/wechat/20260830/002-标题/{JOB_ID}.json"

    got = card_png_candidates(raw, JOB_ID, pipeline_data_dir="")

    assert got == [f"04-output/03_display/wechat/20260830/002-标题/{JOB_ID}.png"]


def test_new_worker_layout_step_is_final_component():
    """worker 重构后目录约定：{platform}/{date}-{index}-{title}/{step}/{file}，
    step 是路径末段（无尾斜杠），换段仍须命中 03_display。"""
    raw = f"04-output/xiaoyuzhou/20260904-001-152_领读/01_ingest/{JOB_ID}.json"

    got = card_png_candidates(raw, JOB_ID, pipeline_data_dir=PIPELINE_DIR)

    assert got == [
        f"04-output/xiaoyuzhou/20260904-001-152_领读/03_display/{JOB_ID}.png",
        f"{PIPELINE_DIR}/xiaoyuzhou/20260904-001-152_领读/03_display/{JOB_ID}.png",
    ]
