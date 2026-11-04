'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { api } from '@/lib/api';
import { buildLessonModel } from '@/lib/courseLesson';
import type { LessonModel } from '@/lib/courseLesson';
import type { CourseDetail } from '@/lib/types';
import LessonView from '@/components/course/LessonView';

function fallbackCourse(courseId: string, lesson: any): CourseDetail {
  return {
    id: courseId,
    course_key: courseId,
    title: lesson?.chapter_title || lesson?.title || '课程',
    total_lessons: 1,
    lessons: lesson ? [lesson] : [],
    created_at: '',
    updated_at: '',
  };
}

export default function LessonPage() {
  const params = useParams<{ courseId: string; lessonKey: string }>();
  const courseId = params?.courseId as string;
  const lessonKey = params?.lessonKey as string;

  const [model, setModel] = useState<LessonModel | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!courseId || !lessonKey) return;
    let cancelled = false;
    setLoading(true);
    setError('');

    Promise.all([
      api.getCourse(courseId).catch(() => null),
      api.getLesson(courseId, lessonKey),
    ])
      .then(([course, lesson]) => {
        if (cancelled) return;
        if (!lesson || !lesson.lesson) {
          setError('课时不存在');
          return;
        }
        setModel(buildLessonModel(course || fallbackCourse(courseId, lesson.lesson), lesson));
      })
      .catch((err) => {
        if (cancelled) return;
        console.error('Failed to load lesson:', err);
        setError('课时加载失败，请返回课程详情重试');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [courseId, lessonKey]);

  if (loading) {
    return (
      <div className="page-inner wide">
        <div className="panel" style={{ padding: '60px 24px', textAlign: 'center' }}>
          <div className="muted small">正在加载课时编译产物…</div>
        </div>
      </div>
    );
  }

  if (error || !model) {
    return (
      <div className="page-inner wide">
        <div className="panel" style={{ padding: '60px 24px', textAlign: 'center' }}>
          <h2 style={{ fontSize: 20, fontWeight: 750 }}>{error || '课时不存在'}</h2>
          <p className="muted" style={{ marginTop: 8 }}>
            该课时可能尚未完成四阶段编译。
          </p>
          <Link
            href={`/courses/${courseId}`}
            className="btn primary"
            style={{ marginTop: 18, display: 'inline-flex' }}
          >
            返回课程详情
          </Link>
        </div>
      </div>
    );
  }

  return <LessonView model={model} lessonKey={lessonKey} />;
}
