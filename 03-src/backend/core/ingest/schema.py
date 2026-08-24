"""Pydantic models for the RawCapture standard format.

Every platform Adapter must produce a RawCapture instance.  This is the
single contract between the ingest layer and the parse layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class RawMeta(BaseModel):
    """Metadata about the capture operation itself."""

    id: UUID = Field(default_factory=uuid4)
    source_platform: str
    # wechat | bilibili | xiaoyuzhou | xhs | douyin | youtube |
    # toutiao | juejin | csdn | upload | generic

    capture_method: str
    # url | wechat_bot | browser_ext | upload | paste

    original_url: Optional[str] = None
    captured_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    adapter_version: str = "1.0.0"
    user_id: UUID


class RawContent(BaseModel):
    """The raw content captured from the source platform."""

    title: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None

    content_type: str = "article"
    # article | video | audio | image | document

    raw_html: Optional[str] = None
    raw_text: Optional[str] = None
    media_urls: list[str] = Field(default_factory=list)
    cover_image: Optional[str] = None

    # Platform-specific extra fields that don't fit the standard schema.
    extra: dict[str, Any] = Field(default_factory=dict)


class RawCapture(BaseModel):
    """Standard output format produced by every Adapter.

    Serialised to: data/raw/{platform}/{YYYYMMDD}/{uuid}.json
    """

    meta: RawMeta
    raw: RawContent
    status: str = "captured"

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
