import { BASE_URL, REQUEST_TIMEOUT } from '../config/index';
import { getToken, clearAuth, silentWechatLogin } from './auth';

export class ApiError extends Error {
  statusCode: number;
  constructor(msg: string, statusCode: number) {
    super(msg);
    this.statusCode = statusCode;
  }
}

/** FastAPI 错误体 detail 提取（对齐 Web lib/api.ts：422 时 detail 是数组，取各 msg 拼「；」） */
export function extractDetail(data: unknown): string {
  const d = (data || {}) as { detail?: unknown };
  if (Array.isArray(d.detail)) {
    return d.detail
      .map((e) => (typeof e === 'string' ? e : ((e as { msg?: string })?.msg || JSON.stringify(e))))
      .join('；');
  }
  if (typeof d.detail === 'string') return d.detail;
  if (d.detail && typeof d.detail === 'object') {
    return (d.detail as { msg?: string }).msg || JSON.stringify(d.detail);
  }
  return '请求失败';
}

/** 401 统一跳登录（带当前页 redirect 回跳）。并发 401 只触发一次跳转 */
let redirecting = false;

function currentPagePath(): string {
  const pages = getCurrentPages();
  const cur: any = pages[pages.length - 1];
  if (!cur || !cur.route) return '';
  if (String(cur.route).indexOf('pages/login') === 0) return '';
  const opts = cur.options || {};
  const qs = Object.keys(opts)
    .map((k) => k + '=' + encodeURIComponent(String(opts[k])))
    .join('&');
  return '/' + cur.route + (qs ? '?' + qs : '');
}

function redirectToLogin(): void {
  if (redirecting) return;
  redirecting = true;
  clearAuth();
  const redirect = currentPagePath();
  wx.reLaunch({
    url: '/pages/login/login' + (redirect ? '?redirect=' + encodeURIComponent(redirect) : ''),
    complete: () => {
      redirecting = false;
    },
  });
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  data?: Record<string, unknown>;
  /** 登录接口用：不注 token；其 401（密码错误）当普通错误展示而非跳转 */
  skipAuth?: boolean;
  /** 内部用：401 静默重登后的重试轮，防循环 */
  _retried?: boolean;
}

/** 401 自愈：静默微信重登（并发 401 共享一次尝试），成功后原请求重放 */
let reloginPromise: Promise<string | null> | null = null;

function silentRelogin(): Promise<string | null> {
  if (!reloginPromise) {
    const p = silentWechatLogin().then((r) => (r && 'token' in r ? r.token : null));
    reloginPromise = p;
    p.finally(() => {
      if (reloginPromise === p) reloginPromise = null;
    });
  }
  return reloginPromise;
}

/** wx.request Promise 封装 —— 页面永远不直接碰 wx.request，一律走 utils/api.ts */
export function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const token = opts.skipAuth ? null : getToken();
    wx.request({
      url: BASE_URL + path,
      method: opts.method || 'GET',
      data: opts.data as any,
      timeout: REQUEST_TIMEOUT,
      header: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: 'Bearer ' + token } : {}),
      },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data as T);
          return;
        }
        if (res.statusCode === 401 && !opts.skipAuth) {
          // token 中途过期：先静默微信重登一次（openid 已绑定则无感续期），
          // 成功重放原请求；失败才真正跳登录页，不打断阅读
          if (!opts._retried) {
            silentRelogin().then((t) => {
              if (t) {
                request<T>(path, { ...opts, _retried: true }).then(resolve, reject);
              } else {
                redirectToLogin();
                reject(new ApiError('登录已过期，请重新登录', 401));
              }
            });
            return;
          }
          redirectToLogin();
          reject(new ApiError('登录已过期，请重新登录', 401));
          return;
        }
        reject(new ApiError(extractDetail(res.data), res.statusCode));
      },
      fail: () => reject(new ApiError('网络请求失败，请检查网络后重试', 0)),
    });
  });
}
