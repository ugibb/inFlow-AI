'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { ArrowLeft, BookOpen, Clock, CheckCircle, Loader2, ChevronDown, ChevronRight } from 'lucide-react';
import { api } from '@/lib/api';
import type { CourseDetail, LessonSummary } from '@/lib/types';

// ─── Subject color mapping ────────────────────────────────────────────────────

const CHAPTER_COLORS: Record<string, { bg: string; text: string; border: string; icon: string }> = {
  reading: { bg: 'bg-blue-50 dark:bg-blue-900/20', text: 'text-blue-600 dark:text-blue-400', border: 'border-blue-200 dark:border-blue-800', icon: '📖' },
  listening: { bg: 'bg-orange-50 dark:bg-orange-900/20', text: 'text-orange-600 dark:text-orange-400', border: 'border-orange-200 dark:border-orange-800', icon: '🎧' },
  speaking: { bg: 'bg-purple-50 dark:bg-purple-900/20', text: 'text-purple-600 dark:text-purple-400', border: 'border-purple-200 dark:border-purple-800', icon: '🗣️' },
  writing: { bg: 'bg-green-50 dark:bg-green-900/20', text: 'text-green-600 dark:text-green-400', border: 'border-green-200 dark:border-green-800', icon: '✍️' },
};

const DEFAULT_COLOR = { bg: 'bg-gray-50 dark:bg-gray-800', text: 'text-gray-600 dark:text-gray-400', border: 'border-gray-200 dark:border-gray-700', icon: '📘' };

function getChapterColor(chapterId?: string) {
  if (!chapterId) return DEFAULT_COLOR;
  return CHAPTER_COLORS[chapterId.toLowerCase()] || DEFAULT_COLOR;
}

// ─── Status Badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const config = {
    draft: { label: '草稿', className: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
    ready: { label: '已就绪', className: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' },
    published: { label: '已发布', className: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' },
  };
  const { label, className } = config[status as keyof typeof config] || config.draft;

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${className}`}>
      {label}
    </span>
  );
}

// ─── Lesson Row ───────────────────────────────────────────────────────────────

function LessonRow({ lesson, courseId }: { lesson: LessonSummary; courseId: string }) {
  const durationMin = Math.round(lesson.duration_sec / 60);

  return (
    <Link
      href={`/courses/${courseId}/${lesson.lesson_key}`}
      className="flex items-center gap-4 p-4 rounded-lg border border-[var(--border-color)] bg-[var(--bg-primary)] hover:border-[var(--accent)]/30 hover:shadow-md transition-all duration-200"
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-sm font-medium text-[var(--text-primary)] truncate">
            {lesson.lesson_key}
          </span>
          <StatusBadge status={lesson.status} />
        </div>
        <h4 className="text-base font-semibold text-[var(--text-primary)] truncate">
          {lesson.title}
        </h4>
        {lesson.chapter_title && (
          <p className="text-sm text-[var(--text-tertiary)] mt-0.5">
            {lesson.chapter_title}
          </p>
        )}
      </div>
      <div className="flex items-center gap-4 text-sm text-[var(--text-secondary)]">
        <div className="flex items-center gap-1">
          <Clock size={14} />
          <span>{durationMin} 分</span>
        </div>
        <div className="flex items-center gap-1">
          <BookOpen size={14} />
          <span>{lesson.segment_count} 段</span>
        </div>
      </div>
    </Link>
  );
}

// ─── Chapter Section ──────────────────────────────────────────────────────────

function ChapterSection({
  chapterId,
  chapterTitle,
  lessons,
  courseId,
  defaultExpanded = false,
}: {
  chapterId: string;
  chapterTitle: string;
  lessons: LessonSummary[];
  courseId: string;
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const color = getChapterColor(chapterId);
  const readyCount = lessons.filter(l => l.status === 'ready').length;

  return (
    <div className={`rounded-xl border ${color.border} overflow-hidden`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className={`w-full flex items-center gap-3 p-4 ${color.bg} hover:opacity-80 transition-opacity`}
      >
        {expanded ? <ChevronDown size={20} className={color.text} /> : <ChevronRight size={20} className={color.text} />}
        <span className="text-2xl">{color.icon}</span>
        <div className="flex-1 text-left">
          <h3 className={`text-lg font-semibold ${color.text}`}>{chapterTitle}</h3>
          <p className="text-sm text-[var(--text-secondary)]">
            {lessons.length} 课时 · {readyCount} 已就绪
          </p>
        </div>
      </button>
      {expanded && (
        <div className="p-4 space-y-2 bg-[var(--bg-primary)]">
          {lessons.map(lesson => (
            <LessonRow key={lesson.id} lesson={lesson} courseId={courseId} />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function CourseDetailPage() {
  const params = useParams();
  const courseId = params.courseId as string;

  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (courseId) {
      loadCourse();
    }
  }, [courseId]);

  async function loadCourse() {
    try {
      setLoading(true);
      const data = await api.getCourse(courseId);
      setCourse(data);
    } catch (error) {
      console.error('Failed to load course:', error);
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 size={40} className="animate-spin text-[var(--accent)]" />
      </div>
    );
  }

  if (!course) {
    return (
      <div className="max-w-4xl mx-auto px-6 py-20 text-center">
        <h2 className="text-2xl font-bold text-[var(--text-primary)] mb-2">课程不存在</h2>
        <p className="text-[var(--text-secondary)]">请返回课程库查看</p>
        <Link href="/courses" className="inline-flex items-center gap-2 mt-6 px-4 py-2 rounded-lg bg-[var(--accent)] text-white hover:opacity-90">
          <ArrowLeft size={16} /> 返回课程库
        </Link>
      </div>
    );
  }

  // Group lessons by chapter
  const lessonsByChapter = new Map<string, LessonSummary[]>();
  course.lessons.forEach(lesson => {
    const chapterId = lesson.chapter_id || 'other';
    if (!lessonsByChapter.has(chapterId)) {
      lessonsByChapter.set(chapterId, []);
    }
    lessonsByChapter.get(chapterId)!.push(lesson);
  });

  // Calculate stats
  const totalLessons = course.lessons.length;
  const readyLessons = course.lessons.filter(l => l.status === 'ready').length;
  const totalDuration = course.lessons.reduce((sum, l) => sum + l.duration_sec, 0);
  const totalHours = (totalDuration / 3600).toFixed(1);

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)] mb-6">
        <Link href="/courses" className="hover:text-[var(--accent)]">课程库</Link>
        <span>/</span>
        <span className="text-[var(--text-primary)]">{course.title}</span>
      </div>

      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-[var(--text-primary)] mb-2">{course.title}</h1>
        {course.description && (
          <p className="text-[var(--text-secondary)]">{course.description}</p>
        )}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <div className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] p-4">
          <div className="text-xs text-[var(--text-tertiary)] mb-1">章节</div>
          <div className="text-2xl font-bold text-[var(--text-primary)]">{lessonsByChapter.size}</div>
        </div>
        <div className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] p-4">
          <div className="text-xs text-[var(--text-tertiary)] mb-1">课时</div>
          <div className="text-2xl font-bold text-[var(--text-primary)]">{totalLessons}</div>
        </div>
        <div className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] p-4">
          <div className="text-xs text-[var(--text-tertiary)] mb-1">总时长</div>
          <div className="text-2xl font-bold text-[var(--text-primary)]">{totalHours}h</div>
        </div>
        <div className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] p-4">
          <div className="text-xs text-[var(--text-tertiary)] mb-1">已就绪</div>
          <div className="text-2xl font-bold text-green-600 dark:text-green-400">{readyLessons}</div>
        </div>
      </div>

      {/* Chapter Sections */}
      <div className="space-y-4">
        {Array.from(lessonsByChapter.entries()).map(([chapterId, lessons], index) => {
          const chapterTitle = lessons[0]?.chapter_title || chapterId;
          return (
            <ChapterSection
              key={chapterId}
              chapterId={chapterId}
              chapterTitle={chapterTitle}
              lessons={lessons}
              courseId={courseId}
              defaultExpanded={index === 0}
            />
          );
        })}
      </div>

      {/* Empty state */}
      {course.lessons.length === 0 && (
        <div className="text-center py-20 text-[var(--text-tertiary)]">
          暂无课时数据
        </div>
      )}
    </div>
  );
}
