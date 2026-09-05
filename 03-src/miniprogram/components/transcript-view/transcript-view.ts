import { formatPlayerTime } from '../../utils/format';

interface SegmentView {
  idx: number;
  time: string;
  text: string;
  /** 起播秒数（点击跳转播放用） */
  start: number;
}

/** 全文转录：逐段「时间 + 文本」，点击跳转播放（数据来自 GET /articles/{id}/transcript） */
Component({
  properties: {
    segments: {
      type: Array,
      value: [] as TranscriptSegment[],
    },
  },

  data: {
    view: [] as SegmentView[],
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
    },
  },

  methods: {
    onTap(e: any) {
      const idx = Number(e.currentTarget.dataset.idx) || 0;
      const item = this.data.view[idx];
      if (item) this.triggerEvent('segmenttap', { start: item.start });
    },
  },
});
