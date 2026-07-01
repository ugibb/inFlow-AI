'use client';

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import type { User, LoginResponse } from '@/lib/types';

// ─── Types ─────────────────────────────────────────────────────────────────

interface AuthContextType {
  user: User | null;
  token: string | null;
  loading: boolean;
  isAuthenticated: boolean;
  isSuperAdmin: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const TOKEN_KEY = 'trove_token';
const ME_VALIDATE_RETRIES = 5;
const ME_VALIDATE_RETRY_MS = 1500;

interface JwtPayload {
  sub?: string;
  username?: string;
  is_super_admin?: boolean;
  exp?: number;
}

/** 后端暂不可达时，从 JWT 解析基础用户信息（不验签，仅作降级展示） */
function userFromToken(token: string): User | null {
  try {
    const part = token.split('.')[1];
    if (!part) return null;
    const payload = JSON.parse(
      atob(part.replace(/-/g, '+').replace(/_/g, '/')),
    ) as JwtPayload;
    if (!payload.sub || !payload.username) return null;
    if (payload.exp && payload.exp * 1000 < Date.now()) return null;
    return {
      id: payload.sub,
      username: payload.username,
      is_super_admin: payload.is_super_admin ?? false,
      is_active: true,
      created_at: '',
      updated_at: '',
    };
  } catch {
    return null;
  }
}

async function fetchCurrentUser(
  storedToken: string,
): Promise<{ status: 'ok'; user: User } | { status: 'invalid' } | { status: 'unreachable' }> {
  for (let attempt = 0; attempt < ME_VALIDATE_RETRIES; attempt++) {
    try {
      const res = await fetch('/api/auth/me', {
        headers: { Authorization: `Bearer ${storedToken}` },
      });
      if (res.status === 401 || res.status === 403) {
        return { status: 'invalid' };
      }
      if (res.ok) {
        const user: User = await res.json();
        return { status: 'ok', user };
      }
    } catch {
      // 网络错误或后端未就绪 — 重试
    }
    if (attempt < ME_VALIDATE_RETRIES - 1) {
      await new Promise((r) => setTimeout(r, ME_VALIDATE_RETRY_MS));
    }
  }
  return { status: 'unreachable' };
}

// ─── Context ───────────────────────────────────────────────────────────────

const AuthContext = createContext<AuthContextType>({
  user: null,
  token: null,
  loading: true,
  isAuthenticated: false,
  isSuperAdmin: false,
  login: async () => {},
  logout: () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

// ─── Provider ──────────────────────────────────────────────────────────────

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // ── Validate token on mount ──────────────────────────────────────────

  useEffect(() => {
    let cancelled = false;

    async function validateOnMount() {
      const storedToken = localStorage.getItem(TOKEN_KEY);
      if (!storedToken) {
        setLoading(false);
        return;
      }

      const result = await fetchCurrentUser(storedToken);
      if (cancelled) return;

      if (result.status === 'invalid') {
        localStorage.removeItem(TOKEN_KEY);
        setToken(null);
        setUser(null);
      } else if (result.status === 'ok') {
        setToken(storedToken);
        setUser(result.user);
      } else {
        // 后端暂不可达（如重启中）：保留 token，用 JWT 降级恢复登录态
        const fallbackUser = userFromToken(storedToken);
        if (fallbackUser) {
          setToken(storedToken);
          setUser(fallbackUser);
        } else {
          localStorage.removeItem(TOKEN_KEY);
          setToken(null);
          setUser(null);
        }
      }
      setLoading(false);
    }

    validateOnMount();
    return () => {
      cancelled = true;
    };
  }, []);

  // ── Login ────────────────────────────────────────────────────────────

  const login = useCallback(async (username: string, password: string) => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000); // 15s timeout

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
        signal: controller.signal,
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({ detail: '登录失败' }));
        throw new Error(errData.detail || '登录失败');
      }

      const data: LoginResponse = await res.json();
      localStorage.setItem(TOKEN_KEY, data.access_token);
      setToken(data.access_token);
      setUser(data.user);
    } catch (err: any) {
      if (err.name === 'AbortError') {
        throw new Error('请求超时，请检查网络连接或稍后重试');
      }
      throw err;
    } finally {
      clearTimeout(timeout);
    }
  }, []);

  // ── Logout ───────────────────────────────────────────────────────────

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
  }, []);

  // ── Derived state ────────────────────────────────────────────────────

  const isAuthenticated = !!token && !!user;
  const isSuperAdmin = user?.is_super_admin ?? false;

  // ── Value ────────────────────────────────────────────────────────────

  const value: AuthContextType = {
    user,
    token,
    loading,
    isAuthenticated,
    isSuperAdmin,
    login,
    logout,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}
