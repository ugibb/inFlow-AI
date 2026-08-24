"""Content parsing service —— 聚合各平台抓取能力。

fetchers.py（2044 行）按平台领域拆分后的兼容入口：
`from backend.core.ingest.fetchers import parser_service, extract_url_from_text` 保持可用。
"""
from backend.core.ingest.fetchers.helpers import extract_url_from_text
from backend.core.ingest.fetchers.base import ParserServiceBase
from backend.core.ingest.fetchers.feishu import FeishuParserMixin
from backend.core.ingest.fetchers.bilibili import BilibiliParserMixin
from backend.core.ingest.fetchers.toutiao import ToutiaoParserMixin
from backend.core.ingest.fetchers.douyin import DouyinParserMixin
from backend.core.ingest.fetchers.youtube import YoutubeParserMixin
from backend.core.ingest.fetchers.xhs import XhsParserMixin


class ParserService(
    ParserServiceBase,
    FeishuParserMixin,
    BilibiliParserMixin,
    ToutiaoParserMixin,
    DouyinParserMixin,
    YoutubeParserMixin,
    XhsParserMixin,
):
    """Extract and clean article content from various platforms."""


parser_service = ParserService()

__all__ = ["ParserService", "parser_service", "extract_url_from_text"]
