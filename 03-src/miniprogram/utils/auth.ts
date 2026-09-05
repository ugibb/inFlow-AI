import { BASE_URL } from '../config/index';

/** Storage keys —— 与 Web 端 localStorage('inFlow_token') 各自独立，互不影响 */
const TOKEN_KEY = 'inflow_token';
const USER_KEY = 'inflow_user';
const PROFILE_KEY = 'inflow_wx_profile';

export function getToken(): string | null {
  try {
    const v = wx.getStorageSync(TOKEN_KEY);
    return v || null;
  } catch {
    return null;
  }
}

export function getUser(): User | null {
  try {
    const v = wx.getStorageSync(USER_KEY);
    return v || null;
  } catch {
    return null;
  }
}

export function setAuth(token: string, user: User): void {
  try {
    wx.setStorageSync(TOKEN_KEY, token);
    wx.setStorageSync(USER_KEY, user);
  } catch {
    /* storage 写入失败极罕见（空间满），登录页后续请求会 401 兜底 */
  }
}

export function clearAuth(): void {
  try {
    wx.removeStorageSync(TOKEN_KEY);
    wx.removeStorageSync(USER_KEY);
    wx.removeStorageSync(PROFILE_KEY);
  } catch {
    /* ignore */
  }
}

/** 微信绑定资料（头像 data URI + 昵称；登录/续登时随 wx_profile 刷新） */
export function getWxProfile(): WxProfile | null {
  try {
    const v = wx.getStorageSync(PROFILE_KEY);
    return v || null;
  } catch {
    return null;
  }
}

export function setWxProfile(p: WxProfile | null): void {
  try {
    if (p) wx.setStorageSync(PROFILE_KEY, p);
    else wx.removeStorageSync(PROFILE_KEY);
  } catch {
    /* ignore */
  }
}

/** wx.login → 一次性 code（5 分钟有效） */
export function wxLoginCode(): Promise<string> {
  return new Promise((resolve, reject) => {
    wx.login({
      success: (r) => (r.code ? resolve(r.code) : reject(new Error('未获取到微信登录凭证'))),
      fail: () => reject(new Error('微信登录失败，请重试')),
    });
  });
}

export type SilentLoginResult = { token: string } | { invite: true } | null;

/**
 * 静默微信登录（app.onLaunch / 401 自愈用）：wx.login → POST /api/auth/wechat。
 * 已绑定 openid 直接换新 JWT（后续访问的无感路径）；后端要求邀请码 →
 * { invite: true }（登录页展示邀请码输入）；其他失败 → null。
 * 直用 wx.request（与 validateStored 同风格），避免与 api.ts 循环 import。
 */
export function silentWechatLogin(): Promise<SilentLoginResult> {
  return wxLoginCode()
    .then(
      (code) =>
        new Promise<WechatLoginResponse>((resolve, reject) => {
          wx.request({
            url: BASE_URL + '/api/auth/wechat',
            method: 'POST',
            data: { code, invite_code: '', nickname: '', avatar_base64: '' },
            timeout: 8000,
            success: (res) => {
              if (res.statusCode >= 200 && res.statusCode < 300) {
                resolve(res.data as WechatLoginResponse);
              } else {
                const detail = ((res.data || {}) as { detail?: unknown }).detail;
                reject({
                  statusCode: res.statusCode,
                  detail: typeof detail === 'string' ? detail : '',
                });
              }
            },
            fail: () => reject({ statusCode: 0, detail: '网络请求失败' }),
          });
        }),
    )
    .then((res) => {
      setAuth(res.access_token, res.user);
      setWxProfile(res.wx_profile || null);
      return { token: res.access_token };
    })
    .catch((e: { statusCode?: number; detail?: string }) => {
      if (e && e.statusCode === 403 && (e.detail || '').indexOf('invite') === 0) {
        return { invite: true };
      }
      return null;
    });
}

/** base64（含 URL-safe 变体）→ UTF-8 字符串。小程序环境无 atob，自实现 */
function base64DecodeUtf8(input: string): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  let str = input.replace(/-/g, '+').replace(/_/g, '/');
  while (str.length % 4) str += '=';
  const bytes: number[] = [];
  let acc = 0;
  let bits = 0;
  for (let i = 0; i < str.length; i += 1) {
    const ch = str.charAt(i);
    if (ch === '=') break;
    const idx = chars.indexOf(ch);
    if (idx < 0) continue;
    acc = (acc << 6) | idx;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      bytes.push((acc >> bits) & 0xff);
    }
  }
  let out = '';
  let i = 0;
  while (i < bytes.length) {
    const b = bytes[i];
    if (b < 0x80) {
      out += String.fromCharCode(b);
      i += 1;
    } else if (b >= 0xc0 && b < 0xe0 && i + 1 < bytes.length) {
      out += String.fromCharCode(((b & 0x1f) << 6) | (bytes[i + 1] & 0x3f));
      i += 2;
    } else if (b >= 0xe0 && b < 0xf0 && i + 2 < bytes.length) {
      out += String.fromCharCode(((b & 0x0f) << 12) | ((bytes[i + 1] & 0x3f) << 6) | (bytes[i + 2] & 0x3f));
      i += 3;
    } else {
      out += '�';
      i += 1;
    }
  }
  return out;
}

/** 从 JWT payload 提取基础信息（不验签，仅本地预检/降级展示用） */
export function decodeJwt(token: string): { sub?: string; username?: string; is_super_admin?: boolean; exp?: number } | null {
  try {
    const part = token.split('.')[1];
    if (!part) return null;
    return JSON.parse(base64DecodeUtf8(part));
  } catch {
    return null;
  }
}

/** JWT 是否已过期（本地预检，省一次必败的网络往返） */
export function tokenExpired(token: string): boolean {
  const p = decodeJwt(token);
  return !!(p && p.exp && p.exp * 1000 < Date.now());
}

/**
 * 启动鉴权（app.onLaunch 调一次），resolve：token（有效或乐观放行）| null（需跳登录）。
 * 时序对齐 Web AuthContext：本地预检 exp → /api/auth/me 校验一次 →
 * 401/403 清空；网络不可达则乐观放行（后续请求失败自然报错）。
 */
export function validateStored(onUser?: (u: User) => void): Promise<string | null> {
  return new Promise((resolve) => {
    const token = getToken();
    if (!token) {
      resolve(null);
      return;
    }
    if (tokenExpired(token)) {
      clearAuth();
      resolve(null);
      return;
    }
    wx.request({
      url: BASE_URL + '/api/auth/me',
      header: { Authorization: 'Bearer ' + token },
      timeout: 8000,
      success: (res) => {
        if (res.statusCode === 401 || res.statusCode === 403) {
          clearAuth();
          resolve(null);
          return;
        }
        if (res.statusCode === 200) {
          const u = res.data as User;
          try {
            wx.setStorageSync(USER_KEY, u);
          } catch {
            /* ignore */
          }
          if (onUser) onUser(u);
        }
        resolve(token);
      },
      fail: () => resolve(token),
    });
  });
}

/**
 * 页面级守卫（onLoad/onShow 用）：本地 token 未过期直接放行；
 * 否则回落启动校验 Promise（覆盖冷启动 /me 一次性校验场景）。
 * authReady 只反映冷启动时刻的状态且只 settle 一次——登录成功 reLaunch
 * 回来的新页面实例若还 await 它，会拿到过期的 null 被误弹回登录页（死循环），
 * 所以守卫一律本地 token 优先，不依赖 login 页是否刷新了 authReady。
 */
export function pageAuth(): Promise<string | null> {
  const t = getToken();
  if (t && !tokenExpired(t)) return Promise.resolve(t);
  const app = getApp<IAppOption>();
  return app.globalData.authReady || Promise.resolve(null);
}
