from pydantic import BaseModel, Field
from typing import Optional, List, Union, Literal
from datetime import datetime
from uuid import UUID

# ---- Article Schemas ----
class ArticleCreate(BaseModel):
    url: str = Field(..., description="文章URL")
    title: Optional[str] = None
    folder_id: Optional[UUID] = None

class ArticleBatchCreate(BaseModel):
    urls: List[str] = Field(..., min_items=1, max_items=20)

class ArticleManualCreate(BaseModel):
    """Manual article creation from pasted content (when URL fetch fails)"""
    url: str = Field(..., description="Original article URL (for reference)")
    title: str = Field(..., min_length=1, description="Article title")
    content: str = Field(..., min_length=10, description="Pasted article content (plain text or HTML)")
    source_platform: Optional[str] = Field(default="other")
    folder_id: Optional[UUID] = None

class ArticleUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    is_favorited: Optional[bool] = None
    folder_id: Optional[UUID] = None
    clean_content: Optional[str] = None  # for note editing


class NoteCreate(BaseModel):
    """Create a blank or pre-filled note (Markdown)."""
    title: str = Field(default="无标题笔记", min_length=1, max_length=500)
    content: str = Field(default="", description="Markdown body")
    folder_id: Optional[UUID] = None

class TagResponse(BaseModel):
    id: UUID
    name: str
    color: str
    is_ai_generated: bool
    description: Optional[str]
    class Config:
        from_attributes = True


class TagUpdate(BaseModel):
    """Fields for updating a tag (all optional)."""
    name: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None


class TagWithCount(TagResponse):
    """Tag with article count for stats endpoint."""
    article_count: int


class MergeTagsRequest(BaseModel):
    """Merge source tag into target tag."""
    source_tag_id: UUID
    target_tag_id: UUID


class BatchDeleteTagsRequest(BaseModel):
    """Batch delete multiple tags by ID."""
    tag_ids: List[UUID] = Field(..., min_items=1)

class FolderResponse(BaseModel):
    id: UUID
    name: str
    parent_id: Optional[UUID] = None
    color: str
    icon: str
    class Config:
        from_attributes = True

class ArticleResponse(BaseModel):
    id: UUID
    title: str
    url: Optional[str] = None
    content_type: str = 'article'
    source_platform: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    summary: Optional[str] = None
    key_points: Optional[list] = None
    reading_time: Optional[int] = 0
    word_count: Optional[int] = 0
    cover_image: Optional[str] = None
    status: str
    fetch_status: Optional[str] = 'completed'  # completed | pending_agent | failed
    is_favorited: bool
    folder_id: Optional[UUID] = None
    tags: List[TagResponse] = []
    folder: Optional[FolderResponse] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class ArticleDetailResponse(ArticleResponse):
    clean_content: Optional[str] = None
    raw_content: Optional[str] = None
    media_url: Optional[str] = None
    # worker 直写的富格式 dict {version,total_duration,chapters:[...]}；
    # 老数据/其他调用方可能还是 list，两种都放行（前端实际走 /chapters 接口，不消费此字段）
    chapters: Optional[Union[list, dict]] = None
    # read 页各标签页内容块存在性快照（含内容类型是否展示该 tab）。
    # 形如 {"raw":{"applicable":bool,"present":bool},"transcript":...,"chapters":...,
    #       "deepRead":...,"ai":...}；由 detail 路由在回填后填充。
    content_blocks: Optional[dict] = None


class RegenerateBlockRequest(BaseModel):
    """单块重新生成请求：block 取值对应 read 页 tab id。

    - raw        原始抓取（article / video）
    - transcript 全文转录（audio）
    - chapters   章节速览（audio / article）
    - deepRead   AI 精读卡片（article / audio / video）
    - ai         AI 解析摘要（所有类型；audio 走 worker，其余云端同步）
    """
    block: Literal["raw", "transcript", "chapters", "deepRead", "ai"]


class DeepReadScreenshotRequest(BaseModel):
    """Current iframe HTML (with theme vars applied) for Playwright export."""
    html: str = Field(..., min_length=100, max_length=2_000_000)

class ArticleListResponse(BaseModel):
    items: List[ArticleResponse]
    total: int
    page: int
    page_size: int

# ---- Knowledge Graph ----
class KnowledgeEdgeResponse(BaseModel):
    id: UUID
    source_article_id: UUID
    target_article_id: UUID
    relation_type: str
    relation_desc: Optional[str]
    weight: float
    class Config:
        from_attributes = True

class GraphDataResponse(BaseModel):
    nodes: list
    edges: list

# ---- Learning Path ----
class LearningPathCreate(BaseModel):
    topic: str = Field(..., description="学习主题")
    description: Optional[str] = None

class LearningPathResponse(BaseModel):
    id: UUID
    title: str
    description: Optional[str]
    topic: Optional[str]
    articles_order: list
    progress: float
    status: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    class Config:
        from_attributes = True

class LearningPathDetailResponse(LearningPathResponse):
    articles: List[ArticleResponse] = []

# ---- Search ----
class SearchRequest(BaseModel):
    query: str
    page: int = 1
    page_size: int = 20

# ---- AI Processing ----
class AIProcessResponse(BaseModel):
    article_id: UUID
    title: str
    summary: str
    key_points: list
    tags: List[TagResponse]
    reading_time: int
    word_count: int
    source_platform: str
    author: str

# ---- Spark (一句话→文章) ----
class SparkCreateRequest(BaseModel):
    sentence: str = Field(..., min_length=1, max_length=500, description="一句话知识点/主题")
    enable_search: bool = Field(default=False, description="是否启用联网搜索（预留）")

class SparkSectionResponse(BaseModel):
    heading: str
    key_points: List[str]
    content: str

class SparkResponse(BaseModel):
    id: str
    title: str
    content: str
    sections: List[SparkSectionResponse] = []
    steps_completed: List[str] = []
    status: str

# ---- File Upload ----
class ArticleTagsUpdate(BaseModel):
    """Request schema for updating an article's tags."""
    tag_ids: List[UUID] = Field(..., description="List of tag UUIDs to assign to the article")

class FileUploadResponse(BaseModel):
    id: UUID
    title: str
    url: str
    source_platform: Optional[str] = None
    author: Optional[str] = None
    summary: Optional[str] = None
    key_points: Optional[list] = None
    reading_time: Optional[int] = 0
    word_count: Optional[int] = 0
    cover_image: Optional[str] = None
    status: str
    is_favorited: bool
    folder_id: Optional[UUID] = None
    tags: List[TagResponse] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    class Config:
        from_attributes = True
