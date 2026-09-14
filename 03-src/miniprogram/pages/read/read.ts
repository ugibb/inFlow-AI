import { api } from '../../utils/api';
import { pageAuth } from '../../utils/auth';
import { resolveImage } from '../../utils/image-url';
import { formatDate, formatDuration, formatPlayerTime, formatReadingTime } from '../../utils/format';
import * as player from '../../utils/player';
import { logInfo, logError } from '../../utils/log';
import { PLATFORM_LABELS } from '../../config/index';

interface TabItem {
  key: 'raw' | 'chapters' | 'transcript' | 'ai';
  label: string;
}

/** 倍速展示文案：1 → 1x，1.25 → 1.25x（避免浮点噪声） */
function formatRate(r: number): string {
  return Math.round(r * 100) / 100 + 'x';
}

/** 剩余时长文案：未载入时长返回 ''（播放条右上不显示 -0:00） */
function remainingText(dur: number, cur: number): string {
  return dur > 0 ? formatPlayerTime(Math.max(0, dur - cur)) : '';
}

/** 进度百分比 0–100：时长未知归 0（自绘进度条用，保留小数让长节目也平滑） */
function progressPct(dur: number, cur: number): number {
  return dur > 0 ? Math.min(100, Math.max(0, (cur / dur) * 100)) : 0;
}

/**
 * 入口参数解析：普通/分享卡片走 options.id；精华卡页脚小程序码走 options.scene
 * （getwxacodeunlimit 的 scene = 文章 UUID 去横线的 32 位 hex，恰好卡 32 字符上限）。
 */
function resolveEntryId(options: Record<string, string | undefined>): string {
  const id = (options && options.id) || '';
  if (id) return id;
  const scene = (options && options.scene) || '';
  if (!scene) return '';
  let hex = '';
  try {
    hex = decodeURIComponent(scene).replace(/[^0-9a-fA-F]/g, '');
  } catch {
    hex = scene.replace(/[^0-9a-fA-F]/g, '');
  }
  if (hex.length !== 32) return '';
  const s = hex.toLowerCase();
  return `${s.slice(0, 8)}-${s.slice(8, 12)}-${s.slice(12, 16)}-${s.slice(16, 20)}-${s.slice(20)}`;
}

/**
 * 阅读页：detail 一次拉全（含 content_blocks 存在性快照），tab 显示由快照驱动；
 * 章节/转录切到时才懒加载并缓存本页内存。可被分享卡片/小程序码直达。
 * 游客只读：无 token（静默登录失败/邀请码未过/分享进入未登录），或已登录但
 * 文章非本账号（404）时走 /guest 通道，持链接/码即可读（UUID 即阅读凭证），
 * 音频播放/章节/转录照常，页面顶部给登录引导条。
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
    /** 提词器：当前播放所在句（transcript-view 高亮跟随用） */
    transcriptActiveIdx: -1,

    // 播放器（音频内容；底部常驻播放条）
    playing: false,
    audioCurrent: 0,
    audioDuration: 0,
    audioCurrentText: '0:00',
    /** 播放条右上「-剩余」文案（时长未知时为空不显示） */
    audioLeftText: '',
    /** 底部播放条当前倍速文案（1x/1.25x…） */
    rateText: '1x',
    /** 自绘进度条百分比 0–100（时长未知时 0） */
    progPercent: 0,

    /** 游客只读模式（章节/转录走 /guest 通道 + 顶部登录引导条） */
    guest: false,
  },

  /** 拖动进度条期间不响应 timeupdate 回写（避免滑块拉锯） */
  scrubbing: false,
  /** 自绘进度条：条几何缓存 + 当前触点（手势内避免重复查询） */
  progRect: null as { left: number; width: number } | null,
  progGesturing: false,
  progX: -1,

  onLoad(options: Record<string, string | undefined>) {
    const id = resolveEntryId(options);
    this.setData({ id, rateText: formatRate(player.getRate()) }); // 胶囊先显示记忆倍速，bindPlayer 再接管
    if (!id) {
      this.setData({ loading: false, error: '缺少文章参数' });
      return;
    }
    pageAuth().then((token) => {
      if (!token) {
        // 未登录（静默登录失败/邀请码门槛/分享直达）→ 游客只读，不强制登录
        this.enterGuest();
        return;
      }
      this.loadDetail();
    });
  },

  async loadDetail() {
    this.setData({ loading: true, error: '' });
    try {
      const a = await api.getArticle(this.data.id);
      this.applyDetail(a);
    } catch (e) {
      // 文章非当前账号（404）→ 转游客只读；真不存在则 guest 请求同样 404 落错误态
      if (!this.data.guest && (e as { statusCode?: number }).statusCode === 404) {
        this.enterGuest();
        return;
      }
      logError('read', 'detail fail', { msg: (e as Error).message });
      this.setData({ loading: false, error: (e as Error).message || '加载失败' });
    }
  },

  /** 转入游客只读模式并加载（无 token / 非本账号文章） */
  enterGuest() {
    this.setData({ guest: true });
    this.loadDetailGuest();
  },

  async loadDetailGuest() {
    this.setData({ loading: true, error: '' });
    try {
      const a = await api.getArticleGuest(this.data.id);
      this.applyDetail(a);
    } catch (e) {
      logError('read', 'guest detail fail', { msg: (e as Error).message });
      this.setData({ loading: false, error: (e as Error).message || '加载失败' });
    }
  },

  /** detail 响应落屏（登录/游客两路共用） */
  applyDetail(a: ArticleDetail) {
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
    logInfo('read', 'detail ok', {
      id: this.data.id,
      ctype: a.content_type,
      media: !!a.media_url,
      contentLen: (a.clean_content || '').length,
    });

    // 订阅全局播放器（详情重试/重新进入都会重绑，模块内是单槽回调）
    this.bindPlayer();

    // 音频顺手预载章节（拿总时长展示）
    if (isAudio && chaptersApplicable) this.loadChapters();
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
      const data = this.data.guest
        ? await api.getChaptersGuest(this.data.id)
        : await api.getChapters(this.data.id);
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
      const data = this.data.guest
        ? await api.getTranscriptGuest(this.data.id)
        : await api.getTranscript(this.data.id);
      logInfo('read', 'transcript ok', { segs: (data.segments || []).length });
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

      // 提词器：按播放时间二分找当前句（翻译 Web timeupdate 高亮）
      const segs = this.data.transcript && this.data.transcript.segments;
      let idx = -1;
      if (segs && segs.length && this.data.activeTab === 'transcript') {
        const t = s.current;
        let lo = 0;
        let hi = segs.length - 1;
        let found = -1;
        while (lo <= hi) {
          const mid = (lo + hi) >> 1;
          if (segs[mid].start <= t) {
            found = mid;
            lo = mid + 1;
          } else {
            hi = mid - 1;
          }
        }
        idx = found >= 0 && t <= segs[found].end ? found : -1;
      }
      if (idx !== this.data.transcriptActiveIdx) this.setData({ transcriptActiveIdx: idx });

      const curText = formatPlayerTime(s.current);
      const leftText = remainingText(s.duration, s.current);
      const rateText = formatRate(s.rate || 1);
      const pct = progressPct(s.duration, s.current);
      // 按秒粒度去重，避免 timeupdate 高频 setData
      if (
        this.data.playing === s.playing &&
        this.data.audioCurrentText === curText &&
        this.data.audioLeftText === leftText &&
        this.data.rateText === rateText
      ) {
        return;
      }
      this.setData({
        playing: s.playing,
        audioCurrent: s.current,
        audioDuration: s.duration,
        audioCurrentText: curText,
        audioLeftText: leftText,
        rateText,
        progPercent: pct,
      });
    });
  },

  onTogglePlay() {
    const meta = this.playMeta();
    if (!meta) return;
    const starting = !this.data.playing;
    player.toggle(meta, this.data.audioCurrent);
    // 对齐 Web onPlay 行为：点播放 → 切到全文转录 + 标签页滚到顶部（提词器尽量占屏）
    if (starting) {
      this.goTranscript();
      this.pinTabsTop();
    }
  },

  /** 切到转录 tab 并懒加载（播放启动时用） */
  goTranscript() {
    if (!this.data.tabs.some((t) => t.key === 'transcript')) return;
    this.setData({ activeTab: 'transcript' });
    if (!this.data.transcript && !this.data.transcriptLoading) this.loadTranscript();
  },

  /**
   * 页面滚动到标签条贴顶。起播会同时切 tab + 渲染 65vh 提词器，页面高度
   * 突变会打断进行中的滚动动画——所以按「视口偏移 + 当前页滚距」算绝对
   * 位置直接落点，并延迟两段校正（120ms / 480ms）兜住渲染时序。
   */
  pinTabsTop() {
    const scrollTabs = () => {
      const q = wx.createSelectorQuery();
      q.select('#read-tabs').boundingClientRect();
      q.selectViewport().scrollOffset();
      q.exec((res) => {
        const rect = (res && res[0]) as { top: number } | null;
        const sc = (res && res[1]) as { scrollTop: number } | null;
        if (!rect || rect.top == null || !sc) return;
        if (Math.abs(rect.top) < 4) return; // 已贴顶
        wx.pageScrollTo({
          scrollTop: Math.max(0, sc.scrollTop + rect.top),
          duration: 200,
        });
      });
    };
    setTimeout(scrollTabs, 120);
    setTimeout(scrollTabs, 480);
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
    this.setData({
      audioCurrent: sec,
      audioCurrentText: formatPlayerTime(sec),
      audioLeftText: remainingText(this.data.audioDuration, sec),
      progPercent: progressPct(this.data.audioDuration, sec),
    });
  },

  /**
   * 自绘进度条：点按/拖动跳转。
   * touchstart 挂起 timeupdate 回写（scrubStart），touchmove 按触点把 clientX 映射成
   * 秒并镜像 UI，touchend 用最终值 seek（scrubEnd）。条几何只在首次测量并缓存，
   * 快速点按恰逢几何未就绪时，measure 完成回调里补做 seek。
   */
  measureProg(): Promise<{ left: number; width: number } | null> {
    if (this.progRect) return Promise.resolve(this.progRect);
    return new Promise((resolve) => {
      const q = wx.createSelectorQuery().in(this);
      q.select('#player-prog').boundingClientRect();
      q.exec((res: any) => {
        const r = res && res[0];
        this.progRect = r && r.width ? { left: r.left, width: r.width } : null;
        resolve(this.progRect);
      });
    });
  },

  touchX(e: any): number {
    const arr = (e && (e.touches || e.changedTouches || [])) as { clientX: number }[];
    const t = arr[0];
    return t ? t.clientX : -1;
  },

  /** clientX → 秒，写镜像 UI；返回落点秒 */
  progXtoSec(clientX: number): number {
    const dur = this.data.audioDuration;
    const rect = this.progRect;
    if (!(dur > 0) || !rect || !rect.width) return this.data.audioCurrent;
    let ratio = (clientX - rect.left) / rect.width;
    ratio = Math.max(0, Math.min(1, ratio));
    const v = ratio * dur;
    this.setData({
      audioCurrent: v,
      audioCurrentText: formatPlayerTime(v),
      audioLeftText: remainingText(dur, v),
      progPercent: progressPct(dur, v),
    });
    return v;
  },

  onProgStart(e: any) {
    if (!(this.data.audioDuration > 0)) return;
    this.scrubbing = true;
    this.progGesturing = true;
    this.progX = this.touchX(e);
    if (this.progX < 0) return;
    player.scrubStart();
    if (this.progRect) {
      this.progXtoSec(this.progX);
    } else {
      this.measureProg().then(() => {
        if (this.data.audioDuration > 0) this.progXtoSec(this.progX);
      });
    }
  },

  onProgMove(e: any) {
    if (!this.progGesturing) return;
    const x = this.touchX(e);
    if (x < 0) return;
    this.progX = x;
    if (this.progRect) this.progXtoSec(x);
  },

  onProgEnd(e: any) {
    if (!this.progGesturing) return;
    const x = this.touchX(e);
    if (x < 0) {
      // touchcancel / 无结束触点：seek 到拖动最后一次落点
      this.progGesturing = false;
      this.scrubbing = false;
      player.scrubEnd(this.data.audioCurrent);
      return;
    }
    this.progX = x;
    if (this.progRect) {
      const v = this.progXtoSec(x);
      this.progGesturing = false;
      this.scrubbing = false;
      player.scrubEnd(v);
    } else {
      // 快速点按，几何尚未就绪：measure 完成后再统一落位并 seek，避免先跳旧值再跳目标
      this.progGesturing = false;
      this.measureProg().then(() => {
        if (this.data.audioDuration > 0) {
          const sec = this.progXtoSec(this.progX);
          this.scrubbing = false;
          player.scrubEnd(sec);
        }
      });
    }
  },

  /**
   * 回退/快进按钮：秒数由 data-delta 决定（−15 回退 / 30 快进，与参考图一致）。
   * 已起播走 seek（播放中不打断、暂停仅移位）；未起播只挪页面镜像位置，
   * 等用户点播放（toggle 以 audioCurrent 为 resumeSec）时从该秒开始。
   */
  onSkip(e: any) {
    const meta = this.playMeta();
    if (!meta) return;
    const delta = Number(e.currentTarget.dataset.delta) || 0;
    const st = player.getState();
    // 基准取整秒：确定性 ±5 步进，避免浮点累积漂移
    const now = Math.round(st.src === meta.src ? st.current : this.data.audioCurrent);
    const dur = this.data.audioDuration;
    const target = Math.max(0, dur > 0 ? Math.min(now + delta, Math.floor(dur)) : now + delta);
    if (target === now) return;
    if (st.src === meta.src) player.seekTo(target);
    this.setData({
      audioCurrent: target,
      audioCurrentText: formatPlayerTime(target),
      audioLeftText: remainingText(this.data.audioDuration, target),
      progPercent: progressPct(this.data.audioDuration, target),
    });
  },

  /** 倍速切换：点按前进一档，环形 0.75→1→1.25→1.5→2→0.75…（异常速率兜底到 1x 再进档） */
  onRateCycle() {
    const opts = player.RATE_OPTIONS;
    let idx = opts.indexOf(player.getRate());
    if (idx < 0) idx = opts.indexOf(1);
    player.setRate(opts[(idx + 1) % opts.length]);
  },

  onUnload() {
    // 只解绑 UI 订阅；音频本身继续播（后台/锁屏不打断）
    player.bind(null);
  },

  onRetry() {
    if (this.data.guest) this.loadDetailGuest();
    else this.loadDetail();
  },

  /** 游客引导条 → 登录页（登录后回到本篇，转正常模式） */
  onGuestLogin() {
    wx.navigateTo({
      url: '/pages/login/login?redirect=' + encodeURIComponent('/pages/read/read?id=' + this.data.id),
    });
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
