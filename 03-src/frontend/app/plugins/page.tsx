'use client';

import React, { useState, useEffect, useCallback } from 'react';
import {
  RefreshCw, Loader2, Play, Square, RotateCw,
  AlertCircle, CheckCircle2, Cpu, Plug, Power, PowerOff,
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';

interface PluginInfo {
  id: string;
  name: string;
  description: string;
  version: string;
  kind: 'process' | 'api';
  status: string;
  config_ready: boolean;
  auto_start: boolean;
  detail: string;
  health: Record<string, unknown>;
}

const STATUS_META: Record<string, { label: string; dot: string; badge: string }> = {
  running: { label: '运行中', dot: 'bg-green-500', badge: 'bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400' },
  enabled: { label: '已启用', dot: 'bg-green-500', badge: 'bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400' },
  stopped: { label: '已停止', dot: 'bg-gray-400', badge: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
  disabled: { label: '已停用', dot: 'bg-gray-400', badge: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
  not_configured: { label: '未配置', dot: 'bg-amber-500', badge: 'bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400' },
  error: { label: '异常', dot: 'bg-red-500', badge: 'bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400' },
};

/** 插件管理 API 需要超管权限，走带 Bearer token 的裸 fetch（与 settings 页同源模式）。 */
function authHeaders(): Record<string, string> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('inFlow_token') : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export default function PluginsPage() {
  const { isSuperAdmin } = useAuth();
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);

  const showMessage = (text: string, ok: boolean) => {
    setMessage({ text, ok });
    setTimeout(() => setMessage(null), 4000);
  };

  const fetchPlugins = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/plugins', { headers: authHeaders() });
      if (!res.ok) {
        const d = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(typeof d.detail === 'string' ? d.detail : `HTTP ${res.status}`);
      }
      setPlugins(await res.json());
    } catch (e: any) {
      setError(e.message || '加载插件列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPlugins();
  }, [fetchPlugins]);

  const act = async (id: string, action: 'start' | 'stop' | 'restart') => {
    setActing(prev => ({ ...prev, [id]: action }));
    setMessage(null);
    try {
      const res = await fetch(`/api/plugins/${id}/${action}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(typeof d.detail === 'string' ? d.detail : `HTTP ${res.status}`);
      }
      const updated = await res.json();
      setPlugins(prev => prev.map(p => (p.id === id ? updated : p)));
      const actionLabel: Record<string, string> = { start: '启动', stop: '停止', restart: '重启' };
      const ok = updated.started || updated.stopped || updated.restarted;
      showMessage(`「${updated.name}」${actionLabel[action]}${ok ? '成功' : '失败'}`, !!ok);
    } catch (e: any) {
      showMessage(e.message || '操作失败', false);
    } finally {
      setActing(prev => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
    }
  };

  /** 根据状态决定可用操作按钮 */
  const renderActions = (p: PluginInfo) => {
    const busy = acting[p.id];
    if (p.kind === 'api') {
      const enabled = p.status === 'enabled';
      return (
        <button
          onClick={() => act(p.id, enabled ? 'stop' : 'start')}
          disabled={!!busy}
          className={`inline-flex items-center gap-2 text-sm px-4 py-2 rounded-lg transition-colors disabled:opacity-50 ${
            enabled
              ? 'border border-[var(--border-color)] hover:bg-[var(--bg-tertiary)] text-[var(--text-secondary)]'
              : 'bg-[var(--accent)] text-white hover:opacity-90'
          }`}
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : enabled ? <PowerOff size={14} /> : <Power size={14} />}
          {enabled ? '停用' : '启用'}
        </button>
      );
    }
    // process
    if (p.status === 'not_configured') {
      return (
        <span className="text-xs text-[var(--text-tertiary)] flex items-center gap-1.5">
          <AlertCircle size={13} />
          缺少配置，无法启动
        </span>
      );
    }
    const running = p.status === 'running';
    return (
      <div className="flex items-center gap-2">
        {running ? (
          <button
            onClick={() => act(p.id, 'stop')}
            disabled={!!busy}
            className="inline-flex items-center gap-2 text-sm px-4 py-2 rounded-lg border border-[var(--border-color)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] disabled:opacity-50 transition-colors"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Square size={14} />}
            停止
          </button>
        ) : (
          <button
            onClick={() => act(p.id, 'start')}
            disabled={!!busy}
            className="inline-flex items-center gap-2 text-sm px-4 py-2 rounded-lg bg-[var(--accent)] text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            启动
          </button>
        )}
        <button
          onClick={() => act(p.id, 'restart')}
          disabled={!!busy}
          className="inline-flex items-center gap-2 text-sm px-3 py-2 rounded-lg border border-[var(--border-color)] text-[var(--text-tertiary)] hover:bg-[var(--bg-tertiary)] disabled:opacity-50 transition-colors"
          title="重启"
        >
          <RotateCw size={14} />
        </button>
      </div>
    );
  };

  const renderHealth = (p: PluginInfo) => {
    const h = p.health || {};
    const rows: { k: string; v: string }[] = [];
    if (typeof h.pid === 'number') rows.push({ k: 'PID', v: String(h.pid) });
    if (typeof h.accounts === 'number') rows.push({ k: '绑定账号', v: String(h.accounts) });
    if (typeof h.articles === 'number') rows.push({ k: '文章数', v: String(h.articles) });
    if (!rows.length) return null;
    return (
      <div className="flex flex-wrap gap-x-4 gap-y-1 pt-3 mt-3 border-t border-[var(--border-color)] text-xs text-[var(--text-tertiary)]">
        {rows.map(r => (
          <span key={r.k}>{r.k}：<span className="font-mono text-[var(--text-secondary)]">{r.v}</span></span>
        ))}
      </div>
    );
  };

  return (
    <div className="p-6 md:p-8 max-w-4xl mx-auto space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">插件管理</h1>
          <p className="text-sm text-[var(--text-tertiary)] mt-1">
            管理外部协同能力（进程型 Bot / API 型同步）的启停与状态
          </p>
        </div>
        <button
          onClick={fetchPlugins}
          disabled={loading}
          className="inline-flex items-center gap-2 text-sm px-3 py-1.5 rounded-lg border border-[var(--border-color)] hover:bg-[var(--bg-tertiary)] disabled:opacity-50"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
      </div>

      {message && (
        <div className={`p-3 rounded-lg flex items-center gap-2 text-sm ${
          message.ok
            ? 'bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400'
            : 'bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400'
        }`}>
          {message.ok ? <CheckCircle2 className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
          {message.text}
        </div>
      )}

      {!isSuperAdmin && !loading && !error && (
        <div className="p-4 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 text-sm flex items-center gap-2">
          <AlertCircle className="w-4 h-4" />
          仅超级管理员可管理插件
        </div>
      )}

      {loading ? (
        <div className="text-center py-16 text-[var(--text-tertiary)] text-sm">
          <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2" />
          正在加载插件列表...
        </div>
      ) : error ? (
        <div className="p-4 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 text-sm flex items-center gap-2">
          <AlertCircle className="w-4 h-4" />
          加载失败：{error}
        </div>
      ) : plugins.length === 0 ? (
        <div className="text-center py-16 text-[var(--text-tertiary)] text-sm">
          暂无插件
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {plugins.map(p => {
            const st = STATUS_META[p.status] || STATUS_META.error;
            return (
              <div
                key={p.id}
                className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] p-5 space-y-3"
              >
                {/* Header */}
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <div className="w-9 h-9 rounded-lg bg-[var(--bg-secondary)] flex items-center justify-center shrink-0">
                      {p.kind === 'process'
                        ? <Cpu size={18} className="text-blue-500" />
                        : <Plug size={18} className="text-purple-500" />}
                    </div>
                    <div className="min-w-0">
                      <h3 className="font-semibold text-[var(--text-primary)] truncate">{p.name}</h3>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-[var(--bg-tertiary)] text-[var(--text-tertiary)]">
                          {p.kind === 'process' ? '进程型' : 'API 型'}
                        </span>
                        <span className="text-[10px] text-[var(--text-tertiary)]">v{p.version}</span>
                        {p.auto_start && (
                          <span className="text-[10px] text-[var(--text-tertiary)]">自动启动</span>
                        )}
                      </div>
                    </div>
                  </div>
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap ${st.badge}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${st.dot}`} />
                    {st.label}
                  </span>
                </div>

                {/* Description */}
                <p className="text-sm text-[var(--text-secondary)]">{p.description}</p>

                {/* Detail (not_configured reason etc.) */}
                {p.detail && (
                  <p className="text-xs text-amber-600 dark:text-amber-400 flex items-center gap-1.5">
                    <AlertCircle size={12} />
                    {p.detail}
                  </p>
                )}

                {/* Health */}
                {renderHealth(p)}

                {/* Actions */}
                <div className="pt-1">
                  {renderActions(p)}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="text-center text-xs text-[var(--text-tertiary)] py-4">
        inFlow AI v1.2
      </div>
    </div>
  );
}
