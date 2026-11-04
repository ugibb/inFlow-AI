'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { Icon, fmt, pad } from './CourseUI';
import {
  findNode,
  evaluateAnswer,
  optionText,
  optionLetter,
  qtypeLabel,
  correctOptionIndex,
} from '@/lib/courseLesson';
import type {
  LessonModel,
  LessonNode,
  Exercise,
  Flashcard,
} from '@/lib/courseLesson';
import { readStudyState, writeStudyState } from '@/lib/courseStudy';
import type { StudyState, CourseNote } from '@/lib/courseStudy';

const PHASES = [
  { key: 'preview', label: '预习', sub: '建认知' },
  { key: 'learn', label: '学习', sub: '带重点听' },
  { key: 'review', label: '复习', sub: '主动回忆' },
  { key: 'practice', label: '练习', sub: '查漏补缺' },
] as const;

type Phase = (typeof PHASES)[number]['key'];

const PREVIEW_THRESHOLD = 4;
const SPEEDS = [1, 1.25, 1.5, 2];
const RATING_LABEL: Record<string, string> = {
  good: '记住了',
  fuzzy: '有点模糊',
  bad: '没印象',
};

function formatSpeed(v: number) {
  return Number.isInteger(v) ? v.toFixed(1) : String(v);
}

function emptyStudy(): StudyState {
  return { position: 0, notes: [], ratings: {}, doneNodes: [], practice: {} };
}

function lineIndexAt(segments: { start: number; end: number }[], t: number): number {
  if (!segments.length) return -1;
  let idx = segments.findIndex((s) => t >= s.start && t < s.end);
  if (idx >= 0) return idx;
  for (let i = segments.length - 1; i >= 0; i--) {
    if (t >= segments[i].start) return i;
  }
  return 0;
}

/** True when one recall line merely restates the other. */
function sameLine(a: string, b: string): boolean {
  const norm = (s: string) => s.replace(/[\s，。、；：！？,.;:!?"'“”‘’（）()]/g, '');
  const x = norm(a);
  const y = norm(b);
  if (!x || !y) return false;
  const [short, long] = x.length <= y.length ? [x, y] : [y, x];
  return short.length >= 8 && long.includes(short);
}

/** Same-origin candidates with the localhost fallback used during development. */
function withCandidates(raw: string): string[] {
  let pathOnly = raw;
  try {
    if (/^https?:\/\//i.test(raw)) {
      const parsed = new URL(raw);
      pathOnly = `${parsed.pathname}${parsed.search}`;
      if (parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1') return [raw];
    }
  } catch {
    /* parse failure: keep original */
  }
  const normalized = pathOnly.startsWith('/') ? pathOnly : `/${pathOnly}`;
  return [raw, `http://localhost${normalized}`];
}

/**
 * Lessons keep the video and the extracted audio side by side
 * (`01-MP4/xxx.mp4` and `02-MP3/xxx.mp3`), so either one can be derived
 * from the other when the API only stores a single media_url.
 */
function deriveMediaSources(raw?: string | null): { video: string[]; audio: string[] } {
  if (!raw) return { video: [], audio: [] };
  const isVideo = /\.(mp4|m4v|webm)(?=\?|$)/i.test(raw);
  if (isVideo) {
    const audioRaw = raw
      .replace(/\/01-MP4\//i, '/02-MP3/')
      .replace(/\.(mp4|m4v|webm)(?=\?|$)/i, '.mp3');
    return {
      video: withCandidates(raw),
      audio: audioRaw !== raw ? withCandidates(audioRaw) : [],
    };
  }
  const videoRaw = raw
    .replace(/\/02-MP3\//i, '/01-MP4/')
    .replace(/\.mp3(?=\?|$)/i, '.mp4');
  return {
    video: videoRaw !== raw ? withCandidates(videoRaw) : [],
    audio: withCandidates(raw),
  };
}

function Waveform({ progress }: { progress: number }) {
  return (
    <div className="waveform">
      {Array.from({ length: 96 }, (_, i) => {
        const h = 12 + Math.round(Math.abs(Math.sin((i + 1) * 1.37)) * 36);
        return (
          <span
            key={i}
            className={'wave-bar' + ((i + 1) / 96 <= progress ? ' on' : '')}
            style={{ height: `${h}px` }}
          />
        );
      })}
    </div>
  );
}

export default function LessonView({
  model,
  lessonKey,
}: {
  model: LessonModel;
  lessonKey: string;
}) {
  const { lesson, course, transcript, duration, chapters, nodes, exercises, flashcards } = model;

  const [phase, setPhase] = useState<Phase>('preview');
  const [study, setStudy] = useState<StudyState>(emptyStudy);
  const [studyReady, setStudyReady] = useState(false);

  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [follow, setFollow] = useState(true);
  const [wantVideo, setWantVideo] = useState(true);

  const [tab, setTab] = useState<'transcript' | 'notes'>('transcript');
  const [search, setSearch] = useState('');
  const [discovered, setDiscovered] = useState<Set<number>>(new Set());
  const [previewCollapsed, setPreviewCollapsed] = useState<Set<number>>(new Set());
  const [treeCollapsed, setTreeCollapsed] = useState<Set<number>>(new Set());
  const [openRecall, setOpenRecall] = useState<Set<number>>(new Set());

  const [selectionMode, setSelectionMode] = useState(false);
  const [selStart, setSelStart] = useState<number | null>(null);
  const [selEnd, setSelEnd] = useState<number | null>(null);

  const [noteCtx, setNoteCtx] = useState<{
    time: number;
    end?: number;
    quote?: string;
    lines?: { time: number; text: string }[];
  } | null>(null);
  const [noteText, setNoteText] = useState('');
  const [sourceTime, setSourceTime] = useState<number | null>(null);

  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [toast, setToast] = useState('');

  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const playerRef = useRef<HTMLDivElement>(null);
  const noteInputRef = useRef<HTMLTextAreaElement>(null);
  const transcriptScrollRef = useRef<HTMLDivElement>(null);
  const programmaticAt = useRef(0);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const timeRef = useRef(0);
  const studyRef = useRef<StudyState>(emptyStudy());
  const resumeAfterNote = useRef(false);

  timeRef.current = time;
  studyRef.current = study;

  /* ---------------- storage ---------------- */
  useEffect(() => {
    setStudy(readStudyState(lessonKey));
    setStudyReady(true);
  }, [lessonKey]);

  function patchStudy(patch: Partial<StudyState>) {
    setStudy((prev) => {
      const next = { ...prev, ...patch };
      writeStudyState(lessonKey, next);
      return next;
    });
  }

  useEffect(() => {
    return () => {
      if (studyReady) writeStudyState(lessonKey, { ...studyRef.current, position: timeRef.current });
      if (toastTimer.current) clearTimeout(toastTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lessonKey, studyReady]);

  function showToast(msg: string) {
    setToast(msg);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(''), 2300);
  }

  /* ---------------- media (video by default, audio optional) ---------------- */
  const media = useMemo(() => deriveMediaSources(lesson.media_url), [lesson.media_url]);
  const mediaMode: 'video' | 'audio' = wantVideo && media.video.length > 0 ? 'video' : 'audio';
  const sources = mediaMode === 'video' ? media.video : media.audio;

  const [srcIndex, setSrcIndex] = useState(0);
  const currentSrc = sources[srcIndex];
  const mediaFailed = sources.length === 0 || srcIndex >= sources.length;

  useEffect(() => {
    setWantVideo(true);
    setSrcIndex(0);
    resumeAfterNote.current = false;
  }, [lesson.media_url]);

  useEffect(() => {
    setSrcIndex(0);
  }, [mediaMode]);

  const getMedia = () => (mediaMode === 'video' ? videoRef.current : audioRef.current);

  function switchMedia(next: 'video' | 'audio') {
    if (next === mediaMode || (next === 'video' && media.video.length === 0)) return;
    setWantVideo(next === 'video');
    setSrcIndex(0);
    showToast(next === 'video' ? '已切换为视频' : '已切换为音频');
  }

  function handleMediaError() {
    if (srcIndex + 1 < sources.length) {
      setSrcIndex(srcIndex + 1);
      return;
    }
    if (mediaMode === 'video') {
      setWantVideo(false);
      setSrcIndex(0);
      showToast('视频不可用，已切换为音频');
    }
  }

  function resumePlayback(el: HTMLMediaElement) {
    el.playbackRate = speed;
    if (timeRef.current > 1 && Number.isFinite(el.duration)) {
      try {
        el.currentTime = Math.min(timeRef.current, Math.max(0, el.duration - 0.25));
      } catch {
        /* metadata not ready */
      }
    }
  }

  useEffect(() => {
    const el = getMedia();
    if (!el) return;
    el.playbackRate = speed;
    if (playing) {
      el.play().catch(() => {
        setPlaying(false);
        showToast('浏览器拦截了自动播放，请再点一次播放');
      });
    } else {
      el.pause();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, currentSrc, speed, mediaMode]);

  useEffect(() => {
    if (studyReady) writeStudyState(lessonKey, { ...study, position: time });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [time]);

  function seekTo(t: number, opts: { play?: boolean } = {}) {
    const target = Math.min(duration, Math.max(0, Number(t) || 0));
    setTime(target);
    const el = getMedia();
    if (el && el.readyState >= 1) {
      try {
        el.currentTime = target;
      } catch {
        /* metadata not ready */
      }
    }
    patchStudy({ position: target });
    if (opts.play) setPlaying(true);
  }

  function togglePlay() {
    if (mediaFailed) {
      showToast('音视频未加载：请确认保存课程文件的本机在线');
      return;
    }
    setPlaying((p) => !p);
  }

  function enterFullscreen() {
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
      return;
    }
    const el = mediaMode === 'video' ? videoRef.current : playerRef.current;
    if (!el) return;
    const p = el.requestFullscreen ? el.requestFullscreen() : null;
    if (p && p.catch) p.catch(() => showToast('当前浏览器不支持全屏'));
    else if (!el.requestFullscreen) showToast('当前浏览器不支持全屏');
  }

  /* ---------------- derived ---------------- */
  const currentLine = useMemo(() => lineIndexAt(transcript, time), [transcript, time]);
  const current = useMemo(
    () => findNode(nodes, time) || nodes[0] || null,
    [nodes, time]
  );
  const currentIndex = current ? nodes.findIndex((n) => n.seq === current.seq) : 0;

  const noteLineSet = useMemo(() => {
    const set = new Set<number>();
    study.notes.forEach((n) => {
      const idx = lineIndexAt(transcript, n.time);
      if (idx >= 0) set.add(idx);
    });
    return set;
  }, [study.notes, transcript]);

  const searchNorm = search.trim().toLowerCase();
  const searchHits = useMemo(
    () =>
      searchNorm
        ? transcript.filter((s) => s.text.toLowerCase().includes(searchNorm)).length
        : transcript.length,
    [searchNorm, transcript]
  );

  const range = useMemo(() => {
    if (selStart === null) return null;
    const end = selEnd === null ? selStart : selEnd;
    return { from: Math.min(selStart, end), to: Math.max(selStart, end) };
  }, [selStart, selEnd]);

  const previewChapters = useMemo(
    () => chapters.filter((c) => c.preview),
    [chapters]
  );
  const previewTotal = previewChapters.length;
  const previewFound = useMemo(
    () => previewChapters.filter((c) => discovered.has(c.seq)).length,
    [previewChapters, discovered]
  );
  const previewNeed = Math.max(0, Math.min(PREVIEW_THRESHOLD, previewTotal) - previewFound);
  const previewUnlocked = previewFound >= Math.min(PREVIEW_THRESHOLD, previewTotal);
  const previewPct = previewTotal ? (previewFound / previewTotal) * 100 : 0;

  const hints = (model.highlights.length ? model.highlights : nodes).slice(0, 3);

  const ratedCount = useMemo(
    () => flashcards.filter((c) => study.ratings[String(c.knowledge_seq)]).length,
    [flashcards, study.ratings]
  );

  const doneNodes = useMemo(() => {
    let count = 0;
    nodes.forEach((n) => {
      if (time >= n.end - 0.2 && n.seq !== current?.seq) count++;
    });
    return count;
  }, [nodes, time, current]);

  const notesSorted = useMemo(
    () => [...study.notes].sort((a, b) => a.time - b.time),
    [study.notes]
  );

  const practiceEntries = exercises.map((ex) => ({
    ex,
    raw: study.practice[String(ex.seq)],
  }));
  const answeredCount = practiceEntries.filter((p) => p.raw !== undefined).length;
  const rightCount = practiceEntries.filter(
    (p) => p.raw !== undefined && evaluateAnswer(p.ex, p.raw).ok
  ).length;
  const wrongCount = answeredCount - rightCount;
  const accuracy = answeredCount ? Math.round((rightCount / answeredCount) * 100) : null;

  function nodeForExercise(ex: Exercise): LessonNode | null {
    return model.nodeBySeq[ex.knowledge_seq] || null;
  }

  function nodeForCard(card: Flashcard): LessonNode | null {
    const direct = model.nodeBySeq[card.knowledge_seq];
    if (direct) return direct;
    const ch = chapters.find((c) => c.seq === card.chapter_seq);
    return ch && ch.nodes.length ? ch.nodes[0] : nodes[0] || null;
  }

  function chapterFor(node: LessonNode | null) {
    if (!node) return null;
    return chapters.find((c) => c.seq === node.chapterSeq) || null;
  }

  /* ---------------- navigation ---------------- */
  function scrollToCurrent(smooth: boolean) {
    if (phase !== 'learn' || tab !== 'transcript') return;
    const sc = transcriptScrollRef.current;
    if (!sc) return;
    const el = sc.querySelector<HTMLElement>('[data-current="1"]');
    if (!el) return;
    programmaticAt.current = Date.now();
    const top = el.offsetTop - sc.clientHeight * 0.4;
    sc.scrollTo({ top: Math.max(0, top), behavior: smooth ? 'smooth' : 'auto' });
  }

  function setPhaseView(next: Phase) {
    if (phase === 'learn' && next !== 'learn') setPlaying(false);
    if (next === 'review' && selectionMode) exitSelection();
    setPhase(next);
    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (next === 'learn') {
      setTimeout(() => scrollToCurrent(false), 140);
    }
  }

  function jumpTo(t: number) {
    setPhaseView('learn');
    seekTo(t);
    showToast('已定位到 ' + fmt(t));
  }

  /* ---------------- preview ---------------- */
  function revealModule(seq: number) {
    if (discovered.has(seq)) return;
    const next = new Set(discovered);
    next.add(seq);
    setDiscovered(next);
  }

  function scrollToPreviewChapter(seq: number) {
    const el = document.getElementById(`preview-ch-${seq}`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function togglePreviewChapter(seq: number) {
    const next = new Set(previewCollapsed);
    if (next.has(seq)) next.delete(seq);
    else next.add(seq);
    setPreviewCollapsed(next);
    scrollToPreviewChapter(seq);
  }

  /* ---------------- transcript ---------------- */
  function selectLine(i: number) {
    if (selStart === null) {
      setSelStart(i);
      setSelEnd(null);
    } else if (selEnd === null) {
      setSelEnd(i);
    } else {
      setSelStart(i);
      setSelEnd(null);
    }
  }

  function mediaPlaying() {
    const el = getMedia();
    return !!el && !el.paused && !el.ended;
  }

  function pauseMedia() {
    const el = getMedia();
    if (el && !el.paused) el.pause();
    setPlaying(false);
  }

  function enterSelection() {
    if (mediaPlaying()) resumeAfterNote.current = true;
    pauseMedia();
    setSelectionMode(true);
    setSelStart(currentLine >= 0 ? currentLine : 0);
    setSelEnd(null);
    setTab('transcript');
    setTimeout(() => scrollToCurrent(true), 60);
  }

  function exitSelection() {
    // Cancelled: keep the player paused, like prototype v3.
    resumeAfterNote.current = false;
    setSelectionMode(false);
    setSelStart(null);
    setSelEnd(null);
  }

  function confirmSelection() {
    if (!range) {
      showToast('请先选择原文');
      return;
    }
    const lines = transcript
      .slice(range.from, range.to + 1)
      .map((s) => ({ time: s.start, text: s.text }));
    const quote = lines.map((l) => l.text).join(' ');
    openNoteModal(
      transcript[range.from].start,
      quote,
      lines,
      transcript[range.to].end
    );
    // Leave selection mode without clearing the resume flag.
    setSelectionMode(false);
    setSelStart(null);
    setSelEnd(null);
  }

  /* ---------------- notes ---------------- */
  function openNoteModal(
    t?: number,
    quote?: string,
    lines?: { time: number; text: string }[],
    end?: number
  ) {
    if (!selectionMode && mediaPlaying()) resumeAfterNote.current = true;
    pauseMedia();
    setNoteCtx({ time: t !== undefined ? t : time, end, quote, lines });
    setNoteText('');
  }

  function closeNoteModal() {
    setNoteCtx(null);
    if (resumeAfterNote.current) {
      resumeAfterNote.current = false;
      setPlaying(true);
    }
  }

  useEffect(() => {
    if (!noteCtx) return;
    const timer = setTimeout(() => noteInputRef.current?.focus(), 60);
    return () => clearTimeout(timer);
  }, [noteCtx]);

  function saveNote() {
    const text = noteText.trim();
    if (!text) {
      showToast('先写点什么再保存');
      return;
    }
    const ctx = noteCtx || { time, quote: '' };
    const note: CourseNote = {
      id: `n-${Date.now()}`,
      time: ctx.time,
      quote: ctx.quote || '',
      text,
      createdAt: Date.now(),
    };
    patchStudy({ notes: [...study.notes, note] });
    const node = findNode(nodes, note.time);
    closeNoteModal();
    setTab('notes');
    showToast(`已保存 · ${fmt(note.time)}${node ? ' · ' + node.title : ''}`);
  }

  function deleteNote(id: string) {
    patchStudy({ notes: study.notes.filter((n) => n.id !== id) });
    showToast('已删除这条想法');
  }

  /* ---------------- source ---------------- */
  function openSourceModal(t: number) {
    setSourceTime(t);
  }

  function sourceLines(t: number) {
    const idx = lineIndexAt(transcript, t);
    const from = Math.max(0, idx - 2);
    const to = Math.min(transcript.length - 1, idx + 2);
    return { idx, from, to, lines: transcript.slice(from, to + 1) };
  }

  /* ---------------- review ---------------- */
  function setRating(seq: number, rating: 'good' | 'fuzzy' | 'bad') {
    const next = new Set(openRecall);
    next.add(seq);
    setOpenRecall(next);
    patchStudy({ ratings: { ...study.ratings, [String(seq)]: rating } });
    const node = model.nodeBySeq[seq];
    showToast(`已标记：${node ? node.title : '知识点'} · ${RATING_LABEL[rating]}`);
  }

  function toggleRecall(seq: number) {
    const next = new Set(openRecall);
    if (next.has(seq)) next.delete(seq);
    else next.add(seq);
    setOpenRecall(next);
  }

  const weakSeqs = useMemo(() => {
    const set = new Set<number>();
    Object.entries(study.ratings).forEach(([seq, r]) => {
      if (r === 'fuzzy' || r === 'bad') set.add(Number(seq));
    });
    exercises.forEach((ex) => {
      const raw = study.practice[String(ex.seq)];
      if (raw !== undefined && !evaluateAnswer(ex, raw).ok) {
        if (ex.knowledge_seq) set.add(ex.knowledge_seq);
      }
    });
    return Array.from(set);
  }, [study.ratings, study.practice, exercises]);

  /* ---------------- practice ---------------- */
  function checkExercise(ex: Exercise, raw: string) {
    if (study.practice[String(ex.seq)] !== undefined) return;
    if (!raw.trim()) return;
    const result = evaluateAnswer(ex, raw);
    patchStudy({ practice: { ...study.practice, [String(ex.seq)]: raw } });
    showToast(result.ok ? '答对了' : '答错了，回看原文再确认一遍');
  }

  function resetPractice() {
    patchStudy({ practice: {} });
    setDrafts({});
    showToast('练习已重置');
  }

  /* ---------------- transcript auto-follow ---------------- */
  useEffect(() => {
    if (phase !== 'learn' || tab !== 'transcript' || !follow) return;
    scrollToCurrent(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentLine, phase, tab, follow]);

  function handleTranscriptScroll() {
    if (Date.now() - programmaticAt.current < 900) return;
    setFollow(false);
  }

  function goCurrent() {
    setFollow(true);
    scrollToCurrent(true);
  }

  /* ============================================================
     render
     ============================================================ */
  const source = sourceTime !== null ? sourceLines(sourceTime) : null;
  const noteNode = noteCtx ? findNode(nodes, noteCtx.time) : null;

  return (
    <>
      <div className="page-inner wide">
        <div className="breadcrumb">
          <Link href="/courses">课程库</Link>
          <Icon name="chevron" />
          <Link href={`/courses/${course.id}`}>{course.subject || '课程'}</Link>
          <Icon name="chevron" />
          <Link href={`/courses/${course.id}`}>{lesson.chapter_title || '章节'}</Link>
          <Icon name="chevron" />
          <span>{lesson.title}</span>
        </div>

        <div className="lesson-toolbar">
          <div className="lesson-title-row">
            <div style={{ minWidth: 0 }}>
              <h1>{lesson.title}</h1>
              <div className="lesson-title-meta">
                <span>
                  {course.subject || '课程'}
                  {course.stage ? ` · ${course.stage}` : ''}
                </span>
                <span className="sep" />
                <span>{lesson.chapter_title || '本课'}</span>
                <span className="sep" />
                <span>{fmt(duration)}</span>
                <span className="sep" />
                <span>{transcript.length} 段转写</span>
              </div>
            </div>
            <div className="lesson-title-actions">
              <span className="badge green">AI 编译 · 已核对</span>
              <span className="proto-chip">
                <span className="dot" />
                本机音视频
              </span>
            </div>
          </div>

          <div className="phase-bar">
            {PHASES.map((p, i) => {
              const idx = PHASES.findIndex((x) => x.key === phase);
              return (
                <React.Fragment key={p.key}>
                  {i > 0 && (
                    <span className={'phase-sep' + (i <= idx ? ' passed' : '')}>
                      <Icon name="right" />
                    </span>
                  )}
                  <button
                    className={
                      'phase-btn' +
                      (p.key === phase ? ' active' : '') +
                      (i < idx ? ' passed' : '')
                    }
                    onClick={() => setPhaseView(p.key)}
                  >
                    <span className="ph-num">{i + 1}</span>
                    <span>{p.label}</span>
                    <span className="ph-sub">{p.sub}</span>
                  </button>
                </React.Fragment>
              );
            })}
          </div>
        </div>

        {/* ============ 阶段 1 · 预习 ============ */}
        <div className={'phase-view' + (phase === 'preview' ? ' active' : '')}>
          <div className="preview-grid">
            <aside className="panel preview-left">
              <div className="panel-head">
                <Icon name="map" size="sm" />
                本课章节
              </div>
              <div>
                {chapters.map((ch, i) => {
                  const mods = ch.preview ? 1 : 0;
                  const done = mods && discovered.has(ch.seq) ? 1 : 0;
                  const complete = mods > 0 && done === mods;
                  return (
                    <div
                      className={'tree-chapter' + (previewCollapsed.has(ch.seq) ? ' collapsed' : '')}
                      key={ch.seq}
                    >
                      <div
                        className={'tree-chapter-head' + (complete ? ' done' : '')}
                        onClick={() => togglePreviewChapter(ch.seq)}
                      >
                        <Icon name="down" size="sm" />
                        <span className="idx">
                          {complete ? <Icon name="check" size="sm" /> : i + 1}
                        </span>
                        <span>{ch.title}</span>
                        <span className="cnt">
                          {mods ? `${done}/${mods}` : `${ch.nodes.length} 节`}
                        </span>
                      </div>
                      <div className="tree-chapter-body">
                        {ch.nodes.map((n) => (
                          <div
                            className="tree-node"
                            key={n.seq}
                            onClick={() => {
                              setPhaseView('learn');
                              seekTo(n.start, { play: true });
                            }}
                          >
                            <span className="dot" />
                            <span>{n.title}</span>
                            <span className="node-time">{fmt(n.start)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
              <div
                className="tiny muted"
                style={{
                  padding: '9px 8px 2px',
                  borderTop: '1px solid var(--border-color)',
                  marginTop: 6,
                  lineHeight: 1.6,
                }}
              >
                点击章节可快速定位；模块需要逐个揭开。
              </div>
            </aside>

            <div className="preview-main">
              <div className="preview-intro">
                <h2>先建立一张地图，再进入课堂</h2>
                <p>{model.introQuestion || '逐个揭开模块，看看老师真正想让你注意什么。'}</p>
                <div className="preview-goals">
                  <span className="goal-chip">
                    <Icon name="target" />
                    本课 {chapters.length} 章
                  </span>
                  <span className="goal-chip">
                    <Icon name="clock" />
                    老师重点 {model.highlights.length} 处
                  </span>
                  <span className="goal-chip">
                    <Icon name="layers" />
                    随堂练习 {exercises.length} 题
                  </span>
                </div>
              </div>

              <div>
                {chapters.map((ch, ci) => {
                  if (!ch.preview) return null;
                  const revealed = discovered.has(ch.seq);
                  return (
                    <div className="chapter-card" id={`preview-ch-${ch.seq}`} key={ch.seq}>
                      <div className="chapter-head">
                        <span className="chapter-index">{ci + 1}</span>
                        <div>
                          <div className="chapter-title">{ch.title}</div>
                          <div className="chapter-sub">{ch.summary || ch.learning?.structure || ''}</div>
                        </div>
                        <div className="chapter-progress">
                          <b>{revealed ? 1 : 0}</b> / 1 已揭开
                        </div>
                      </div>
                      <div className="chapter-body">
                        <div className="module-grid">
                          <div
                            className={'module' + (revealed ? ' revealed' : '')}
                            onClick={() => revealModule(ch.seq)}
                          >
                            <div className="module-top">
                              <Icon name={revealed ? 'check-circle' : 'lock'} size="sm" />
                              <span>{ch.preview.heading}</span>
                            </div>
                            <div className="module-hint" style={revealed ? { display: 'none' } : undefined}>
                              点击揭开老师要你注意的点
                            </div>
                            <div className="module-insight">
                              <p>{ch.preview.questions.join('　')}</p>
                              <span
                                className="module-src"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  openSourceModal(ch.start);
                                }}
                              >
                                打开原文 {fmt(ch.start)} <Icon name="right" size="sm" />
                              </span>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <aside className="preview-side">
              <div className="panel discovery-card">
                <div className="discovery-top">
                  <div
                    className="ring"
                    style={{
                      background: `conic-gradient(var(--accent) ${previewPct}%, var(--bg-tertiary) 0)`,
                    }}
                  >
                    <b>
                      {previewFound}/{previewTotal}
                    </b>
                  </div>
                  <div>
                    <h3>探索进度</h3>
                    <p>
                      共 {previewTotal} 个模块 · 揭开 {Math.min(PREVIEW_THRESHOLD, previewTotal)}{' '}
                      个即可解锁学习
                    </p>
                  </div>
                </div>
                <div className={'chapter-status' + (chapters.length > 6 ? ' many' : '')}>
                  {chapters.map((ch, i) => {
                    const mods = ch.preview ? 1 : 0;
                    const done = mods && discovered.has(ch.seq) ? 1 : 0;
                    const cls = mods === 0 ? '' : done === 0 ? '' : done === mods ? 'complete' : 'partial';
                    return (
                      <div
                        className={'ch-status ' + cls}
                        key={ch.seq}
                        onClick={() => scrollToPreviewChapter(ch.seq)}
                      >
                        <div className="ch-dot" />
                        <div className="ch-label">第{i + 1}章</div>
                        <div className="ch-count">
                          {mods ? `${done}/${mods}` : `${ch.nodes.length} 节`}
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="cta-box">
                  {previewUnlocked ? (
                    <button className="btn primary" onClick={() => setPhaseView('learn')}>
                      开始学习 <Icon name="right" size="sm" />
                    </button>
                  ) : (
                    <button className="btn primary" disabled>
                      <Icon name="lock" size="sm" />再探索 {previewNeed} 个模块解锁
                    </button>
                  )}
                  <div className="cta-tip">
                    {previewUnlocked
                      ? '已解锁：先看知识树，再进入学习'
                      : '不用全部揭开，抓住老师反复强调的点即可'}
                  </div>
                </div>
              </div>

              <div className="panel">
                <div className="panel-head">
                  <Icon name="star" size="sm" />
                  老师提示
                </div>
                <div className="panel-body" style={{ paddingTop: 4, paddingBottom: 6 }}>
                  {hints.map((h) => (
                    <div
                      className="hint-item"
                      key={h.seq}
                      onClick={() => openSourceModal(h.start)}
                    >
                      <Icon name="star" size="sm" />
                      <div>
                        {h.statement || h.title}
                        <span className="t">原文 {fmt(h.start)} →</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="panel" style={{ padding: '13px 14px' }}>
                <div className="tiny muted">内容状态</div>
                <div style={{ fontSize: 12, fontWeight: 650, marginTop: 3 }}>
                  AI 编译 · 已核对 {previewTotal}/{previewTotal} 模块
                </div>
                <div className="tiny muted" style={{ marginTop: 4, lineHeight: 1.6 }}>
                  每条摘要都绑定原文时间点，可随时回看。
                </div>
              </div>
            </aside>
          </div>
        </div>

        {/* ============ 阶段 2 · 学习 ============ */}
        <div className={'phase-view' + (phase === 'learn' ? ' active' : '')}>
          <div className="learn-grid">
            <aside className="panel tree-panel">
              <div className="panel-head">
                <Icon name="list" size="sm" />
                本课章节
                <span className="panel-sub">
                  {doneNodes} / {nodes.length}
                </span>
              </div>
              <div className="panel-body">
                {chapters.map((ch) => (
                  <div
                    className={'tree-chapter' + (treeCollapsed.has(ch.seq) ? ' collapsed' : '')}
                    key={ch.seq}
                  >
                    <div
                      className="tree-chapter-head"
                      onClick={() => {
                        const next = new Set(treeCollapsed);
                        if (next.has(ch.seq)) next.delete(ch.seq);
                        else next.add(ch.seq);
                        setTreeCollapsed(next);
                      }}
                    >
                      <Icon name="down" size="sm" />
                      <span>{ch.title}</span>
                      <span className="panel-sub">{ch.nodes.length}</span>
                    </div>
                    <div className="tree-chapter-body">
                      {ch.nodes.map((n) => {
                        const active = current?.seq === n.seq;
                        const done = time >= n.end - 0.2 && !active;
                        const noteCount = study.notes.filter((note) => {
                          const hit = findNode(nodes, note.time);
                          return hit?.seq === n.seq;
                        }).length;
                        return (
                          <div
                            className={
                              'tree-node' +
                              (active ? ' active' : '') +
                              (done ? ' done' : '')
                            }
                            key={n.seq}
                            onClick={() => seekTo(n.start, { play: true })}
                          >
                            <span className="dot" />
                            <span>{n.title}</span>
                            <span className="node-note">{noteCount > 0 ? `· ${noteCount}` : ''}</span>
                            <span className="node-time">{fmt(n.start)}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
              <div className="tree-foot">
                <span>● 点击节点跳转</span>
                <span style={{ color: 'var(--purple)' }}>● 有想法</span>
              </div>
            </aside>

            <div className="learn-center">
              <div className="panel player-panel" ref={playerRef}>
                <div className="player-head">
                  <div style={{ minWidth: 0 }}>
                    <div className="player-kicker">
                      <span className="live-dot" />
                      {mediaMode === 'video' ? '本地视频 · 真实播放' : '本地音频 · 真实播放'}
                    </div>
                    <div className="player-title">
                      {lesson.title} · {course.title}
                    </div>
                  </div>
                  <div className="player-tools">
                    <button
                      type="button"
                      className="media-toggle"
                      disabled={!media.video.length}
                      title={mediaMode === 'video' ? '切换为音频播放' : '切换为视频播放'}
                      onClick={() => switchMedia(mediaMode === 'video' ? 'audio' : 'video')}
                    >
                      {mediaMode === 'video' ? '切换音频' : '切换视频'}
                    </button>
                    <span className="badge blue">
                      {mediaMode === 'video' ? '视频' : '音频'} · {fmt(Math.round(duration))}
                    </span>
                  </div>
                </div>

                {currentSrc && !mediaFailed && mediaMode === 'video' && (
                  <video
                    ref={videoRef}
                    className="lesson-video"
                    src={currentSrc}
                    preload="metadata"
                    playsInline
                    title="点击播放 / 暂停"
                    onClick={togglePlay}
                    onDoubleClick={enterFullscreen}
                    onLoadedMetadata={(e) => resumePlayback(e.currentTarget)}
                    onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
                    onPlay={() => setPlaying(true)}
                    onEnded={() => setPlaying(false)}
                    onError={handleMediaError}
                  />
                )}
                {currentSrc && !mediaFailed && mediaMode === 'audio' && (
                  <audio
                    ref={audioRef}
                    src={currentSrc}
                    preload="metadata"
                    onLoadedMetadata={(e) => resumePlayback(e.currentTarget)}
                    onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
                    onPlay={() => setPlaying(true)}
                    onEnded={() => setPlaying(false)}
                    onError={handleMediaError}
                  />
                )}

                {mediaFailed ? (
                  <div className="video-fallback show">
                    音视频不可达：请确认保存课程文件的本机在线。
                    <br />
                    转写与四阶段仍可正常使用。
                  </div>
                ) : mediaMode === 'video' ? null : (
                  <div
                    onClick={(e) => {
                      const rect = e.currentTarget.getBoundingClientRect();
                      const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
                      seekTo(ratio * duration);
                    }}
                  >
                    <Waveform progress={duration ? Math.min(1, time / duration) : 0} />
                  </div>
                )}

                <div
                  className="seek"
                  onPointerDown={(e) => {
                    try {
                      e.currentTarget.setPointerCapture(e.pointerId);
                    } catch {
                      /* ignore */
                    }
                    const rect = e.currentTarget.getBoundingClientRect();
                    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
                    seekTo(ratio * duration);
                  }}
                  onPointerMove={(e) => {
                    if (e.buttons !== 1) return;
                    const rect = e.currentTarget.getBoundingClientRect();
                    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
                    seekTo(ratio * duration);
                  }}
                >
                  <div
                    className="seek-fill"
                    style={{ width: `${duration ? Math.min(100, (time / duration) * 100) : 0}%` }}
                  />
                  <div
                    className="seek-knob"
                    style={{ left: `${duration ? Math.min(100, (time / duration) * 100) : 0}%` }}
                  />
                </div>
                <div className="player-times">
                  <span>{fmt(time)}</span>
                  <span>{fmt(Math.round(duration))}</span>
                </div>
                <div className="player-controls">
                  <button
                    className="icon-btn round"
                    title="后退 15 秒"
                    aria-label="后退 15 秒"
                    onClick={() => seekTo(time - 15)}
                  >
                    <Icon name="rewind" />
                  </button>
                  <button className="play-btn" onClick={togglePlay} aria-label="播放 / 暂停">
                    <Icon name={playing ? 'pause' : 'play'} />
                  </button>
                  <button
                    className="icon-btn round"
                    title="前进 15 秒"
                    aria-label="前进 15 秒"
                    onClick={() => seekTo(time + 15)}
                  >
                    <Icon name="forward" />
                  </button>
                  <button
                    className="speed-btn"
                    title="切换倍速"
                    onClick={() => {
                      const idx = SPEEDS.indexOf(speed);
                      const next = SPEEDS[(idx + 1) % SPEEDS.length];
                      setSpeed(next);
                      showToast('播放速度 ' + formatSpeed(next) + '×');
                    }}
                  >
                    {formatSpeed(speed)}×
                  </button>
                  <button className="speed-btn" title="全屏播放" onClick={enterFullscreen}>
                    全屏
                  </button>
                  <div className="player-extra">
                    <button className="btn soft sm" onClick={enterSelection}>
                      <Icon name="pen" size="sm" />
                      记录想法
                    </button>
                  </div>
                </div>
              </div>

              {current && (
                <div className="panel know-panel">
                  <div className="know-head">
                    <span className="badge blue">正在讲</span>
                    <span className="badge gray">{chapterFor(current)?.title || current.chapterTitle}</span>
                    <span className="know-time">
                      {fmt(current.start)} – {fmt(current.end)}
                    </span>
                  </div>
                  <h3 className="know-title">{current.title}</h3>
                  <p className="know-summary">{current.statement}</p>
                  {(current.kind === 'exam_tip' || current.importance >= 3) && (
                    <div className="teacher-hl">
                      <Icon name="star" size="sm" />
                      <div>
                        <b>老师强调</b>　{current.statement}
                      </div>
                    </div>
                  )}
                  <div className="know-actions">
                    <button
                      className="btn ghost sm"
                      onClick={() => openSourceModal(current.start)}
                    >
                      <Icon name="search" size="sm" />
                      查看老师原文 {fmt(current.start)}
                    </button>
                    <button className="btn ghost sm" onClick={enterSelection}>
                      <Icon name="pen" size="sm" />
                      记录想法
                    </button>
                  </div>
                </div>
              )}

              <div className="panel next-panel">
                {currentIndex >= nodes.length - 1 ? (
                  <>
                    <div className="panel-head">
                      <Icon name="check-circle" size="sm" />
                      本课已讲完<span className="panel-sub">用练习收个尾</span>
                    </div>
                    <div className="next-foot" style={{ borderTop: 0 }}>
                      <span className="hint">共 {nodes.length} 个知识节点</span>
                      <button className="btn soft sm" onClick={() => setPhaseView('practice')}>
                        进入练习 <Icon name="right" size="sm" />
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="panel-head">
                      <Icon name="clock" size="sm" />
                      接下来
                      <span className="panel-sub">
                        还剩 {nodes.length - currentIndex - 1} 个节点
                      </span>
                    </div>
                    <div className="next-list">
                      {nodes.slice(currentIndex + 1, currentIndex + 3).map((n) => (
                        <div className="next-item" key={n.seq} onClick={() => jumpTo(n.start)}>
                          <span className="next-time">{fmt(n.start)}</span>
                          <span className="next-title">{n.title}</span>
                          <Icon name="chevron" size="sm" />
                        </div>
                      ))}
                    </div>
                    <div className="next-foot">
                      <span className="hint">
                        {current.end >= duration - 1 ? '已到本节末尾' : '点击节点可跳转'}
                      </span>
                      <button className="btn soft sm" onClick={() => setPhaseView('practice')}>
                        做本节练习 <Icon name="right" size="sm" />
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>

            <aside className={'panel transcript-panel' + (tab === 'notes' ? ' notes-mode' : '')}>
              <div className="panel-head transcript-head">
                <div className="seg-tabs">
                  <button
                    className={'seg-tab' + (tab === 'transcript' ? ' active' : '')}
                    onClick={() => {
                      setTab('transcript');
                      if (selectionMode) exitSelection();
                    }}
                  >
                    逐句原文 <span className="count">{transcript.length}</span>
                  </button>
                  <button
                    className={'seg-tab' + (tab === 'notes' ? ' active' : '')}
                    onClick={() => {
                      setTab('notes');
                      if (selectionMode) exitSelection();
                    }}
                  >
                    我的想法 <span className="count">{study.notes.length}</span>
                  </button>
                </div>
                <button
                  className={'back-current' + (!follow ? ' show' : '')}
                  onClick={goCurrent}
                >
                  <Icon name="down" size="sm" />
                  回到当前
                </button>
              </div>

              <div className="transcript-tools">
                <label className={'search-box' + (searchNorm ? ' has-value' : '')}>
                  <Icon name="search" size="sm" />
                  <input
                    placeholder="搜原文关键词…"
                    autoComplete="off"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                  <button
                    className="clear-btn"
                    aria-label="清空搜索"
                    onClick={() => setSearch('')}
                  >
                    <Icon name="x" size="sm" />
                  </button>
                </label>
                <button
                  className={'mode-pill' + (selectionMode ? ' active' : '')}
                  onClick={() => {
                    if (selectionMode) exitSelection();
                    else enterSelection();
                  }}
                >
                  {selectionMode ? '选择模式' : '点击跳转'}
                </button>
              </div>

              {selectionMode && (
                <div className="selection-banner">
                  <Icon name={selEnd !== null ? 'check-circle' : 'pen'} size="sm" />
                  <span>
                    {selEnd !== null
                      ? '已选定范围，可点击其他行重新选择'
                      : '点击选择结束行，或直接提交想法'}
                  </span>
                </div>
              )}

              <div
                className="transcript-scroll"
                ref={transcriptScrollRef}
                onScroll={handleTranscriptScroll}
              >
                <div>
                  {transcript.map((seg, i) => {
                    const dim = !!searchNorm && !seg.text.toLowerCase().includes(searchNorm);
                    const selected = !!range && i >= range.from && i <= range.to;
                    return (
                      <div
                        className={
                          'tline' +
                          (i === currentLine ? ' current' : '') +
                          (time >= seg.end ? ' read' : '') +
                          (noteLineSet.has(i) ? ' has-note' : '') +
                          (selectionMode ? ' selectable' : '') +
                          (selected ? ' selected' : '') +
                          (dim ? ' dim' : '')
                        }
                        key={i}
                        data-current={i === currentLine ? '1' : undefined}
                        onClick={() => {
                          if (selectionMode) selectLine(i);
                          else seekTo(seg.start, { play: true });
                        }}
                      >
                        <span className="t">{fmt(seg.start)}</span>
                        <span>{seg.text}</span>
                      </div>
                    );
                  })}
                </div>
                <div
                  className="transcript-empty"
                  style={{ display: searchNorm && searchHits === 0 ? 'block' : 'none' }}
                >
                  没有找到匹配的原文，换个关键词试试。
                </div>
              </div>

              <div className="notes-scroll">
                <div>
                  {notesSorted.length === 0 ? (
                    <div className="notes-empty">
                      <Icon name="note" />
                      <div>
                        还没有想法。
                        <br />
                        听课时点“记录想法”，会自动绑定当前时间。
                      </div>
                    </div>
                  ) : (
                    notesSorted.map((n) => {
                      const node = findNode(nodes, n.time);
                      return (
                        <div
                          className="note-card"
                          key={n.id}
                          onClick={() => jumpTo(n.time)}
                        >
                          <div className="note-card-top">
                            <Icon name="note" size="sm" />
                            <span className="n-time">{fmt(n.time)}</span>
                            <span>{node ? node.title : ''}</span>
                            <button
                              className="del"
                              title="删除"
                              onClick={(e) => {
                                e.stopPropagation();
                                deleteNote(n.id);
                              }}
                            >
                              <Icon name="trash" size="sm" />
                            </button>
                          </div>
                          <p>{n.text}</p>
                          {n.quote ? <div className="quote">{n.quote}</div> : null}
                        </div>
                      );
                    })
                  )}
                </div>
              </div>

              {tab === 'transcript' && (
                <div className="notequick">
                  <b>此刻发生了什么？</b>
                  <p className="muted small">
                    视频正在讲一个知识点。你的笔记会自动绑定当前时间，并在课后归入对应节点。
                  </p>
                  <button className="btn primary-blue" onClick={enterSelection}>
                    ＋ 记录此刻想法
                  </button>
                </div>
              )}
            </aside>
          </div>
        </div>

        {/* ============ 阶段 3 · 复习 ============ */}
        <div className={'phase-view' + (phase === 'review' ? ' active' : '')}>
          <div className="review-grid">
            <aside className="panel review-left">
              <div className="panel-head">
                <Icon name="map" size="sm" />
                本课章节
                <span className="panel-sub">
                  已回忆 {ratedCount}/{flashcards.length}
                </span>
              </div>
              <div className="panel-body">
                <div className="mastery-list">
                  {chapters.map((ch) => (
                    <div className="tree-chapter" key={ch.seq}>
                      <div className="tree-chapter-head">
                        <Icon name="down" size="sm" />
                        <span>{ch.title}</span>
                        <span className="panel-sub">{ch.nodes.length}</span>
                      </div>
                      <div className="tree-chapter-body">
                        {ch.nodes.map((n) => {
                          const r = study.ratings[String(n.seq)];
                          return (
                            <div className="tree-node" key={n.seq} onClick={() => jumpTo(n.start)}>
                              <span className={'mastery-dot' + (r ? ' ' + r : '')} />
                              <span>{n.title}</span>
                              <span className="node-time">{fmt(n.start)}</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mastery-legend">
                  <span>
                    <i style={{ background: 'var(--success)' }} />
                    记住
                  </span>
                  <span>
                    <i style={{ background: 'var(--warning)' }} />
                    模糊
                  </span>
                  <span>
                    <i style={{ background: 'var(--danger)' }} />
                    没印象
                  </span>
                </div>
              </div>
            </aside>

            <div className="review-center">
              <div className="section-head" style={{ marginTop: 0 }}>
                <h2>主动回忆</h2>
                <span className="badge purple">不翻原文，先说一遍</span>
                <span className="muted small" style={{ marginLeft: 'auto' }}>
                  {ratedCount} / {flashcards.length}
                </span>
              </div>
              <p className="section-desc">
                点击卡片先在心里回答，再展开对照。判断“记住 / 模糊 / 没印象”，系统会把薄弱点带到练习环节。
              </p>
              <div>
                {flashcards.map((card, i) => {
                  const node = nodeForCard(card);
                  const r = study.ratings[String(card.knowledge_seq)];
                  const open = openRecall.has(card.knowledge_seq);
                  return (
                    <div className={'recall-card' + (open ? ' open' : '')} key={card.seq}>
                      <div
                        className="recall-head"
                        onClick={() => toggleRecall(card.knowledge_seq)}
                      >
                        <div className="recall-top">
                          <span className="recall-no">{pad(i + 1)}</span>
                          <span className="recall-node">
                            {node
                              ? node.title
                              : chapters.find((c) => c.seq === card.chapter_seq)?.title || ''}{' '}
                            · {fmt(node ? node.start : 0)}
                          </span>
                          {r ? (
                            <span className={'recall-state ' + r}>{RATING_LABEL[r]}</span>
                          ) : null}
                          <span className="recall-toggle">
                            {open ? '收起' : '展开对照'} <Icon name="down" size="sm" />
                          </span>
                        </div>
                        <h3>{card.front}</h3>
                        <div className="recall-prompt">先别急着点开 · 用一句话说出答案</div>
                      </div>
                      <div className="recall-answer">
                        <p>{card.back}</p>
                        <ul className="recall-points">
                          <li>分类：{card.category}</li>
                          {node && node.statement && !sameLine(node.statement, card.back) ? (
                            <li>{node.statement}</li>
                          ) : null}
                        </ul>
                        <div className="recall-actions">
                          <button
                            className="btn ghost sm"
                            onClick={() => node && jumpTo(node.start)}
                          >
                            <Icon name="play" size="sm" />
                            跳转 {fmt(node ? node.start : 0)}
                          </button>
                          <button
                            className="btn ghost sm"
                            onClick={() => node && openSourceModal(node.start)}
                          >
                            <Icon name="search" size="sm" />
                            原文
                          </button>
                          <div className="rating-row">
                            <button
                              className={'rating-btn' + (r === 'good' ? ' on' : '')}
                              onClick={() => node && setRating(node.seq, 'good')}
                            >
                              记住了
                            </button>
                            <button
                              className={'rating-btn' + (r === 'fuzzy' ? ' on' : '')}
                              onClick={() => node && setRating(node.seq, 'fuzzy')}
                            >
                              有点模糊
                            </button>
                            <button
                              className={'rating-btn' + (r === 'bad' ? ' on' : '')}
                              onClick={() => node && setRating(node.seq, 'bad')}
                            >
                              没印象
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <aside className="review-side">
              <div className="panel">
                <div className="panel-head">
                  <Icon name="clock" size="sm" />
                  复习时间轴
                </div>
                <div className="panel-body">
                  <div className="timeline">
                    {[
                      ...nodes.map((n) => ({ time: n.start, kind: 'node', text: n.title })),
                      ...model.highlights.map((h) => ({
                        time: h.start,
                        kind: 'highlight',
                        text: h.statement || h.title,
                      })),
                      ...study.notes.map((n) => ({ time: n.time, kind: 'note', text: n.text })),
                    ]
                      .sort((a, b) => a.time - b.time)
                      .map((it, i) => (
                        <div
                          className={
                            'tl-item' +
                            (it.kind === 'highlight' ? ' highlight' : '') +
                            (it.kind === 'note' ? ' note' : '')
                          }
                          key={i}
                          onClick={() => jumpTo(it.time)}
                        >
                          <span className="tl-dot" />
                          <div className="tl-time">
                            {fmt(it.time)} ·{' '}
                            {it.kind === 'highlight'
                              ? '老师强调'
                              : it.kind === 'note'
                                ? '我的想法'
                                : '知识节点'}
                          </div>
                          <div className="tl-text">{it.text}</div>
                        </div>
                      ))}
                  </div>
                </div>
              </div>

              <div className="panel">
                <div className="panel-head">
                  <Icon name="star" size="sm" />
                  老师重点
                </div>
                <div className="panel-body">
                  {model.highlights.map((h) => (
                    <div className="hl-item" key={h.seq} onClick={() => jumpTo(h.start)}>
                      <Icon name="star" size="sm" />
                      <div>
                        <p>{h.statement || h.title}</p>
                        <span className="t">
                          {h.title} · {fmt(h.start)} →
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="panel">
                <div className="panel-head">
                  <Icon name="alert" size="sm" />
                  薄弱知识点
                </div>
                <div className="panel-body">
                  {weakSeqs.length ? (
                    <>
                      {weakSeqs.map((seq) => {
                        const n = model.nodeBySeq[seq];
                        if (!n) return null;
                        return (
                          <div className="weak-chip" key={seq} onClick={() => jumpTo(n.start)}>
                            <Icon name="alert" size="sm" />
                            {n.title}
                            <span>{fmt(n.start)}</span>
                          </div>
                        );
                      })}
                      <button
                        className="btn soft sm"
                        style={{ width: '100%', marginTop: 3 }}
                        onClick={() => setPhaseView('practice')}
                      >
                        去练习查漏 <Icon name="right" size="sm" />
                      </button>
                    </>
                  ) : (
                    <div className="weak-empty">
                      <Icon name="check-circle" size="sm" />
                      暂无薄弱点，继续保持
                    </div>
                  )}
                </div>
              </div>
            </aside>
          </div>
        </div>

        {/* ============ 阶段 4 · 练习 ============ */}
        <div className={'phase-view' + (phase === 'practice' ? ' active' : '')}>
          <div className="practice-grid">
            <aside className="panel practice-left">
              <div className="panel-head">
                <Icon name="target" size="sm" />
                练习进度
              </div>
              <div className="panel-body">
                <div className="practice-progress">
                  <b>{answeredCount}</b>
                  <span>/ {exercises.length} 已完成</span>
                </div>
                <div className="bar">
                  <i
                    style={{
                      width: `${exercises.length ? (answeredCount / exercises.length) * 100 : 0}%`,
                    }}
                  />
                </div>
                <div className="practice-stats">
                  <div>
                    正确率<b>{accuracy === null ? '--' : accuracy + '%'}</b>
                  </div>
                  <div>
                    答对<b>{rightCount}</b>
                  </div>
                  <div>
                    答错<b>{wrongCount}</b>
                  </div>
                </div>
                <div className="q-nav">
                  {exercises.map((ex, i) => {
                    const raw = study.practice[String(ex.seq)];
                    const cls =
                      raw === undefined
                        ? ''
                        : evaluateAnswer(ex, raw).ok
                          ? 'done'
                          : 'wrong';
                    return (
                      <button
                        className={'q-dot ' + cls}
                        key={ex.seq}
                        onClick={() =>
                          document
                            .getElementById(`q-${ex.seq}`)
                            ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                        }
                      >
                        {i + 1}
                      </button>
                    );
                  })}
                </div>
                <button className="btn ghost sm" style={{ width: '100%' }} onClick={resetPractice}>
                  <Icon name="rotate" size="sm" />
                  重新练习
                </button>
              </div>
            </aside>

            <div className="practice-center">
              <div className="section-head" style={{ marginTop: 0 }}>
                <h2>随堂练习</h2>
                <span className="badge green">AI 生成 · 已校验</span>
                <span className="muted small" style={{ marginLeft: 'auto' }}>
                  {exercises.length} 题 · 约 {Math.max(5, Math.round(exercises.length * 0.7))} 分钟
                </span>
              </div>
              <p className="section-desc">
                题目只覆盖本课时明确讲过的内容；每道题都绑定原文时间点，答错可以直接回看。
              </p>
              <div>
                {exercises.map((ex, i) => {
                  const raw = study.practice[String(ex.seq)];
                  const answered = raw !== undefined;
                  const result = answered ? evaluateAnswer(ex, raw) : null;
                  const node = nodeForExercise(ex);
                  const isChoice = ex.qtype === 'choice';
                  const isJudge = ex.qtype === 'judge';
                  const options = isJudge ? ['正确', '错误'] : ex.options || [];
                  const selectedIdx = drafts[String(ex.seq)] !== undefined
                    ? Number(drafts[String(ex.seq)])
                    : undefined;
                  const correctIdx = isChoice
                    ? correctOptionIndex(ex)
                    : isJudge
                      ? (ex.answer || '').includes('正确')
                        ? 0
                        : 1
                      : -1;
                  const chosenIdx = answered
                    ? (() => {
                        const n = Number(raw);
                        if (Number.isInteger(n) && n >= 0 && n < options.length) return n;
                        return options.findIndex(
                          (o) => optionText(o) === optionText(raw) || o === raw
                        );
                      })()
                    : selectedIdx;
                  const draft = drafts[String(ex.seq)] ?? '';
                  return (
                    <div className="panel q-card" id={`q-${ex.seq}`} key={ex.seq}>
                      <div className="q-head">
                        <span className="q-index">{pad(i + 1)}</span>
                        <span className="q-type">{qtypeLabel(ex.qtype)}</span>
                        <span className="q-node">{node ? node.title : ''}</span>
                        <span
                          className="q-src"
                          onClick={() => node && openSourceModal(node.start)}
                        >
                          <Icon name="play" size="sm" />
                          {fmt(node ? node.start : 0)}
                        </span>
                      </div>
                      <p className="q-text">{ex.stem}</p>

                      {isChoice || isJudge ? (
                        <>
                          <div className={'opts' + (isJudge ? ' row' : '')}>
                            {options.map((opt, oi) => {
                              const isSelected = chosenIdx === oi && !answered;
                              const cls =
                                answered
                                  ? oi === correctIdx
                                    ? ' correct locked'
                                    : oi === chosenIdx
                                      ? ' incorrect locked'
                                      : ' locked'
                                  : isSelected
                                    ? ' selected'
                                    : '';
                              return (
                                <div
                                  className={'opt' + cls}
                                  key={oi}
                                  onClick={() => {
                                    if (answered) return;
                                    setDrafts({ ...drafts, [String(ex.seq)]: String(oi) });
                                  }}
                                >
                                  <span className="key">{optionLetter(oi)}</span>
                                  <span>{optionText(opt)}</span>
                                </div>
                              );
                            })}
                          </div>
                          <div className="q-actions">
                            <button
                              className="btn primary sm"
                              disabled={answered || chosenIdx === undefined}
                              onClick={() => {
                                if (chosenIdx === undefined) return;
                                checkExercise(
                                  ex,
                                  isJudge ? options[chosenIdx] : String(chosenIdx)
                                );
                              }}
                            >
                              检查答案
                            </button>
                          </div>
                        </>
                      ) : (
                        <div className="fill-row">
                          <input
                            className={
                              'fill-input' +
                              (answered ? (result?.ok ? ' correct' : ' incorrect') : '')
                            }
                            placeholder={ex.qtype === 'short' ? '用一句话回答…' : '填写答案…'}
                            autoComplete="off"
                            value={answered ? raw : draft}
                            disabled={answered}
                            onChange={(e) =>
                              setDrafts({ ...drafts, [String(ex.seq)]: e.target.value })
                            }
                          />
                          <button
                            className="btn primary sm"
                            disabled={answered || !draft.trim()}
                            onClick={() => checkExercise(ex, draft)}
                          >
                            检查答案
                          </button>
                        </div>
                      )}

                      {result && (
                        <div className={'feedback show ' + (result.ok ? 'ok' : 'bad')}>
                          <div className="fb-title">
                            <Icon name={result.ok ? 'check-circle' : 'alert'} size="sm" />
                            {result.ok ? '回答正确' : '回答错误'}
                          </div>
                          {!result.ok && (
                            <div>
                              正确答案：<b>{result.correct}</b>　你的答案：{result.chosen}
                            </div>
                          )}
                          <div style={{ marginTop: 4 }}>{ex.explanation}</div>
                          <span
                            className="fb-src"
                            onClick={() => node && openSourceModal(node.start)}
                          >
                            <Icon name="play" size="sm" />
                            回看原文 {fmt(node ? node.start : 0)}
                          </span>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            <aside className="practice-side">
              <div className="panel">
                <div className="panel-head">
                  <Icon name="check-circle" size="sm" />
                  练习结果
                </div>
                <div className="panel-body">
                  {answeredCount === 0 ? (
                    <p className="muted small" style={{ lineHeight: 1.7 }}>
                      还没有完成任何题目。
                      <br />
                      先做几题，就能看到正确率和薄弱点。
                    </p>
                  ) : (
                    <>
                      <div className="score-big">
                        {rightCount}
                        <small> / {answeredCount}</small>
                      </div>
                      <div className="score-sub">
                        正确率 {accuracy}% · 还剩 {exercises.length - answeredCount} 题
                      </div>
                      <div className="score-tags">
                        {wrongCount > 0 ? (
                          <span className="badge red">{wrongCount} 题需回看</span>
                        ) : (
                          <span className="badge green">已答全对</span>
                        )}
                        {answeredCount < exercises.length ? (
                          <span className="badge gray">继续练习</span>
                        ) : (
                          <span className="badge blue">已完成</span>
                        )}
                      </div>
                    </>
                  )}
                </div>
              </div>

              <div className="panel">
                <div className="panel-head">
                  <Icon name="alert" size="sm" />
                  薄弱知识点
                </div>
                <div className="panel-body">
                  {(() => {
                    const weak = new Set<number>();
                    exercises.forEach((ex) => {
                      const raw = study.practice[String(ex.seq)];
                      if (raw !== undefined && !evaluateAnswer(ex, raw).ok && ex.knowledge_seq) {
                        weak.add(ex.knowledge_seq);
                      }
                    });
                    return weak.size ? (
                      Array.from(weak)
                        .map((seq) => {
                        const n = model.nodeBySeq[seq];
                        if (!n) return null;
                        return (
                          <div className="weak-chip" key={seq} onClick={() => jumpTo(n.start)}>
                            <Icon name="alert" size="sm" />
                            {n.title}
                            <span>{fmt(n.start)}</span>
                          </div>
                        );
                      })
                    ) : answeredCount > 0 ? (
                      <div className="weak-empty">
                        <Icon name="check-circle" size="sm" />
                        已答题目全部正确
                      </div>
                    ) : (
                      <p className="muted small">答完题后自动标记</p>
                    );
                  })()}
                </div>
              </div>

              <div className="panel">
                <div className="panel-head">
                  <Icon name="layers" size="sm" />
                  关联课程节点
                </div>
                <div className="panel-body">
                  {Array.from(new Set(exercises.map((ex) => ex.knowledge_seq)))
                    .map((seq) => model.nodeBySeq[seq])
                    .filter((n): n is LessonNode => !!n)
                    .map((n) => (
                      <div className="node-link" key={n.seq} onClick={() => jumpTo(n.start)}>
                        <Icon name="book" size="sm" />
                        <span>{n.title}</span>
                        <span className="t">{fmt(n.start)}</span>
                      </div>
                    ))}
                </div>
              </div>
            </aside>
          </div>
        </div>
      </div>

      {/* ============ Modals ============ */}
      <div
        className={'modal' + (noteCtx ? ' open' : '')}
        onClick={(e) => {
          if (e.target === e.currentTarget) closeNoteModal();
        }}
      >
        <div className="modal-box">
          <div className="modal-head">
            <h3>记录我的想法</h3>
            <button
              className="icon-btn"
              aria-label="关闭"
              onClick={closeNoteModal}
            >
              <Icon name="x" />
            </button>
          </div>
          <div className="modal-meta">
            <span className="badge blue">
              {noteCtx && noteCtx.end !== undefined && noteCtx.end > noteCtx.time
                ? `${fmt(noteCtx.time)} – ${fmt(noteCtx.end)}`
                : fmt(noteCtx ? noteCtx.time : time)}
            </span>
            <span>{noteNode ? noteNode.title : ''}</span>
            <span className="muted">已自动绑定</span>
          </div>
          {noteCtx?.lines?.length ? (
            <div className="quote-box quote-lines">
              <span className="q-label">针对以下原文</span>
              {noteCtx.lines.map((line, i) => (
                <div className="quote-line" key={i}>
                  <span className="ql-time">{fmt(line.time)}</span>
                  <span>
                    {line.text.length > 40 ? line.text.slice(0, 40) + '…' : line.text}
                  </span>
                </div>
              ))}
            </div>
          ) : noteCtx?.quote ? (
            <div className="quote-box">
              <span className="q-label">针对以下原文</span>
              {noteCtx.quote}
            </div>
          ) : null}
          <textarea
            id="noteText"
            ref={noteInputRef}
            value={noteText}
            onChange={(e) => setNoteText(e.target.value)}
            placeholder="例如：这里老师说填空和判断占了 20 题，我之前的复习顺序可能排反了……"
          />
          <div className="modal-tip">
            保存后自动绑定当前时间与知识节点；可在复习时间轴中回看。
          </div>
          <div className="modal-actions">
            <span className="spacer" />
            <button className="btn" onClick={closeNoteModal}>
              取消
            </button>
            <button className="btn primary" onClick={saveNote}>
              保存想法
            </button>
          </div>
        </div>
      </div>

      <div
        className={'modal' + (sourceTime !== null ? ' open' : '')}
        onClick={(e) => {
          if (e.target === e.currentTarget) setSourceTime(null);
        }}
      >
        <div className="modal-box">
          <div className="modal-head">
            <h3>老师原文</h3>
            <button
              className="icon-btn"
              aria-label="关闭"
              onClick={() => setSourceTime(null)}
            >
              <Icon name="x" />
            </button>
          </div>
          <div className="modal-meta">
            <span className="badge blue">{fmt(sourceTime !== null ? sourceTime : 0)}</span>
            <span>
              {sourceTime !== null
                ? (findNode(nodes, sourceTime)?.title || '')
                : ''}
            </span>
            <span className="muted">Whisper 原稿 · 未改写</span>
          </div>
          <div className="source-quote">
            {source?.lines.map((s, i) => {
              const isTarget = source.from + i === source.idx;
              return (
                <p key={i} style={{ margin: '4px 0' }}>
                  <span
                    className="muted tiny"
                    style={{ display: 'inline-block', width: 34 }}
                  >
                    {fmt(s.start)}
                  </span>
                  <span className={isTarget ? 'hl' : ''}>{s.text}</span>
                </p>
              );
            })}
          </div>
          <div className="modal-actions">
            <span className="spacer" />
            <button className="btn" onClick={() => setSourceTime(null)}>
              关闭
            </button>
            <button
              className="btn primary"
              onClick={() => {
                const t = sourceTime;
                setSourceTime(null);
                if (t !== null) jumpTo(t);
              }}
            >
              在时间轴中打开
            </button>
          </div>
        </div>
      </div>

      <div className={'select-bar' + (selectionMode ? ' show' : '')}>
        <span>
          <b>已选 {range ? range.to - range.from + 1 : 0} 句</b>
        </span>
        <span className="sb-meta">
          {range
            ? `${fmt(transcript[range.from].start)} – ${fmt(transcript[range.to].end)}`
            : ''}
        </span>
        <button className="btn sm light" onClick={exitSelection}>
          取消
        </button>
        <button className="btn sm white" onClick={confirmSelection}>
          用这段原文记录想法
        </button>
      </div>

      <div className={'toast' + (toast ? ' show' : '')} role="status" aria-live="polite">
        {toast}
      </div>
    </>
  );
}
