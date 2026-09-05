import { PLATFORM_LABELS, PLATFORM_GRADIENTS } from '../../config/index';
import { formatDate } from '../../utils/format';

/**
 * 瀑布流卡片（翻译 Web components/ArticleCard.tsx）：
 * 封面自然比例 + 渐变占位兜底 / 平台+日期行 / 标题 / 摘要或处理状态 / 标签 / 作者+时长。
 * cover_image 由页面在 setData 前经 resolveImage 改写好。
 */
Component({
  properties: {
    article: {
      type: Object,
      value: {} as Article,
    },
  },

  data: {
    platformLabel: '',
    gradient: '',
    initial: '',
    publishedDate: '',
    isAudio: false,
    coverFailed: false,
  },

  observers: {
    article(a: Article) {
      const platformKey = (a && a.source_platform) || 'generic';
      const label = PLATFORM_LABELS[platformKey] || platformKey;
      this.setData({
        platformLabel: label,
        gradient: PLATFORM_GRADIENTS[platformKey] || PLATFORM_GRADIENTS.generic,
        initial: label.charAt(0).toUpperCase(),
        publishedDate: formatDate(a && a.published_at),
        isAudio: !!(a && a.content_type === 'audio'),
        coverFailed: false,
      });
    },
  },

  methods: {
    /** 封面加载失败（防盗链/图源失效）→ 渐变占位，列表不掉高度 */
    onCoverError() {
      this.setData({ coverFailed: true });
    },
    onTap() {
      const a = this.data.article as Article;
      if (a && a.id) this.triggerEvent('cardtap', { id: a.id });
    },
  },
});
