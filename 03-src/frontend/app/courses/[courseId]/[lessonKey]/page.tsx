'use client';

import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft, Play, Pause, SkipBack, SkipForward, Volume2,
  CheckCircle, Circle, AlertCircle, Clock, BookOpen, Brain, Dumbbell,
  Loader2, ChevronRight, ChevronDown, Search,
} from 'lucide-react';
import { api } from '@/lib/api';
import type { LessonDetail, TranscriptSegment } from '@/lib/types';

// ─── Phase Types ──────────────────────────────────────────────────────────────

type Phase = 'preview' | 'learn' | 'review' | 'practice';

const PHASE_CONFIG: Record<Phase, { label: string; sublabel: string; icon: any; color: string }> = {
  preview: { label: '预习', sublabel: '建认知', icon: BookOpen, color: 'text-blue-600 dark:text-blue-400' },
  learn: { label: '学习', sublabel: '带重点听', icon: Brain, color: 'text-purple-600 dark:text-purple-400' },
  review: { label: '复习', sublabel: '主动回忆', icon: CheckCircle, color: 'text-green-600 dark:text-green-400' },
  practice: { label: '练习', sublabel: '查漏补缺', icon: Dumbbell, color: 'text-orange-600 dark:text-orange-400' },
};

// ─── Phase Bar ────────────────────────────────────────────────────────────────

function PhaseBar({ currentPhase, onPhaseChange }: { currentPhase: Phase; onPhaseChange: (phase: Phase) => void }) {
  const phases: Phase[] = ['preview', 'learn', 'review', 'practice'];
  const currentIndex = phases.indexOf(currentPhase);

  return (
    <div className="flex items-center gap-2 p-2 rounded-xl bg-[var(--bg-tertiary)]">
      {phases.map((phase, index) => {
        const config = PHASE_CONFIG[phase];
        const Icon = config.icon;
        const isActive = phase === currentPhase;
        const isPassed = index < currentIndex;

        return (
          <button
            key={phase}
            onClick={() => onPhaseChange(phase)}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
              isActive
                ? 'bg-[var(--bg-primary)] shadow-sm ' + config.color
                : isPassed
                ? 'text-[var(--text-secondary)] hover:bg-[var(--bg-primary)]/50'
                : 'text-[var(--text-tertiary)] hover:bg-[var(--bg-primary)]/50'
            }`}
          >
            {isPassed && <CheckCircle size={16} className="text-green-500" />}
            {!isPassed && <Icon size={16} />}
            <span>{config.label}</span>
            <span className="text-xs opacity-70 hidden sm:inline">· {config.sublabel}</span>
          </button>
        );
      })}
    </div>
  );
}

// ─── Audio Player ─────────────────────────────────────────────────────────────

function AudioPlayer({
  mediaUrl,
  duration,
  currentTime,
  onTimeUpdate,
  isPlaying,
  onPlayPause,
}: {
  mediaUrl?: string;
  duration: number;
  currentTime: number;
  onTimeUpdate: (time: number) => void;
  isPlaying: boolean;
  onPlayPause: () => void;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const progressRef = useRef<HTMLDivElement>(null);

  // 候选音源：同源正向地址 → 本机回环（http://localhost 属浏览器"可信来源"，
  // 不会被 https 页面的混合内容策略拦截）。课程音视频不落云端，直接读本机文件。
  const candidates = useMemo(() => {
    if (!mediaUrl) return [] as string[];
    let pathOnly = mediaUrl;
    try {
      if (/^https?:\/\//i.test(mediaUrl)) {
        const parsed = new URL(mediaUrl);
        pathOnly = `${parsed.pathname}${parsed.search}`;
        if (parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1') return [mediaUrl];
      }
    } catch {
      /* 解析失败按原样处理 */
    }
    const normalized = pathOnly.startsWith('/') ? pathOnly : `/${pathOnly}`;
    return [mediaUrl, `http://localhost${normalized}`];
  }, [mediaUrl]);

  const [srcIndex, setSrcIndex] = useState(0);
  const currentSrc = candidates[srcIndex];
  const exhausted = candidates.length > 0 && srcIndex >= candidates.length;

  useEffect(() => {
    setSrcIndex(0);
  }, [mediaUrl]);

  function handleAudioError() {
    // src 变化后浏览器会自动重新加载，无需手动 load()
    setSrcIndex((i) => i + 1);
  }

  useEffect(() => {
    if (audioRef.current) {
      if (isPlaying) {
        audioRef.current.play().catch(() => {});
      } else {
        audioRef.current.pause();
      }
    }
  }, [isPlaying]);

  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.currentTime = currentTime;
    }
  }, [currentTime]);

  function handleTimeUpdate() {
    if (audioRef.current) {
      onTimeUpdate(audioRef.current.currentTime);
    }
  }

  function handleProgressClick(e: React.MouseEvent<HTMLDivElement>) {
    if (progressRef.current && duration > 0) {
      const rect = progressRef.current.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const percentage = x / rect.width;
      const newTime = percentage * duration;
      onTimeUpdate(newTime);
      if (audioRef.current) {
        audioRef.current.currentTime = newTime;
      }
    }
  }

  const formatTime = (sec: number) => {
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <div className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] p-4">
      {currentSrc && !exhausted && (
        <audio
          ref={audioRef}
          src={currentSrc}
          preload="metadata"
          onTimeUpdate={handleTimeUpdate}
          onError={handleAudioError}
        />
      )}

      <div className="flex items-center gap-3 mb-3">
        <button
          onClick={onPlayPause}
          className="w-10 h-10 rounded-full bg-[var(--accent)] text-white flex items-center justify-center hover:opacity-90 transition-opacity"
        >
          {isPlaying ? <Pause size={18} /> : <Play size={18} className="ml-0.5" />}
        </button>
        <div className="flex-1">
          <div
            ref={progressRef}
            onClick={handleProgressClick}
            className="h-2 rounded-full bg-[var(--bg-tertiary)] cursor-pointer relative"
          >
            <div
              className="absolute left-0 top-0 h-full rounded-full bg-[var(--accent)] transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
        <div className="text-xs text-[var(--text-secondary)] font-mono">
          {formatTime(currentTime)} / {formatTime(duration)}
        </div>
      </div>

      {!mediaUrl && (
        <div className="text-xs text-[var(--text-tertiary)] text-center py-2">
          音频文件未配置
        </div>
      )}

      {exhausted && (
        <div className="text-xs text-[var(--text-tertiary)] text-center py-2">
          音频未加载——课程音视频保存在本机，只有同一台电脑打开时才能播放。
        </div>
      )}
    </div>
  );
}

// ─── Transcript Panel ─────────────────────────────────────────────────────────

function TranscriptPanel({
  segments,
  currentTime,
  onSeek,
}: {
  segments: TranscriptSegment[];
  currentTime: number;
  onSeek: (time: number) => void;
}) {
  const [searchQuery, setSearchQuery] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);

  const filteredSegments = searchQuery
    ? segments.filter(s => s.text.toLowerCase().includes(searchQuery.toLowerCase()))
    : segments;

  // Find current segment
  const currentIndex = segments.findIndex(s => currentTime >= s.start && currentTime < s.end);

  // Auto-scroll to current segment
  useEffect(() => {
    if (currentIndex >= 0 && scrollRef.current) {
      const element = scrollRef.current.children[currentIndex] as HTMLElement;
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
  }, [currentIndex]);

  const formatTime = (sec: number) => {
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  return (
    <div className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] flex flex-col h-full">
      <div className="p-3 border-b border-[var(--border-color)]">
        <div className="flex items-center gap-2 mb-2">
          <Search size={14} className="text-[var(--text-tertiary)]" />
          <input
            type="text"
            placeholder="搜索字幕..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="flex-1 text-sm bg-transparent outline-none text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)]"
          />
        </div>
        <div className="text-xs text-[var(--text-tertiary)]">
          {filteredSegments.length} 段
        </div>
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-1">
        {filteredSegments.map((segment, index) => {
          const isCurrent = index === currentIndex;
          return (
            <button
              key={segment.id}
              onClick={() => onSeek(segment.start)}
              className={`w-full text-left p-2 rounded-lg text-sm transition-colors ${
                isCurrent
                  ? 'bg-[var(--accent-light)] text-[var(--accent)]'
                  : 'hover:bg-[var(--bg-hover)] text-[var(--text-primary)]'
              }`}
            >
              <span className="font-mono text-xs opacity-60 mr-2">[{formatTime(segment.start)}]</span>
              {segment.text}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ─── Preview Phase ────────────────────────────────────────────────────────────

function PreviewPhase({ lesson }: { lesson: LessonDetail }) {
  const preview = lesson.views?.preview;
  const chapters = lesson.chapters?.chapters || [];

  if (!preview) {
    return <div className="text-center py-20 text-[var(--text-tertiary)]">暂无预习数据</div>;
  }

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] p-6">
        <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-2">先建立一张地图，再进入课堂</h3>
        <p className="text-sm text-[var(--text-secondary)]">
          通过探索以下模块，你将了解本课的核心概念和结构。点击每个模块卡片查看详情。
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {chapters.map((chapter: any, index: number) => (
          <div key={index} className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] p-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="w-6 h-6 rounded-full bg-[var(--accent)] text-white text-xs flex items-center justify-center font-bold">
                {index + 1}
              </span>
              <h4 className="font-semibold text-[var(--text-primary)]">{chapter.title}</h4>
            </div>
            {chapter.summary && (
              <p className="text-sm text-[var(--text-secondary)] line-clamp-2">{chapter.summary}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Learn Phase ──────────────────────────────────────────────────────────────

function LearnPhase({ lesson }: { lesson: LessonDetail }) {
  const knowledge = lesson.knowledge_tree?.knowledge_points || [];
  const teaching = lesson.teaching?.teaching_items || [];

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] p-6">
        <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-4">知识树</h3>
        <div className="space-y-2">
          {knowledge.slice(0, 10).map((point: any, index: number) => (
            <div key={index} className="flex items-start gap-3 p-3 rounded-lg bg-[var(--bg-hover)]">
              <CheckCircle size={18} className="text-green-500 mt-0.5 flex-shrink-0" />
              <div>
                <div className="font-medium text-[var(--text-primary)]">{point.title}</div>
                {point.statement && (
                  <div className="text-sm text-[var(--text-secondary)] mt-1">{point.statement}</div>
                )}
              </div>
            </div>
          ))}
          {knowledge.length > 10 && (
            <div className="text-sm text-[var(--text-tertiary)] text-center py-2">
              还有 {knowledge.length - 10} 个知识点...
            </div>
          )}
        </div>
      </div>

      {teaching.length > 0 && (
        <div className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] p-6">
          <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-4">教学要点</h3>
          <div className="space-y-3">
            {teaching.slice(0, 5).map((item: any, index: number) => (
              <div key={index} className="p-3 rounded-lg bg-[var(--bg-hover)]">
                <div className="font-medium text-[var(--text-primary)] mb-1">{item.title}</div>
                {item.content && (
                  <div className="text-sm text-[var(--text-secondary)]">{item.content}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Review Phase ─────────────────────────────────────────────────────────────

function ReviewPhase({ lesson }: { lesson: LessonDetail }) {
  const review = lesson.views?.review;
  const flashcards = review?.flashcards || [];
  const [revealedCards, setRevealedCards] = useState<Set<number>>(new Set());

  function toggleCard(index: number) {
    const newSet = new Set(revealedCards);
    if (newSet.has(index)) {
      newSet.delete(index);
    } else {
      newSet.add(index);
    }
    setRevealedCards(newSet);
  }

  if (flashcards.length === 0) {
    return <div className="text-center py-20 text-[var(--text-tertiary)]">暂无复习卡片</div>;
  }

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] p-6">
        <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-2">主动回忆</h3>
        <p className="text-sm text-[var(--text-secondary)] mb-4">
          不翻原文，先说一遍。点击卡片揭示答案。
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {flashcards.map((card: any, index: number) => (
          <div
            key={index}
            onClick={() => toggleCard(index)}
            className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] p-5 cursor-pointer hover:border-[var(--accent)]/30 transition-all"
          >
            <div className="flex items-start gap-3 mb-3">
              <span className="w-6 h-6 rounded-full bg-[var(--accent)] text-white text-xs flex items-center justify-center font-bold flex-shrink-0">
                {index + 1}
              </span>
              <div className="flex-1">
                <div className="font-medium text-[var(--text-primary)]">{card.question || card.prompt}</div>
              </div>
            </div>
            {revealedCards.has(index) && (
              <div className="mt-3 pt-3 border-t border-[var(--border-color)]">
                <div className="text-sm text-[var(--text-secondary)]">
                  {card.answer || card.points?.join(', ') || '答案'}
                </div>
              </div>
            )}
            {!revealedCards.has(index) && (
              <div className="text-xs text-[var(--text-tertiary)] mt-2">点击揭示答案</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Practice Phase ───────────────────────────────────────────────────────────

function PracticePhase({ lesson }: { lesson: LessonDetail }) {
  const practice = lesson.views?.practice;
  const exercises = practice?.exercises || [];
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [showFeedback, setShowFeedback] = useState<Record<number, boolean>>({});

  function handleAnswer(index: number, answer: string) {
    setAnswers({ ...answers, [index]: answer });
  }

  function checkAnswer(index: number) {
    setShowFeedback({ ...showFeedback, [index]: true });
  }

  if (exercises.length === 0) {
    return <div className="text-center py-20 text-[var(--text-tertiary)]">暂无练习题</div>;
  }

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] p-6">
        <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-2">随堂练习</h3>
        <p className="text-sm text-[var(--text-secondary)]">
          AI 生成 · 已校验
        </p>
      </div>

      <div className="space-y-4">
        {exercises.map((exercise: any, index: number) => (
          <div key={index} className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] p-5">
            <div className="flex items-start gap-3 mb-4">
              <span className="w-6 h-6 rounded-full bg-[var(--accent)] text-white text-xs flex items-center justify-center font-bold flex-shrink-0">
                {index + 1}
              </span>
              <div className="flex-1">
                <div className="text-sm text-[var(--text-tertiary)] mb-1">{exercise.type}</div>
                <div className="font-medium text-[var(--text-primary)]">{exercise.question || exercise.text}</div>
              </div>
            </div>

            {exercise.options && (
              <div className="space-y-2 mb-4">
                {exercise.options.map((option: string, optIndex: number) => {
                  const optKey = String.fromCharCode(65 + optIndex);
                  const isSelected = answers[index] === optKey;
                  return (
                    <button
                      key={optIndex}
                      onClick={() => handleAnswer(index, optKey)}
                      className={`w-full text-left p-3 rounded-lg border transition-all ${
                        isSelected
                          ? 'border-[var(--accent)] bg-[var(--accent-light)]'
                          : 'border-[var(--border-color)] hover:border-[var(--accent)]/30'
                      }`}
                    >
                      <span className="font-medium mr-2">{optKey}.</span>
                      {option}
                    </button>
                  );
                })}
              </div>
            )}

            <button
              onClick={() => checkAnswer(index)}
              disabled={!answers[index] || showFeedback[index]}
              className="px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              检查答案
            </button>

            {showFeedback[index] && (
              <div className={`mt-4 p-3 rounded-lg ${
                answers[index] === exercise.answer
                  ? 'bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800'
                  : 'bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800'
              }`}>
                <div className="font-medium text-sm mb-1">
                  {answers[index] === exercise.answer ? '✓ 正确！' : '✗ 错误'}
                </div>
                {exercise.explanation && (
                  <div className="text-sm text-[var(--text-secondary)]">{exercise.explanation}</div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function LessonPage() {
  const params = useParams();
  const courseId = params.courseId as string;
  const lessonKey = params.lessonKey as string;

  const [lesson, setLesson] = useState<LessonDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [currentPhase, setCurrentPhase] = useState<Phase>('preview');
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);

  useEffect(() => {
    if (courseId && lessonKey) {
      loadLesson();
    }
  }, [courseId, lessonKey]);

  async function loadLesson() {
    try {
      setLoading(true);
      const data = await api.getLesson(courseId, lessonKey);
      setLesson(data);
    } catch (error) {
      console.error('Failed to load lesson:', error);
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

  if (!lesson) {
    return (
      <div className="max-w-4xl mx-auto px-6 py-20 text-center">
        <h2 className="text-2xl font-bold text-[var(--text-primary)] mb-2">课时不存在</h2>
        <p className="text-[var(--text-secondary)]">请返回课程详情查看</p>
        <Link href={`/courses/${courseId}`} className="inline-flex items-center gap-2 mt-6 px-4 py-2 rounded-lg bg-[var(--accent)] text-white hover:opacity-90">
          <ArrowLeft size={16} /> 返回课程
        </Link>
      </div>
    );
  }

  const transcript = lesson.transcript;
  const segments: TranscriptSegment[] = transcript?.segments || [];

  return (
    <div className="max-w-7xl mx-auto px-6 py-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)] mb-4">
        <Link href="/courses" className="hover:text-[var(--accent)]">课程库</Link>
        <span>/</span>
        <Link href={`/courses/${courseId}`} className="hover:text-[var(--accent)]">课程详情</Link>
        <span>/</span>
        <span className="text-[var(--text-primary)]">{lesson.lesson.lesson_key}</span>
      </div>

      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-[var(--text-primary)] mb-1">{lesson.lesson.title}</h1>
        <div className="flex items-center gap-4 text-sm text-[var(--text-secondary)]">
          <span>{lesson.lesson.chapter_title}</span>
          <span>·</span>
          <span>{Math.round(lesson.lesson.duration_sec / 60)} 分钟</span>
          <span>·</span>
          <span>{lesson.lesson.segment_count} 段字幕</span>
        </div>
      </div>

      {/* Phase Bar */}
      <div className="mb-6">
        <PhaseBar currentPhase={currentPhase} onPhaseChange={setCurrentPhase} />
      </div>

      {/* Main Content */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Phase Content */}
        <div className="lg:col-span-2">
          {currentPhase === 'preview' && <PreviewPhase lesson={lesson} />}
          {currentPhase === 'learn' && <LearnPhase lesson={lesson} />}
          {currentPhase === 'review' && <ReviewPhase lesson={lesson} />}
          {currentPhase === 'practice' && <PracticePhase lesson={lesson} />}
        </div>

        {/* Right: Audio + Transcript */}
        <div className="space-y-4">
          <AudioPlayer
            mediaUrl={lesson.lesson.media_url}
            duration={lesson.lesson.duration_sec}
            currentTime={currentTime}
            onTimeUpdate={setCurrentTime}
            isPlaying={isPlaying}
            onPlayPause={() => setIsPlaying(!isPlaying)}
          />
          {segments.length > 0 && (
            <div className="h-[600px]">
              <TranscriptPanel
                segments={segments}
                currentTime={currentTime}
                onSeek={setCurrentTime}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
