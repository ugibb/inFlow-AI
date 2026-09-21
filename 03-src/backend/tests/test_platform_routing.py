"""P4：视频号/公众号分流 + 新平台路由 + 视频任务步骤显示修复。

三组断言对应三个已发生的缺陷：

1. 视频号分享链 ``https://weixin.qq.com/sph/<token>`` 与公众号同域，靠路径前缀区分。
   云端原有三处判据都只看域名（``"weixin.qq.com" in url`` / 域前缀正则），
   视频号被误判成公众号 → 落 ``04-output/wechat_article/``。
2. 子串式域名匹配：``"x.com" in url`` 会命中 ``netflix.com``，引入 twitter 前必须先换。
3. ``_EXT_RANK`` 缺 ``preprocessing``/``preprocessed`` → 归 0 → 视频任务整个抽离阶段
   所有步骤都显示"未开始"（现网已发生；接新视频平台前必须先修）。
"""

from __future__ import annotations

import asyncio
import uuid

from backend.core.ingest.adapters.base import AdapterError
from backend.core.ingest.adapters.registry import adapter_registry
from backend.core.ingest.adapters.wechat import WechatAdapter
from backend.core.ingest.fetchers import parser_service
from backend.core.ingest.orchestrator import _infer_content_type
from backend.core.pipeline.pipeline_steps import (
    _EXT_RANK,
    _build_specs,
    _ext_step_done,
)

JOB_ID = uuid.UUID("ffbd2813-5d3b-412d-bb3b-e3cef05c620d")


# ── 1. 视频号 / 公众号分流 ────────────────────────────────────────────


def test_sph_share_link_routes_to_wechat_channels():
    assert adapter_registry.resolve("https://weixin.qq.com/sph/AbCdEf").platform == "wechat_channels"


def test_channels_web_domain_routes_to_wechat_channels():
    """视频号网页域若不认领，会落到 GenericAdapter → 又挤进 generic 目录。"""
    url = "https://channels.weixin.qq.com/web/pages/feed"
    assert adapter_registry.resolve(url).platform == "wechat_channels"


def test_official_account_still_routes_to_wechat():
    for url in (
        "https://mp.weixin.qq.com/s/AbCdEf",
        "https://weixin.qq.com/other/path",
    ):
        assert adapter_registry.resolve(url).platform == "wechat", url


def test_registry_order_puts_channels_before_wechat():
    """先到先得语义：顺序反转时 WechatAdapter 会抢先认领 /sph/。"""
    platforms = adapter_registry.list_platforms()
    assert platforms.index("wechat_channels") < platforms.index("wechat")
    assert platforms[-1] == "generic"


def test_wechat_adapter_declines_sph_as_double_insurance():
    """即使顺序被改坏，WechatAdapter 自己也不接视频号分享链。"""
    assert WechatAdapter().can_handle("https://weixin.qq.com/sph/AbCdEf") is False
    assert WechatAdapter().can_handle("https://mp.weixin.qq.com/s/AbCdEf") is True


# ── 2. 新平台路由 + hostname 匹配 ─────────────────────────────────────


def test_twitter_hosts_route_to_twitter():
    for url in (
        "https://twitter.com/u/status/1",
        "https://www.twitter.com/u/status/1",
        "https://mobile.twitter.com/u/status/1",
        "https://x.com/u/status/1",
        "https://t.co/AbCdEf",
    ):
        assert adapter_registry.resolve(url).platform == "twitter", url


def test_netflix_is_not_twitter():
    """子串实现下 ``"x.com" in "netflix.com"`` 为真 —— hostname 匹配必须挡住。"""
    assert adapter_registry.resolve("https://www.netflix.com/watch/123").platform == "generic"
    assert parser_service.detect_platform("https://www.netflix.com/watch/123") == "other"


def test_detect_platform_ignores_query_string():
    url = "https://example.com/redirect?to=https://bilibili.com/x"
    assert parser_service.detect_platform(url) == "other"


def test_detect_platform_splits_channels_from_official_account():
    assert parser_service.detect_platform("https://weixin.qq.com/sph/AbC") == "wechat_channels"
    assert parser_service.detect_platform("https://channels.weixin.qq.com/web/x") == "wechat_channels"
    assert parser_service.detect_platform("https://mp.weixin.qq.com/s/AbC") == "wechat"
    assert parser_service.detect_platform("https://weixin.qq.com/other/path") == "wechat"


def test_cloud_adapters_refuse_to_fetch():
    """云端无登录态/无本地微信通道 —— 抓取必须显式拒绝，不能静默产出垃圾。"""
    cases = [
        ("https://weixin.qq.com/sph/AbCdEf", "wechat_channels"),
        ("https://x.com/u/status/1", "twitter"),
    ]
    for url, platform in cases:
        adapter = adapter_registry.resolve(url)
        assert adapter.platform == platform
        try:
            asyncio.run(adapter.fetch(url, user_id=uuid.uuid4()))
        except AdapterError as exc:
            assert exc.platform == platform
        else:
            raise AssertionError(f"{platform} adapter 不应实际抓取")


# ── 3. stub content_type 推断 ─────────────────────────────────────────


def test_infer_content_type_video_platforms():
    assert _infer_content_type("youtube", "https://youtu.be/x") == "video"
    assert _infer_content_type("douyin", "https://v.douyin.com/x") == "video"
    assert _infer_content_type("wechat_channels", "https://weixin.qq.com/sph/AbC") == "video"


def test_infer_content_type_bilibili_mixed_by_path():
    assert _infer_content_type("bilibili", "https://www.bilibili.com/video/BV1xx") == "video"
    assert _infer_content_type("bilibili", "https://b23.tv/BV1xx") == "video"
    assert _infer_content_type("bilibili", "https://www.bilibili.com/audio/au123") == "audio"
    assert _infer_content_type("bilibili") == "audio"


def test_infer_content_type_xhs_twitter_stay_article_until_worker_capture():
    """URL 无法区分图文/视频 → 云端不猜，靠 worker capture 回写 raw.content_type。"""
    assert _infer_content_type("xhs", "https://www.xiaohongshu.com/explore/abc") == "article"
    assert _infer_content_type("twitter", "https://x.com/u/status/1") == "article"
    assert _infer_content_type("wechat", "https://mp.weixin.qq.com/s/AbC") == "article"


# ── 4. 视频任务步骤显示（_EXT_RANK 修复）─────────────────────────────


def test_ext_rank_covers_every_worker_status():
    for status in (
        "pending", "capturing", "captured",
        "preprocessing", "preprocessed",
        "normalizing", "normalized",
        "transcribing", "transcribed",
        "parsing", "parsed",
        "composing", "composed",
        "indexing", "ready",
    ):
        assert status in _EXT_RANK, f"_EXT_RANK 缺 {status}：会归 0，整条流水线显示未开始"


def test_video_chain_rank_is_monotonic():
    chain = [
        "capturing", "captured",
        "preprocessing", "preprocessed",
        "transcribing", "transcribed",
        "parsing", "parsed",
        "composing", "composed",
        "indexing", "ready",
    ]
    ranks = [_EXT_RANK[s] for s in chain]
    assert ranks == sorted(ranks)


def test_extract_phase_marks_download_done_and_extract_active():
    """回归：修复前 preprocessing 不在 _EXT_RANK → 0 → 资源/视频步全显示"未开始"。"""
    assert _ext_step_done("capture", "preprocessing")
    assert _ext_step_done("video_download", "preprocessing")
    # 正在跑的抽离/截图两步显示 active（未 done）
    assert not _ext_step_done("extract_audio", "preprocessing")
    assert not _ext_step_done("screenshots", "preprocessing")


def test_preprocessed_marks_extract_and_screenshots_done():
    """回归：修复前 ``extract_audio``/``screenshots`` 不在表内 → 阈值 99 → 永不 done。"""
    assert _ext_step_done("extract_audio", "preprocessed")
    assert _ext_step_done("screenshots", "preprocessed")
    assert not _ext_step_done("transcribe", "preprocessed")


def test_transcribe_and_later_steps_done_by_rank():
    assert not _ext_step_done("transcribe", "transcribing")
    assert _ext_step_done("transcribe", "transcribed")
    assert _ext_step_done("transcribe", "parsing")
    assert not _ext_step_done("parse", "parsing")
    assert _ext_step_done("parse", "parsed")
    assert not _ext_step_done("index", "composed")
    assert _ext_step_done("index", "ready")


def test_audio_branch_unaffected_by_new_ranks(tmp_path):
    """音频管线不经 preprocessing，新增档位不得改变其显示。"""
    raw = _make_raw(tmp_path)
    specs = _build_specs("audio", raw, JOB_ID)
    ids = [s.id for s in specs]
    assert "extract_audio" not in ids and "screenshots" not in ids
    assert _ext_step_done("capture", "capturing") is False
    assert _ext_step_done("capture", "captured") is True
    assert _ext_step_done("media_download", "captured") is True
    assert _ext_step_done("transcribe", "normalized") is True


def test_capture_step_claims_manual_action_failures(tmp_path):
    """视频号的人工介入失败要定位到「资源」步，前端才渲染得出重试入口。"""
    specs = _build_specs("video", _make_raw(tmp_path), JOB_ID)
    capture = next(s for s in specs if s.id == "capture")
    assert "manual_action" in capture.error_keys
    assert "capturing" in capture.error_keys


def _make_raw(tmp_path) -> str:
    ingest = tmp_path / "01_ingest"
    ingest.mkdir(exist_ok=True)
    raw = ingest / f"{JOB_ID}.json"
    raw.write_text("{}", encoding="utf-8")
    return str(raw)
