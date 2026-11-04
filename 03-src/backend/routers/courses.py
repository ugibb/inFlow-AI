"""Course API routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from uuid import UUID

from backend.core.database import get_db
from backend.core.dependencies import get_current_user
from backend.core.models.course import Course, CourseLesson, CourseProgress
from backend.core.models.user import User
from backend.core.schemas.course import (
    CourseSummary, CourseDetail,
    LessonSummary, LessonDetail, LessonTranscript,
    ProgressUpdate, ProgressResponse,
    CourseImportRequest, CourseImportResponse,
)

router = APIRouter(prefix="/api/courses", tags=["courses"])


# ---- Course List & Detail ----

@router.get("", response_model=list[CourseSummary])
async def list_courses(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """课程列表"""
    result = await db.execute(
        select(Course).order_by(Course.created_at.desc())
    )
    courses = result.scalars().all()

    # 统计每门课的课时数
    response = []
    for course in courses:
        # 统计课时数
        count_result = await db.execute(
            select(func.count(CourseLesson.id)).where(CourseLesson.course_id == course.id)
        )
        total = count_result.scalar() or 0

        course_dict = CourseSummary.model_validate(course)
        course_dict.total_lessons = total
        response.append(course_dict)

    return response


@router.get("/{course_id}", response_model=CourseDetail)
async def get_course(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """课程详情 + 课时清单"""
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")

    # 获取课时列表
    result = await db.execute(
        select(CourseLesson)
        .where(CourseLesson.course_id == course_id)
        .order_by(CourseLesson.chapter_id, CourseLesson.order_index)
    )
    lessons = result.scalars().all()

    return CourseDetail(
        id=course.id,
        course_key=course.course_key,
        title=course.title,
        subject=course.subject,
        stage=course.stage,
        description=course.description,
        total_lessons=len(lessons),
        created_at=course.created_at,
        updated_at=course.updated_at,
        lessons=[LessonSummary.model_validate(l) for l in lessons],
    )


# ---- Lesson Detail ----

@router.get("/{course_id}/lessons/{lesson_key}", response_model=LessonDetail)
async def get_lesson(
    course_id: UUID,
    lesson_key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """单节课完整数据（四阶段 + 转写）"""
    result = await db.execute(
        select(CourseLesson).where(
            CourseLesson.course_id == course_id,
            CourseLesson.lesson_key == lesson_key,
        )
    )
    lesson = result.scalar_one_or_none()
    if not lesson:
        raise HTTPException(status_code=404, detail="课时不存在")

    return LessonDetail(
        lesson=LessonSummary.model_validate(lesson),
        chapters=lesson.chapters_data,
        knowledge_tree=lesson.knowledge_data,
        teaching=lesson.teaching_data,
        views=lesson.views_data,
        audit=lesson.audit_data,
        transcript=lesson.transcript_data,
    )


@router.get("/{course_id}/lessons/{lesson_key}/transcript", response_model=LessonTranscript)
async def get_transcript(
    course_id: UUID,
    lesson_key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """转写段落（字幕联动用）"""
    result = await db.execute(
        select(CourseLesson.transcript_data).where(
            CourseLesson.course_id == course_id,
            CourseLesson.lesson_key == lesson_key,
        )
    )
    transcript_data = result.scalar_one_or_none()
    if not transcript_data:
        raise HTTPException(status_code=404, detail="转写数据不存在")

    return LessonTranscript(
        lesson_key=lesson_key,
        language=transcript_data.get("language"),
        duration=transcript_data.get("duration"),
        segments=transcript_data.get("segments", []),
    )


# ---- Progress ----

@router.put("/{course_id}/lessons/{lesson_key}/progress", response_model=ProgressResponse)
async def update_progress(
    course_id: UUID,
    lesson_key: str,
    data: ProgressUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新学习进度"""
    # 查找课时
    result = await db.execute(
        select(CourseLesson.id).where(
            CourseLesson.course_id == course_id,
            CourseLesson.lesson_key == lesson_key,
        )
    )
    lesson_id = result.scalar_one_or_none()
    if not lesson_id:
        raise HTTPException(status_code=404, detail="课时不存在")

    # 查找或创建进度记录
    result = await db.execute(
        select(CourseProgress).where(
            CourseProgress.user_id == user.id,
            CourseProgress.lesson_id == lesson_id,
        )
    )
    progress = result.scalar_one_or_none()

    if not progress:
        progress = CourseProgress(user_id=user.id, lesson_id=lesson_id)
        db.add(progress)

    # 更新字段
    if data.status is not None:
        progress.status = data.status
    if data.current_sec is not None:
        progress.current_sec = data.current_sec
    if data.notes is not None:
        progress.notes = data.notes
    if data.exercise_answers is not None:
        progress.exercise_answers = data.exercise_answers

    await db.flush()
    await db.refresh(progress)

    return ProgressResponse.model_validate(progress)


# ---- Import (Admin) ----

@router.post("/import", response_model=CourseImportResponse)
async def import_course(
    data: CourseImportRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导入解析结果（开发用）"""
    # 检查是否为管理员
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    # 查找或创建课程
    result = await db.execute(
        select(Course).where(Course.course_key == data.course_key)
    )
    course = result.scalar_one_or_none()

    if not course:
        course = Course(
            course_key=data.course_key,
            title=data.course_title,
            subject=data.subject,
            stage=data.stage,
            description=data.description,
        )
        db.add(course)
        await db.flush()

    # 查找或创建课时
    result = await db.execute(
        select(CourseLesson).where(
            CourseLesson.course_id == course.id,
            CourseLesson.lesson_key == data.lesson_key,
        )
    )
    lesson = result.scalar_one_or_none()

    if not lesson:
        lesson = CourseLesson(
            course_id=course.id,
            lesson_key=data.lesson_key,
        )
        db.add(lesson)

    # 填充课时数据
    parsed = data.parsed_data
    lesson.title = data.lesson_title
    lesson.chapter_id = data.chapter_id
    lesson.chapter_title = data.chapter_title
    lesson.duration_sec = data.duration_sec
    lesson.segment_count = data.segment_count
    lesson.status = "ready"

    # AI 解析结果
    lesson.chapters_data = parsed.get("chapters")
    lesson.knowledge_data = parsed.get("knowledge")
    lesson.teaching_data = parsed.get("teaching")
    lesson.views_data = {
        "preview": parsed.get("preview"),
        "learning": parsed.get("learning"),
        "review": parsed.get("review"),
        "practice": parsed.get("practice"),
    }
    lesson.audit_data = parsed.get("audit")

    # 转写数据
    if data.transcript_data:
        lesson.transcript_data = data.transcript_data

    # 媒体
    if data.media_url:
        lesson.media_url = data.media_url
    if data.source_hash:
        lesson.source_hash = data.source_hash

    await db.flush()
    await db.refresh(lesson)

    return CourseImportResponse(
        course_id=course.id,
        lesson_id=lesson.id,
        status="success",
        message=f"已导入 {data.lesson_key}",
    )
