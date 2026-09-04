'use client';

import React, { useCallback } from 'react';
import { Clock, Star, Loader2, Hourglass, XCircle, Headphones, FileText } from 'lucide-react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import type { Article } from '@/lib/types';

interface ArticleCardProps {
  article: Article;
}

const PLATFORM_LABELS: Record<string, string> = {
  wechat: '微信公众号', bilibili: 'B 站', xiaoyuzhou: '小宇宙',
  xhs: '小红书', douyin: '抖音', youtube: 'YouTube',
  toutiao: '今日头条', juejin: '掘金', csdn: 'CSDN',
  feishu: '飞书', upload: '上传文件', generic: '网页', note: '笔记',
};

const PLATFORM_GRADIENTS: Record<string, string> = {
  xiaoyuzhou: 'linear-gradient(135deg, #ff9500 0%, #e07800 100%)',
  bilibili:   'linear-gradient(135deg, #fb7299 0%, #e0507a 100%)',
  wechat:     'linear-gradient(135deg, #34c759 0%, #22a344 100%)',
  youtube:    'linear-gradient(135deg, #ff3b30 0%, #c0392b 100%)',
  xhs:        'linear-gradient(135deg, #ff2d55 0%, #cc1f44 100%)',
  douyin:     'linear-gradient(135deg, #444 0%, #111 100%)',
  feishu:     'linear-gradient(135deg, #3370ff 0%, #1a53cc 100%)',
  note:       'linear-gradient(135deg, #5856d6 0%, #3a38b0 100%)',
  upload:     'linear-gradient(135deg, #8e8e93 0%, #636366 100%)',
  juejin:     'linear-gradient(135deg, #007fff 0%, #0055cc 100%)',
  generic:    'linear-gradient(135deg, #007aff 0%, #0055cc 100%)',
};

function formatPublishedDate(dateStr?: string): string {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr;
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

export default function ArticleCard({ article }: ArticleCardProps) {
  const router = useRouter();

  const handleTagClick = useCallback(
    (e: React.MouseEvent, tagName: string) => {
      e.preventDefault();
      e.stopPropagation();
      router.push(`/library?tag=${encodeURIComponent(tagName)}`);
    },
    [router]
  );

  const platform = article.source_platform || 'generic';
  const isAudio = article.content_type === 'audio';
  const gradient = PLATFORM_GRADIENTS[platform] || PLATFORM_GRADIENTS.generic;
  const initial = (PLATFORM_LABELS[platform] || platform).charAt(0).toUpperCase();

  return (
    <Link
      href={`/read/${article.id}`}
      className="block bg-[var(--bg-primary)] rounded-xl border border-[var(--border-color)] overflow-hidden hover:border-[var(--accent)]/30 hover:shadow-lg transition-all duration-200 group"
    >
      {/* Cover image — natural aspect ratio; gradient placeholder keeps a fixed height */}
      {article.cover_image ? (
        <div className="relative w-full overflow-hidden">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={article.cover_image}
            alt=""
            className="w-full h-auto block group-hover:scale-105 transition-transform duration-300"
          />
          {article.is_favorited && (
            <span className="absolute top-2.5 right-2.5 flex items-center justify-center w-6 h-6 rounded-full bg-black/30 backdrop-blur-sm">
              <Star size={13} className="fill-[var(--warning)] text-[var(--warning)]" />
            </span>
          )}
        </div>
      ) : (
        <div
          className="relative h-36 w-full overflow-hidden flex items-center justify-center"
          style={{ background: gradient }}
        >
          <span className="text-6xl font-bold text-white/20 select-none">{initial}</span>
          {article.is_favorited && (
            <span className="absolute top-2.5 right-2.5 flex items-center justify-center w-6 h-6 rounded-full bg-black/30 backdrop-blur-sm">
              <Star size={13} className="fill-[var(--warning)] text-[var(--warning)]" />
            </span>
          )}
        </div>
      )}

      {/* Info section */}
      <div className="p-4 space-y-2">
        {/* Platform + content type */}
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-[var(--text-tertiary)]">
            {PLATFORM_LABELS[platform] || platform}
          </span>
          {isAudio
            ? <Headphones size={12} className="text-[var(--text-tertiary)]" />
            : <FileText size={12} className="text-[var(--text-tertiary)]" />
          }
          {article.published_at && (
            <span className="text-xs text-[var(--text-tertiary)] ml-auto shrink-0">
              {formatPublishedDate(article.published_at)}
            </span>
          )}
        </div>

        {/* Title */}
        <h3 className="font-semibold text-sm leading-snug text-[var(--text-primary)] group-hover:text-[var(--accent)] transition-colors line-clamp-2">
          {article.title}
        </h3>

        {/* Summary / status */}
        {article.fetch_status === 'pending_agent' ? (
          <div className="flex items-center gap-1.5 text-xs text-[var(--accent)] bg-[var(--accent-light)] px-2.5 py-1.5 rounded-md w-fit">
            <Hourglass size={12} className="animate-pulse" />
            <span>等待本地代采…</span>
          </div>
        ) : article.fetch_status === 'failed' ? (
          <div className="flex items-center gap-1.5 text-xs text-[var(--danger,#ef4444)] bg-[var(--danger-light,rgba(239,68,68,0.1))] px-2.5 py-1.5 rounded-md w-fit">
            <XCircle size={12} />
            <span>代采失败</span>
          </div>
        ) : article.summary ? (
          <p className="text-xs text-[var(--text-secondary)] line-clamp-2">
            {article.summary}
          </p>
        ) : article.content_type !== 'note' && (
          <div className="flex items-center gap-1.5 text-xs text-[var(--accent)] bg-[var(--accent-light)] px-2.5 py-1.5 rounded-md w-fit">
            <Loader2 size={12} className="animate-spin" />
            <span>AI 正在处理摘要…</span>
          </div>
        )}

        {/* Tags */}
        {article.tags && article.tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {article.tags.slice(0, 4).map((tag) => (
              <span
                key={tag.id}
                onClick={(e) => handleTagClick(e, tag.name)}
                className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium cursor-pointer hover:opacity-80 transition-opacity"
                style={{ backgroundColor: tag.color + '18', color: tag.color }}
              >
                {tag.name}
              </span>
            ))}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center gap-3 text-xs text-[var(--text-tertiary)] pt-0.5">
          {article.author && (
            <span className="truncate max-w-[140px]">{article.author}</span>
          )}
          <span className="flex items-center gap-1 shrink-0">
            <Clock size={11} />
            {article.reading_time || 1}min
          </span>
        </div>
      </div>
    </Link>
  );
}
