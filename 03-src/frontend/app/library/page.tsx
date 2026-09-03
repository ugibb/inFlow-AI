'use client';

import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import Link from 'next/link';
import {
  Search, X, LayoutGrid, Filter, Check, FolderOpen, ChevronRight,
  PanelLeftClose, PanelLeft, Plus, Loader2, Trash2, Tag, Edit2,
  FolderKanban, MoreHorizontal, GitMerge, Palette, Headphones, FileText, Globe,
} from 'lucide-react';
import { useSearchParams } from 'next/navigation';
import { api } from '@/lib/api';
import type { Article, Tag as TagType, TagWithCount, Folder, ArticleListResponse, IngestJob, PlatformCount } from '@/lib/types';
import ArticleCard from '@/components/ArticleCard';
import AddContentModal from '@/components/AddContentModal';
import { useAuth } from '@/contexts/AuthContext';

// ─── Platform labels (shared with processing page) ───────────────────────────

const PLATFORM_LABELS: Record<string, string> = {
  wechat: '微信公众号', bilibili: 'B 站', xiaoyuzhou: '小宇宙',
  xhs: '小红书', douyin: '抖音', youtube: 'YouTube',
  toutiao: '今日头条', juejin: '掘金', csdn: 'CSDN',
  '36kr': '36 氪', sspai: '少数派', jianshu: '简书',
  weibo: '微博', douban: '豆瓣', medium: 'Medium',
  upload: '上传文件', generic: '网页', note: '笔记',
  spark: 'AI 生成', other: '其他',
};

const PLATFORM_GRADIENTS: Record<string, string> = {
  xiaoyuzhou: 'linear-gradient(135deg, #ff9500 0%, #e07800 100%)',
  bilibili:   'linear-gradient(135deg, #fb7299 0%, #e0507a 100%)',
  wechat:     'linear-gradient(135deg, #34c759 0%, #22a344 100%)',
  youtube:    'linear-gradient(135deg, #ff3b30 0%, #c0392b 100%)',
  xhs:        'linear-gradient(135deg, #ff2d55 0%, #cc1f44 100%)',
  douyin:     'linear-gradient(135deg, #444 0%, #111 100%)',
  note:       'linear-gradient(135deg, #5856d6 0%, #3a38b0 100%)',
  upload:     'linear-gradient(135deg, #8e8e93 0%, #636366 100%)',
  juejin:     'linear-gradient(135deg, #007fff 0%, #0055cc 100%)',
  generic:    'linear-gradient(135deg, #007aff 0%, #0055cc 100%)',
};

// ─── Processing card ──────────────────────────────────────────────────────────

function ProcessingJobCard({ job }: { job: IngestJob }) {
  const preview = job.raw_preview;
  const platform = preview?.platform || job.source_platform || 'generic';
  const title = preview?.title || job.source_url || '处理中…';
  const isAudio = preview?.content_type === 'audio';

  const gradient = PLATFORM_GRADIENTS[platform] || PLATFORM_GRADIENTS.generic;
  const initial = (PLATFORM_LABELS[platform] || platform).charAt(0).toUpperCase();

  const href = `/processing/${job.job_id}`;

  return (
    <Link
      href={href}
      className="block rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] overflow-hidden hover:border-[var(--accent)]/30 hover:shadow-lg transition-all duration-200"
    >
      {/* Cover image / gradient placeholder */}
      <div className="relative h-44 w-full overflow-hidden">
        {preview?.cover_image ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={preview.cover_image} alt="" className="w-full h-full object-cover" />
        ) : (
          <div
            className="w-full h-full flex items-center justify-center"
            style={{ background: gradient }}
          >
            <span className="text-6xl font-bold text-white/20 select-none">{initial}</span>
          </div>
        )}
      </div>

      {/* Info section */}
      <div className="p-4 space-y-2">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-[var(--accent-light)] text-[var(--accent)]">
            <Loader2 size={10} className="animate-spin" /> 处理中
          </span>
          <span className="text-xs text-[var(--text-tertiary)]">
            {PLATFORM_LABELS[platform] || platform}
          </span>
          {isAudio && <Headphones size={12} className="text-[var(--text-tertiary)]" />}
          {!isAudio && preview?.content_type && <FileText size={12} className="text-[var(--text-tertiary)]" />}
        </div>
        <p className="text-sm font-semibold text-[var(--text-primary)] leading-snug line-clamp-2">{title}</p>
        {preview?.author && (
          <p className="text-xs text-[var(--text-tertiary)] truncate">{preview.author}</p>
        )}
      </div>
    </Link>
  );
}

// 每页拉取条数（后端 page_size 上限 100）
const PAGE_SIZE = 24;

// 平台来源下拉选项不再硬编码：由 GET /articles/platforms 返回的真实平台动态生成，
// 新平台自动出现，避免静态列表漏平台（如小宇宙/youtube）。见搜索栏 sourceFilter select。
const TAG_COLORS = [
  '#007aff', '#5856d6', '#ff9500', '#34c759', '#ff3b30',
  '#af52de', '#ff2d55', '#00c7be', '#007aff', '#ffcc00',
];

function normalizedArticleUrl(raw?: string | null): string {
  if (!raw) return '';
  try {
    const u = new URL(raw);
    const host = u.host.toLowerCase();
    const path = u.pathname.replace(/\/+$/, '') || '/';
    return `${u.protocol}//${host}${path}`;
  } catch {
    return raw.trim();
  }
}

function articleQualityScore(a: Article): number {
  let score = 0;
  if (a.cover_image) score += 4;
  if (a.summary) score += 4;
  if ((a.key_points?.length || 0) > 0) score += 2;
  if (a.fetch_status === 'completed') score += 2;
  if (a.fetch_status === 'failed') score -= 2;
  if (a.fetch_status === 'ingesting' || a.fetch_status === 'pending_agent') score -= 1;
  return score;
}

export default function LibraryPage() {
  const searchParams = useSearchParams();
  const { loading: authLoading, token } = useAuth();
  const [articles, setArticles] = useState<Article[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const [username, setUsername] = useState('');

  const [search, setSearch] = useState('');
  const [searchMode, setSearchMode] = useState<'semantic' | 'keyword'>('semantic');
  const [statusFilter, setStatusFilter] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [folderFilter, setFolderFilter] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [platformCounts, setPlatformCounts] = useState<PlatformCount[]>([]);

  const [tags, setTags] = useState<TagWithCount[]>([]);
  const [folders, setFolders] = useState<Folder[]>([]);

  // Left panel state
  const [showFolderPanel, setShowFolderPanel] = useState(true);
  const [activeLeftTab, setActiveLeftTab] = useState<'folders' | 'platforms' | 'tags'>('platforms');

  // Folder state
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const [creating, setCreating] = useState(false);
  const [editingFolderId, setEditingFolderId] = useState<string | null>(null);
  const [editingFolderName, setEditingFolderName] = useState('');

  // Tag management state
  const [tagSearch, setTagSearch] = useState('');
  const [showNewTag, setShowNewTag] = useState(false);
  const [newTagName, setNewTagName] = useState('');
  const [newTagColor, setNewTagColor] = useState(TAG_COLORS[0]);
  const [creatingTag, setCreatingTag] = useState(false);
  const [editingTag, setEditingTag] = useState<string | null>(null);
  const [editTagName, setEditTagName] = useState('');
  const [editTagColor, setEditTagColor] = useState('');
  const [savingTag, setSavingTag] = useState(false);
  const [mergeFromTag, setMergeFromTag] = useState<string | null>(null);

  // Active ingest jobs (shown as processing cards)
  const [activeJobs, setActiveJobs] = useState<IngestJob[]>([]);
  const prevJobIdsRef = useRef<string>('');
  const listEmptyRetryRef = useRef(0);

  // Article selection
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [moveToFolderId, setMoveToFolderId] = useState('');
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [showFilters, setShowFilters] = useState(false);

  // Apply URL search params
  useEffect(() => {
    const urlTag = searchParams.get('tag');
    const urlSource = searchParams.get('source_platform');
    const urlUsername = searchParams.get('username');
    if (urlTag) { setTagFilter(urlTag); setShowFilters(true); } else { setTagFilter(''); }
    if (urlSource) { setSourceFilter(urlSource); setShowFilters(true); } else { setSourceFilter(''); }
    if (urlUsername) { setUsername(urlUsername); } else { setUsername(''); }
  }, [searchParams]);

  const showToast = (m: string, t: 'success' | 'error') => {
    setToast({ message: m, type: t });
    setTimeout(() => setToast(null), 3000);
  };

  // 是否处于无筛选的默认视图（空列表自动重试仅在该视图下生效）
  const hasActiveFilters = !!(statusFilter || tagFilter || folderFilter || sourceFilter || search || username);

  // 列表请求参数（fetchArticles 与 loadMore 共用）
  const buildListParams = useCallback((pageNum: number): any => {
    const params: any = { page: pageNum, page_size: PAGE_SIZE, sort: 'updated_at' };
    if (statusFilter) params.status = statusFilter;
    if (tagFilter) params.tag = tagFilter;
    if (folderFilter) params.folder_id = folderFilter;
    if (sourceFilter) params.source_platform = sourceFilter;
    if (search) { params.search = search; params.search_mode = searchMode; }
    if (username) params.username = username;
    return params;
  }, [statusFilter, tagFilter, folderFilter, sourceFilter, search, searchMode, username]);

  // fetchArticles 始终拉第 1 页，两种语义：
  //   非 silent → replace：骨架屏 + 整表替换 + 重置回第 1 页（初始加载、筛选/搜索变化、手动重试）
  //   silent    → merge：只把第 1 页合并进列表头部（sort=updated_at，新文章/刚处理完的必在第 1 页），
  //                深处已加载的卡片原样保留，按 article.id 复用 DOM，滚动位置不丢；失败静默待下轮重试。
  const fetchArticles = useCallback(async (opts?: { silent?: boolean }) => {
    const silent = opts?.silent === true;
    if (!silent) { setLoading(true); setError(''); }
    try {
      const data = await api.getArticles(buildListParams(1)) as ArticleListResponse;
      if (silent) {
        const firstPageIds = new Set(data.items.map(a => a.id));
        setArticles(prev => [...data.items, ...prev.filter(a => !firstPageIds.has(a.id))]);
      } else {
        setArticles(data.items); setPage(1);
      }
      setTotal(data.total);
      // 平台计数随列表一起静默刷新，入库/收藏后侧栏 tab 数字保持同步（失败忽略）
      api.getPlatformCounts().then(setPlatformCounts).catch(() => {});
      if (!hasActiveFilters && data.total === 0 && data.items.length === 0 && listEmptyRetryRef.current < 2) {
        listEmptyRetryRef.current += 1;
        window.setTimeout(() => fetchArticlesRef.current({ silent: true }), 800);
        return;
      }
      if (data.total > 0) listEmptyRetryRef.current = 0;
    } catch (e: any) {
      if (!silent) setError(e.message || '加载失败');
    } finally { if (!silent) setLoading(false); }
  }, [buildListParams, hasActiveFilters]);

  const fetchTags = async () => { try { setTags(await api.getTags()); } catch {} };
  const fetchFolders = async () => { try { setFolders(await api.getFolders()); } catch {} };

  const fetchActiveJobs = useCallback(async () => {
    try {
      const jobs = await api.getActiveIngestJobs();
      setActiveJobs(jobs);
    } catch {}
  }, []);

  const fetchArticlesRef = useRef(fetchArticles);
  fetchArticlesRef.current = fetchArticles;

  // ─── 无限滚动：滚到底部附近自动追加下一页 ────────────────────────────────────
  const hasMore = page * PAGE_SIZE < total;

  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore || authLoading || !token) return;
    setLoadingMore(true);
    try {
      const data = await api.getArticles(buildListParams(page + 1)) as ArticleListResponse;
      setArticles(prev => [...prev, ...data.items]);
      setTotal(data.total);
      setPage(p => p + 1);
    } catch {} finally { setLoadingMore(false); }
  }, [loadingMore, hasMore, authLoading, token, page, buildListParams]);

  const loadMoreRef = useRef(loadMore);
  loadMoreRef.current = loadMore;
  const sentinelRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // 哨兵进入视口（提前 600px 预加载）→ 加载下一页。root 必须挂右栏滚动容器，
  // 页面滚动发生在该容器内而非 window，默认 root 会永远不触发。
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const io = new IntersectionObserver(
      entries => { if (entries[0]?.isIntersecting) loadMoreRef.current(); },
      { root: scrollContainerRef.current, rootMargin: '600px 0px' },
    );
    io.observe(sentinel);
    return () => io.disconnect();
  }, [loading, error]);

  useEffect(() => {
    if (authLoading || !token) return;
    fetchArticles();
  }, [authLoading, token, fetchArticles]);
  useEffect(() => {
    if (authLoading || !token) return;
    fetchTags();
    fetchFolders();
    fetchActiveJobs();
    api.getPlatformCounts().then(setPlatformCounts).catch(() => {});
  }, [authLoading, token, fetchActiveJobs]);

  // Poll active jobs every 3s; when count drops, a job finished → refresh articles
  useEffect(() => {
    if (activeJobs.length === 0) return;
    const currentIds = activeJobs.map(j => j.job_id).sort().join(',');
    if (prevJobIdsRef.current && prevJobIdsRef.current !== currentIds) {
      fetchArticlesRef.current({ silent: true });
    }
    prevJobIdsRef.current = currentIds;
    const t = setInterval(fetchActiveJobs, 3000);
    return () => clearInterval(t);
  }, [activeJobs, fetchActiveJobs]);

  // Poll while any article is still processing. Two scenarios:
  //   1) fetch_status === 'pending_agent' — waiting for local agent (mac may be off).
  //      Longer cap because agent latency is unpredictable.
  //   2) summary missing on a non-note article — AI background task in flight; usually fast.
  // Cap total attempts (not per-render) so re-renders during polling don't extend it.
  const pollAttemptsRef = useRef(0);
  const pendingIdsRef = useRef<string>('');
  useEffect(() => {
    const agentPending = articles.some(a => a.fetch_status === 'pending_agent');
    const summaryPending = articles.some(
      a => !a.summary && a.content_type !== 'note' && a.fetch_status !== 'pending_agent' && a.fetch_status !== 'failed'
    );
    const pendingIds = articles
      .filter(a =>
        a.fetch_status === 'pending_agent' ||
        (!a.summary && a.content_type !== 'note' && a.fetch_status !== 'failed')
      )
      .map(a => a.id)
      .sort()
      .join(',');
    if (pendingIds !== pendingIdsRef.current) {
      pendingIdsRef.current = pendingIds;
      pollAttemptsRef.current = 0;
    }
    if (!pendingIds) return;
    // Agent-pending: poll up to ~5min (60 × 5s). AI summary only: keep old ~32s.
    const cap = agentPending ? 60 : 8;
    const interval = agentPending ? 5000 : 4000;
    if (pollAttemptsRef.current >= cap) return;
    const t = setTimeout(() => {
      pollAttemptsRef.current += 1;
      fetchArticlesRef.current({ silent: true });
    }, interval);
    return () => clearTimeout(t);
  }, [articles]);

  // Debounced search via ref to avoid stale closure
  useEffect(() => {
    if (authLoading || !token) return;
    const t = setTimeout(() => { fetchArticlesRef.current(); }, 300);
    return () => clearTimeout(t);
  }, [search, authLoading, token]);
  useEffect(() => {
    if (authLoading || !token) return;
    if (search) { fetchArticlesRef.current(); }
  }, [searchMode, search, authLoading, token]);

  const toggleSelect = (id: string) => {
    const next = new Set(selectedIds);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelectedIds(next);
  };

  // 批量操作后原地更新列表（不整表重拉），避免已滚到的深处内容被重置
  const removeFromList = (ids: Set<string>) => {
    setArticles(prev => prev.filter(a => !ids.has(a.id)));
    setTotal(t => Math.max(0, t - ids.size));
  };

  const batchDelete = async () => {
    if (!confirm(`确定删除选中的 ${selectedIds.size} 篇文章？`)) return;
    for (const id of Array.from(selectedIds)) { try { await api.deleteArticle(id); } catch {} }
    removeFromList(selectedIds);
    setSelectedIds(new Set()); showToast('批量删除完成', 'success');
  };

  const batchArchive = async () => {
    for (const id of Array.from(selectedIds)) { try { await api.updateArticle(id, { status: 'archived' }); } catch {} }
    removeFromList(selectedIds);
    setSelectedIds(new Set()); showToast('已归档', 'success');
  };

  const batchMoveToFolder = async (folderId: string) => {
    const folderName = folders.find(f => f.id === folderId)?.name || '所选文件夹';
    try {
      await api.batchMoveArticles(Array.from(selectedIds), folderId);
      // 正在浏览目标文件夹之外的视图时，被移走的卡片就地消失；其余情况卡片仍在
      if (folderFilter && folderFilter !== folderId) removeFromList(selectedIds);
      setSelectedIds(new Set()); setMoveToFolderId('');
      showToast(`已移动到「${folderName}」`, 'success');
    } catch (e: any) { showToast(e.message || '移动失败', 'error'); }
  };

  // Folder CRUD
  const createFolder = async () => {
    if (!newFolderName.trim()) return;
    setCreating(true);
    try {
      await api.createFolder(newFolderName.trim());
      setNewFolderName(''); setShowNewFolder(false);
      showToast('文件夹已创建', 'success'); fetchFolders();
    } catch (e: any) { showToast(e.message || '创建失败', 'error'); }
    finally { setCreating(false); }
  };

  const deleteFolder = async (id: string) => {
    if (!confirm('确认删除该文件夹？文章将移至根目录。')) return;
    try {
      await api.deleteFolder(id);
      if (folderFilter === id) setFolderFilter('');
      showToast('文件夹已删除', 'success'); fetchFolders();
    } catch (e: any) { showToast(e.message || '删除失败', 'error'); }
  };

  const startEditFolder = (f: Folder) => {
    setEditingFolderId(f.id);
    setEditingFolderName(f.name);
  };

  const cancelEditFolder = () => {
    setEditingFolderId(null);
    setEditingFolderName('');
  };

  const saveEditFolder = async () => {
    if (!editingFolderId) return;
    const name = editingFolderName.trim();
    if (!name) { cancelEditFolder(); return; }
    const original = folders.find(f => f.id === editingFolderId)?.name;
    if (name === original) { cancelEditFolder(); return; }
    try {
      await api.updateFolder(editingFolderId, { name });
      cancelEditFolder();
      showToast('文件夹已重命名', 'success');
      fetchFolders();
    } catch (e: any) {
      showToast(e.message || '重命名失败', 'error');
    }
  };

  // Tag CRUD
  const createTag = async () => {
    if (!newTagName.trim()) return;
    setCreatingTag(true);
    try {
      await api.createTag(newTagName.trim(), newTagColor);
      setNewTagName(''); setShowNewTag(false); setNewTagColor(TAG_COLORS[0]);
      showToast('标签已创建', 'success'); fetchTags();
    } catch (e: any) { showToast(e.message || '创建失败', 'error'); }
    finally { setCreatingTag(false); }
  };

  const updateTag = async (id: string) => {
    if (!editTagName.trim()) return;
    setSavingTag(true);
    try {
      await api.updateTag(id, { name: editTagName.trim(), color: editTagColor });
      setEditingTag(null);
      showToast('标签已更新', 'success'); fetchTags();
    } catch (e: any) { showToast(e.message || '更新失败', 'error'); }
    finally { setSavingTag(false); }
  };

  const deleteTag = async (id: string) => {
    if (!confirm('确定删除该标签？')) return;
    try {
      await api.deleteTag(id);
      if (tagFilter === id) setTagFilter('');
      showToast('标签已删除', 'success'); fetchTags();
    } catch (e: any) { showToast(e.message || '删除失败', 'error'); }
  };

  const mergeTag = async (fromId: string, toId: string) => {
    if (!confirm('确认合并？源标签将被删除。')) return;
    try {
      await api.mergeTags(fromId, toId);
      setMergeFromTag(null);
      if (tagFilter === fromId) setTagFilter(toId);
      showToast('标签已合并', 'success'); fetchTags();
    } catch (e: any) { showToast(e.message || '合并失败', 'error'); }
  };

  const filteredTags = tags.filter(t => t.name.toLowerCase().includes(tagSearch.toLowerCase()));

  const statusTabs = [
    { value: '', label: '全部' },
    { value: 'unread', label: '未读' },
    { value: 'completed', label: '已读' },
    { value: 'favorite', label: '⭐ 收藏' },
    { value: 'archived', label: '已归档' },
  ];

  const selectedFolderName = folders.find(f => f.id === folderFilter)?.name;

  // Deduplicate historical duplicates by canonical URL, keeping the richer card.
  const dedupedArticles = useMemo(() => {
    const bestByUrl = new Map<string, Article>();
    for (const article of articles) {
      const key = normalizedArticleUrl(article.url);
      if (!key) {
        // Keep non-URL content (notes/manual text/upload) unchanged.
        bestByUrl.set(`__no_url__${article.id}`, article);
        continue;
      }
      const existing = bestByUrl.get(key);
      if (!existing) {
        bestByUrl.set(key, article);
        continue;
      }
      const scoreExisting = articleQualityScore(existing);
      const scoreCurrent = articleQualityScore(article);
      if (scoreCurrent > scoreExisting) {
        bestByUrl.set(key, article);
      } else if (scoreCurrent === scoreExisting) {
        // Tie-breaker: keep the latest updated record.
        const tExisting = new Date(existing.updated_at || existing.created_at || 0).getTime();
        const tCurrent = new Date(article.updated_at || article.created_at || 0).getTime();
        if (tCurrent > tExisting) bestByUrl.set(key, article);
      }
    }
    return Array.from(bestByUrl.values());
  }, [articles]);

  // 处理中同一集会同时产生 job 卡 + article stub 卡；保留 article 卡（信息更完整），
  // 仅当 job 尚未绑定 article（stub 还没生成的一瞬间）才用 ProcessingJobCard 兜底展示进度。
  const articleIds = useMemo(() => new Set(dedupedArticles.map(a => a.id)), [dedupedArticles]);
  const articleUrlKeys = useMemo(
    () => new Set(dedupedArticles.map(a => normalizedArticleUrl(a.url)).filter(Boolean)),
    [dedupedArticles],
  );
  const visibleJobs = useMemo(
    () => activeJobs.filter(j => {
      if (j.article_id && articleIds.has(j.article_id)) return false;
      const jobUrl = normalizedArticleUrl(j.source_url);
      if (jobUrl && articleUrlKeys.has(jobUrl)) return false;
      return true;
    }),
    [activeJobs, articleIds, articleUrlKeys],
  );

  return (
    <>
    <div className="flex h-[calc(100vh-0px)] max-w-7xl mx-auto">
      {/* Toast */}
      {toast && (
        <div className={`fixed top-20 right-8 z-50 px-5 py-3 rounded-xl shadow-lg transition-all ${
          toast.type === 'success' ? 'bg-[#34c759] text-white' : 'bg-[#ff3b30] text-white'
        }`}>{toast.message}</div>
      )}

      {/* Left Panel: Folders + Platforms + Tags (desktop) */}
      <div className={`hidden md:block border-r border-[var(--border-color)] bg-[var(--bg-primary)] transition-all duration-200 ${
        showFolderPanel ? 'w-60' : 'w-0 overflow-hidden border-r-0'
      }`}>
        <div className="p-3 h-full flex flex-col">
          {/* Tab bar */}
          <div className="flex mb-3 p-0.5 bg-[var(--bg-secondary)] rounded-lg">
            <button
              onClick={() => setActiveLeftTab('folders')}
              className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 text-xs font-medium rounded-md transition-all ${
                activeLeftTab === 'folders'
                  ? 'bg-[var(--bg-primary)] text-[var(--accent)] shadow-sm'
                  : 'text-[var(--text-tertiary)] hover:text-[var(--text-primary)]'
              }`}
            >
              <FolderKanban size={13} /> 文件夹
            </button>
            <button
              onClick={() => setActiveLeftTab('platforms')}
              className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 text-xs font-medium rounded-md transition-all ${
                activeLeftTab === 'platforms'
                  ? 'bg-[var(--bg-primary)] text-[var(--accent)] shadow-sm'
                  : 'text-[var(--text-tertiary)] hover:text-[var(--text-primary)]'
              }`}
            >
              <Globe size={13} /> 平台
            </button>
            <button
              onClick={() => setActiveLeftTab('tags')}
              className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 text-xs font-medium rounded-md transition-all ${
                activeLeftTab === 'tags'
                  ? 'bg-[var(--bg-primary)] text-[var(--accent)] shadow-sm'
                  : 'text-[var(--text-tertiary)] hover:text-[var(--text-primary)]'
              }`}
            >
              <Tag size={13} /> 标签
            </button>
          </div>

          {/* Folders Tab */}
          {activeLeftTab === 'folders' && (
            <>
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">全部文件夹</span>
                <button onClick={() => setShowNewFolder(!showNewFolder)} className="p-1 rounded hover:bg-[var(--bg-secondary)] text-[var(--text-tertiary)] hover:text-[var(--accent)] transition-colors" title="新建文件夹">
                  <Plus size={14} />
                </button>
              </div>

              {showNewFolder && (
                <div className="flex items-center gap-1 mb-2">
                  <input type="text" value={newFolderName} onChange={e => setNewFolderName(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') createFolder(); if (e.key === 'Escape') { setShowNewFolder(false); setNewFolderName(''); } }}
                    placeholder="文件夹名称..." autoFocus
                    className="flex-1 px-2 py-1.5 bg-[var(--bg-secondary)] rounded text-xs outline-none focus:ring-2 focus:ring-[var(--accent)]/20" />
                  <button onClick={createFolder} disabled={creating || !newFolderName.trim()} className="p-1 text-[var(--accent)] hover:bg-[var(--accent-light)] rounded disabled:opacity-40">
                    {creating ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
                  </button>
                  <button onClick={() => { setShowNewFolder(false); setNewFolderName(''); }} className="p-1 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] rounded">
                    <X size={12} />
                  </button>
                </div>
              )}

              <button onClick={() => setFolderFilter('')}
                className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-sm transition-colors mb-0.5 ${
                  !folderFilter ? 'bg-[var(--accent-light)] text-[var(--accent)] font-medium' : 'text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]'
                }`}>
                <LayoutGrid size={14} /> <span className="truncate flex-1 text-left">全部文章</span>
              </button>

              <div className="flex-1 overflow-y-auto mt-1 space-y-0.5">
                {folders.map(f => {
                  const isEditing = editingFolderId === f.id;
                  return (
                    <div key={f.id} className="group relative">
                      {isEditing ? (
                        <div className="flex items-center gap-1 px-2 py-1 rounded-md bg-[var(--bg-secondary)]">
                          <FolderOpen size={14} style={{ color: f.color || 'var(--accent)' }} className="shrink-0" />
                          <input
                            autoFocus
                            value={editingFolderName}
                            onChange={e => setEditingFolderName(e.target.value)}
                            onKeyDown={e => {
                              if (e.key === 'Enter') saveEditFolder();
                              if (e.key === 'Escape') cancelEditFolder();
                            }}
                            onBlur={saveEditFolder}
                            className="flex-1 min-w-0 bg-transparent text-sm outline-none text-[var(--text-primary)]"
                          />
                        </div>
                      ) : (
                        <>
                          <button onClick={() => setFolderFilter(f.id)}
                            className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-sm transition-colors pr-12 ${
                              folderFilter === f.id ? 'bg-[var(--accent-light)] text-[var(--accent)] font-medium' : 'text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]'
                            }`}>
                            <FolderOpen size={14} style={{ color: f.color || 'var(--accent)' }} />
                            <span className="truncate flex-1 text-left">{f.name}</span>
                            {folderFilter === f.id && <ChevronRight size={12} />}
                          </button>
                          <div className="absolute right-1 top-1/2 -translate-y-1/2 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                            <button onClick={() => startEditFolder(f)}
                              className="p-1 rounded hover:bg-[var(--bg-tertiary)] text-[var(--text-tertiary)] hover:text-[var(--accent)]"
                              title="重命名">
                              <Edit2 size={11} />
                            </button>
                            <button onClick={() => deleteFolder(f.id)}
                              className="p-1 rounded hover:bg-[var(--danger-light)] text-[var(--text-tertiary)] hover:text-[#ff3b30]"
                              title="删除">
                              <Trash2 size={11} />
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {/* Tags Tab */}
          {activeLeftTab === 'tags' && (
            <>
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">{tags.length} 个标签</span>
                <button onClick={() => setShowNewTag(!showNewTag)} className="p-1 rounded hover:bg-[var(--bg-secondary)] text-[var(--text-tertiary)] hover:text-[var(--accent)] transition-colors" title="新建标签">
                  <Plus size={14} />
                </button>
              </div>

              {/* Tag search + new tag form */}
              <div className="relative mb-2">
                <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]" />
                <input type="text" value={tagSearch} onChange={e => setTagSearch(e.target.value)}
                  placeholder="搜索标签..." className="w-full pl-7 pr-3 py-1.5 bg-[var(--bg-secondary)] rounded text-xs outline-none focus:ring-1 focus:ring-[var(--accent)]/20" />
              </div>

              {showNewTag && (
                <div className="mb-2 p-2 bg-[var(--bg-secondary)] rounded-lg space-y-2">
                  <input type="text" value={newTagName} onChange={e => setNewTagName(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') createTag(); if (e.key === 'Escape') { setShowNewTag(false); setNewTagName(''); } }}
                    placeholder="标签名称..." autoFocus className="w-full px-2 py-1.5 bg-[var(--bg-primary)] rounded text-xs outline-none" />
                  <div className="flex gap-1 flex-wrap">
                    {TAG_COLORS.map(c => (
                      <button key={c} onClick={() => setNewTagColor(c)}
                        className={`w-5 h-5 rounded-full border-2 transition-all ${newTagColor === c ? 'border-[var(--text-primary)] scale-110' : 'border-transparent'}`}
                        style={{ backgroundColor: c }} />
                    ))}
                  </div>
                  <div className="flex gap-1">
                    <button onClick={createTag} disabled={creatingTag || !newTagName.trim()}
                      className="flex-1 py-1 text-xs bg-[var(--accent)] text-white rounded hover:bg-[var(--accent-hover)] disabled:opacity-40">
                      {creatingTag ? <Loader2 size={12} className="animate-spin mx-auto" /> : '创建'}
                    </button>
                    <button onClick={() => { setShowNewTag(false); setNewTagName(''); }}
                      className="px-3 py-1 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)] rounded">取消</button>
                  </div>
                </div>
              )}

              <div className="flex-1 overflow-y-auto space-y-1">
                {filteredTags.map(t => (
                  <div key={t.id} className="group relative">
                    {editingTag === t.id ? (
                      <div className="p-2 bg-[var(--bg-secondary)] rounded-lg space-y-2">
                        <input type="text" value={editTagName} onChange={e => setEditTagName(e.target.value)}
                          onKeyDown={e => { if (e.key === 'Enter') updateTag(t.id); if (e.key === 'Escape') setEditingTag(null); }}
                          autoFocus className="w-full px-2 py-1 bg-[var(--bg-primary)] rounded text-xs outline-none" />
                        <div className="flex gap-1 flex-wrap">
                          {TAG_COLORS.map(c => (
                            <button key={c} onClick={() => setEditTagColor(c)}
                              className={`w-5 h-5 rounded-full border-2 ${editTagColor === c ? 'border-[var(--text-primary)] scale-110' : 'border-transparent'}`}
                              style={{ backgroundColor: c }} />
                          ))}
                        </div>
                        <div className="flex gap-1">
                          <button onClick={() => updateTag(t.id)} disabled={savingTag}
                            className="flex-1 py-1 text-xs bg-[var(--accent)] text-white rounded disabled:opacity-40">
                            {savingTag ? <Loader2 size={10} className="animate-spin mx-auto" /> : '保存'}
                          </button>
                          <button onClick={() => setEditingTag(null)} className="px-2 py-1 text-xs rounded hover:bg-[var(--bg-tertiary)]">取消</button>
                        </div>
                      </div>
                    ) : (
                      <div
                        onClick={() => {
                          setTagFilter(tagFilter === t.name ? '' : t.name);
                          if (activeLeftTab === 'tags') setShowFilters(true);
                        }}
                        className={`flex items-center gap-2 px-2 py-1.5 rounded-md text-sm cursor-pointer transition-colors pr-16 ${
                          tagFilter === t.name
                            ? 'bg-[var(--accent-light)] text-[var(--accent)] font-medium'
                            : 'text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]'
                        }`}>
                        <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: t.color || '#007aff' }} />
                        <span className="truncate flex-1">{t.name}</span>
                        {t.article_count !== undefined && (
                          <span className="text-[10px] text-[var(--text-tertiary)] bg-[var(--bg-tertiary)] px-1.5 py-0.5 rounded-full">{t.article_count}</span>
                        )}
                        {/* Hover actions */}
                        <div className="absolute right-1 top-1/2 -translate-y-1/2 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                          {mergeFromTag === t.id ? (
                            <>
                              <span className="text-[10px] text-[var(--text-tertiary)]">合并到:</span>
                              <select
                                size={1}
                                onChange={e => { if (e.target.value) mergeTag(t.id, e.target.value); setMergeFromTag(null); }}
                                className="text-[10px] bg-[var(--bg-primary)] rounded border border-[var(--border-color)] px-1 py-0.5"
                                onClick={e => e.stopPropagation()}
                              >
                                <option value="">选择...</option>
                                {tags.filter(ot => ot.id !== t.id).map(ot => (
                                  <option key={ot.id} value={ot.id}>{ot.name}</option>
                                ))}
                              </select>
                              <button onClick={e => { e.stopPropagation(); setMergeFromTag(null); }} className="p-0.5 text-[var(--text-tertiary)]">
                                <X size={10} />
                              </button>
                            </>
                          ) : (
                            <>
                              <button onClick={e => { e.stopPropagation(); setEditingTag(t.id); setEditTagName(t.name); setEditTagColor(t.color || '#007aff'); }}
                                className="p-0.5 rounded hover:bg-[var(--bg-tertiary)] text-[var(--text-tertiary)] hover:text-[var(--accent)]" title="编辑">
                                <Edit2 size={10} />
                              </button>
                              <button onClick={e => { e.stopPropagation(); setMergeFromTag(t.id); }}
                                className="p-0.5 rounded hover:bg-[var(--bg-tertiary)] text-[var(--text-tertiary)] hover:text-[var(--accent)]" title="合并">
                                <GitMerge size={10} />
                              </button>
                              <button onClick={e => { e.stopPropagation(); deleteTag(t.id); }}
                                className="p-0.5 rounded hover:bg-[var(--danger-light)] text-[var(--text-tertiary)] hover:text-[#ff3b30]" title="删除">
                                <Trash2 size={10} />
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
                {filteredTags.length === 0 && !showNewTag && (
                  <div className="text-center py-8 text-[var(--text-tertiary)] text-xs">
                    {tagSearch ? '无匹配标签' : '暂无标签'}
                  </div>
                )}
              </div>
            </>
          )}

          {/* Platforms Tab */}
          {activeLeftTab === 'platforms' && (
            <>
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">文章平台</span>
              </div>

              <button onClick={() => setSourceFilter('')}
                className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-sm transition-colors mb-0.5 ${
                  !sourceFilter ? 'bg-[var(--accent-light)] text-[var(--accent)] font-medium' : 'text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]'
                }`}>
                <LayoutGrid size={14} /> <span className="truncate flex-1 text-left">全部文章</span>
              </button>

              <div className="flex-1 overflow-y-auto mt-1 space-y-0.5">
                {platformCounts.map(pc => {
                  const active = sourceFilter === pc.platform;
                  const label = PLATFORM_LABELS[pc.platform] || pc.platform;
                  const gradient = PLATFORM_GRADIENTS[pc.platform] || PLATFORM_GRADIENTS.generic;
                  return (
                    <button key={pc.platform}
                      onClick={() => setSourceFilter(active ? '' : pc.platform)}
                      className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-sm transition-colors ${
                        active
                          ? 'bg-[var(--accent-light)] text-[var(--accent)] font-medium'
                          : 'text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]'
                      }`}
                      title={label}>
                      <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: gradient }} />
                      <span className="truncate flex-1 text-left">{label}</span>
                      <span className="text-[10px] text-[var(--text-tertiary)] bg-[var(--bg-tertiary)] px-1.5 py-0.5 rounded-full">{pc.count}</span>
                      {active && <ChevronRight size={12} className="shrink-0" />}
                    </button>
                  );
                })}
                {platformCounts.length === 0 && (
                  <div className="text-center py-8 text-[var(--text-tertiary)] text-xs">暂无平台数据</div>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Right: Main content */}
      <div ref={scrollContainerRef} className="flex-1 min-w-0 p-4 md:p-6 overflow-y-auto">
        {/* Mobile folder selector */}
        <div className="md:hidden mb-4">
          <select value={folderFilter} onChange={e => setFolderFilter(e.target.value)}
            className="w-full px-3 py-2 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-lg text-sm outline-none text-[var(--text-primary)]">
            <option value="">📁 全部文件夹</option>
            {folders.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
          </select>
        </div>

        {/* Header */}
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between mb-6 gap-4">
          <div className="flex items-center gap-3">
            <button onClick={() => setShowFolderPanel(!showFolderPanel)}
              className="hidden md:flex p-1.5 rounded-lg hover:bg-[var(--bg-secondary)] text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
              title={showFolderPanel ? '收起面板' : '展开面板'}>
              {showFolderPanel ? <PanelLeftClose size={18} /> : <PanelLeft size={18} />}
            </button>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-bold text-[var(--text-primary)]">知识库</h1>
                {selectedFolderName && (
                  <span className="flex items-center gap-1 px-2 py-0.5 bg-[var(--accent-light)] text-[var(--accent)] text-xs font-medium rounded-full">
                    <FolderOpen size={12} /> {selectedFolderName}
                  </span>
                )}
                {tagFilter && (
                  <span className="flex items-center gap-1 px-2 py-0.5 bg-[var(--accent-light)] text-[var(--accent)] text-xs font-medium rounded-full">
                    <Tag size={12} /> {tagFilter}
                  </span>
                )}
                {sourceFilter && (
                  <span className="flex items-center gap-1 px-2 py-0.5 bg-[var(--accent-light)] text-[var(--accent)] text-xs font-medium rounded-full">
                    <Globe size={12} /> {PLATFORM_LABELS[sourceFilter] || sourceFilter}
                  </span>
                )}
              </div>
              <p className="text-sm text-[var(--text-tertiary)] mt-1">{total} 篇文章</p>
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={() => setShowFilters(!showFilters)}
              className="flex items-center gap-2 px-4 py-2 text-sm border border-[var(--border-color)] rounded-lg hover:bg-[var(--bg-secondary)] transition-colors">
              <Filter size={16} /> 筛选
            </button>
          </div>
        </div>

        {/* Search & Filter Bar */}
        <div className="bg-[var(--bg-primary)] rounded-xl p-4 mb-6 border border-[var(--border-color)] space-y-4">
          <div className="relative">
            <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]" />
            <input type="text" value={search} onChange={e => setSearch(e.target.value)}
              placeholder={searchMode === 'semantic' ? '语义搜索 — 按意思匹配内容...' : '关键词搜索 — 精确匹配标题或内容...'}
              className="w-full pl-10 pr-20 py-2.5 bg-[var(--bg-secondary)] rounded-lg text-sm outline-none focus:ring-2 focus:ring-[#007aff]/20 transition-all" />
            <button
              onClick={() => { setSearchMode(m => m === 'semantic' ? 'keyword' : 'semantic'); if (search) { setPage(1); } }}
              className="absolute right-2 top-1/2 -translate-y-1/2 px-2 py-1 text-[11px] rounded-md font-medium transition-colors"
              style={{
                backgroundColor: searchMode === 'semantic' ? 'rgba(0,122,255,0.1)' : 'var(--bg-tertiary)',
                color: searchMode === 'semantic' ? 'var(--accent)' : 'var(--text-tertiary)',
              }}
              title={searchMode === 'semantic' ? '点击切换为关键词搜索' : '点击切换为语义搜索'}
            >
              {searchMode === 'semantic' ? '🧠 语义' : '🔤 关键词'}
            </button>
          </div>

          <div className="flex gap-1 p-1 bg-[var(--bg-secondary)] rounded-lg">
            {statusTabs.map(tab => (
              <button key={tab.value} onClick={() => { setStatusFilter(tab.value); setPage(1); }}
                className={`flex-1 py-2 text-sm rounded-md transition-all ${
                  statusFilter === tab.value ? 'bg-[var(--bg-primary)] text-[var(--accent)] shadow-sm font-medium' : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                }`}>{tab.label}</button>
            ))}
          </div>

          {showFilters && (
            <div className="flex flex-wrap gap-3 pt-2 border-t border-[var(--border-color)]">
              <select value={tagFilter} onChange={e => { setTagFilter(e.target.value); setPage(1); }}
                className="px-3 py-2 bg-[var(--bg-secondary)] rounded-lg text-sm outline-none text-[var(--text-primary)]">
                <option value="">所有标签</option>
                {tags.map(t => <option key={t.id} value={t.name}>{t.name}</option>)}
              </select>
              <select value={sourceFilter} onChange={e => { setSourceFilter(e.target.value); setPage(1); }}
                className="px-3 py-2 bg-[var(--bg-secondary)] rounded-lg text-sm outline-none text-[var(--text-primary)]">
                <option value="">全部来源</option>
                {platformCounts.map(pc => (
                  <option key={pc.platform} value={pc.platform}>{PLATFORM_LABELS[pc.platform] || pc.platform}</option>
                ))}
              </select>
              {(tagFilter || sourceFilter) && (
                <button onClick={() => { setTagFilter(''); setSourceFilter(''); setPage(1); }}
                  className="px-3 py-2 text-sm text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)] rounded-lg transition-colors flex items-center gap-1">
                  <X size={14} /> 清除筛选
                </button>
              )}
            </div>
          )}
        </div>

        {/* Batch Actions */}
        {selectedIds.size > 0 && (
          <div className="flex items-center gap-3 mb-4 p-3 bg-[var(--accent-light)] rounded-xl">
            <span className="text-sm font-medium text-[var(--accent)]">已选 {selectedIds.size} 篇</span>
            <button onClick={batchArchive} className="px-3 py-1.5 text-xs bg-[var(--bg-primary)] rounded-lg hover:shadow-sm">归档</button>
            <div className="relative">
              <button
                onClick={() => setMoveToFolderId(moveToFolderId ? '' : '__open__')}
                className="px-3 py-1.5 text-xs bg-[var(--accent)] text-white rounded-lg hover:bg-[var(--accent-hover)] flex items-center gap-1"
              >
                <FolderOpen size={13} /> 移动到
              </button>
              {moveToFolderId === '__open__' && (
                <div className="absolute top-full mt-1 left-0 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-lg shadow-lg z-20 py-1 min-w-[160px] max-h-48 overflow-y-auto">
                  <button
                    onClick={() => { batchMoveToFolder(''); }}
                    className="w-full text-left px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]"
                  >📁 根目录（无文件夹）</button>
                  {folders.map(f => (
                    <button
                      key={f.id}
                      onClick={() => batchMoveToFolder(f.id)}
                      className="w-full text-left px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)] flex items-center gap-1.5"
                    >
                      <FolderOpen size={12} style={{ color: f.color || 'var(--accent)' }} />
                      {f.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button onClick={batchDelete} className="px-3 py-1.5 text-xs bg-[#ff3b30] text-white rounded-lg hover:bg-[#e0352b]">删除</button>
            <button onClick={() => setSelectedIds(new Set())} className="ml-auto text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)]"><X size={16} /></button>
          </div>
        )}

        {/* Article Grid */}
        {loading ? (
          <div className="columns-1 sm:columns-2 lg:columns-3 gap-4">
            {Array.from({ length: 9 }).map((_, i) => (
              <div key={i} className="break-inside-avoid mb-4 bg-[var(--bg-primary)] rounded-xl border border-[var(--border-color)] overflow-hidden animate-pulse">
                <div className="h-36 bg-[var(--bg-secondary)]" />
                <div className="p-4 space-y-2">
                  <div className="h-3 bg-[var(--bg-secondary)] rounded w-16" />
                  <div className="h-4 bg-[var(--bg-secondary)] rounded w-3/4" />
                  <div className="h-4 bg-[var(--bg-secondary)] rounded w-2/3" />
                  <div className="flex gap-2">
                    <div className="h-5 bg-[var(--bg-secondary)] rounded-full w-14" />
                    <div className="h-5 bg-[var(--bg-secondary)] rounded-full w-14" />
                  </div>
                  <div className="h-3 bg-[var(--bg-secondary)] rounded w-1/3" />
                </div>
              </div>
            ))}
          </div>
        ) : error ? (
          <div className="text-center py-16">
            <p className="text-[#ff3b30] mb-4">{error}</p>
            <button onClick={() => fetchArticles()} className="px-6 py-2 bg-[var(--accent)] text-white rounded-lg hover:bg-[var(--accent-hover)]">重试</button>
          </div>
        ) : articles.length === 0 && visibleJobs.length === 0 ? (
          <div className="text-center py-16">
            <div className="w-20 h-20 mx-auto mb-4 rounded-2xl bg-[var(--bg-secondary)] flex items-center justify-center">
              <LayoutGrid size={32} className="text-[var(--text-tertiary)]" />
            </div>
            <p className="text-[var(--text-secondary)] text-lg mb-2">{folderFilter ? `「${selectedFolderName}」文件夹为空` : '还没有文章'}</p>
            <p className="text-[var(--text-tertiary)] text-sm">{folderFilter ? '在知识库中为文章分配到此文件夹' : '粘贴文章链接开始构建你的知识库'}</p>
          </div>
        ) : (
          <>
            <div className="columns-1 sm:columns-2 lg:columns-3 gap-4">
              {visibleJobs.map(job => (
                <div key={job.job_id} className="break-inside-avoid mb-4">
                  <ProcessingJobCard job={job} />
                </div>
              ))}
              {dedupedArticles.map(article => (
                <div key={article.id} className="break-inside-avoid mb-4 relative group">
                  <div className="absolute top-3 left-3 z-10">
                    <button onClick={(e) => { e.preventDefault(); toggleSelect(article.id); }}
                      className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-all ${
                        selectedIds.has(article.id) ? 'bg-[var(--accent)] border-[#007aff]' : 'border-[#aeaeb2] opacity-0 group-hover:opacity-100'
                      }`}>
                      {selectedIds.has(article.id) && <Check size={12} className="text-white" />}
                    </button>
                  </div>
                  <ArticleCard article={article} />
                </div>
              ))}
            </div>
            {/* 无限滚动：哨兵进入视口自动加载下一页 */}
            <div ref={sentinelRef} className="h-px" />
            {loadingMore && (
              <div className="flex justify-center py-6">
                <Loader2 size={20} className="animate-spin text-[var(--text-tertiary)]" />
              </div>
            )}
            {!hasMore && total > PAGE_SIZE && (
              <div className="text-center py-6 text-xs text-[var(--text-tertiary)]">已经到底啦</div>
            )}
          </>
        )}
      </div>
    </div>
    <AddContentModal onSuccess={() => fetchArticles()} />
    </>
  );
}