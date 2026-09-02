"""articles 内容字段接口（022 迁移后读 DB）单元测试——无 PostgreSQL 依赖。

覆盖：
- ``GET /articles/{id}/chapters``：读 articles.chapters JSONB（worker 直写富格式）；
  total_duration 缺失时从 transcript 补；空值 404
- ``GET /articles/{id}/transcript``：读 articles.transcript，返回前端 JobTranscript 结构；空值 404
- ``GET /articles/{id}/deep-read``：读 articles.deep_read_html；空值 404
- ``GET /articles/{id}``：media_url 字段优先于 _get_ingest_extras 文件兜底
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backend.core.models.article import Article
from backend.routers.articles import (
    _content_block_summary,
    get_article,
    get_article_chapters,
    get_article_deep_read,
    get_article_transcript,
)

# ── Fakes ──────────────────────────────────────────────────────────────────


class FakeSession:
    """最小 AsyncSession 替身：db.get(Article, id) 返回预置 article。"""

    def __init__(self, article: Article | None) -> None:
        self._article = article

    async def get(self, model, pk):
        return self._article if model is Article else None


def _admin() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), is_super_admin=True)


def _article(**overrides) -> Article:
    base = dict(
        id=uuid.uuid4(),
        title="一期播客",
        content_type="audio",
        user_id=None,
        chapters=None,
        transcript=None,
        deep_read_html=None,
        media_url=None,
        raw_content=None,
        cover_image=None,
        # model_validate 必填字段（真实 DB 行均有值，fake 需显式给）
        status="unread",
        fetch_status="completed",
        is_favorited=False,
        word_count=0,
        reading_time=0,
    )
    base.update(overrides)
    return Article(**base)


# ── chapters ───────────────────────────────────────────────────────────────


def test_chapters_returns_rich_format_from_db():
    payload = {
        "version": "1.0", "total_duration": 3600.0,
        "chapters": [{"index": 1, "title": "开场", "start_time": 0.0,
                      "end_time": 120.0, "summary": "自我介绍"}],
    }
    article = _article(chapters=payload)

    got = asyncio_run(get_article_chapters(article.id, FakeSession(article), _admin()))
    assert got == payload  # 前端 ArticleChaptersResponse 逐字段一致


def test_chapters_fills_total_duration_from_transcript():
    payload = {"version": "1.0", "total_duration": 0,
               "chapters": [{"index": 1, "title": "开场", "start_time": 0.0}]}
    article = _article(chapters=payload, transcript={"language": "zh", "duration": 5400.5, "segments": []})

    got = asyncio_run(get_article_chapters(article.id, FakeSession(article), _admin()))
    assert got["total_duration"] == 5400.5


def test_chapters_empty_returns_404():
    article = _article(chapters=None)
    with pytest.raises(HTTPException) as e:
        asyncio_run(get_article_chapters(article.id, FakeSession(article), _admin()))
    assert e.value.status_code == 404


# ── transcript ─────────────────────────────────────────────────────────────


def test_transcript_returns_job_transcript_shape():
    article = _article(transcript={
        "language": "zh", "duration": 3600.5,
        "segments": [{"start": 0.0, "end": 3.2, "text": "大家好"}],
    })

    got = asyncio_run(get_article_transcript(article.id, FakeSession(article), _admin()))
    assert got == {"language": "zh", "duration": 3600.5,
                   "segments": [{"start": 0.0, "end": 3.2, "text": "大家好"}]}


def test_transcript_missing_returns_404():
    article = _article(transcript=None)
    with pytest.raises(HTTPException) as e:
        asyncio_run(get_article_transcript(article.id, FakeSession(article), _admin()))
    assert e.value.status_code == 404


# ── deep-read ──────────────────────────────────────────────────────────────


def test_deep_read_returns_html_from_db():
    article = _article(deep_read_html="<div>card</div>")
    res = asyncio_run(get_article_deep_read(article.id, FakeSession(article), _admin()))
    assert res.status_code == 200
    assert res.body == b"<div>card</div>"


def test_deep_read_missing_returns_404():
    article = _article(deep_read_html=None)
    with pytest.raises(HTTPException) as e:
        asyncio_run(get_article_deep_read(article.id, FakeSession(article), _admin()))
    assert e.value.status_code == 404


# ── get_article media_url 字段优先 ─────────────────────────────────────────


def test_get_article_prefers_db_media_url_over_file_fallback():
    article = _article(media_url="https://cdn.example.com/audio.m4a?sign=db")

    async def fake_extras(db, article_id):
        return ("https://cdn.example.com/audio.m4a?sign=file", None, None, None)

    with patch("backend.routers.articles._get_ingest_extras", new=AsyncMock(side_effect=fake_extras)):
        detail = asyncio_run(get_article(article.id, FakeSession(article), _admin()))

    assert detail.media_url == "https://cdn.example.com/audio.m4a?sign=db"


def test_get_article_falls_back_to_file_media_url():
    article = _article(media_url=None)

    async def fake_extras(db, article_id):
        return ("https://cdn.example.com/audio.m4a?sign=file", "raw text", None, None)

    with patch("backend.routers.articles._get_ingest_extras", new=AsyncMock(side_effect=fake_extras)):
        detail = asyncio_run(get_article(article.id, FakeSession(article), _admin()))

    assert detail.media_url == "https://cdn.example.com/audio.m4a?sign=file"
    assert detail.raw_content == "raw text"


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


# ── content_blocks 存在性快照（read 页生成进度 / 单块重生成入口的依据）────────


def _rich_chapters() -> dict:
    return {"version": "1.0", "total_duration": 3600.0,
            "chapters": [{"index": 1, "title": "开场", "start_time": 0.0,
                          "end_time": 120.0, "summary": "自我介绍"}]}


def test_content_blocks_audio_full_pipeline_all_present():
    article = _article(
        content_type="audio",
        raw_content="节目信息：主理人访谈",
        chapters=_rich_chapters(),
        transcript={"language": "zh", "duration": 3600.0, "segments": [{"start": 0.0, "end": 1.0, "text": "你好"}]},
        deep_read_html="<div>卡片</div>",
        summary="本期聊了……",
        key_points=["要点一"],
    )
    cb = _content_block_summary(article)
    # 音频 raw（节目信息）不可独立重生成 → 不参与进度
    assert cb["raw"] == {"applicable": False, "present": True}
    assert cb["transcript"] == {"applicable": True, "present": True}
    assert cb["chapters"] == {"applicable": True, "present": True}
    assert cb["deepRead"] == {"applicable": True, "present": True}
    assert cb["ai"] == {"applicable": True, "present": True}


def test_content_blocks_article_partial_flags_missing():
    article = _article(
        content_type="article",
        raw_content="正文抓取成功",
        chapters=None,          # 缺章节
        transcript=None,        # article 不适用
        deep_read_html=None,    # 缺精读
        summary="",             # 缺 AI
        key_points=[],
    )
    cb = _content_block_summary(article)
    assert cb["raw"] == {"applicable": True, "present": True}
    assert cb["transcript"] == {"applicable": False, "present": False}
    assert cb["chapters"] == {"applicable": True, "present": False}
    assert cb["deepRead"] == {"applicable": True, "present": False}
    assert cb["ai"] == {"applicable": True, "present": False}


def test_content_blocks_notes_only_ai_applicable():
    article = _article(content_type="note", raw_content=None, summary=None)
    cb = _content_block_summary(article)
    assert cb["raw"]["applicable"] is False
    assert cb["deepRead"]["applicable"] is False
    assert cb["ai"] == {"applicable": True, "present": False}


def test_content_blocks_video_and_fallback_raw():
    article = _article(content_type="video", raw_content=None, summary=None)
    # raw 未写回 DB，但 ingest 文件里仍有原文兜底 → present 应来自 raw_fallback
    cb = _content_block_summary(article, raw_fallback="文件兜底原文")
    assert cb["raw"] == {"applicable": True, "present": True}
    assert cb["ai"]["present"] is False
