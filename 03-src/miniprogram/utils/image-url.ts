import { BASE_URL, PROXY_IMAGE_HOSTS } from '../config/index';

const PROXY_PREFIX = BASE_URL + '/api/images/proxy';

function hostnameOf(url: string): string {
  const m = /^https?:\/\/([^/?#]+)/i.exec(url);
  return m ? m[1].toLowerCase() : '';
}

/**
 * 全项目唯一的图片地址改写点（列表封面 / md 内嵌图 / 分享图一律经过它）：
 * - data: URI → 原样
 * - 已是本站代理绝对地址 → 原样
 * - 防盗链域名外链（微信 mmbiz / 小红书 / 抖音 CDN）→ 改写为后端代理
 *   （小程序 <image> 带不了 Referer，直连必 403）
 * - 代理相对路径 /api/images/proxy?... → 拼 BASE_URL
 * - 其他绝对地址 → 原样；站内相对路径 → 拼 BASE_URL
 */
export function resolveImage(src?: string | null): string {
  if (!src) return '';
  const s = src.trim();
  if (!s) return '';
  if (s.indexOf('data:') === 0) return s;
  if (/^https?:\/\//i.test(s)) {
    if (s.indexOf(PROXY_PREFIX) === 0) return s;
    const host = hostnameOf(s);
    const hot = PROXY_IMAGE_HOSTS.some((h) => host === h || host.endsWith('.' + h));
    return hot ? PROXY_PREFIX + '?url=' + encodeURIComponent(s) : s;
  }
  if (s.charAt(0) === '/') return BASE_URL + s;
  return s;
}
