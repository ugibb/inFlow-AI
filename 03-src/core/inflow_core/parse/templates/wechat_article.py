"""WeChat Official Account article parse template.

WeChat articles are typically long-form text with images.  This template
focuses on extracting clean Markdown with preserved structure, identifying
the author's main argument, and generating contextual tags for the
Chinese tech/business knowledge domain.
"""

from __future__ import annotations

import logging
from inflow_core.ingest.schema import RawCapture
from inflow_core.parse.schema import ParsedArticle
from inflow_core.parse.templates.base import AbstractTemplate

logger = logging.getLogger("inFlow.parse.templates.wechat_article")


class WechatArticleTemplate(AbstractTemplate):
    template_id = "wechat_article"
    platform = "wechat"
    version = "1.0"

    def build_prompt(self, raw: RawCapture) -> str:
        title = raw.raw.title or ""
        author = raw.raw.author or ""
        content = raw.raw.raw_text or raw.raw.raw_html or ""
        content_snippet = content[:8000]

        return f"""你是一个公众号内容深度分析助手。请分析以下微信公众号文章，提取结构化信息。

【文章信息】
标题: {title}
作者/公众号: {author}
正文:
{content_snippet}

【输出要求】
严格输出以下 JSON 格式，不要有任何额外文字：

{{
  "title": "文章标题（清晰版，若原标题是标题党则改为准确标题）",
  "summary": "5句话摘要，每句完整表达一个核心论点",
  "key_points": ["核心观点1", "核心观点2", "核心观点3"],
  "tags": ["标签1", "标签2"],
  "author": "作者或公众号名称",
  "clean_content": "Markdown 格式正文，保留段落结构，去除表情和广告",
  "reading_time": 5,
  "word_count": 1200
}}

注意事项：
- key_points 应是文章的核心主张，不是简单重复标题
- tags 选择内容领域词，如：AI、产品、创业、投资、科技等
- clean_content 保留原文逻辑顺序，只去除噪音（广告、点赞引导、版权声明等）
- 若文章包含数据或案例，请在 key_points 中体现
"""

    def parse_response(self, llm_output: str) -> ParsedArticle:
        return self.llm_output_to_article(llm_output)
