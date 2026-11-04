"""
Import course parsed data into PostgreSQL.

Usage:
  cd 03-src/backend
  python scripts/import_course.py \
    --parsed-json F:/00-CC/inFlow-local/05-src/skills/course/output/R_001_parsed.json \
    --transcript-json "F:/00-CC/00-inFlowAI_src/01-input/02-course/20261030-雅思-T260126基础强化班/03-TXT/R_001_录1_词性的区分及其意义_005716.json" \
    --course-key "20261030-雅思-T260126基础强化班" \
    --course-title "雅思·基础强化班" \
    --subject "雅思" \
    --stage "基础强化" \
    --chapter-id "reading" \
    --chapter-title "阅读" \
    --media-url "/media/courses/20261030-雅思-T260126基础强化班/02-MP3/R_001.mp3"
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add backend parent directory to path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir.parent))

from sqlalchemy import select
from backend.core.database import async_session, init_db
from backend.core.models.course import Course, CourseLesson


async def import_course(args):
    """Import a single lesson into the database."""
    # Load parsed JSON
    parsed_path = Path(args.parsed_json)
    if not parsed_path.exists():
        print(f"Error: {parsed_path} not found")
        return False

    with open(parsed_path, "r", encoding="utf-8") as f:
        parsed = json.load(f)

    # Load transcript JSON (optional)
    transcript_data = None
    if args.transcript_json:
        transcript_path = Path(args.transcript_json)
        if transcript_path.exists():
            with open(transcript_path, "r", encoding="utf-8") as f:
                transcript_data = json.load(f)
            print(f"Loaded transcript: {transcript_data['meta']['segment_count']} segments")
        else:
            print(f"Warning: {transcript_path} not found, skipping transcript")

    async with async_session() as db:
        # Find or create course
        result = await db.execute(
            select(Course).where(Course.course_key == args.course_key)
        )
        course = result.scalar_one_or_none()

        if not course:
            course = Course(
                course_key=args.course_key,
                title=args.course_title,
                subject=args.subject,
                stage=args.stage,
                description=args.description or f"{args.subject} {args.stage} 课程",
            )
            db.add(course)
            await db.flush()
            print(f"Created course: {course.course_key} ({course.id})")
        else:
            print(f"Found existing course: {course.course_key} ({course.id})")

        # Find or create lesson
        lesson_key = parsed["lesson_id"]
        result = await db.execute(
            select(CourseLesson).where(
                CourseLesson.course_id == course.id,
                CourseLesson.lesson_key == lesson_key,
            )
        )
        lesson = result.scalar_one_or_none()

        if not lesson:
            lesson = CourseLesson(
                course_id=course.id,
                lesson_key=lesson_key,
            )
            db.add(lesson)
            print(f"Creating lesson: {lesson_key}")
        else:
            print(f"Updating existing lesson: {lesson_key}")

        # Fill lesson data
        lesson.title = parsed["title"]
        lesson.chapter_id = args.chapter_id
        lesson.chapter_title = args.chapter_title
        lesson.duration_sec = parsed["duration_sec"]
        lesson.segment_count = parsed["segment_count"]
        lesson.status = "ready"

        # AI parsed data
        lesson.chapters_data = parsed.get("chapters")
        lesson.knowledge_data = parsed.get("knowledge_tree")
        lesson.teaching_data = parsed.get("teaching")
        lesson.views_data = parsed.get("views")
        lesson.audit_data = parsed.get("audit")

        # Transcript
        if transcript_data:
            lesson.transcript_data = transcript_data

        # Media
        if args.media_url:
            lesson.media_url = args.media_url

        # Source hash (compute from parsed content for idempotency)
        import hashlib
        hash_content = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
        lesson.source_hash = hashlib.sha256(hash_content.encode()).hexdigest()

        await db.commit()
        print("\n[OK] Import complete:")
        print(f"  Course: {course.title} ({course.id})")
        print(f"  Lesson: {lesson.title} ({lesson.id})")
        print(f"  Duration: {lesson.duration_sec:.1f}s")
        print(f"  Segments: {lesson.segment_count}")
        print(f"  Status: {lesson.status}")
        print(f"  Source hash: {lesson.source_hash[:16]}...")

        return True


async def run(args):
    await init_db()
    return await import_course(args)


def main():
    parser = argparse.ArgumentParser(description="Import course parsed data")
    parser.add_argument("--parsed-json", required=True, help="Path to R_001_parsed.json")
    parser.add_argument("--transcript-json", help="Path to Whisper transcript JSON")
    parser.add_argument("--course-key", required=True, help="Course unique key")
    parser.add_argument("--course-title", required=True, help="Course title")
    parser.add_argument("--subject", default="雅思", help="Subject name")
    parser.add_argument("--stage", default="基础强化", help="Stage name")
    parser.add_argument("--description", help="Course description")
    parser.add_argument("--chapter-id", default="reading", help="Chapter ID (reading/listening/speaking/writing)")
    parser.add_argument("--chapter-title", default="阅读", help="Chapter title")
    parser.add_argument("--media-url", help="Media file URL")

    args = parser.parse_args()

    print("Initializing database...")
    # Single event loop for init_db + import — engine's asyncpg connection pool
    # is bound to whichever loop first touches it; two asyncio.run() calls
    # would produce "attached to a different loop" RuntimeError.
    success = asyncio.run(run(args))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
