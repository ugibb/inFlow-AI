"""Generic parse template — fallback for any platform without a dedicated template.

Used for: douyin, youtube, toutiao, juejin, csdn, and unknown platforms.
Produces a standard ParsedArticle with title, summary, key_points, tags,
and clean Markdown content.
"""

from __future__ import annotations

import logging
from inflow_core.ingest.schema import RawCapture
from inflow_core.parse.schema import ParsedArticle
from inflow_core.parse.templates.base import AbstractTemplate

logger = logging.getLogger("inFlow.parse.templates.generic")

_SCHEMA_HINT = """{
  "title": "文章标题",
  "summary": "5句话摘要",
  "key_points": ["要点1", "要点2", "要点3"],
  "tags": ["标签1", "标签2"],
  "author": "作者名",
  "clean_content": "Markdown 正文...",
  "reading_time": 5,
  "word_count": 1200
}"""


class GenericTemplate(AbstractTemplate):
    template_id = "generic"
    platform = "generic"
    version = "1.0"

    def build_prompt(self, raw: RawCapture) -> str:
        title = raw.raw.title or ""
        author = raw.raw.author or ""
        content = raw.raw.raw_text or raw.raw.raw_html or ""
        content_snippet = content[:6000]

        return f"""你是一个内容分析助手。请分析以下网页内容，提取结构化信息，用于知识库建设。

【原始内容】
标题: {title}
作者: {author}
内容:
{content_snippet}

【输出要求】
严格输出如下 JSON 格式，不要有任何额外文字：

{_SCHEMA_HINT}

字段说明：
- title: 文章标题（若原标题清晰则直接使用，否则根据内容生成）
- summary: 用 5 句话概括核心内容，每句话完整表达一个要点
- key_points: 提炼 3-8 个核心观点或知识点
- tags: 提取 3-6 个标签（主题词 + 领域词，如"产品设计"、"AI"）
- author: 作者名（不确定则留空字符串）
- clean_content: 将原文整理为结构清晰的 Markdown 格式，保留核心内容，去除广告和无关信息
- reading_time: 估算阅读分钟数（中文 300 字/分钟）
- word_count: 正文字符数估算
"""

    def parse_response(self, llm_output: str) -> ParsedArticle:
        return self.llm_output_to_article(llm_output)
