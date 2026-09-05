import { formatPlayerTime } from '../../utils/format';

interface ChapterView {
  indexLabel: string;
  title: string;
  range: string;
  summary: string;
  /** 起播秒数（点击章节跳转播放用） */
  start: number;
}

/** 章节速览列表：序号 / 标题 / 时间区间 / 摘要，点击跳转播放（数据来自 GET /articles/{id}/chapters） */
Component({
  properties: {
    chapters: {
      type: Array,
      value: [] as ArticleChapter[],
    },
  },

  data: {
    view: [] as ChapterView[],
  },

  observers: {
    chapters(list: ArticleChapter[]) {
      const view = (list || []).map((c) => ({
        indexLabel: String(c.index != null ? c.index : 0).padStart(2, '0'),
        title: c.title || '',
        range: formatPlayerTime(c.start_time) + ' - ' + formatPlayerTime(c.end_time),
        summary: c.summary || '',
        start: c.start_time || 0,
      }));
      this.setData({ view });
    },
  },

  methods: {
    onTap(e: any) {
      const idx = Number(e.currentTarget.dataset.idx) || 0;
      const item = this.data.view[idx];
      if (item) this.triggerEvent('chaptertap', { startTime: item.start });
    },
  },
});
