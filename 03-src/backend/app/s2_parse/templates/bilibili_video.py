"""Bilibili video/article parse template.

For videos the raw content may contain:
- Video description (desc)
- Subtitle text or ASR transcript
- Up主 info

For articles (专栏/opus) it's standard article HTML converted to text.
"""

from __future__ import annotations

import logging
from app.s1_ingest.schema import RawCapture
from app.s2_parse.schema import ParsedArticle
from app.s2_parse.templates.base import AbstractTemplate

logger = logging.getLogger("trove.parse.templates.bilibili_video")


class BilibiliVideoTemplate(AbstractTemplate):
    template_id = "bilibili_video"
    platform = "bilibili"
    version = "1.0"

    def build_prompt(self, raw: RawCapture) -> str:
        title = raw.raw.title or ""
        author = raw.raw.author or ""
        content_type = raw.raw.content_type
        content = raw.raw.raw_text or ""
        content_snippet = content[:8000]

        type_hint = "视频（含字幕/ASR转录）" if content_type == "video" else "专栏文章"

        return f"""你是一个 B站内容分析助手。请分析以下 B站{type_hint}，提取结构化信息。

【内容信息】
标题: {title}
UP主: {author}
内容类型: {type_hint}
内容:
{content_snippet}

【输出要求】
严格输出以下 JSON 格式，不要有任何额外文字：

{{
  "title": "内容标题",
  "summary": "5句话概括核心内容",
  "key_points": ["核心观点或知识点1", "核心观点2", "核心观点3"],
  "tags": ["标签1", "标签2"],
  "author": "UP主名称",
  "clean_content": "Markdown 格式内容整理，视频则以字幕为主体",
  "reading_time": 5,
  "word_count": 1000
}}

注意：
- 若为视频且有字幕，clean_content 应整理字幕为连贯的文字内容
- 若字幕质量差（如 ASR 转录错误），请适当纠正明显错误
- key_points 突出最有价值的信息点
"""

    def parse_response(self, llm_output: str) -> ParsedArticle:
        return self.llm_output_to_article(llm_output)
