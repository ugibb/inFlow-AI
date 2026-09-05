/**
 * 音频播放器（播客收听）：wx.getBackgroundAudioManager 单例封装。
 * 模块级状态全局一份——离开阅读页/切后台/锁屏不打断，重新进入页面
 * bind() 即可恢复 UI；换一篇文章播放则自动切源。
 * 注意：playing 自维护（onPlay/onPause/onStop/onEnded 置位），
 * 不读 bgm.paused——部分基础库首次播放前该值不可靠。
 */

export interface PlayerState {
  src: string;
  playing: boolean;
  /** 秒 */
  current: number;
  /** 秒 */
  duration: number;
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

function emit(): void {
  if (!listener) return;
  listener({
    src: currentSrc,
    playing,
    current: bgm ? Math.max(0, bgm.currentTime || 0) : 0,
    duration: bgm ? Math.max(0, bgm.duration || 0) : 0,
  });
}

function ensure(): WechatMiniprogram.BackgroundAudioManager {
  if (bgm) return bgm;
  bgm = wx.getBackgroundAudioManager();
  bgm.onPlay(() => {
    playing = true;
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
    currentSrc = '';
    emit();
    wx.showToast({ title: '播放失败，节目源可能失效', icon: 'none' });
  });
  bgm.onCanplay(() => {
    if (pendingSeek > 0 && bgm) {
      bgm.seek(pendingSeek);
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
  };
}

/** 从头（或指定秒）起播一个源：title 必须先于 src 设置（iOS 要求） */
function start(meta: PlayMeta, startSec: number): void {
  const m = ensure();
  currentSrc = meta.src;
  pendingSeek = startSec > 0 ? startSec : 0;
  m.title = (meta.title || '未命名节目').slice(0, 100);
  if (meta.cover) m.coverImgUrl = meta.cover;
  m.src = meta.src; // 设置 src 即自动播放
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
    m.seek(resumeSec);
  }
  m.play();
}

/** 跳到指定秒并确保在播（章节/转录句点击） */
export function seekPlay(meta: PlayMeta, sec: number): void {
  if (currentSrc !== meta.src) {
    start(meta, sec);
    return;
  }
  const m = ensure();
  m.seek(Math.max(0, sec));
  if (!playing) m.play();
}

/** 拖动进度条开始：挂起 timeupdate 回写 */
export function scrubStart(): void {
  scrubbing = true;
}

/** 拖动结束：落位到目标秒（同源已加载才真正 seek，否则等起播时用） */
export function scrubEnd(sec: number): void {
  scrubbing = false;
  if (bgm && currentSrc) bgm.seek(Math.max(0, sec));
}
