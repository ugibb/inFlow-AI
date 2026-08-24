'use client';

import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { StepLogEntry } from '@/lib/api';

const POLL_INTERVAL_MS = 3000;
const STALE_THRESHOLD_MS = 10 * 60 * 1000; // 10 minutes — Groq segments can take several minutes

export interface StepLogsState {
  logs: StepLogEntry[];
  isStale: boolean;
  staleSecs: number;
}

export function useStepLogs(
  jobId: string | undefined,
  step: string,
  enabled: boolean,
): StepLogsState {
  const [logs, setLogs] = useState<StepLogEntry[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!enabled || !jobId) {
      setLogs([]);
      return;
    }

    let cancelled = false;

    const poll = async () => {
      try {
        const data = await api.getJobLogs(jobId, step);
        if (!cancelled) setLogs(data.logs);
      } catch {
        // silently ignore poll errors — UI stays on stale data
      }
    };

    poll();
    timerRef.current = setInterval(poll, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [jobId, step, enabled]);

  const lastEntry = logs[logs.length - 1];
  const lastTs = lastEntry?.ts;
  const staleSecs = lastTs ? Math.floor((Date.now() - parseHHMMSS(lastTs)) / 1000) : 0;
  const isStale = logs.length > 0 && staleSecs > STALE_THRESHOLD_MS / 1000;

  return { logs, isStale, staleSecs };
}

// ts is stored as "HH:MM:SS" (local time of the server).
// We reconstruct today's date in local time for the diff — good enough for display.
function parseHHMMSS(ts: string): number {
  const [h, m, s] = ts.split(':').map(Number);
  const d = new Date();
  d.setHours(h, m, s, 0);
  return d.getTime();
}
