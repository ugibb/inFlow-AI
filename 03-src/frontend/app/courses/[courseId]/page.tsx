'use client';

import React, { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { api } from '@/lib/api';
import type { CourseDetail, LessonSummary } from '@/lib/types';
import { Icon, fmt } from '@/components/course/CourseUI';

const PIPE_STEPS = ['目录索引', '音频 / 转写', '章节归并', '四阶段编译', '发布'];
const COVER_COLORS = ['blue', 'orange', 'purple', 'green', 'gray'];

function hashStr(str: string) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0;
  return h;
}

function coverChar(course: { subject?: string; title?: string }) {
  const raw = course.subject || course.title || '课';
  const cleaned = raw.replace(/[^\u4e00-\u9fa5A-Za-z0-9]/g, '');
  return (cleaned[0] || '课').toUpperCase();
}

interface ChapterGroup {
  id: string;
  title: string;
  lessons: LessonSummary[];
  ready: number;
  hours: number;
  segments: number;
}

function groupChapters(lessons: LessonSummary[]): ChapterGroup[] {
  const map = new Map<string, ChapterGroup>();
  lessons.forEach((l) => {
    const id = l.chapter_id || 'default';
    if (!map.has(id)) {
      map.set(id, {
        id,
        title: l.chapter_title || '未分章',
        lessons: [],
        ready: 0,
        hours: 0,
        segments: 0,
      });
    }
    const g = map.get(id)!;
    g.lessons.push(l);
    if (l.status === 'ready' || l.status === 'published') g.ready += 1;
    g.hours += (l.duration_sec || 0) / 3600;
    g.segments += l.segment_count || 0;
  });
  return Array.from(map.values());
}

function lessonNo(index: number) {
  return `第${String(index + 1).padStart(2, '0')}讲`;
}

export default function CourseDetailPage() {
  const params = useParams<{ courseId: string }>();
  const courseId = params?.courseId;
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!courseId) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await api.getCourse(courseId);
        if (!cancelled) {
          setCourse(data);
          const first = groupChapters(data.lessons || [])[0];
          if (first) setOpen({ [first.id]: true });
        }
      } catch (e: any) {
        if (!cancelled) setError(e?.message || '课程加载失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  const chapters = useMemo(() => groupChapters(course?.lessons || []), [course]);
  const totals = useMemo(() => {
    const lessons = course?.lessons || [];
    return {
      lessons: lessons.length,
      hours: lessons.reduce((s, l) => s + (l.duration_sec || 0), 0) / 3600,
      ready: lessons.filter((l) => l.status === 'ready' || l.status === 'published').length,
      segments: lessons.reduce((s, l) => s + (l.segment_count || 0), 0),
    };
  }, [course]);

  const steps = totals.ready > 0 && totals.ready === totals.lessons ? 4 : totals.lessons > 0 ? 3 : 1;
  const pipelineLabel =
    totals.lessons === 0
      ? '仅索引 · 未转写'
      : totals.ready > 0
        ? `四阶段编译中 · ${totals.ready} / ${totals.lessons}`
        : '已转写 · 待 AI 编译';
  const color = COVER_COLORS[hashStr(course?.course_key || course?.title || '') % COVER_COLORS.length];

  if (loading) {
    return (
      <div className="page-inner">
        <div className="lib-empty">正在加载课程…</div>
      </div>
    );
  }

  if (error || !course) {
    return (
      <div className="page-inner">
        <div className="breadcrumb">
          <Link href="/courses">课程库</Link>
          <Icon name="chevron" />
          <span>课程</span>
        </div>
        <div className="lib-empty">{error || '课程不存在'}</div>
      </div>
    );
  }

  return (
    <div className="page-inner">
      <div className="breadcrumb">
        <Link href="/courses">课程库</Link>
        <Icon name="chevron" />
        <span>{course.title}</span>
      </div>

      <div className="course-hero">
        <div className={`course-cover cover-lg ${color}`}>{coverChar(course)}</div>
        <div className="course-hero-body">
          <h1>{course.title}</h1>
          <div className="course-hero-meta">
            <span>{course.stage || '未标注'}</span>
            <span>{course.subject || '课程'}</span>
            <span>{chapters.length} 个章节</span>
            <span>{totals.lessons.toLocaleString()} 节</span>
            <span>{totals.hours.toFixed(1)} 小时</span>
          </div>
          <div className="course-tags">
            <span className="course-tag">{course.course_key}</span>
            <span className="course-tag">{totals.segments > 0 ? `真实转写 ${totals.segments} 段` : '待转写'}</span>
            <span className="course-tag">{totals.ready} 节已编译</span>
          </div>
        </div>
        <div className="course-hero-stat">
          <div>
            <b>{totals.lessons.toLocaleString()}</b>
            <span>节目录</span>
          </div>
          <div>
            <b>{totals.hours.toFixed(1)}</b>
            <span>小时</span>
          </div>
          <div>
            <b>{totals.ready}</b>
            <span>份转写</span>
          </div>
        </div>
      </div>

      <div className="pipeline-bar">
        {PIPE_STEPS.map((name, i) => {
          const cls = i < steps ? 'done' : i === steps ? 'now' : '';
          return (
            <React.Fragment key={name}>
              <span className={`pipeline-step ${cls}`}>
                <span className="n">{i < steps ? <Icon name="check" size="sm" /> : i + 1}</span>
                {name}
              </span>
              {i < PIPE_STEPS.length - 1 && <span className="pipeline-sep">/</span>}
            </React.Fragment>
          );
        })}
        <span style={{ marginLeft: 'auto', color: 'var(--text-tertiary)' }}>{pipelineLabel}</span>
      </div>

      <div className="section-head">
        <h2>章节</h2>
        <span className="badge gray">由目录结构自动识别</span>
        <span className="muted small" style={{ marginLeft: 'auto' }}>
          {chapters.length} 个章节 · {totals.lessons.toLocaleString()} 节
        </span>
      </div>

      <div className="section-list">
        {chapters.length === 0 && (
          <div className="card lesson-empty">
            <div className="empty-icon">
              <Icon name="layers" size="lg" />
            </div>
            <h3>还没有课时数据</h3>
            <p>目录已建立，等待音频、转写与四阶段编译结果写入云端数据库。</p>
          </div>
        )}
        {chapters.map((ch, i) => {
          const isOpen = open[ch.id] ?? false;
          return (
            <div key={ch.id} className={`section-card ${i === 0 && totals.ready > 0 ? 'pilot' : ''}`}>
              <div
                className="section-card-head"
                onClick={() => setOpen((prev) => ({ ...prev, [ch.id]: !isOpen }))}
              >
                <span className="section-idx">{i + 1}</span>
                <div style={{ minWidth: 0 }}>
                  <div className="section-name">{ch.title}</div>
                  <div className="section-sub">
                    {ch.lessons.length} 节 · {ch.hours.toFixed(1)} 小时
                  </div>
                </div>
                <div className="section-counts">
                  <span>
                    {ch.lessons.length} 节 · {ch.hours.toFixed(1)} 小时
                  </span>
                  {ch.ready > 0 ? (
                    <span className="badge green">已编译 {ch.ready}</span>
                  ) : (
                    <span className="badge gray">待编译</span>
                  )}
                  <Icon name={isOpen ? 'up' : 'down'} size="sm" />
                </div>
              </div>
              {isOpen && (
                <>
                  <div className="section-body">
                    {ch.lessons.map((lesson, li) => {
                      const ready = lesson.status === 'ready' || lesson.status === 'published';
                      const row = (
                        <>
                          <div className="lesson-no">{lessonNo(li)}</div>
                          <div className="lesson-main">
                            <div className="lesson-title">{lesson.title}</div>
                            <div className="lesson-sub">
                              <span>{lesson.lesson_key}</span>
                              <span>{lesson.segment_count} 段转写</span>
                              <span>{ready ? '四阶段已编译' : '待 AI 编译'}</span>
                            </div>
                          </div>
                          <div className="lesson-side">
                            <span className="lesson-dur">{fmt(lesson.duration_sec || 0)}</span>
                            {ready ? (
                              <span className="badge green">可学习</span>
                            ) : (
                              <span className="badge gray">待编译</span>
                            )}
                            <span className="lesson-go">
                              <Icon name={ready ? 'right' : 'lock'} size="sm" />
                            </span>
                          </div>
                        </>
                      );
                      return ready ? (
                        <Link
                          key={lesson.id}
                          href={`/courses/${course.id}/${lesson.lesson_key}`}
                          className="lesson-row"
                        >
                          {row}
                        </Link>
                      ) : (
                        <div key={lesson.id} className="lesson-row disabled">
                          {row}
                        </div>
                      );
                    })}
                  </div>
                  <div className="section-foot">
                    <span>
                      共 {ch.lessons.length} 节 · {ch.ready} 份已编译
                    </span>
                    <span>{ch.ready > 0 ? '点击课时进入四阶段学习' : '先完成音频 / 转写'}</span>
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>

      <div className="course-note">
        <b>章节是从目录结构自动识别的，不是手填的。</b>导入时第二层目录 → 章节，视频 / 音频文件 → 课时；
        可以在 <b>course.yaml</b> 里改名、合并、隐藏或调整顺序。
        {course.description ? (
          <>
            <br />
            <b>这门课：</b>
            {course.description}。
          </>
        ) : null}
        <br />
        媒体文件与转写就绪后，按“预习 → 学习 → 复习 → 练习”依次生成学习资产。
      </div>
    </div>
  );
}
