'use client';

import React, { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/api';
import type { CourseDetail, CourseSummary, LessonSummary } from '@/lib/types';
import { Icon, fmt } from '@/components/course/CourseUI';
import { readStudyState } from '@/lib/courseStudy';

interface EnrichedCourse extends CourseSummary {
  lessons: LessonSummary[];
  chapters: { id: string; title: string; lessons: LessonSummary[] }[];
  ready: number;
  hours: number;
  segments: number;
}

type FilterId = 'all' | 'pilot' | 'transcribed' | 'indexed';

const FILTERS: { id: FilterId; label: string }[] = [
  { id: 'all', label: '全部' },
  { id: 'pilot', label: '样板' },
  { id: 'transcribed', label: '已转写' },
  { id: 'indexed', label: '仅索引' },
];

const COVER_COLORS = ['blue', 'orange', 'purple', 'green', 'gray'];

function hashStr(str: string) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0;
  return h;
}

function coverChar(course: CourseSummary) {
  const raw = course.subject || course.title || '课';
  const cleaned = raw.replace(/[^\u4e00-\u9fa5A-Za-z0-9]/g, '');
  return (cleaned[0] || '课').toUpperCase();
}

function courseStatus(c: EnrichedCourse): FilterId {
  if (c.ready > 0) return 'pilot';
  if (c.lessons.length > 0) return 'transcribed';
  return 'indexed';
}

function statusBadge(status: FilterId) {
  if (status === 'pilot') return <span className="badge blue">样板</span>;
  if (status === 'transcribed') return <span className="badge green">已转写</span>;
  return <span className="badge gray">仅索引</span>;
}

function pipeDot(status: FilterId) {
  if (status === 'pilot') return 'run';
  if (status === 'indexed') return 'wait';
  return 'ok';
}

function pipelineText(c: EnrichedCourse) {
  const status = courseStatus(c);
  if (status === 'pilot') return `四阶段编译中 · ${c.ready} / ${c.lessons.length}`;
  if (status === 'transcribed') return '已转写 · 待 AI 编译';
  return '仅索引 · 未转写';
}

function buildChapters(lessons: LessonSummary[]) {
  const map = new Map<string, { id: string; title: string; lessons: LessonSummary[] }>();
  lessons.forEach((l) => {
    const id = l.chapter_id || 'default';
    if (!map.has(id)) map.set(id, { id, title: l.chapter_title || '未分章', lessons: [] });
    map.get(id)!.lessons.push(l);
  });
  return Array.from(map.values());
}

function enrich(course: CourseSummary, detail: CourseDetail | null): EnrichedCourse {
  const lessons = detail?.lessons ?? [];
  return {
    ...course,
    lessons,
    chapters: buildChapters(lessons),
    ready: lessons.filter((l) => l.status === 'ready' || l.status === 'published').length,
    hours: lessons.reduce((sum, l) => sum + (l.duration_sec || 0), 0) / 3600,
    segments: lessons.reduce((sum, l) => sum + (l.segment_count || 0), 0),
  };
}

function searchMatch(c: EnrichedCourse, q: string) {
  if (!q) return true;
  const hay = [
    c.title,
    c.subject,
    c.stage,
    c.description,
    c.course_key,
    ...c.lessons.map((l) => l.title),
    ...c.chapters.map((ch) => ch.title),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  return hay.includes(q.toLowerCase());
}

function matchesFilter(c: EnrichedCourse, filter: FilterId) {
  if (filter === 'all') return true;
  return courseStatus(c) === filter;
}

export default function CoursesPage() {
  const [courses, setCourses] = useState<EnrichedCourse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterId>('all');
  const [query, setQuery] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await api.listCourses();
        const details = await Promise.all(
          list.map((c) => api.getCourse(c.id).catch(() => null))
        );
        if (!cancelled) setCourses(list.map((c, i) => enrich(c, details[i])));
      } catch (e: any) {
        if (!cancelled) setError(e?.message || '课程加载失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const stats = useMemo(() => {
    const lessons = courses.reduce((s, c) => s + c.lessons.length, 0);
    const hours = courses.reduce((s, c) => s + c.hours, 0);
    const ready = courses.reduce((s, c) => s + c.ready, 0);
    return { lessons, hours, ready };
  }, [courses]);

  const counts = useMemo(() => {
    const result = {} as Record<FilterId, number>;
    FILTERS.forEach((f) => {
      result[f.id] = courses.filter((c) => matchesFilter(c, f.id)).length;
    });
    return result;
  }, [courses]);

  const filtered = useMemo(
    () => courses.filter((c) => matchesFilter(c, filter) && searchMatch(c, query)),
    [courses, filter, query]
  );

  // Resume = the course with the most compiled lessons.
  const resume = useMemo(() => {
    const course = [...courses].sort((a, b) => b.ready - a.ready)[0];
    if (!course) return null;
    const lesson =
      course.lessons.find((l) => l.status === 'ready' || l.status === 'published') ||
      course.lessons[0];
    if (!lesson) return null;
    return { course, lesson, study: readStudyState(lesson.lesson_key) };
  }, [courses]);

  const resumePct = resume
    ? Math.round((resume.course.ready / Math.max(resume.course.lessons.length, 1)) * 100)
    : 0;

  return (
    <div className="page-inner">
      <header className="page-head">
        <div>
          <h1>课程库</h1>
          <p>先索引全部课程，再把优先课程编译成可导航、可复习、可溯源的知识地图。</p>
        </div>
        <div className="head-actions">
          <span className="proto-chip">
            <span className="dot" />
            云端数据 · 实时
          </span>
        </div>
      </header>

      {resume && (
        <div className="resume-card">
          <div className="resume-icon">
            <Icon name="cap" />
          </div>
          <div className="resume-body">
            <div className="resume-kicker">继续学习 · 已编译课程</div>
            <div className="resume-title">
              {resume.course.title} / {resume.lesson.title}
            </div>
            <div className="resume-meta">
              <span>
                {resume.lesson.chapter_title || resume.course.subject || '课程'} ·{' '}
                {resume.course.lessons.length} 节
              </span>
              <span>
                {resume.study.position > 0
                  ? `上次停在 ${fmt(resume.study.position)}`
                  : '尚未开始'}
              </span>
              <span>{resume.study.notes.length} 条想法</span>
            </div>
          </div>
          <div className="resume-progress">
            <div className="row">
              <span>{resume.lesson.chapter_title || resume.course.subject || '课程'}进度</span>
              <b>{resumePct}%</b>
            </div>
            <div className="bar">
              <i style={{ width: `${resumePct}%` }} />
            </div>
            <div className="tiny muted" style={{ marginTop: 6 }}>
              {resume.course.ready} 节已生成 · {resume.course.lessons.length} 节目录
            </div>
          </div>
          <Link
            className="btn primary"
            href={`/courses/${resume.course.id}/${resume.lesson.lesson_key}`}
          >
            继续学习
          </Link>
        </div>
      )}

      <div className="stats">
        <div className="stat">
          <b>{loading ? '—' : courses.length}</b>
          <span>门课程 / 资料集</span>
        </div>
        <div className="stat">
          <b>{loading ? '—' : stats.lessons.toLocaleString()}</b>
          <span>节目录</span>
        </div>
        <div className="stat">
          <b>{loading ? '—' : stats.hours.toFixed(1)}</b>
          <span>小时</span>
        </div>
        <div className="stat">
          <b>{loading ? '—' : stats.ready}</b>
          <span>份已转写</span>
        </div>
      </div>

      <div className="section-head" style={{ marginTop: 20 }}>
        <h2>全部课程</h2>
        <span className="badge blue">按目录自动编目</span>
        <span className="muted small" style={{ marginLeft: 'auto' }}>
          云端数据库 · 实时同步
        </span>
      </div>

      <div className="lib-toolbar">
        <div className="lib-search">
          <Icon name="search" />
          <input
            type="search"
            placeholder="搜索课程、学科、章节…"
            autoComplete="off"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="lib-filters">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              className={`chip ${filter === f.id ? 'on' : ''}`}
              onClick={() => setFilter(f.id)}
            >
              {f.label} {counts[f.id] ?? 0}
            </button>
          ))}
        </div>
        <div className="lib-count">
          {filtered.length} / {courses.length} 门
        </div>
      </div>

      {loading ? (
        <div className="lib-empty">正在加载课程…</div>
      ) : error ? (
        <div className="lib-empty">课程加载失败：{error}</div>
      ) : filtered.length === 0 ? (
        <div className="lib-empty">没有匹配的课程，试试其他关键词或筛选条件。</div>
      ) : (
        <div className="lib-grid">
          {filtered.map((c) => {
            const status = courseStatus(c);
            const color = COVER_COLORS[hashStr(c.course_key || c.title) % COVER_COLORS.length];
            const tags = [
              `${c.chapters.length} 个章节`,
              c.subject || '课程',
              c.stage || '未标注',
              c.segments > 0 ? `真实转写 ${c.segments} 段` : '待转写',
            ];
            return (
              <Link
                key={c.id}
                href={`/courses/${c.id}`}
                className={`course-card ${status === 'pilot' ? 'pilot' : ''}`}
              >
                <div className="course-top">
                  <div className={`course-cover ${color}`}>{coverChar(c)}</div>
                  <div style={{ minWidth: 0 }}>
                    <div className="course-title">{c.title}</div>
                    <div className="course-sub">
                      {c.course_key} · {c.chapters.length} 个章节
                    </div>
                  </div>
                  <span className="course-pill">{statusBadge(status)}</span>
                </div>
                <div className="course-tags">
                  {tags.map((t) => (
                    <span key={t} className="course-tag">
                      {t}
                    </span>
                  ))}
                </div>
                <div className="course-meta">
                  <span>
                    <b>{c.lessons.length.toLocaleString()}</b> 节
                  </span>
                  <span>
                    <b>{c.hours.toFixed(1)}</b> 小时
                  </span>
                  <span>
                    <b>{c.ready}</b> 份转写
                  </span>
                </div>
                <div className="course-foot">
                  <span className="course-pipeline">
                    <span className={`pipe-dot ${pipeDot(status)}`} />
                    {pipelineText(c)}
                  </span>
                  <span className="course-go">
                    查看课程 <Icon name="right" size="sm" />
                  </span>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      <div className="catalog-note">
        <b>课程库按目录自动编目：</b>当前共 {courses.length} 门课程、{stats.lessons} 节目录、
        约 {stats.hours.toFixed(1)} 小时，其中 {stats.ready} 节完成四阶段编译。
        页面结构固定为 <b>课程库 → 课程 → 章节 → 课时 → 媒体 / 学习资产</b>，
        新增课程只增加数据，不再改页面。
      </div>
    </div>
  );
}
