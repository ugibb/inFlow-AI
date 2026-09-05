import { BASE_URL } from '../config/index';

/** Storage keys —— 与 Web 端 localStorage('inFlow_token') 各自独立，互不影响 */
const TOKEN_KEY = 'inflow_token';
const USER_KEY = 'inflow_user';

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
  } catch {
    /* ignore */
  }
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
