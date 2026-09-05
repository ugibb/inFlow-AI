import { formatPlayerTime } from '../../utils/format';
import { logInfo } from '../../utils/log';

/**
 * 全文转录（提词器 + 虚拟列表，翻译 Web read 页交互）：
 *  - 当前句高亮（蓝底/蓝字/左蓝条），已播句变淡 0.3，未播 0.8
 *  - 播放中自动跟随：当前句平滑滚动钉在窗口 18% 处
 *  - 手动滚动 → 暂停跟随 + 「返回播放位置」胶囊，5s 无操作自动恢复
 *  - 点击句子 → 通知页面 seek 播放（并恢复跟随）
 *  虚拟列表只渲染焦点 ±窗口内的句子；位置 = 初始按字数估行高，
 *  每次换窗口后用 SelectorQuery 实测覆盖（估高累计几百句必然漂移，
 *  定位/补页一律以实测为准，未测区域才用估算外推）。
 *  active-index 由页面按播放时间二分算出。
 */

/** 版面估算（rpx，750 设计稿）——仅作初始猜测与未测区域外推 */
const FONT_RPX = 26;
const LINE_H_RPX = 46;
const PAD_RPX = 24;
/** 文本列宽 = 750 - 页边48 - 面板48 - 内层16 - 句内40 - 时间列84 - 间隙16 */
const TEXT_COL_RPX = 498;
const CHARS_PER_LINE = Math.floor(TEXT_COL_RPX / FONT_RPX);
/** 渲染窗口：焦点前 40 句起共 160 句（约数屏，正常滚动追不空） */
const WIN_BEFORE = 40;
const WIN_SIZE = 160;
/** 跟随钉位：当前句距窗口顶部 18% */
const PIN_RATIO = 0.18;

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

  /** 全量句（不进 data）；tops 混合实测/估算；estH 每句估算高（外推用） */
  all: [] as Seg[],
  tops: [] as number[],
  estH: [] as number[],
  totalH: 0,
  viewH: 0,
  winStart: 0,
  winEnd: 0,
  follow: true,
  programmaticUntil: 0,
  resumeTimer: 0,
  /** 换窗后待精确落位的句（测量完成后消费） */
  wantPin: -1,
  measuring: false,
  scale: 0.5,

  lifetimes: {
    attached() {
      this.follow = true;
      this.programmaticUntil = 0;
      this.resumeTimer = 0;
      this.wantPin = -1;
      this.measuring = false;
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
      const estH = (list || []).map((s) => {
        const len = (s.text || '').length;
        const lines = Math.max(1, Math.ceil(len / CHARS_PER_LINE));
        return (lines * LINE_H_RPX + PAD_RPX) * scale;
      });
      this.estH = estH;
      this.all = (list || []).map((s, i) => ({
        ai: i,
        time: formatPlayerTime(s.start),
        text: s.text || '',
        start: s.start || 0,
      }));
      const tops: number[] = [0];
      let acc = 0;
      for (const h of estH) {
        acc += h;
        tops.push(acc);
      }
      this.tops = tops;
      this.totalH = acc;
      this.winStart = 0;
      this.winEnd = 0;
      logInfo('tl', 'transcript built', { n: this.all.length, estPx: Math.round(acc) });
      this.recentre(this.data.activeIdx >= 0 ? this.data.activeIdx : 0, true);
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

    /**
     * 渲染窗口对齐到 idx。pin=true：跟随模式，测完后精确钉位并校正占位；
     * pin=false：用户滚动补页，只换窗口不动滚动位置（不打扰手势）。
     */
    recentre(idx: number, pin: boolean) {
      const n = this.all.length;
      if (!n) return;
      const start = Math.max(0, Math.min(idx - WIN_BEFORE, n - 1));
      const end = Math.min(n, start + WIN_SIZE);
      const same = start === this.winStart && end === this.winEnd;
      this.winStart = start;
      this.winEnd = end;
      if (!same) {
        this.setData({
          view: this.all.slice(start, end),
          padTop: Math.round(this.tops[start] || 0),
          padBottom: Math.round(Math.max(0, this.totalH - (this.tops[end] || this.totalH))),
        });
      }
      this.wantPin = pin ? idx : -1;
      wx.nextTick(() => this.measure());
    },

    /** 实测当前窗口内各句真实位置，覆盖 tops；跟随模式下随后精确落位 */
    measure() {
      if (this.measuring) return;
      const n = this.all.length;
      if (!n) return;
      this.measuring = true;
      // 查询发起时的窗口（回调到达前可能已换窗，映射按当时快照）
      const qStart = this.winStart;
      const qEnd = this.winEnd;
      const q = this.createSelectorQuery();
      q.select('.tl-scroll').boundingClientRect();
      q.select('.tl-scroll').scrollOffset();
      q.selectAll('.seg-item').boundingClientRect();
      q.exec((res) => {
        this.measuring = false;
        const svRect = res[0] as { top: number; height: number } | null;
        const sc = res[1] as { scrollTop: number } | null;
        const items = res[2] as { top: number }[] | null;
        if (!svRect || !items || !items.length) return;
        if (svRect.height) this.viewH = svRect.height;
        // 内容顶部在页面坐标系中的 y（scroll-view 顶 - 已滚距离）
        const base = (svRect.top || 0) - ((sc && sc.scrollTop) || 0);
        for (let k = 0; k < items.length; k++) {
          const gi = qStart + k;
          if (gi < qEnd) this.tops[gi] = items[k].top - base;
        }
        // 窗口末端与总高按实测末端外推，供未测区域定位
        const lastGi = qStart + items.length - 1;
        if (lastGi >= 0 && lastGi < n && this.estH[lastGi] != null) {
          const endTop = this.tops[lastGi] + this.estH[lastGi];
          if (qEnd < this.tops.length) this.tops[qEnd] = endTop;
          this.totalH = Math.max(this.totalH, endTop);
        }
        // 跟随：校正占位 + 按实测位置钉位（窗口已变则丢弃，新窗口会自带一次测量）
        if (this.winStart !== qStart || this.winEnd !== qEnd) return;
        if (this.wantPin >= 0 && this.wantPin >= this.winStart && this.wantPin < this.winEnd) {
          const p = this.wantPin;
          this.wantPin = -1;
          this.setData({
            padTop: Math.round(this.tops[this.winStart]),
            padBottom: Math.round(Math.max(0, this.totalH - this.tops[this.winEnd])),
          });
          this.pinTo(p, true);
        }
      });
    },

    onActive(nv: number) {
      const changed = nv !== this.data.activeIdx;
      this.setData({ activeIdx: nv });
      if (nv < 0) return;
      // 暂停跟随期间（用户自己在看别处）绝不重排窗口——内容不能在手指下跳动
      if (!this.follow) return;
      if (nv < this.winStart + 15 || nv >= this.winEnd - 15) {
        this.recentre(nv, true);
        return;
      }
      if (changed) this.pinTo(nv, true);
    },

    /** 把第 idx 句钉到窗口 18% 处 */
    pinTo(idx: number, smooth: boolean) {
      const target = Math.max(0, (this.tops[idx] || 0) - this.viewH * PIN_RATIO);
      this.programmaticUntil = Date.now() + 1200;
      this.setData({ scrollTop: target, scrollAnim: smooth });
    },

    onScroll(e: any) {
      // 可视中心补页（程序滚动/用户滚动都需要；只换窗口不打扰滚动位置）
      const st = (e && e.detail && e.detail.scrollTop) || 0;
      const focus = this.idxAt(st + this.viewH * 0.4);
      if (focus < this.winStart + 10 || focus >= this.winEnd - 10) {
        this.recentre(focus, false);
      }

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
      if (this.data.activeIdx >= 0) this.recentre(this.data.activeIdx, true);
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
