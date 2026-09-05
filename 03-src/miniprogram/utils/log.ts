/**
 * 实时日志（真机排查用）：写入微信官方「实时日志」，
 * mp.weixin.qq.com → 开发 → 运维中心 → 实时日志 可查最后一条——
 * 真机闪退/白屏时，看停在哪一步就能定位现场。DevTools 下退化为 console。
 */

const rt: WechatMiniprogram.RealtimeLogManager | null = (() => {
  try {
    return wx.getRealtimeLogManager ? wx.getRealtimeLogManager() : null;
  } catch {
    return null;
  }
})();

export function logInfo(tag: string, msg: string, extra?: Record<string, unknown>): void {
  console.log(`[${tag}] ${msg}`, extra || '');
  try {
    if (rt) rt.info(tag, msg, extra || '');
  } catch {
    /* ignore */
  }
}

export function logError(tag: string, msg: string, extra?: Record<string, unknown>): void {
  console.error(`[${tag}] ${msg}`, extra || '');
  try {
    if (rt) rt.error(tag, msg, extra || '');
  } catch {
    /* ignore */
  }
}
