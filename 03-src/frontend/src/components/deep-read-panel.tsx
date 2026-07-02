'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import cardThemesData from '@/lib/card-themes.json';
import { api } from '@/lib/api';
import type { CardThemesResponse } from '@/lib/types';

interface DeepReadPanelProps {
  articleId: string;
  html: string;
}

const CAT_EMOJI: Record<string, string> = {
  '极简': '○',
  '精致': '✦',
  '醒目': '◆',
  '聚焦': '◎',
  '媒体': '⬡',
  '温暖': '☀',
  '艺术': '◬',
  '品牌': '◉',
};

const FONT_SIZES = [14, 15, 16] as const;

/** Strip legacy in-HTML toolbar if present (Card HTML itself stays unchanged on disk). */
function stripEmbeddedToolbar(html: string): string {
  return html
    .replace(/<div id="card-toolbar">[\s\S]*?<\/div>\s*/i, '')
    .replace(/<!-- card-toolbar:[\s\S]*?<\/script>\s*/gi, '')
    .replace(/body\s*\{\s*padding-top:\s*76px\s*!important;\s*\}/g, '');
}

function cleanupIframeDoc(doc: Document): void {
  doc.getElementById('card-toolbar')?.remove();
  if (doc.body) {
    doc.body.style.paddingTop = '';
  }
}

function applyThemeToDoc(doc: Document, vars: Record<string, string>, slug: string): void {
  const root = doc.documentElement;
  Object.entries(vars).forEach(([key, value]) => {
    root.style.setProperty(key, value);
  });
  if (doc.body) {
    doc.body.dataset.theme = slug;
  }
}

function serializeIframeHtml(doc: Document): string {
  const dt = doc.doctype;
  const doctype = dt
    ? `<!DOCTYPE ${dt.name}>`
    : '<!DOCTYPE html>';
  return `${doctype}\n${doc.documentElement.outerHTML}`;
}

const CARD_THEMES = cardThemesData as CardThemesResponse;

export function DeepReadPanel({ articleId, html }: DeepReadPanelProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const themes = CARD_THEMES;
  const [currentTheme, setCurrentTheme] = useState('newspaper');
  /** 用户点击分类后才展开具体样式行；默认 null 不显示 */
  const [expandedCat, setExpandedCat] = useState<string | null>(null);
  const [fontSize, setFontSize] = useState<number>(15);
  const [viewport, setViewport] = useState<'mobile' | 'pc'>('mobile');
  const [exporting, setExporting] = useState(false);

  const cleanHtml = useMemo(() => stripEmbeddedToolbar(html), [html]);

  useEffect(() => {
    setExpandedCat(null);
  }, [html]);

  const resizeIframe = useCallback(() => {
    const iframe = iframeRef.current;
    const doc = iframe?.contentDocument;
    if (!iframe || !doc) return;
    const h = doc.documentElement?.scrollHeight ?? doc.body?.scrollHeight ?? 0;
    if (h > 0) iframe.style.height = `${h + 32}px`;
  }, []);

  const applyTheme = useCallback(
    (slug: string) => {
      const doc = iframeRef.current?.contentDocument;
      const theme = themes.themes[slug];
      if (!doc || !theme) return;
      applyThemeToDoc(doc, theme.vars, slug);
      setCurrentTheme(slug);
      requestAnimationFrame(resizeIframe);
    },
    [themes, resizeIframe],
  );

  const applyFontSize = useCallback((size: number) => {
    const doc = iframeRef.current?.contentDocument;
    if (doc?.body) doc.body.style.fontSize = `${size}px`;
    setFontSize(size);
    requestAnimationFrame(resizeIframe);
  }, [resizeIframe]);

  const applyViewport = useCallback((mode: 'mobile' | 'pc') => {
    const doc = iframeRef.current?.contentDocument;
    if (doc?.body) {
      doc.body.classList.toggle('vp-mobile', mode === 'mobile');
      doc.body.classList.toggle('vp-pc', mode === 'pc');
    }
    setViewport(mode);
    requestAnimationFrame(resizeIframe);
  }, [resizeIframe]);

  const handleIframeLoad = useCallback(() => {
    const doc = iframeRef.current?.contentDocument;
    if (!doc) return;

    cleanupIframeDoc(doc);

    const initialSlug = doc.body?.dataset.theme || 'newspaper';
    const themeEntry = themes.themes[initialSlug];
    if (themeEntry) {
      applyThemeToDoc(doc, themeEntry.vars, initialSlug);
      setCurrentTheme(initialSlug);
    } else if (themes.themes.newspaper) {
      applyThemeToDoc(doc, themes.themes.newspaper.vars, themes.themes.newspaper.slug);
      setCurrentTheme(themes.themes.newspaper.slug);
    }

    doc.body.style.fontSize = `${fontSize}px`;
    doc.body.classList.add(viewport === 'mobile' ? 'vp-mobile' : 'vp-pc');

    resizeIframe();
  }, [themes, fontSize, viewport, resizeIframe]);

  useEffect(() => {
    if (iframeRef.current?.contentDocument) {
      handleIframeLoad();
    }
  }, [handleIframeLoad]);

  const handleCategoryClick = (catKey: string) => {
    if (expandedCat === catKey) {
      setExpandedCat(null);
      return;
    }
    setExpandedCat(catKey);
    const first = Object.values(themes.themes).find((t) => t.category === catKey);
    if (first) applyTheme(first.slug);
  };

  const handleExport = async () => {
    const doc = iframeRef.current?.contentDocument;
    if (!doc?.body || exporting) return;
    setExporting(true);
    try {
      await doc.fonts.ready;
      const blob = await api.captureArticleDeepReadScreenshot(
        articleId,
        serializeIframeHtml(doc),
      );
      const link = document.createElement('a');
      link.download = `inFlow-card-${currentTheme}.png`;
      link.href = URL.createObjectURL(blob);
      link.click();
      URL.revokeObjectURL(link.href);
    } catch {
      /* ignore */
    } finally {
      setExporting(false);
    }
  };

  const activeAccent = themes.themes[currentTheme]?.vars['--theme-accent'] ?? '#4B6EF5';
  const categoryThemes = expandedCat
    ? Object.values(themes.themes).filter((t) => t.category === expandedCat)
    : [];

  return (
    <div className="space-y-0">
      {/* Toolbar — sticky within AI精读 tab, below page top bar (h-12) */}
      <div
        id="card-toolbar"
        className="sticky top-12 z-20 -mx-4 sm:-mx-6 mb-4 bg-white border border-[#e8e8e8] rounded-xl shadow-sm overflow-hidden"
        style={{ fontFamily: "-apple-system, BlinkMacSystemFont, 'PingFang SC', 'Segoe UI', sans-serif" }}
      >
        <div className="flex items-center gap-1.5 px-2.5 sm:px-3 py-1.5 flex-wrap">
          <span className="font-bold text-[11px] tracking-wide text-[#bfa050] mr-1 shrink-0">THEMES</span>
          <div className="flex gap-1 flex-wrap flex-1 min-w-0">
            {themes.categories.map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => handleCategoryClick(cat)}
                className={`px-2 py-0.5 rounded-xl border text-[11px] whitespace-nowrap transition-colors ${
                  expandedCat === cat
                    ? 'bg-[#1a1a1a] text-white border-[#1a1a1a]'
                    : 'bg-white text-[#666] border-[#e0e0e0] hover:bg-[#f5f5f5]'
                }`}
              >
                {CAT_EMOJI[cat] ?? '·'} {cat}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1.5 ml-auto shrink-0">
            <div className="flex gap-0.5">
              {FONT_SIZES.map((sz) => (
                <button
                  key={sz}
                  type="button"
                  onClick={() => applyFontSize(sz)}
                  className={`px-1.5 py-0.5 rounded border text-[10px] leading-snug transition-colors ${
                    fontSize === sz
                      ? 'bg-[#1a1a1a] text-white border-[#1a1a1a]'
                      : 'bg-white text-[#555] border-[#ddd] hover:bg-[#f5f5f5]'
                  }`}
                >
                  {sz === 14 ? 'A-' : sz === 16 ? 'A+' : 'A'}
                </button>
              ))}
            </div>
            <div className="flex gap-0.5">
              <button
                type="button"
                title="移动端 750px"
                onClick={() => applyViewport('mobile')}
                className={`px-1.5 py-0.5 rounded border text-xs leading-snug transition-colors ${
                  viewport === 'mobile'
                    ? 'bg-[#1a1a1a] border-[#1a1a1a]'
                    : 'bg-white border-[#ddd] hover:bg-[#f5f5f5]'
                }`}
              >
                📱
              </button>
              <button
                type="button"
                title="PC 1080px"
                onClick={() => applyViewport('pc')}
                className={`px-1.5 py-0.5 rounded border text-xs leading-snug transition-colors ${
                  viewport === 'pc'
                    ? 'bg-[#1a1a1a] border-[#1a1a1a]'
                    : 'bg-white border-[#ddd] hover:bg-[#f5f5f5]'
                }`}
              >
                💻
              </button>
            </div>
            <button
              type="button"
              onClick={handleExport}
              disabled={exporting}
              className="px-2.5 py-1 rounded-md text-[11px] font-semibold text-white whitespace-nowrap disabled:opacity-50"
              style={{ background: 'linear-gradient(135deg, #bfa050, #d4b87a)' }}
            >
              {exporting ? '生成中…' : '📷 截图'}
            </button>
          </div>
        </div>
        {expandedCat && categoryThemes.length > 0 && (
          <div className="flex items-center gap-1 px-2.5 sm:px-3 py-1.5 flex-wrap bg-[#fafafa] border-t border-[#f0f0f0]">
            {categoryThemes.map((t) => (
              <button
                key={t.slug}
                type="button"
                title={t.description}
                onClick={() => applyTheme(t.slug)}
                className={`px-2 py-0.5 rounded-[10px] border text-[11px] whitespace-nowrap transition-colors ${
                  currentTheme === t.slug ? 'font-semibold' : 'text-[#555] border-[#e0e0e0] bg-white hover:bg-[#f0f0f0]'
                }`}
                style={
                  currentTheme === t.slug
                    ? {
                        borderColor: activeAccent,
                        color: activeAccent,
                        background: `color-mix(in srgb, ${activeAccent} 8%, white)`,
                      }
                    : undefined
                }
              >
                {t.name}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Card iframe */}
      <div
        className={`mx-auto transition-[max-width] duration-200 ${
          viewport === 'mobile' ? 'max-w-[750px]' : 'max-w-[1080px]'
        }`}
      >
        <iframe
          ref={iframeRef}
          title="AI 精读"
          srcDoc={cleanHtml}
          sandbox="allow-scripts allow-same-origin"
          className="w-full border-0 rounded-2xl bg-white shadow-sm"
          style={{ minHeight: '60vh' }}
          onLoad={handleIframeLoad}
        />
      </div>
    </div>
  );
}
