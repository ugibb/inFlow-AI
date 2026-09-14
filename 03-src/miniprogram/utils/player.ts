/**
 * 音频播放器（播客收听）：wx.getBackgroundAudioManager 单例封装。
 * 模块级状态全局一份——离开阅读页/切后台/锁屏不打断，重新进入页面
 * bind() 即可恢复 UI；换一篇文章播放则自动切源。
 * 注意：playing 自维护（onPlay/onPause/onStop/onEnded 置位），
 * 不读 bgm.paused——部分基础库首次播放前该值不可靠。
 * iOS 真机：src 设置后到 onCanplay 之前 seek 会异常/闪退——
 * 全部 seek 经 ready 门卫，未就绪的排队 pendingSeek 到 onCanplay 再执行。
 */

import { logInfo, logError } from './log';

export interface PlayerState {
  src: string;
  playing: boolean;
  /** 秒 */
  current: number;
  /** 秒 */
  duration: number;
  /** 播放倍速 0.5–2（bgm 起播默认 1） */
  rate: number;
}

export interface PlayMeta {
  src: string;
  title: string;
  cover?: string;
}

type Listener = (s: PlayerState) => void;

let bgm: WechatMiniprogram.BackgroundAudioManager | null = null;
let listener: Listener | null = null;
let currentSrc = '';
let playing = false;
/** 拖动进度条期间为 true：暂停回写 current，避免滑块拉锯 */
let scrubbing = false;
/** 换源后等 onCanplay 再执行的 seek 位置 */
let pendingSeek = 0;
/** onCanplay 置位、换源清零：iOS 未就绪时 seek 会出问题 */
let ready = false;
/** 播放倍速：随 bgm 应用；切源/部分平台会把系统倍速重置回 1，onCanplay/onPlay 兜底重落 */
const RATE_KEY = 'inflow_player_rate';
export const RATE_OPTIONS = [0.75, 1, 1.25, 1.5, 2];
let rate = loadRate();

function loadRate(): number {
  try {
    const v = wx.getStorageSync(RATE_KEY) as unknown;
    return typeof v === 'number' && v >= 0.5 && v <= 2 ? v : 1;
  } catch {
    return 1;
  }
}

/** 安全 seek：未就绪就排队 */
function safeSeek(sec: number): void {
  if (!bgm) {
    pendingSeek = sec;
    return;
  }
  if (!ready) {
    pendingSeek = sec;
    return;
  }
  try {
    bgm.seek(Math.max(0, sec));
  } catch {
    pendingSeek = sec;
  }
}

function safePlay(): void {
  if (!bgm) return;
  try {
    bgm.play();
  } catch {
    /* 个别平台 play 抛异常，忽略：onError 会兜底 */
  }
}

/** 把当前倍速应用到 bgm。类型包个别版本未收录该字段，用结构化兜底；不支持倍速的平台静默忽略 */
function applyRate(): void {
  if (!bgm || !currentSrc) return;
  try {
    (bgm as unknown as { playbackRate?: number }).playbackRate = rate;
  } catch {
    /* ignore */
  }
}

function emit(): void {
  if (!listener) return;
  listener({
    src: currentSrc,
    playing,
    current: bgm ? Math.max(0, bgm.currentTime || 0) : 0,
    duration: bgm ? Math.max(0, bgm.duration || 0) : 0,
    rate,
  });
}

function ensure(): WechatMiniprogram.BackgroundAudioManager {
  if (bgm) return bgm;
  bgm = wx.getBackgroundAudioManager();
  bgm.onPlay(() => {
    playing = true;
    applyRate(); // Android 暂停态改速不生效，onPlay 处于在播状态再落一次
    emit();
  });
  const stop = () => {
    playing = false;
    emit();
  };
  bgm.onPause(stop);
  bgm.onStop(stop);
  bgm.onEnded(() => {
    playing = false;
    emit();
  });
  bgm.onError(() => {
    // 源失效/格式不支持：清掉占住的 src，让下次点击走重新起播
    playing = false;
    ready = false;
    currentSrc = '';
    emit();
    logError('player', 'bgm onError');
    wx.showToast({ title: '播放失败，节目源可能失效', icon: 'none' });
  });
  bgm.onCanplay(() => {
    ready = true;
    applyRate(); // 切源后系统可能把倍速重置回 1，就绪点重落
    if (pendingSeek > 0 && bgm) {
      try {
        bgm.seek(pendingSeek);
      } catch {
        /* ignore */
      }
      pendingSeek = 0;
    }
  });
  bgm.onTimeUpdate(() => {
    if (!scrubbing) emit();
  });
  return bgm;
}

/** 订阅状态（页面 onShow/加载完绑定，onUnload 传 null 解绑）；绑定即刻回放当前快照 */
export function bind(l: Listener | null): void {
  listener = l;
  if (l && bgm) emit();
}

export function getState(): PlayerState {
  return {
    src: currentSrc,
    playing,
    current: bgm ? Math.max(0, bgm.currentTime || 0) : 0,
    duration: bgm ? Math.max(0, bgm.duration || 0) : 0,
    rate,
  };
}

/** 从头（或指定秒）起播一个源：title 必须先于 src 设置（iOS 要求） */
function start(meta: PlayMeta, startSec: number): void {
  const m = ensure();
  currentSrc = meta.src;
  ready = false;
  pendingSeek = startSec > 0 ? startSec : 0;
  m.title = (meta.title || '未命名节目').slice(0, 100);
  if (meta.cover) m.coverImgUrl = meta.cover;
  logInfo('player', 'start', { startSec, host: meta.src.slice(0, 40) });
  m.src = meta.src; // 设置 src 即自动播放
  applyRate();
  playing = true;
  emit();
}

/**
 * 播放/暂停切换（底部播放条按钮）。
 * resumeSec：当前 UI 上的进度——同源暂停期间若拖动过进度条，先 seek 再续播。
 */
export function toggle(meta: PlayMeta, resumeSec?: number): void {
  if (currentSrc !== meta.src) {
    start(meta, resumeSec && resumeSec > 0 ? resumeSec : 0);
    return;
  }
  const m = ensure();
  if (playing) {
    m.pause();
    return;
  }
  if (resumeSec != null && Math.abs((m.currentTime || 0) - resumeSec) > 1) {
    safeSeek(resumeSec);
  }
  safePlay();
}

/** 跳到指定秒并确保在播（章节/转录句点击） */
export function seekPlay(meta: PlayMeta, sec: number): void {
  if (currentSrc !== meta.src) {
    start(meta, sec);
    return;
  }
  safeSeek(sec);
  if (!playing) safePlay();
}

/** 跳到绝对秒但保留当前播放/暂停态（±5s / 进度条落位共用；未起播则忽略，由页面镜像兜位） */
export function seekTo(sec: number): void {
  if (!bgm || !currentSrc) return;
  safeSeek(Math.max(0, sec));
}

/** 当前记忆的倍速（含尚未起播、未应用 bgm 时） */
export function getRate(): number {
  return rate;
}

/** 设定播放倍速：写缓存、落 bgm 并广播刷 UI；0.5–2，越界收敛 */
export function setRate(r: number): void {
  const v = Math.min(2, Math.max(0.5, r));
  if (v === rate) return;
  rate = v;
  try {
    wx.setStorageSync(RATE_KEY, v);
  } catch {
    /* 存储失败不影响本次播放 */
  }
  applyRate();
  emit();
}

/** 拖动进度条开始：挂起 timeupdate 回写 */
export function scrubStart(): void {
  scrubbing = true;
}

/** 拖动结束：落位到目标秒（未就绪则排队 pendingSeek） */
export function scrubEnd(sec: number): void {
  scrubbing = false;
  if (bgm && currentSrc) safeSeek(sec);
}
