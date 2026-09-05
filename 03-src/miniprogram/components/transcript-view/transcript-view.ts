import { formatPlayerTime } from '../../utils/format';

interface SegmentView {
  idx: number;
  time: string;
  text: string;
}

/** 全文转录：逐段「时间 + 文本」（数据来自 GET /articles/{id}/transcript） */
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
      }));
      this.setData({ view });
    },
  },

  methods: {},
});
