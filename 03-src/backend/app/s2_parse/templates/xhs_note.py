"""Xiaohongshu (小红书) note parse template.

XHS notes are short-form: title, body text (often emoji-heavy), and
hashtags.  The prompt strips noise and extracts the useful knowledge.
"""

from __future__ import annotations

import logging
from app.s1_ingest.schema import RawCapture
from app.s2_parse.schema import ParsedArticle
from app.s2_parse.templates.base import AbstractTemplate

logger = logging.getLogger("inFlow.parse.templates.xhs_note")


class XhsNoteTemplate(AbstractTemplate):
    template_id = "xhs_note"
    platform = "xhs"
    version = "1.0"

    def build_prompt(self, raw: RawCapture) -> str:
        title = raw.raw.title or ""
        author = raw.raw.author or ""
        content = raw.raw.raw_text or raw.raw.raw_html or ""
        content_snippet = content[:4000]

        return f"""你是一个小红书内容分析助手。请分析以下小红书笔记，提取有价值的信息。

【笔记信息】
标题: {title}
作者: {author}
内容:
{content_snippet}

【输出要求】
严格输出以下 JSON 格式，不要有任何额外文字：

{{
  "title": "笔记标题（去掉多余表情符号）",
  "summary": "3-5句话概括笔记核心内容",
  "key_points": ["实用信息点1", "实用信息点2"],
  "tags": ["标签1", "标签2"],
  "author": "作者名称",
  "clean_content": "Markdown 格式内容，去除表情符号和引流话术，保留实质内容",
  "reading_time": 2,
  "word_count": 300
}}

注意：
- 小红书笔记通常较短，summary 可以是 3 句话
- 去除表情符号、「点赞收藏关注」等引流话术
- 保留实用的方法、步骤、推荐等核心内容
"""

    def parse_response(self, llm_output: str) -> ParsedArticle:
        return self.llm_output_to_article(llm_output)
