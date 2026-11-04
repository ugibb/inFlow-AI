'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { Search, BookOpen, Clock, FileText, GraduationCap, Loader2 } from 'lucide-react';
import { api } from '@/lib/api';
import type { CourseSummary } from '@/lib/types';

// ─── Subject color mapping ────────────────────────────────────────────────────

const SUBJECT_COLORS: Record<string, { bg: string; text: string; icon: string }> = {
  reading: { bg: 'bg-blue-50 dark:bg-blue-900/20', text: 'text-blue-600 dark:text-blue-400', icon: '📖' },
  listening: { bg: 'bg-orange-50 dark:bg-orange-900/20', text: 'text-orange-600 dark:text-orange-400', icon: '🎧' },
  speaking: { bg: 'bg-purple-50 dark:bg-purple-900/20', text: 'text-purple-600 dark:text-purple-400', icon: '🗣️' },
  writing: { bg: 'bg-green-50 dark:bg-green-900/20', text: 'text-green-600 dark:text-green-400', icon: '✍️' },
};

const DEFAULT_COLOR = { bg: 'bg-gray-50 dark:bg-gray-800', text: 'text-gray-600 dark:text-gray-400', icon: '📘' };

function getSubjectColor(subject?: string) {
  if (!subject) return DEFAULT_COLOR;
  const key = subject.toLowerCase();
  if (key.includes('阅读') || key === 'reading') return SUBJECT_COLORS.reading;
  if (key.includes('听力') || key === 'listening') return SUBJECT_COLORS.listening;
  if (key.includes('口语') || key === 'speaking') return SUBJECT_COLORS.speaking;
  if (key.includes('写作') || key === 'writing') return SUBJECT_COLORS.writing;
  return DEFAULT_COLOR;
}

// ─── Course Card ──────────────────────────────────────────────────────────────

function CourseCard({ course }: { course: CourseSummary }) {
  const color = getSubjectColor(course.subject);

  return (
    <Link
      href={`/courses/${course.id}`}
      className="block rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] p-5 hover:border-[var(--accent)]/30 hover:shadow-lg transition-all duration-200"
    >
      {/* Header */}
      <div className="flex items-start gap-3 mb-3">
        <div className={`w-12 h-12 rounded-xl flex items-center justify-center text-2xl ${color.bg}`}>
          {color.icon}
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-base font-semibold text-[var(--text-primary)] truncate">
            {course.title}
          </h3>
          {course.subject && (
            <p className="text-sm text-[var(--text-tertiary)] mt-0.5">
              {course.subject} {course.stage && `· ${course.stage}`}
            </p>
          )}
        </div>
      </div>

      {/* Stats */}
      <div className="flex items-center gap-4 text-sm text-[var(--text-secondary)]">
        <div className="flex items-center gap-1">
          <BookOpen size={14} />
          <span>{course.total_lessons} 课时</span>
        </div>
        {course.description && (
          <p className="text-xs text-[var(--text-tertiary)] truncate flex-1">
            {course.description}
          </p>
        )}
      </div>
    </Link>
  );
}

// ─── Stats Card ───────────────────────────────────────────────────────────────

function StatCard({ icon: Icon, value, label }: { icon: any; value: string | number; label: string }) {
  return (
    <div className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] p-4">
      <div className="flex items-center gap-2 mb-1">
        <Icon size={16} className="text-[var(--text-tertiary)]" />
        <span className="text-xs text-[var(--text-tertiary)]">{label}</span>
      </div>
      <div className="text-2xl font-bold text-[var(--text-primary)]">{value}</div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function CoursesPage() {
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    loadCourses();
  }, []);

  async function loadCourses() {
    try {
      setLoading(true);
      const data = await api.listCourses();
      setCourses(data);
    } catch (error) {
      console.error('Failed to load courses:', error);
    } finally {
      setLoading(false);
    }
  }

  // Filter courses by search query
  const filteredCourses = courses.filter(course =>
    course.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    course.subject?.toLowerCase().includes(searchQuery.toLowerCase()) ||
    course.description?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Calculate stats
  const totalCourses = courses.length;
  const totalLessons = courses.reduce((sum, c) => sum + c.total_lessons, 0);

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      {/* Page Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-[var(--text-primary)] mb-2">课程库</h1>
        <p className="text-sm text-[var(--text-secondary)]">按目录自动编目的课程与资料集</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard icon={GraduationCap} value={totalCourses} label="门课程" />
        <StatCard icon={BookOpen} value={totalLessons} label="节目录" />
        <StatCard icon={Clock} value="—" label="小时" />
        <StatCard icon={FileText} value="—" label="份已转写" />
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-3 mb-6">
        <div className="relative flex-1 max-w-md">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]" />
          <input
            type="text"
            placeholder="搜索课程..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2 rounded-full border border-[var(--border-color)] bg-[var(--bg-primary)] text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent-light)]"
          />
        </div>
        <div className="text-sm text-[var(--text-tertiary)] ml-auto">
          共 {filteredCourses.length} 门
        </div>
      </div>

      {/* Course Grid */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 size={32} className="animate-spin text-[var(--accent)]" />
        </div>
      ) : filteredCourses.length === 0 ? (
        <div className="text-center py-20 text-[var(--text-tertiary)]">
          {searchQuery ? '没有找到匹配的课程' : '暂无课程数据'}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredCourses.map(course => (
            <CourseCard key={course.id} course={course} />
          ))}
        </div>
      )}

      {/* Note */}
      <div className="mt-8 p-4 rounded-xl border border-dashed border-[var(--border-color)] text-sm text-[var(--text-secondary)] leading-relaxed">
        <strong className="text-[var(--text-primary)]">说明：</strong>
        课程库自动编目所有课程资料。点击课程卡片查看课时列表，选择已就绪的课时进入四阶段学习（预习 → 学习 → 复习 → 练习）。
      </div>
    </div>
  );
}
