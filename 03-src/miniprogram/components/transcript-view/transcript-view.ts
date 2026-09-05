import { formatPlayerTime } from '../../utils/format';

/** 全文转录（提词器模式，翻译 Web read 页交互）：
 *  - 当前句高亮（蓝底/蓝字/左蓝条），已播句变淡 0.3，未播 0.8
 *  - 播放中自动跟随：当前句平滑滚动钉在窗口 18% 处
 *  - 手动滚动 → 暂停跟随 + 「返回播放位置」胶囊，5s 无操作自动恢复
 *  - 点击句子 → 通知页面 seek 播放（并恢复跟随）
 *  数据来自 GET /articles/{id}/transcript；active-index 由页面按播放时间二分算出。
 */
Component({
  properties: {
    segments: {
      type: Array,
      value: [] as TranscriptSegment[],
    },
    /** 当前播放所在句下标；-1 = 无（暂停/未播/越界） */
    activeIndex: {
      type: Number,
      value: -1,
      observer(nv: number) {
        const changed = nv !== this.data.activeIdx;
        this.setData({ activeIdx: nv });
        if (nv >= 0 && changed && this.follow) this.scrollToIdx(nv, true);
      },
    },
  },

  data: {
    view: [] as SegmentView[],
    activeIdx: -1,
    /** scroll-view 受控滚动位置 */
    scrollTop: 0,
    scrollAnim: true,
    showPill: false,
  },

  /** 各句在滚动内容内的绝对 top（渲染后测量）；窗口高度 */
  offsets: null as number[] | null,
  viewH: 0,
  /** 自动跟随开关；programmaticUntil 区分程序滚动与用户滚动 */
  follow: true,
  programmaticUntil: 0,
  resumeTimer: 0,

  lifetimes: {
    attached() {
      this.follow = true;
      this.programmaticUntil = 0;
      this.resumeTimer = 0;
      this.offsets = null;
      this.viewH = 0;
    },
    detached() {
      if (this.resumeTimer) clearTimeout(this.resumeTimer);
    },
    ready() {
      this.measure();
    },
  },

  observers: {
    segments(list: TranscriptSegment[]) {
      const view = (list || []).map((s, i) => ({
        idx: i,
        time: formatPlayerTime(s.start),
        text: s.text || '',
        start: s.start || 0,
      }));
      this.setData({ view });
      this.offsets = null;
      wx.nextTick(() => this.measure());
    },
  },

  methods: {
    /** 渲染后测量：scroll-view 视口高度 + 各句绝对位置（一次性批量查询） */
    measure() {
      const q = this.createSelectorQuery();
      q.select('.tl-scroll').boundingClientRect();
      q.selectAll('.seg-item').boundingClientRect();
      q.select('.tl-scroll').scrollOffset();
      q.exec((res) => {
        const svRect = res[0] as { top: number; height: number } | null;
        const items = res[1] as { top: number }[] | null;
        const sc = res[2] as { scrollTop: number } | null;
        if (!svRect || !items || !items.length) return;
        this.viewH = svRect.height;
        const base = (sc && sc.scrollTop) || 0;
        this.offsets = items.map((r) => r.top - svRect.top + base);
        // 首次测量时若已在播放：直接落位（无动画），不等下一句切换
        if (this.follow && this.data.activeIdx >= 0) {
          this.scrollToIdx(this.data.activeIdx, false);
        }
      });
    },

    /** 把第 idx 句钉到窗口 18% 处 */
    scrollToIdx(idx: number, smooth: boolean) {
      if (!this.offsets || !this.viewH) return;
      const target = Math.max(0, (this.offsets[idx] || 0) - this.viewH * 0.18);
      this.programmaticUntil = Date.now() + 700;
      this.setData({ scrollTop: target, scrollAnim: smooth });
    },

    onScroll() {
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
      if (this.data.activeIdx >= 0) this.scrollToIdx(this.data.activeIdx, true);
    },

    onResumeFollow() {
      this.resumeFollow();
    },

    onTap(e: any) {
      const idx = Number(e.currentTarget.dataset.idx) || 0;
      const item = this.data.view[idx];
      // 点击即恢复跟随（下一拍 timeupdate 高亮滚动到位），对齐 Web 行为
      this.follow = true;
      if (this.data.showPill) this.setData({ showPill: false });
      if (item) this.triggerEvent('segmenttap', { start: item.start });
    },
  },
});

interface SegmentView {
  idx: number;
  time: string;
  text: string;
  /** 起播秒数（点击跳转播放用） */
  start: number;
}
