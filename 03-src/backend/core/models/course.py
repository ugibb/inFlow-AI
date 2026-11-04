"""Course module ORM models: courses / course_lessons / course_progress."""

from sqlalchemy import Column, String, Text, Integer, DateTime, Float, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from backend.core.database import Base


class Course(Base):
    __tablename__ = 'courses'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_key = Column(String(100), nullable=False, unique=True)  # "20261030-雅思-T260126基础强化班"
    title = Column(String(300), nullable=False)
    subject = Column(String(50))        # "雅思"
    stage = Column(String(50))          # "基础强化"
    description = Column(Text)
    total_lessons = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    lessons = relationship('CourseLesson', back_populates='course', cascade='all, delete-orphan', lazy='selectin')


class CourseLesson(Base):
    __tablename__ = 'course_lessons'
    __table_args__ = (
        UniqueConstraint('course_id', 'lesson_key', name='uq_course_lessons_key'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(UUID(as_uuid=True), ForeignKey('courses.id', ondelete='CASCADE'), nullable=False)
    lesson_key = Column(String(50), nullable=False)   # "R_001"
    title = Column(String(300), nullable=False)
    chapter_id = Column(String(50))                    # "reading"
    chapter_title = Column(String(100))                # "阅读"
    order_index = Column(Integer, default=0)
    duration_sec = Column(Float, nullable=False)
    segment_count = Column(Integer, default=0)
    status = Column(String(20), default='draft')       # draft / ready / published

    # AI 解析结果（JSONB 整存）
    chapters_data = Column(JSONB)     # ① 章节结构
    knowledge_data = Column(JSONB)    # ② 知识点树
    teaching_data = Column(JSONB)     # ③ 教学内容
    views_data = Column(JSONB)        # ④⑤⑥⑦ 四阶段视图
    audit_data = Column(JSONB)        # ⑧ 审计

    # 转写原文
    transcript_data = Column(JSONB)   # Whisper JSON segments

    # 媒体
    media_url = Column(String(2048))
    source_hash = Column(String(128))

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    course = relationship('Course', back_populates='lessons')
    progress_records = relationship('CourseProgress', back_populates='lesson', cascade='all, delete-orphan', lazy='selectin')


class CourseProgress(Base):
    __tablename__ = 'course_progress'
    __table_args__ = (
        UniqueConstraint('user_id', 'lesson_id', name='uq_course_progress_user_lesson'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    lesson_id = Column(UUID(as_uuid=True), ForeignKey('course_lessons.id', ondelete='CASCADE'), nullable=False)
    status = Column(String(20), default='not_started')  # not_started / in_progress / completed
    current_sec = Column(Float, default=0)
    notes = Column(JSONB)              # [{id, time, text, nodeId, quote}]
    exercise_answers = Column(JSONB)   # [{seq, answer, correct}]

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    lesson = relationship('CourseLesson', back_populates='progress_records')
