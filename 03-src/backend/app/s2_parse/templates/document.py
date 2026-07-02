"""Document parse template — handles PDF, DOCX, EPUB, and other uploaded files.

Document content is typically already in Markdown after MarkItDown conversion.
This template produces a structured summary without heavy reformatting.
"""

from __future__ import annotations

import logging
from app.s1_ingest.schema import RawCapture
from app.s2_parse.schema import ParsedArticle
from app.s2_parse.templates.base import AbstractTemplate

logger = logging.getLogger("inFlow.parse.templates.document")


class DocumentTemplate(AbstractTemplate):
    template_id = "document"
    platform = "upload"
    version = "1.0"

    def build_prompt(self, raw: RawCapture) -> str:
        filename = raw.raw.extra.get("filename", "")
        title = raw.raw.title or filename or "上传文档"
        content = raw.raw.raw_text or ""
        # Documents can be long — use a longer snippet
        content_snippet = content[:10000]

        return f"""你是一个文档分析助手。请分析以下上传文档，提取结构化信息。

【文档信息】
文件名: {filename}
标题: {title}
内容（前10000字符）:
{content_snippet}

【输出要求】
严格输出以下 JSON 格式，不要有任何额外文字：

{{
  "title": "文档标题",
  "summary": "5句话摘要，概括文档核心内容和目的",
  "key_points": ["核心论点或章节要点1", "要点2", "要点3"],
  "tags": ["标签1", "标签2"],
  "author": "作者（文档内有则填写，否则留空）",
  "clean_content": "Markdown 格式整理后的文档内容，保留主要章节结构",
  "reading_time": 10,
  "word_count": 3000
}}

注意：
- 对于长文档，clean_content 可以是核心章节的摘要，不必复制全文
- key_points 应反映文档的主要论点或结论
- 学术文档请保留方法论和核心发现
"""

    def parse_response(self, llm_output: str) -> ParsedArticle:
        return self.llm_output_to_article(llm_output)
