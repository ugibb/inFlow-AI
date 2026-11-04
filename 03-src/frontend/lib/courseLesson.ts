import type {
  CourseDetail,
  LessonDetail,
  LessonSummary,
  TranscriptSegment,
} from './types';

export interface PreviewCard {
  chapter_seq: number;
  chapter_title: string;
  heading: string;
  questions: string[];
  key_terms?: string[];
}

export interface LearningCard {
  chapter_seq: number;
  chapter_title: string;
  key_points: string[];
  structure: string;
  board_notes: string;
  checkpoints: string[];
}

export interface Flashcard {
  seq: number;
  front: string;
  back: string;
  category: string;
  chapter_seq: number;
  knowledge_seq: number;
}

export interface Exercise {
  seq: number;
  qtype: 'choice' | 'fill' | 'judge' | 'short' | string;
  stem: string;
  options: string[] | null;
  answer: string;
  explanation: string;
  difficulty: number;
  chapter_seq: number;
  knowledge_seq: number;
}

export interface LessonNode {
  seq: number;
  kind: string;
  title: string;
  statement: string;
  quote: string;
  importance: number;
  start: number;
  end: number;
  chapterSeq: number;
  chapterTitle: string;
}

export interface LessonChapter {
  seq: number;
  title: string;
  summary: string;
  start: number;
  end: number;
  nodes: LessonNode[];
  preview?: PreviewCard;
  learning?: LearningCard;
}

export interface GlossTerm {
  term: string;
  meaning: string;
  chapter_seq?: number;
}

export interface LessonModel {
  course: CourseDetail;
  detail: LessonDetail;
  lesson: LessonSummary;
  transcript: TranscriptSegment[];
  duration: number;
  chapters: LessonChapter[];
  nodes: LessonNode[];
  nodeBySeq: Record<number, LessonNode>;
  previewCards: PreviewCard[];
  learningCards: LearningCard[];
  flashcards: Flashcard[];
  exercises: Exercise[];
  glossary: GlossTerm[];
  introQuestion: string;
  highlights: LessonNode[];
  audit: any;
}

export function segmentIndex(
  segmentId: string | number | undefined,
  segments: TranscriptSegment[]
): number {
  if (segmentId === undefined || segmentId === null || segmentId === '') return -1;
  if (typeof segmentId === 'number') {
    return segmentId >= 0 && segmentId < segments.length ? segmentId : -1;
  }
  const digits = String(segmentId).replace(/[^\d]/g, '');
  const n = parseInt(digits, 10);
  if (!Number.isFinite(n)) return -1;
  const idx = n - 1;
  return idx >= 0 && idx < segments.length ? idx : -1;
}

function nodeTimeRange(segmentIds: string[], segments: TranscriptSegment[]): { start: number; end: number } {
  let start = Number.POSITIVE_INFINITY;
  let end = 0;
  (segmentIds || []).forEach((sid) => {
    const idx = segmentIndex(sid, segments);
    if (idx < 0) return;
    start = Math.min(start, segments[idx].start);
    end = Math.max(end, segments[idx].end);
  });
  if (!Number.isFinite(start)) return { start: 0, end: 0 };
  return { start, end };
}

export function buildLessonModel(course: CourseDetail, detail: LessonDetail): LessonModel {
  const transcript = [...(detail.transcript?.segments || [])].sort((a, b) => a.start - b.start);
  const duration =
    detail.lesson.duration_sec ||
    (transcript.length ? transcript[transcript.length - 1].end : 0);

  const preview = detail.views?.preview || {};
  const learning = detail.views?.learning || {};
  const review = detail.views?.review || {};
  const practice = detail.views?.practice || {};

  const previewCards: PreviewCard[] = preview.preview_cards || [];
  const learningCards: LearningCard[] = learning.learning_cards || [];
  const flashcards: Flashcard[] = review.flashcards || [];
  const exercises: Exercise[] = practice.exercises || [];
  const glossary: GlossTerm[] = preview.glossary || [];
  const introQuestion: string = preview.intro_question || '';

  const rawChapters: any[] = detail.chapters?.chapters || [];
  const rawNodes: any[] = detail.knowledge_tree?.knowledge_points || [];

  // Chapter time ranges from segment ids.
  const chapters: LessonChapter[] = rawChapters.map((c, i) => {
    const startIdx = segmentIndex(c.start_segment_id, transcript);
    const endIdx = segmentIndex(c.end_segment_id, transcript);
    const start = startIdx >= 0 ? transcript[startIdx].start : i === 0 ? 0 : 0;
    const end = endIdx >= 0 ? transcript[endIdx].end : duration;
    return {
      seq: c.seq ?? i + 1,
      title: c.title || `第 ${i + 1} 章`,
      summary: c.summary || '',
      start,
      end: Math.max(start, end),
      nodes: [],
      preview: previewCards.find((p) => p.chapter_seq === (c.seq ?? i + 1)),
      learning: learningCards.find((l) => l.chapter_seq === (c.seq ?? i + 1)),
    };
  });

  if (chapters.length === 0) {
    chapters.push({
      seq: 1,
      title: detail.lesson.chapter_title || '本课',
      summary: '',
      start: 0,
      end: duration,
      nodes: [],
      preview: previewCards[0],
      learning: learningCards[0],
    });
  }

  const chapterIndexFor = (idx: number) => {
    let hit = 0;
    for (let i = 0; i < chapters.length; i++) {
      const startIdx = segmentIndex(rawChapters[i]?.start_segment_id, transcript);
      const endIdx = segmentIndex(rawChapters[i]?.end_segment_id, transcript);
      if (startIdx < 0 && endIdx < 0) continue;
      if (idx >= startIdx && idx <= endIdx) return i;
      if (idx > endIdx) hit = i;
    }
    return hit;
  };

  const nodes: LessonNode[] = rawNodes
    .map((n, i) => {
      const ranges = nodeTimeRange(n.segment_ids || [], transcript);
      const firstIdx = segmentIndex((n.segment_ids || [])[0], transcript);
      const chIdx = chapterIndexFor(firstIdx);
      const ch = chapters[chIdx] || chapters[0];
      return {
        seq: n.seq ?? i + 1,
        kind: n.kind || 'concept',
        title: n.title || `知识点 ${i + 1}`,
        statement: n.statement || '',
        quote: n.quote || '',
        importance: n.importance || 1,
        start: ranges.start,
        end: ranges.end,
        chapterSeq: ch.seq,
        chapterTitle: ch.title,
      };
    })
    .sort((a, b) => a.start - b.start || a.seq - b.seq);

  // Non-overlapping timeline: each node runs until the next node starts.
  nodes.forEach((n, i) => {
    const next = nodes[i + 1];
    if (next && next.start > n.start) n.end = next.start;
    else n.end = Math.max(n.end, n.start + 1);
  });
  if (nodes.length) nodes[nodes.length - 1].end = Math.max(nodes[nodes.length - 1].end, duration);

  nodes.forEach((n) => {
    const ch = chapters.find((c) => c.seq === n.chapterSeq);
    if (ch) ch.nodes.push(n);
  });

  const nodeBySeq: Record<number, LessonNode> = {};
  nodes.forEach((n) => {
    nodeBySeq[n.seq] = n;
  });

  const highlights = nodes.filter((n) => n.kind === 'exam_tip' || n.importance >= 3);

  return {
    course,
    detail,
    lesson: detail.lesson,
    transcript,
    duration,
    chapters,
    nodes,
    nodeBySeq,
    previewCards,
    learningCards,
    flashcards,
    exercises,
    glossary,
    introQuestion,
    highlights,
    audit: detail.audit,
  };
}

export function findNode(nodes: LessonNode[], t: number): LessonNode | null {
  if (!nodes.length) return null;
  let hit = nodes[0];
  for (const n of nodes) {
    if (n.start <= t) hit = n;
    else break;
  }
  return hit;
}

export function nodeOfSeq(model: LessonModel, seq: number): LessonNode | null {
  return model.nodeBySeq[seq] || null;
}

/** Strip the baked-in "A. " prefix from generated options. */
export function optionText(option: string): string {
  return String(option || '').replace(/^\s*[A-Da-d][.、:：]\s*/, '').trim();
}

export function optionLetter(index: number): string {
  return String.fromCharCode(65 + index);
}

/** Index of the correct choice option, or -1 when it cannot be derived. */
export function correctOptionIndex(ex: Exercise): number {
  const options = ex.options || [];
  const letter = String(ex.answer || '')
    .trim()
    .toUpperCase()
    .replace(/[^A-D]/g, '');
  if (letter) {
    const idx = letter.charCodeAt(0) - 65;
    return idx >= 0 && idx < options.length ? idx : -1;
  }
  return options.findIndex((o) => normalize(optionText(o)) === normalize(ex.answer));
}

export function qtypeLabel(qtype: string): string {
  if (qtype === 'choice') return '单选题';
  if (qtype === 'fill') return '填空题';
  if (qtype === 'judge') return '判断题';
  if (qtype === 'short') return '简答题';
  return qtype;
}

function normalize(str: string): string {
  return String(str || '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '')
    .replace(/[。，,.、；;：:！？!?"'“”‘’()（）]/g, '');
}

function cleanAnswer(answer: string): string {
  return String(answer || '')
    .replace(/[（(][^）)]*[）)]/g, '')
    .trim();
}

export interface AnswerResult {
  ok: boolean;
  chosen: string;
  correct: string;
}

/**
 * Lenient checking shared by the practice UI and persisted answers.
 * choice: stored option index ("0".."3") or text; judge: stored text;
 * fill/short: free text.
 */
export function evaluateAnswer(ex: Exercise, raw: string | undefined): AnswerResult {
  if (raw === undefined || raw === '') {
    return { ok: false, chosen: '', correct: ex.answer };
  }

  if (ex.qtype === 'choice') {
    const options = ex.options || [];
    let idx = Number(raw);
    if (!Number.isInteger(idx) || idx < 0 || idx >= options.length) {
      idx = options.findIndex((o) => normalize(optionText(o)) === normalize(raw));
    }
    const answerIdx = (() => {
      const letter = String(ex.answer || '').trim().toUpperCase().replace(/[^A-D]/g, '');
      if (letter) return letter.charCodeAt(0) - 65;
      return options.findIndex((o) => normalize(optionText(o)) === normalize(ex.answer));
    })();
    return {
      ok: idx >= 0 && idx === answerIdx,
      chosen: idx >= 0 ? optionText(options[idx] || raw) : raw,
      correct: answerIdx >= 0 ? optionText(options[answerIdx]) : ex.answer,
    };
  }

  if (ex.qtype === 'judge') {
    const value = normalize(raw);
    const answer = normalize(ex.answer);
    return { ok: value === answer, chosen: raw, correct: ex.answer };
  }

  // fill + short: accept any listed alternative; for multi-alternative
  // answers accept partial matches (e.g. "任意三个后缀").
  const answer = cleanAnswer(ex.answer);
  const parts = answer
    .split(/[、/／，,；;|｜]/)
    .map((s) => normalize(s))
    .filter(Boolean);
  const normRaw = normalize(raw);

  if (parts.length > 1) {
    const hits = parts.filter((p) => normRaw.includes(p) || p.includes(normRaw)).length;
    const needed = ex.qtype === 'short' ? 1 : Math.min(3, parts.length);
    const ok = normRaw.length >= 2 && (hits >= needed || (parts.length > 4 && hits >= 1));
    return { ok, chosen: raw, correct: answer };
  }

  if (ex.qtype === 'short') {
    const chars = Array.from(new Set(normalize(answer).split('')));
    const hitChars = chars.filter((c) => normRaw.includes(c)).length;
    const ratio = chars.length ? hitChars / chars.length : 0;
    return { ok: ratio >= 0.45, chosen: raw, correct: answer };
  }

  return {
    ok: normRaw === normalize(answer) || normRaw.includes(normalize(answer)),
    chosen: raw,
    correct: answer,
  };
}
