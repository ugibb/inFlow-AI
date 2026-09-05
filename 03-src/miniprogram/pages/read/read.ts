import { api } from '../../utils/api';
import { pageAuth } from '../../utils/auth';
import { resolveImage } from '../../utils/image-url';
import { formatDate, formatDuration, formatPlayerTime, formatReadingTime } from '../../utils/format';
import * as player from '../../utils/player';
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

    // 播放器（音频内容；底部常驻播放条）
    playing: false,
    audioCurrent: 0,
    audioDuration: 0,
    audioCurrentText: '0:00',
    audioDurationText: '',
  },

  /** 拖动进度条期间不响应 timeupdate 回写（避免滑块拉锯） */
  scrubbing: false,

  onLoad(options: Record<string, string | undefined>) {
    const id = (options && options.id) || '';
    this.setData({ id });
    if (!id) {
      this.setData({ loading: false, error: '缺少文章参数' });
      return;
    }
    pageAuth().then((token) => {
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

      // 订阅全局播放器（详情重试/重新进入都会重绑，模块内是单槽回调）
      this.bindPlayer();

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

  // ── 播放器（音频内容）────────────────────────────────────

  playMeta(): player.PlayMeta | null {
    const a = this.data.article;
    if (!a || !a.media_url) return null;
    return { src: a.media_url, title: a.title || '未命名节目', cover: this.data.cover || undefined };
  },

  /** 订阅全局播放器：只响应「本篇」的源（换篇/别的文章在播时本页播放条保持闲置） */
  bindPlayer() {
    player.bind((s) => {
      const url = this.data.article && this.data.article.media_url;
      if (!url || s.src !== url) return;
      const curText = formatPlayerTime(s.current);
      const durText = s.duration ? formatPlayerTime(s.duration) : '';
      // 按秒粒度去重，避免 timeupdate 高频 setData
      if (
        this.data.playing === s.playing &&
        this.data.audioCurrentText === curText &&
        this.data.audioDurationText === durText
      ) {
        return;
      }
      this.setData({
        playing: s.playing,
        audioCurrent: s.current,
        audioDuration: s.duration,
        audioCurrentText: curText,
        audioDurationText: durText,
      });
    });
  },

  onTogglePlay() {
    const meta = this.playMeta();
    if (!meta) return;
    player.toggle(meta, this.data.audioCurrent);
  },

  /** 章节点击 → 跳到起始秒播放 */
  onChapterTap(e: any) {
    this.seekAudio(Number(e.detail.startTime) || 0);
  },

  /** 转录句点击 → 跳到起始秒播放 */
  onSegmentTap(e: any) {
    this.seekAudio(Number(e.detail.start) || 0);
  },

  seekAudio(sec: number) {
    const meta = this.playMeta();
    if (!meta) {
      wx.showToast({ title: '该内容无音频可播放', icon: 'none' });
      return;
    }
    player.seekPlay(meta, sec);
    this.setData({ audioCurrent: sec, audioCurrentText: formatPlayerTime(sec) });
  },

  onScrubbing(e: any) {
    const v = Number(e.detail.value) || 0;
    this.scrubbing = true;
    player.scrubStart();
    this.setData({ audioCurrent: v, audioCurrentText: formatPlayerTime(v) });
  },

  onScrubEnd(e: any) {
    const v = Number(e.detail.value) || 0;
    this.scrubbing = false;
    player.scrubEnd(v);
    this.setData({ audioCurrent: v, audioCurrentText: formatPlayerTime(v) });
  },

  onUnload() {
    // 只解绑 UI 订阅；音频本身继续播（后台/锁屏不打断）
    player.bind(null);
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
