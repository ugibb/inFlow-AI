'use client';

import { useRef, useState, useLayoutEffect } from 'react';
import { createPortal } from 'react-dom';
import { Check, Loader2, AlertCircle, XCircle, RotateCcw } from 'lucide-react';
import { useStepLogs } from '@/hooks/useStepLogs';
import type { StepLogEntry } from '@/lib/api';
import type { PipelineStep } from '@/lib/types';

// ── Step definitions per content type ────────────────────────────────

type StepDef = {
  label: string;
  /** Job statuses where this step shows a spinner (in progress). */
  activeStatuses: string[];
  /** Job status that means this step completed and the next hasn't started yet. */
  doneStatus: string;
  retryFrom: string;
};

const ARTICLE_STEPS: StepDef[] = [
  { label: '采集',     activeStatuses: ['pending', 'capturing'], doneStatus: 'captured', retryFrom: 'capturing' },
  { label: 'AI 解析',  activeStatuses: ['parsing'],              doneStatus: 'parsed',   retryFrom: 'parsing'   },
  { label: '语义索引', activeStatuses: ['indexing'],             doneStatus: '',         retryFrom: 'indexing'  },
  { label: '完成',     activeStatuses: [],                       doneStatus: '',         retryFrom: ''          },
];

const AUDIO_STEPS: StepDef[] = [
  { label: '采集',     activeStatuses: ['pending', 'capturing'], doneStatus: 'captured',    retryFrom: 'capturing'    },
  { label: '转录',     activeStatuses: ['transcribing'],          doneStatus: 'transcribed', retryFrom: 'transcribing' },
  { label: 'AI 解析',  activeStatuses: ['parsing'],               doneStatus: 'parsed',      retryFrom: 'parsing'      },
  { label: '语义索引', activeStatuses: ['indexing'],              doneStatus: '',            retryFrom: 'indexing'     },
  { label: '完成',     activeStatuses: [],                        doneStatus: '',            retryFrom: ''             },
];

const VIDEO_STEPS: StepDef[] = [
  { label: '采集',     activeStatuses: ['pending', 'capturing'],  doneStatus: 'captured',     retryFrom: 'capturing'    },
  { label: '预处理',   activeStatuses: ['preprocessing'],          doneStatus: 'preprocessed', retryFrom: 'capturing'    },
  { label: '转录',     activeStatuses: ['transcribing'],           doneStatus: 'transcribed',  retryFrom: 'transcribing' },
  { label: 'AI 解析',  activeStatuses: ['parsing'],                doneStatus: 'parsed',       retryFrom: 'parsing'      },
  { label: '语义索引', activeStatuses: ['indexing'],               doneStatus: '',             retryFrom: 'indexing'     },
  { label: '完成',     activeStatuses: [],                         doneStatus: '',             retryFrom: ''             },
];

function getSteps(contentType: string): StepDef[] {
  if (contentType === 'audio') return AUDIO_STEPS;
  if (contentType === 'video') return VIDEO_STEPS;
  return ARTICLE_STEPS;
}

// ── Step state resolution ─────────────────────────────────────────────

type StepState = 'done' | 'active' | 'failed' | 'pending';

function resolveSteps(
  steps: StepDef[],
  status: string,
  errorStage: string | null | undefined,
): StepState[] {
  if (status === 'ready') return steps.map(() => 'done');

  if (status === 'failed' || status === 'cancelled') {
    let failedIdx = -1;
    if (errorStage) {
      failedIdx = steps.findIndex(
        (s) =>
          s.activeStatuses.includes(errorStage) ||
          s.doneStatus === errorStage ||
          s.retryFrom === errorStage,
      );
    }
    if (failedIdx < 0) failedIdx = steps.length - 2;
    return steps.map((_, i) => {
      if (i < failedIdx) return 'done';
      if (i === failedIdx) return 'failed';
      return 'pending';
    });
  }

  const activeIdx = steps.findIndex((s) => s.activeStatuses.includes(status));
  if (activeIdx >= 0) {
    return steps.map((_, i) => (i < activeIdx ? 'done' : i === activeIdx ? 'active' : 'pending'));
  }

  const doneIdx = steps.findIndex((s) => s.doneStatus === status);
  if (doneIdx >= 0) {
    return steps.map((_, i) => (i <= doneIdx ? 'done' : 'pending'));
  }

  return steps.map(() => 'pending');
}

// ── Log Popover — portal-based, escapes any overflow/stacking context ─

function LogPopover({
  logs,
  isStale,
  staleSecs,
  anchorEl,
}: {
  logs: StepLogEntry[];
  isStale: boolean;
  staleSecs: number;
  anchorEl: HTMLElement | null;
}) {
  // 'above' | 'below' — flip to below when the pipeline bar is too close to the top
  const [coords, setCoords] = useState<{
    placement: 'above' | 'below';
    y: number;
    left: number;       // popup center X (clamped to stay in viewport)
    caretPct: number;   // caret left% relative to popup width — points at trigger
  } | null>(null);

  // Approximate max popover height: header(36) + logs(188) + stale bar(32) + padding
  const POPOVER_W = 460;
  const POPOVER_MAX_H = 270;
  const GAP = 8;

  useLayoutEffect(() => {
    if (!anchorEl) return;
    const r = anchorEl.getBoundingClientRect();
    const triggerCX = r.left + r.width / 2;
    const clampedX = Math.max(POPOVER_W / 2, Math.min(window.innerWidth - POPOVER_W / 2, triggerCX));
    const spaceAbove = r.top;
    const placement = spaceAbove >= POPOVER_MAX_H + GAP ? 'above' : 'below';
    // Caret offset: how far the trigger center is from the popup center
    const caretPct = Math.max(8, Math.min(92,
      ((triggerCX - clampedX) / POPOVER_W + 0.5) * 100
    ));
    setCoords({
      placement,
      y: placement === 'above' ? r.top - GAP : r.bottom + GAP,
      left: clampedX,
      caretPct,
    });
  }, [anchorEl]);

  if (!coords) return null;

  const staleLabel = staleSecs >= 60
    ? `${Math.floor(staleSecs / 60)} 分钟无更新`
    : `${staleSecs} 秒无更新`;

  const posStyle: React.CSSProperties =
    coords.placement === 'above'
      ? { position: 'fixed', bottom: window.innerHeight - coords.y, left: coords.left, transform: 'translateX(-50%)', zIndex: 9999, width: POPOVER_W }
      : { position: 'fixed', top: coords.y,                         left: coords.left, transform: 'translateX(-50%)', zIndex: 9999, width: POPOVER_W };

  const caretBase = 'absolute w-[9px] h-[9px] bg-white';
  const caretStyle: React.CSSProperties = { left: `${coords.caretPct}%`, transform: 'translateX(-50%) rotate(45deg)' };

  const popover = (
    <div
      style={posStyle}
      className="bg-white border border-[#e5e5ea] rounded-2xl overflow-hidden shadow-[0_12px_40px_rgba(0,0,0,0.14),0_2px_8px_rgba(0,0,0,0.06)]"
    >
      {/* Caret — dynamically offset to point at the active step */}
      {coords.placement === 'above' ? (
        <div className={`${caretBase} -bottom-[5px] border-r border-b border-[#e5e5ea]`} style={caretStyle} />
      ) : (
        <div className={`${caretBase} -top-[5px] border-l border-t border-[#e5e5ea]`} style={caretStyle} />
      )}

      {/* Header */}
      <div className="flex items-center gap-1.5 px-3 py-2 border-b border-[#f2f2f7]">
        <span className="text-[11px] font-semibold text-[#6e6e73] flex-1">运行日志</span>
        {isStale ? (
          <>
            <span className="w-1.5 h-1.5 rounded-full bg-[#ff9500]" />
            <span className="text-[10px] font-medium text-[#ff9500]">{staleLabel}</span>
          </>
        ) : (
          <>
            <span className="w-1.5 h-1.5 rounded-full bg-[#34c759] animate-pulse" />
            <span className="text-[10px] font-medium text-[#34c759]">实时</span>
          </>
        )}
      </div>

      {/* Log entries — newest first */}
      <div className="max-h-[188px] overflow-y-auto py-1">
        {[...logs].reverse().map((entry, i) => (
          <div
            key={i}
            className="flex gap-2 px-3 py-[3px] text-[11px] leading-[1.45] hover:bg-[#f5f5f7]"
          >
            <span className="text-[#aeaeb2] tabular-nums shrink-0 pt-px text-[10px] tracking-tight">
              {entry.ts}
            </span>
            <span className="text-[#1d1d1f] truncate">{entry.msg}</span>
          </div>
        ))}
      </div>

      {/* Stale warning */}
      {isStale && (
        <div className="flex items-center gap-1.5 px-3 py-1.5 bg-[#ff9500]/[0.07] border-t border-[#ff9500]/20 text-[10.5px] text-[#e68600]">
          <span>⚠</span>
          <span>日志已停止更新，如怀疑卡住可手动点击步骤重试</span>
        </div>
      )}
    </div>
  );

  return createPortal(popover, document.body);
}

// ── ActiveStep — wraps the active step with hover-to-show log popover ─

function ActiveStep({
  children,
  logs,
  isStale,
  staleSecs,
}: {
  children: React.ReactNode;
  logs: StepLogEntry[];
  isStale: boolean;
  staleSecs: number;
}) {
  const [hovered, setHovered] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  return (
    <div
      ref={ref}
      className="relative flex items-center gap-1 shrink-0"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className="flex items-center gap-1">{children}</div>
      {hovered && (
        <LogPopover
          logs={logs}
          isStale={isStale}
          staleSecs={staleSecs}
          anchorEl={ref.current}
        />
      )}
    </div>
  );
}

// ── Props ─────────────────────────────────────────────────────────────

function logStepForPipelineStep(step: PipelineStep): string {
  switch (step.id) {
    case 'capture':
    case 'media_download':
    case 'video_download':
      return 'capturing';
    case 'normalize':
      return 'normalizing';
    case 'transcribe':
    case 'extract_audio':
    case 'screenshots':
      return step.id === 'transcribe' ? 'transcribing' : 'preprocessing';
    case 'chapters':
    case 'parse':
      return 'parsing';
    case 'compose_html':
    case 'compose_png':
      return 'composing';
    case 'index':
      return 'indexing';
    default:
      return step.retry_from || '';
  }
}

interface PipelineBarProps {
  status: string;
  contentType?: string;
  errorStage?: string | null;
  jobId?: string;
  pipelineSteps?: PipelineStep[] | null;
  onStop?: () => void;
  onRetry?: (fromStep: string) => void;
  className?: string;
}

// ── Component ─────────────────────────────────────────────────────────

export function PipelineBar({
  status,
  contentType = 'article',
  errorStage,
  jobId,
  pipelineSteps,
  onStop,
  onRetry,
  className = '',
}: PipelineBarProps) {
  const useApiSteps = pipelineSteps && pipelineSteps.length > 0;
  const compressed = useApiSteps ? pipelineSteps.length >= 8 : false;

  const legacySteps = getSteps(contentType);
  const legacyStates = resolveSteps(legacySteps, status, errorStage);

  const displaySteps = useApiSteps
    ? pipelineSteps.map((s) => ({
        label: compressed ? s.short_label : s.label,
        retryFrom: s.retry_from || '',
        state: s.state,
        logStep: logStepForPipelineStep(s),
      }))
    : legacySteps.map((s, idx) => ({
        label: s.label,
        retryFrom: s.retryFrom,
        state: legacyStates[idx],
        logStep: s.activeStatuses[0] || s.retryFrom,
      }));

  const isReady     = status === 'ready';
  const isFailed    = status === 'failed';
  const isCancelled = status === 'cancelled';
  const isActive    = !isReady && !isFailed && !isCancelled;

  const activeStepIdx = displaySteps.findIndex((s) => s.state === 'active');
  const activeLogStep = activeStepIdx >= 0 ? displaySteps[activeStepIdx].logStep : '';
  const { logs, isStale, staleSecs } = useStepLogs(
    jobId,
    activeLogStep,
    !!jobId && activeStepIdx >= 0,
  );
  const hasLogs = logs.length > 0;

  return (
    <div
      className={`flex items-center h-9 px-5 rounded-xl bg-[#f5f5f7] ${className}`}
    >
      {/* ── Steps + connectors ───────────────────────────────────────── */}
      <div className="flex items-center flex-1 min-w-0">
        {displaySteps.flatMap((step, idx) => {
          const state = step.state;
          const isLast = idx === displaySteps.length - 1;
          const nextFilled = !isLast && (state === 'done' || state === 'active');
          const isRetryable = !!onRetry && step.retryFrom !== '';
          const showLogPopover = state === 'active' && !!jobId && hasLogs;

          const iconColor =
            state === 'done'    ? 'bg-[var(--success)]/15 text-[var(--success)]' :
            state === 'active'  ? 'bg-[var(--accent)]/15 text-[var(--accent)]'   :
            state === 'failed'  ? 'bg-red-500/10 text-red-500'                    :
                                  'text-[var(--text-tertiary)]';

          const labelColor =
            state === 'done'    ? 'text-[var(--success)]'       :
            state === 'active'  ? 'text-[var(--accent)]'        :
            state === 'failed'  ? 'text-red-500'                :
                                  'text-[var(--text-tertiary)]';

          const inner = (
            <>
              <span className={`relative flex items-center justify-center w-4 h-4 rounded-full shrink-0 ${iconColor}`}>
                <span className={isRetryable && !showLogPopover ? 'group-hover:opacity-0 transition-opacity duration-150' : ''}>
                  {state === 'done'   ? <Check size={10} strokeWidth={3} />            :
                   state === 'active' ? <Loader2 size={10} className="animate-spin" /> :
                   state === 'failed' ? <AlertCircle size={10} />                      :
                   <span className="w-1.5 h-1.5 rounded-full border border-current opacity-40 block" />}
                </span>
                {isRetryable && !showLogPopover && (
                  <span className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-150 text-[#007aff]">
                    <RotateCcw size={9} />
                  </span>
                )}
              </span>

              <span className={`text-[11px] font-medium whitespace-nowrap leading-none transition-colors duration-150 ${labelColor} ${
                isRetryable && !showLogPopover
                  ? 'group-hover:text-[#007aff] group-hover:underline group-hover:decoration-dotted group-hover:underline-offset-2'
                  : ''
              }`}>
                {step.label}
              </span>
            </>
          );

          const connEl = (
            <div key={`c${idx}`} className="flex items-center flex-1 min-w-[20px] mx-2">
              <div className={`flex-1 border-t border-dashed ${nextFilled ? 'border-[var(--success)]/40' : 'border-[#d1d1d6]'}`} />
              <span className={`text-[10px] leading-none -ml-px shrink-0 ${nextFilled ? 'text-[var(--success)]/50' : 'text-[#aeaeb2]'}`}>›</span>
            </div>
          );

          // Active step with logs — use portal-based ActiveStep
          if (showLogPopover) {
            const stepEl = (
              <ActiveStep key={step.label} logs={logs} isStale={isStale} staleSecs={staleSecs}>
                {inner}
              </ActiveStep>
            );
            return isLast ? [stepEl] : [stepEl, connEl];
          }

          const stepEl = isRetryable ? (
            <button
              key={step.label}
              type="button"
              onClick={() => onRetry!(step.retryFrom)}
              title={`从「${step.label}」重新处理`}
              className="group flex items-center gap-1 shrink-0 rounded-md px-1.5 py-0.5 -mx-1.5 -my-0.5 hover:bg-[#007aff]/[0.09] transition-colors duration-150 cursor-pointer"
            >
              {inner}
            </button>
          ) : (
            <div key={step.label} className="flex items-center gap-1 shrink-0">
              {inner}
            </div>
          );

          return isLast ? [stepEl] : [stepEl, connEl];
        })}
      </div>

      {/* ── 停止按钮（处理中时显示）── */}
      {isActive && onStop && (
        <div className="ml-4 shrink-0">
          <button
            onClick={onStop}
            title="停止处理"
            className="flex items-center gap-1 px-2 h-6 rounded-md text-[11px] font-medium text-[#86868b] hover:text-red-500 hover:bg-red-50 transition-colors"
          >
            <XCircle size={10} />
            停止
          </button>
        </div>
      )}
    </div>
  );
}
