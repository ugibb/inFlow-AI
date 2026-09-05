import { formatPlayerTime } from '../../utils/format';
import { logInfo } from '../../utils/log';

/**
 * 全文转录（提词器 + 虚拟列表，翻译 Web read 页交互）：
 *  - 当前句高亮（蓝底/蓝字/左蓝条），已播句变淡 0.3，未播 0.8
 *  - 播放中自动跟随：当前句平滑滚动钉在窗口 18% 处
 *  - 手动滚动 → 暂停跟随 + 「返回播放位置」胶囊，5s 无操作自动恢复
 *  - 点击句子 → 通知页面 seek 播放（并恢复跟随）
 *  长转录（上千句）真机一次性渲染会内存溢出闪退——这里只渲染焦点
 *  ±窗口内的 ~100 句，上下用等高 spacer 占位，位置按字数估算行高累计。
 *  active-index 由页面按播放时间二分算出。
 */

/** 版面估算（rpx，750 设计稿）：文本列有效宽 / 字号 / 行高 / 每句上下留白 */
const FONT_RPX = 26;
const LINE_H_RPX = 46;
const PAD_RPX = 24;
/** 文本列宽 = 750 - 页边距48 - 面板内边距48 - 内层16 - 句内边距40 - 时间列84 - 间隙16 */
const TEXT_COL_RPX = 498;
const CHARS_PER_LINE = Math.floor(TEXT_COL_RPX / FONT_RPX);
/** 渲染窗口：焦点前 25 句到后 75 句 */
const WIN_BEFORE = 25;
const WIN_SIZE = 100;

interface Seg {
  /** 全量下标（虚拟列表里 wx:key 与点击回查都用它） */
  ai: number;
  time: string;
  text: string;
  start: number;
}

Component({
  properties: {
    segments: {
      type: Array,
      value: [] as TranscriptSegment[],
    },
    /** 当前播放所在句下标；-1 = 无（暂停/未播/间隙） */
    activeIndex: {
      type: Number,
      value: -1,
      observer(nv: number) {
        this.onActive(nv);
      },
    },
  },

  data: {
    view: [] as Seg[],
    /** 上下占位高度（px），与全量位置累计对齐 */
    padTop: 0,
    padBottom: 0,
    activeIdx: -1,
    scrollTop: 0,
    scrollAnim: true,
    showPill: false,
  },

  /** 全量句（不进 data）；tops[i] = 第 i 句在内容里的顶部偏移 px */
  all: [] as Seg[],
  tops: [] as number[],
  totalH: 0,
  scale: 0.5,
  heights: [] as number[],
  viewH: 0,
  winStart: 0,
  winEnd: 0,
  follow: true,
  programmaticUntil: 0,
  resumeTimer: 0,

  lifetimes: {
    attached() {
      this.follow = true;
      this.programmaticUntil = 0;
      this.resumeTimer = 0;
      this.winStart = 0;
      this.winEnd = 0;
      try {
        this.scale = wx.getWindowInfo().windowWidth / 750;
      } catch {
        this.scale = 0.5;
      }
      // 65vh 兜底，ready 后实测覆盖
      this.viewH = 750 * 0.65 * this.scale;
    },
    detached() {
      if (this.resumeTimer) clearTimeout(this.resumeTimer);
    },
    ready() {
      this.createSelectorQuery()
        .select('.tl-scroll')
        .boundingClientRect((r) => {
          if (r && r.height) this.viewH = r.height;
        })
        .exec();
    },
  },

  observers: {
    segments(list: TranscriptSegment[]) {
      const scale = this.scale;
      const heights = (list || []).map((s) => {
        const len = (s.text || '').length;
        const lines = Math.max(1, Math.ceil(len / CHARS_PER_LINE));
        return (lines * LINE_H_RPX + PAD_RPX) * scale;
      });
      this.heights = heights;
      this.all = (list || []).map((s, i) => ({
        ai: i,
        time: formatPlayerTime(s.start),
        text: s.text || '',
        start: s.start || 0,
      }));
      const tops: number[] = [0];
      let acc = 0;
      for (const h of heights) {
        acc += h;
        tops.push(acc);
      }
      this.tops = tops;
      this.totalH = acc;
      this.winStart = 0;
      this.winEnd = 0;
      logInfo('tl', 'transcript built', { n: this.all.length, estPx: Math.round(acc) });
      this.recentre(this.data.activeIdx >= 0 ? this.data.activeIdx : 0);
    },
  },

  methods: {
    /** px 偏移 → 句下标（最后一个 tops[i] <= px） */
    idxAt(px: number): number {
      const tops = this.tops;
      let lo = 0;
      let hi = tops.length - 1;
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (tops[mid] <= px) lo = mid;
        else hi = mid - 1;
      }
      return Math.min(lo, Math.max(0, this.all.length - 1));
    },

    /** 渲染窗口对齐到 idx（padTop/padBottom 按同一份 tops 计算，切换不打扰滚动位置） */
    recentre(idx: number) {
      const n = this.all.length;
      if (!n) return;
      const start = Math.max(0, Math.min(idx - WIN_BEFORE, n - 1));
      const end = Math.min(n, start + WIN_SIZE);
      if (start === this.winStart && end === this.winEnd) return;
      this.winStart = start;
      this.winEnd = end;
      this.setData({
        view: this.all.slice(start, end),
        padTop: Math.round(this.tops[start]),
        padBottom: Math.round(this.totalH - this.tops[end]),
      });
    },

    onActive(nv: number) {
      const changed = nv !== this.data.activeIdx;
      this.setData({ activeIdx: nv });
      if (nv < 0) return;
      // 激活句必须落在渲染窗口内（即便暂停了自动跟随）
      if (nv < this.winStart + 10 || nv >= this.winEnd - 10) this.recentre(nv);
      if (changed && this.follow) this.pinTo(nv, true);
    },

    /** 把第 idx 句钉到窗口 18% 处 */
    pinTo(idx: number, smooth: boolean) {
      const target = Math.max(0, this.tops[idx] - this.viewH * 0.18);
      this.programmaticUntil = Date.now() + 1200;
      this.setData({ scrollTop: target, scrollAnim: smooth });
    },

    onScroll(e: any) {
      // 可视窗口补页（程序滚动/用户滚动都需要）
      const st = (e && e.detail && e.detail.scrollTop) || 0;
      const focus = this.idxAt(st + this.viewH * 0.4);
      if (focus < this.winStart + 10 || focus >= this.winEnd - 10) this.recentre(focus);

      if (Date.now() < this.programmaticUntil) return;
      // 用户手动滚动：暂停跟随 + 出胶囊，5s 无操作自动恢复
      this.follow = false;
      if (!this.data.showPill) this.setData({ showPill: true });
      if (this.resumeTimer) clearTimeout(this.resumeTimer);
      this.resumeTimer = setTimeout(() => this.resumeFollow(), 5000);
    },

    resumeFollow() {
      if (this.resumeTimer) {
        clearTimeout(this.resumeTimer);
        this.resumeTimer = 0;
      }
      this.follow = true;
      if (this.data.showPill) this.setData({ showPill: false });
      if (this.data.activeIdx >= 0) this.pinTo(this.data.activeIdx, true);
    },

    onResumeFollow() {
      this.resumeFollow();
    },

    onTap(e: any) {
      const ai = Number(e.currentTarget.dataset.ai) || 0;
      const item = this.all[ai];
      // 点击即恢复跟随（下一拍 timeupdate 高亮滚动到位），对齐 Web 行为
      this.follow = true;
      if (this.data.showPill) this.setData({ showPill: false });
      if (item) this.triggerEvent('segmenttap', { start: item.start });
    },
  },
});
