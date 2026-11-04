/**
 * Per-lesson study state kept in localStorage.
 * Used by the four-phase lesson page and the library resume card.
 */

export interface CourseNote {
  id: string;
  time: number;
  quote?: string;
  text: string;
  createdAt: number;
}

export interface StudyState {
  position: number;
  notes: CourseNote[];
  /** recall card rating keyed by knowledge_seq */
  ratings: Record<string, 'good' | 'fuzzy' | 'bad'>;
  /** knowledge point seqs already passed in the learning phase */
  doneNodes: number[];
  /** checked practice answers keyed by exercise seq */
  practice: Record<string, string>;
}

const EMPTY: StudyState = {
  position: 0,
  notes: [],
  ratings: {},
  doneNodes: [],
  practice: {},
};

function storageKey(lessonKey: string) {
  return `inflow.course.study.${lessonKey}`;
}

export function readStudyState(lessonKey: string): StudyState {
  if (typeof window === 'undefined' || !lessonKey) return { ...EMPTY };
  try {
    const raw = window.localStorage.getItem(storageKey(lessonKey));
    if (!raw) return { ...EMPTY, notes: [], ratings: {}, doneNodes: [], practice: {} };
    const parsed = JSON.parse(raw) as Partial<StudyState>;
    return {
      position: typeof parsed.position === 'number' ? parsed.position : 0,
      notes: Array.isArray(parsed.notes) ? parsed.notes : [],
      ratings: parsed.ratings && typeof parsed.ratings === 'object' ? parsed.ratings : {},
      doneNodes: Array.isArray(parsed.doneNodes) ? parsed.doneNodes : [],
      practice: parsed.practice && typeof parsed.practice === 'object' ? parsed.practice : {},
    };
  } catch {
    return { ...EMPTY, notes: [], ratings: {}, doneNodes: [], practice: {} };
  }
}

export function writeStudyState(lessonKey: string, state: StudyState) {
  if (typeof window === 'undefined' || !lessonKey) return;
  try {
    window.localStorage.setItem(storageKey(lessonKey), JSON.stringify(state));
  } catch {
    /* quota / private mode — study still works for this session */
  }
}

export function updateStudyState(
  lessonKey: string,
  patch: Partial<StudyState> | ((prev: StudyState) => Partial<StudyState>)
): StudyState {
  const prev = readStudyState(lessonKey);
  const next = { ...prev, ...(typeof patch === 'function' ? patch(prev) : patch) };
  writeStudyState(lessonKey, next);
  return next;
}
