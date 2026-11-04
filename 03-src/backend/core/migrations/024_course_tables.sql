-- 024: Course module tables (courses / course_lessons / course_progress)
-- Naming: snake_case plural, course_ prefix for associated tables

CREATE TABLE IF NOT EXISTS courses (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_key      VARCHAR(100) NOT NULL UNIQUE,
    title           VARCHAR(300) NOT NULL,
    subject         VARCHAR(50),
    stage           VARCHAR(50),
    description     TEXT,
    total_lessons   INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS course_lessons (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id       UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    lesson_key      VARCHAR(50) NOT NULL,
    title           VARCHAR(300) NOT NULL,
    chapter_id      VARCHAR(50),
    chapter_title   VARCHAR(100),
    order_index     INTEGER DEFAULT 0,
    duration_sec    REAL NOT NULL,
    segment_count   INTEGER DEFAULT 0,
    status          VARCHAR(20) DEFAULT 'draft',

    chapters_data   JSONB,
    knowledge_data  JSONB,
    teaching_data   JSONB,
    views_data      JSONB,
    audit_data      JSONB,

    transcript_data JSONB,

    media_url       VARCHAR(2048),
    source_hash     VARCHAR(128),

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_course_lessons_key UNIQUE (course_id, lesson_key)
);

CREATE TABLE IF NOT EXISTS course_progress (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lesson_id       UUID NOT NULL REFERENCES course_lessons(id) ON DELETE CASCADE,
    status          VARCHAR(20) DEFAULT 'not_started',
    current_sec     REAL DEFAULT 0,
    notes           JSONB,
    exercise_answers JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_course_progress_user_lesson UNIQUE (user_id, lesson_id)
);

CREATE INDEX IF NOT EXISTS idx_course_lessons_course_id ON course_lessons(course_id);
CREATE INDEX IF NOT EXISTS idx_course_progress_user_id ON course_progress(user_id);
CREATE INDEX IF NOT EXISTS idx_course_progress_lesson_id ON course_progress(lesson_id);
