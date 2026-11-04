"""Pydantic schemas for Course API."""

from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime
from uuid import UUID


# ---- Course Schemas ----

class CourseSummary(BaseModel):
    """课程列表项"""
    id: UUID
    course_key: str
    title: str
    subject: Optional[str] = None
    stage: Optional[str] = None
    description: Optional[str] = None
    total_lessons: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CourseDetail(CourseSummary):
    """课程详情（含课时清单）"""
    lessons: List["LessonSummary"] = []


# ---- Lesson Schemas ----

class LessonSummary(BaseModel):
    """课时列表项"""
    id: UUID
    lesson_key: str
    title: str
    chapter_id: Optional[str] = None
    chapter_title: Optional[str] = None
    order_index: int = 0
    duration_sec: float
    segment_count: int = 0
    status: str = "draft"
    media_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class LessonDetail(BaseModel):
    """课时完整数据（四阶段 + 转写）"""
    lesson: LessonSummary
    chapters: Optional[Any] = None       # chapters_data JSONB
    knowledge_tree: Optional[Any] = None  # knowledge_data JSONB
    teaching: Optional[Any] = None        # teaching_data JSONB
    views: Optional[Any] = None           # views_data JSONB
    audit: Optional[Any] = None           # audit_data JSONB
    transcript: Optional[Any] = None      # transcript_data JSONB


class LessonTranscript(BaseModel):
    """转写段落（字幕联动）"""
    lesson_key: str
    language: Optional[str] = None
    duration: Optional[float] = None
    segments: List[Any] = []


# ---- Progress Schemas ----

class ProgressUpdate(BaseModel):
    """更新学习进度"""
    status: Optional[str] = Field(default=None, pattern="^(not_started|in_progress|completed)$")
    current_sec: Optional[float] = None
    notes: Optional[List[Any]] = None
    exercise_answers: Optional[List[Any]] = None


class ProgressResponse(BaseModel):
    """学习进度响应"""
    id: UUID
    user_id: UUID
    lesson_id: UUID
    status: str
    current_sec: float
    notes: Optional[Any] = None
    exercise_answers: Optional[Any] = None
    updated_at: datetime

    class Config:
        from_attributes = True


# ---- Import Schemas ----

class CourseImportRequest(BaseModel):
    """导入解析结果"""
    course_key: str
    course_title: str
    subject: Optional[str] = None
    stage: Optional[str] = None
    description: Optional[str] = None
    lesson_key: str
    lesson_title: str
    chapter_id: Optional[str] = None
    chapter_title: Optional[str] = None
    duration_sec: float
    segment_count: int = 0
    parsed_data: dict  # R_001_parsed.json 完整内容
    transcript_data: Optional[dict] = None  # Whisper JSON
    media_url: Optional[str] = None
    source_hash: Optional[str] = None


class CourseImportResponse(BaseModel):
    """导入结果"""
    course_id: UUID
    lesson_id: UUID
    status: str
    message: str


# Rebuild models for forward references
CourseDetail.model_rebuild()
