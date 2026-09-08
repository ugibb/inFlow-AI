import { api } from '../../utils/api';
import { pageAuth } from '../../utils/auth';
import { logInfo } from '../../utils/log';
import { distributeColumns, MasonryColumn } from '../../utils/masonry';
import { resolveImage } from '../../utils/image-url';
import { PLATFORM_LABELS, PAGE_SIZE } from '../../config/index';

interface PlatformChip extends PlatformCount {
  label: string;
}

/** 列表数据进 data 前统一改写：封面走代理、标签最多展示 4 个 */
function decorate(a: Article): Article {
  return {
    ...a,
    cover_image: resolveImage(a.cover_image),
    tags: (a.tags || []).slice(0, 4),
  };
}

/**
 * 首页（tab1）：瀑布流 + 搜索（语义/关键词）+ 平台 chips + 主理人弹层 +
 * 无限滚动 + 下拉刷新静默合并（翻译 Web library/page.tsx 的数据流）。
 * 未登录不强踢登录页（审核要求「未登录可体验基本功能」）：进游客视图，
 * 展示示例文章（/api/articles/demo，无鉴权）+ 登录引导；空库也展示示例。
 */
Page({
  data: {
    columns: [] as MasonryColumn[],
    skeletonCols: [0, 1] as number[],
    loading: true,
    error: '',
    loadingMore: false,
    hasMore: false,
    total: 0,
    itemCount: 0,

    keyword: '',
    searchMode: 'semantic' as 'semantic' | 'keyword',

    platformCounts: [] as PlatformChip[],
    authorCounts: [] as AuthorCount[],
    platform: '',
    author: '',

    showAuthorPicker: false,
    authorKeyword: '',

    /** 游客态（未登录浏览）：隐藏搜索/筛选，展示引导 + 示例文章 */
    guest: false,
    demo: null as Article | null,
    demoLoading: false,
  },

  /** 全量有序源（不进 data，减小 setData 体积；columns 是它的分列派生） */
  items: [] as Article[],
  page: 1,
  firstShow: true,
  searchTimer: 0,

  onLoad() {
    pageAuth().then((token) => {
      if (!token) {
        this.enterGuestView();
        return;
      }
      this.reload();
      this.fetchCounts();
    });
  },

  onShow() {
    if (this.firstShow) {
      // 冷启动首帧：onLoad 已发起加载，跳过
      this.firstShow = false;
      return;
    }
    pageAuth().then((t) => {
      if (!t) return;
      // 游客态中完成登录（login redirect / 静默登录生效）→ 切回正式列表
      if (this.data.guest) {
        this.setData({ guest: false, loading: true, demo: null });
        this.reload();
        this.fetchCounts();
        return;
      }
      // 从 read 页返回 / tab 切回：静默合并第一页（保滚动位置）+ 刷新筛选计数
      this.fetchArticles(true);
      this.fetchCounts();
    });
  },

  onUnload() {
    if (this.searchTimer) clearTimeout(this.searchTimer);
  },

  // ── 数据加载 ──────────────────────────────────────────────

  buildParams(pageNum: number) {
    const d = this.data;
    return {
      page: pageNum,
      page_size: PAGE_SIZE,
      sort: 'published_at',
      ...(d.platform ? { source_platform: d.platform } : {}),
      ...(d.author ? { author: d.author } : {}),
      ...(d.keyword.trim() ? { search: d.keyword.trim(), search_mode: d.searchMode } : {}),
    };
  },

  /** 非静默：整表替换 + 重置第 1 页（初始加载、筛选/搜索变化、重试） */
  async reload() {
    this.setData({ loading: true, error: '' });
    try {
      const data = await api.getArticles(this.buildParams(1));
      logInfo('lib', 'list ok', { total: data.total, got: data.items.length });
      this.items = data.items.map(decorate);
      this.page = 1;
      this.setData({
        columns: distributeColumns(this.items),
        total: data.total,
        itemCount: this.items.length,
        hasMore: this.items.length < data.total,
        loading: false,
      });
      // 新账号空库（审核员/新用户首屏）：补展示示例文章
      if (!this.items.length) this.loadDemo();
    } catch (e) {
      this.setData({ loading: false, error: (e as Error).message || '加载失败' });
    }
  },

  /**
   * 静默合并（下拉刷新 / onShow）：只把第 1 页合并进列表头部，按 id 去重，
   * 深处已加载的卡片原样保留，滚动位置不丢；失败静默待下轮。
   */
  async fetchArticles(silent = false) {
    if (!silent) return this.reload();
    try {
      const data = await api.getArticles(this.buildParams(1));
      const firstPageIds = new Set(data.items.map((a) => a.id));
      const merged = [...data.items.map(decorate), ...this.items.filter((a) => !firstPageIds.has(a.id))];
      this.items = merged;
      this.page = 1;
      this.setData({
        columns: distributeColumns(merged),
        total: data.total,
        itemCount: merged.length,
        hasMore: merged.length < data.total,
      });
    } catch {
      /* 静默 */
    }
  },

  async fetchCounts() {
    try {
      const [platforms, authors] = await Promise.all([api.getPlatformCounts(), api.getAuthorCounts()]);
      this.setData({
        platformCounts: platforms.map((p) => ({ ...p, label: PLATFORM_LABELS[p.platform] || p.platform })),
        authorCounts: authors,
      });
    } catch {
      /* 筛选数据失败不阻塞列表 */
    }
  },

  // ── 下拉刷新 / 触底加载 ───────────────────────────────────

  onPullDownRefresh() {
    Promise.all([this.fetchArticles(true), this.fetchCounts()]).finally(() => {
      wx.stopPullDownRefresh();
    });
  },

  onReachBottom() {
    this.loadMore();
  },

  async loadMore() {
    if (this.data.loadingMore || this.data.loading || !this.data.hasMore) return;
    this.setData({ loadingMore: true });
    try {
      const data = await api.getArticles(this.buildParams(this.page + 1));
      this.items = [...this.items, ...data.items.map(decorate)];
      this.page += 1;
      this.setData({
        columns: distributeColumns(this.items),
        total: data.total,
        itemCount: this.items.length,
        hasMore: this.items.length < data.total,
        loadingMore: false,
      });
    } catch {
      this.setData({ loadingMore: false });
    }
  },

  // ── 搜索（300ms 防抖 + 语义/关键词 toggle）─────────────────

  onSearchInput(e: any) {
    this.setData({ keyword: e.detail.value });
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => {
      this.onFilterChange();
    }, 300) as unknown as number;
  },

  onSearchConfirm() {
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.onFilterChange();
  },

  onClearSearch() {
    if (this.searchTimer) clearTimeout(this.searchTimer);
    if (!this.data.keyword) return;
    this.setData({ keyword: '' });
    this.onFilterChange();
  },

  onToggleSearchMode() {
    const next = this.data.searchMode === 'semantic' ? 'keyword' : 'semantic';
    this.setData({ searchMode: next });
    if (this.data.keyword.trim()) this.onFilterChange();
  },

  // ── 筛选 ──────────────────────────────────────────────────

  onSelectPlatform(e: any) {
    const p = String(e.currentTarget.dataset.platform || '');
    if (p === this.data.platform) return;
    this.setData({ platform: p });
    this.onFilterChange();
  },

  onOpenAuthorPicker() {
    this.setData({ showAuthorPicker: true, authorKeyword: '' });
  },

  onCloseAuthorPicker() {
    this.setData({ showAuthorPicker: false });
  },

  onAuthorKeywordInput(e: any) {
    this.setData({ authorKeyword: e.detail.value });
  },

  onSelectAuthor(e: any) {
    const a = String(e.currentTarget.dataset.author || '');
    this.setData({ showAuthorPicker: false, author: a });
    this.onFilterChange();
  },

  onClearAuthor() {
    this.setData({ showAuthorPicker: false, author: '' });
    this.onFilterChange();
  },

  /** 筛选/搜索变化：回到顶部并整体重拉 */
  onFilterChange() {
    wx.pageScrollTo({ scrollTop: 0, duration: 0 });
    this.reload();
  },

  // ── 其他 ──────────────────────────────────────────────────

  onRetry() {
    this.reload();
  },

  // ── 游客态（未登录浏览）────────────────────────────────────

  /** 进入游客视图：不拉列表，加载示例文章（失败静默退回纯引导） */
  enterGuestView() {
    this.setData({ guest: true, loading: false, error: '' });
    this.loadDemo();
  },

  async loadDemo() {
    this.setData({ demoLoading: true });
    try {
      const a = await api.getArticleDemo();
      this.setData({ demo: decorate(a), demoLoading: false });
    } catch {
      // 云端未配置 DEMO_ARTICLE_ID / 网络失败：引导卡仍完整可用
      this.setData({ demo: null, demoLoading: false });
    }
  },

  /** 登录引导 → 登录页（登录成功 reLaunch 回首页转正式列表） */
  onGoLogin() {
    wx.navigateTo({
      url: '/pages/login/login?redirect=' + encodeURIComponent('/pages/library/library'),
    });
  },

  onCardTap(e: any) {
    const id = e.detail && e.detail.id;
    if (id) wx.navigateTo({ url: '/pages/read/read?id=' + id });
  },

  onShareAppMessage() {
    return { title: 'inFlow 知识库', path: '/pages/library/library' };
  },
});
