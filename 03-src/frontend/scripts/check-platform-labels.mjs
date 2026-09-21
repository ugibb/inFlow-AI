#!/usr/bin/env node
/**
 * 平台名映射一致性检查（零依赖，node scripts/check-platform-labels.mjs）。
 *
 * 为什么需要它：4 处平台名映射都是 `Record<string, string>`，漏改一个 key 不会产生
 * 任何 TypeScript 报错 —— 索引返回 undefined 后静默回落成原始 slug（页面上直接印出
 * "wechat_channels"）。这是"看起来做完了"最容易骗过人的地方，所以用脚本兜住。
 *
 * 校验三件事：
 * 1. REQUIRED_PLATFORMS 在每个文件的标签表里都存在
 * 2. 标签值互不相同（视频号复制公众号那行就会被抓住）
 * 3. ArticleCard / read 页的 key 集合是 library 页的子集（library 是全量基准表）
 *
 * 构建上下文：本脚本挂在 `npm run build` 前，而前端镜像是**只以 03-src/frontend 为
 * 上下文**构建的（docker-compose.yml 的 `context: ./03-src/frontend`），镜像里没有
 * ../miniprogram。所以 Web 三处表**必须存在**（路径写错要当场炸），小程序表标
 * `optional`：文件不在就跳过并打印，否则会把镜像构建带崩。
 */

import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

/** 新增平台必须在所有映射表里出现 */
const REQUIRED_PLATFORMS = ['wechat_channels', 'twitter'];

/** library 页是基准表（key 最全），另两处 Web 映射必须被它覆盖 */
const WEB_LABEL_TARGETS = [
  { file: 'app/library/page.tsx', marker: "const PLATFORM_LABELS", base: true },
  { file: 'components/ArticleCard.tsx', marker: "const PLATFORM_LABELS", base: false },
  { file: 'app/read/[id]/page.tsx', marker: "const map: Record<string, string>", base: false },
];

const GRADIENT_TARGETS = [
  { file: 'app/library/page.tsx', marker: "const PLATFORM_GRADIENTS" },
  { file: 'components/ArticleCard.tsx', marker: "const PLATFORM_GRADIENTS" },
];

// optional：小程序不在前端镜像的构建上下文里，缺文件跳过（见文件头说明）
const MINIPROGRAM_TARGETS = [
  { file: '../miniprogram/config/index.ts', marker: "export const PLATFORM_LABELS", optional: true },
  { file: '../miniprogram/config/index.ts', marker: "export const PLATFORM_GRADIENTS", optional: true },
];

/** 取出 `marker` 后第一个 `{...}` 对象字面量（带引号状态跟踪，避免被字符串里的 } 骗到） */
function extractObjectBody(src, marker) {
  const at = src.indexOf(marker);
  if (at === -1) throw new Error(`找不到标记：${marker}`);
  const open = src.indexOf('{', at);
  if (open === -1) throw new Error(`标记后无对象字面量：${marker}`);
  let depth = 0;
  let quote = null;
  for (let i = open; i < src.length; i += 1) {
    const ch = src[i];
    if (quote) {
      if (ch === '\\') i += 1;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === "'" || ch === '"' || ch === '`') quote = ch;
    else if (ch === '{') depth += 1;
    else if (ch === '}') {
      depth -= 1;
      if (depth === 0) return src.slice(open + 1, i);
    }
  }
  throw new Error(`对象字面量未闭合：${marker}`);
}

/** 对象体 → { key: value }（含 '36kr' 这类带引号的 key） */
function parseEntries(body) {
  const entries = new Map();
  const re = /(['"]?)([A-Za-z_][\w-]*)\1\s*:\s*(['"])((?:\\.|(?!\3).)*)\3/g;
  for (const m of body.matchAll(re)) entries.set(m[2], m[4]);
  return entries;
}

function loadEntries({ file, marker, optional = false }) {
  const path = join(ROOT, file);
  if (!existsSync(path)) {
    // 非 optional 的缺文件是真错误（多半是路径写错了），必须炸；optional 的
    // 只在仓库里存在（本地跑得到），镜像里没有 —— 记下来，不静默
    if (!optional) throw new Error(`找不到文件：${path}`);
    skipped.push(file);
    return null;
  }
  return parseEntries(extractObjectBody(readFileSync(path, 'utf8'), marker));
}

const failures = [];
const skipped = [];

// ── 1 + 2：标签表 ────────────────────────────────────────────────────────────
for (const target of WEB_LABEL_TARGETS) {
  const entries = loadEntries(target);
  for (const platform of REQUIRED_PLATFORMS) {
    if (!entries.has(platform)) {
      failures.push(`${target.file}: 标签表缺 key "${platform}"（会静默显示英文 slug）`);
    }
  }
  const wechat = entries.get('wechat');
  const channels = entries.get('wechat_channels');
  if (wechat && channels && wechat === channels) {
    failures.push(`${target.file}: wechat_channels 与 wechat 标签相同（"${channels}"）`);
  }
}

// ── 3：Web 三处 key 集合互相包含 ─────────────────────────────────────────────
const webKeys = WEB_LABEL_TARGETS.map((t) => ({ file: t.file, keys: loadEntries(t) }));
const base = webKeys.find((_, i) => WEB_LABEL_TARGETS[i].base);
if (base) {
  for (const { file, keys } of webKeys) {
    if (file === base.file) continue;
    const missing = [...keys.keys()].filter((k) => !base.keys.has(k));
    if (missing.length) {
      failures.push(`${base.file} 缺 ${file} 中的 key：${missing.join(', ')}`);
    }
  }
}

// ── 渐变表 + 小程序 ─────────────────────────────────────────────────────────
for (const target of [...GRADIENT_TARGETS, ...MINIPROGRAM_TARGETS]) {
  const entries = loadEntries(target);
  if (!entries) continue; // 小程序不在构建上下文里
  for (const platform of REQUIRED_PLATFORMS) {
    if (!entries.has(platform)) {
      failures.push(`${target.file}: 缺 "${platform}"（${target.marker}）`);
    }
  }
  const wechat = entries.get('wechat');
  const channels = entries.get('wechat_channels');
  if (wechat && channels && wechat === channels) {
    failures.push(`${target.file}: wechat_channels 与 wechat 视觉样式相同`);
  }
}

if (failures.length) {
  console.error('✗ 平台名映射不一致：');
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
// 报"实际查了什么"，别把跳过的算成查过
const skippedFiles = [...new Set(skipped)];
const scope = skippedFiles.length
  ? `web ${WEB_LABEL_TARGETS.length} 处 + 渐变 ${GRADIENT_TARGETS.length} 处；跳过 ${skippedFiles.join('、')}（不在本次构建上下文内）`
  : `web ${WEB_LABEL_TARGETS.length} 处 + 小程序 2 表`;
console.log(`✓ 平台名映射一致（${scope}，新增平台均已就位）`);
