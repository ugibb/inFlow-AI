import { api } from '../../utils/api';
import { resolveImage } from '../../utils/image-url';
import { formatDate, formatDuration, formatReadingTime } from '../../utils/format';
import { PLATFORM_LABELS } from '../../config/index';

interface TabItem {
  key: 'raw' | 'chapters' | 'transcript' | 'ai';
  label: string;
}

/**
 * 阅读页：detail 一次拉全（含 content_blocks 存在性快照），tab 显示由快照驱动；
 * 章节/转录切到时才懒加载并缓存本页内存。可被分享卡片直达（无 token 走登录闭环）。
 */
Page({
  data: {
    id: '',
    loading: true,
    error: '',
    article: null as ArticleDetail | null,
    cover: '',
    platformLabel: '',
    publishedDate: '',
    readingTimeText: '',

    tabs: [] as TabItem[],
    activeTab: '' as string,

    chapters: null as ArticleChaptersResponse | null,
    chaptersLoading: false,
    chaptersError: '',
    totalDurationText: '',

    transcript: null as JobTranscript | null,
    transcriptLoading: false,
    transcriptError: '',
  },

  onLoad(options: Record<string, string | undefined>) {
    const id = (options && options.id) || '';
    this.setData({ id });
    if (!id) {
      this.setData({ loading: false, error: '缺少文章参数' });
      return;
    }
    const app = getApp<IAppOption>();
    if (!app.globalData.authReady) return;
    app.globalData.authReady.then((token) => {
      if (!token) {
        wx.reLaunch({
          url:
            '/pages/login/login?redirect=' +
            encodeURIComponent('/pages/read/read?id=' + id),
        });
        return;
      }
      this.loadDetail();
    });
  },

  async loadDetail() {
    this.setData({ loading: true, error: '' });
    try {
      const a = await api.getArticle(this.data.id);
      const blocks = a.content_blocks || {};
      const isAudio = a.content_type === 'audio';

      // tab 可见性 = 后端 content_blocks 快照（缺快照的老数据按内容类型兜底）
      const chaptersApplicable = blocks.chapters ? blocks.chapters.applicable : isAudio || a.content_type === 'article';
      const transcriptApplicable = blocks.transcript ? blocks.transcript.applicable : isAudio;

      const tabs: TabItem[] = [{ key: 'raw', label: isAudio ? '节目信息' : '原文' }];
      if (chaptersApplicable) tabs.push({ key: 'chapters', label: '章节速览' });
      if (transcriptApplicable) tabs.push({ key: 'transcript', label: '全文转录' });
      tabs.push({ key: 'ai', label: 'AI 摘要' });
      // MVP 隐藏 deepRead（HTML 精读小程序无法承载，二期卡片化）

      this.setData({
        article: a,
        cover: resolveImage(a.cover_image),
        platformLabel: PLATFORM_LABELS[a.source_platform || 'generic'] || a.source_platform || '',
        publishedDate: formatDate(a.published_at),
        readingTimeText: formatReadingTime(a.reading_time || 0),
        tabs,
        // 音频默认落在章节速览（MVP 无播放器，章节是最有用入口）
        activeTab: isAudio && chaptersApplicable ? 'chapters' : 'raw',
        loading: false,
      });
      wx.setNavigationBarTitle({ title: a.title || '阅读' });

      // 音频顺手预载章节（拿总时长展示）
      if (isAudio && chaptersApplicable) this.loadChapters();
    } catch (e) {
      this.setData({ loading: false, error: (e as Error).message || '加载失败' });
    }
  },

  onTabTap(e: any) {
    const key = String(e.currentTarget.dataset.key || '');
    this.setData({ activeTab: key });
    if (key === 'chapters' && !this.data.chapters && !this.data.chaptersLoading) {
      this.loadChapters();
    }
    if (key === 'transcript' && !this.data.transcript && !this.data.transcriptLoading) {
      this.loadTranscript();
    }
  },

  async loadChapters() {
    if (this.data.chaptersLoading) return;
    this.setData({ chaptersLoading: true, chaptersError: '' });
    try {
      const data = await api.getChapters(this.data.id);
      this.setData({
        chapters: data,
        chaptersLoading: false,
        totalDurationText: data.total_duration ? formatDuration(data.total_duration) : '',
      });
    } catch (e) {
      this.setData({ chaptersLoading: false, chaptersError: (e as Error).message || '加载失败' });
    }
  },

  async loadTranscript() {
    if (this.data.transcriptLoading) return;
    this.setData({ transcriptLoading: true, transcriptError: '' });
    try {
      const data = await api.getTranscript(this.data.id);
      this.setData({ transcript: data, transcriptLoading: false });
    } catch (e) {
      this.setData({ transcriptLoading: false, transcriptError: (e as Error).message || '加载失败' });
    }
  },

  onCopyUrl() {
    const url = this.data.article && this.data.article.url;
    if (!url) return;
    wx.setClipboardData({
      data: url,
      success: () => wx.showToast({ title: '原文链接已复制', icon: 'none' }),
    });
  },

  onCopyMedia() {
    const url = this.data.article && this.data.article.media_url;
    if (!url) return;
    wx.setClipboardData({
      data: url,
      success: () => wx.showToast({ title: '节目链接已复制', icon: 'none' }),
    });
  },

  onRetry() {
    this.loadDetail();
  },

  // ── 分享（个人主体可用）──────────────────────────────────

  onShareAppMessage() {
    const a = this.data.article;
    return {
      title: (a && a.title) || 'inFlow 知识库',
      path: '/pages/read/read?id=' + this.data.id,
      imageUrl: this.data.cover || undefined,
    };
  },

  onShareTimeline() {
    const a = this.data.article;
    return {
      title: (a && a.title) || 'inFlow 知识库',
      query: 'id=' + this.data.id,
      imageUrl: this.data.cover || undefined,
    };
  },
});
