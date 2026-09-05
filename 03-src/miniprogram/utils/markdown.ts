import { resolveImage } from './image-url';

/**
 * 简易 Markdown 解析器（MVP）：逐行状态机解析为类型化节点数组，
 * 由 md-view 组件 WXML 分类型渲染。
 * 覆盖：标题 / 段落 / 粗体 / 斜体 / 行内代码 / 链接 / 无序有序列表 /
 *       引用 / 独立成行的图片 / 围栏代码块 / 分隔线。
 * 未覆盖（表格、嵌套列表、HTML 片段）按段落降级渲染，不丢内容。
 */

let keyCounter = 0;
function nextKey(): string {
  keyCounter += 1;
  return 'k' + keyCounter;
}

const INLINE_SPLIT_RE = /(!\[[^\]]*\]\([^)\s]+\)|\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/;

/** 行内解析：粗体 / 斜体 / 行内码 / 链接；行内图片降级为可复制的链接段 */
export function parseInline(text: string): MdInlineSeg[] {
  const segs: MdInlineSeg[] = [];
  const parts = text.split(INLINE_SPLIT_RE);
  for (const p of parts) {
    if (!p) continue;
    let m: RegExpExecArray | null;
    if ((m = /^!\[([^\]]*)\]\(([^)\s]+)\)$/.exec(p))) {
      segs.push({ t: 'link', text: m[1] || '查看图片', href: m[2], kk: nextKey() });
    } else if (p.length >= 4 && p.startsWith('**') && p.endsWith('**')) {
      segs.push({ t: 'bold', text: p.slice(2, -2), kk: nextKey() });
    } else if (p.length >= 2 && p.startsWith('`') && p.endsWith('`')) {
      segs.push({ t: 'code', text: p.slice(1, -1), kk: nextKey() });
    } else if ((m = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(p))) {
      segs.push({ t: 'link', text: m[1], href: m[2], kk: nextKey() });
    } else if (p.length >= 2 && p.startsWith('*') && p.endsWith('*') && !p.startsWith('**')) {
      segs.push({ t: 'italic', text: p.slice(1, -1), kk: nextKey() });
    } else {
      segs.push({ t: 'text', text: p, kk: nextKey() });
    }
  }
  return segs;
}

const FENCE_RE = /^\s*```\s*(\S*)\s*$/;
const FENCE_END_RE = /^\s*```\s*$/;
const HEADING_RE = /^(#{1,4})\s+(.*)$/;
const HR_RE = /^(-{3,}|\*{3,}|_{3,})\s*$/;
const IMG_LINE_RE = /^!\[([^\]]*)\]\(([^)\s]+)\)$/;
const QUOTE_RE = /^>\s?/;
const UL_RE = /^\s*[-*+]\s+(.*)$/;
const OL_RE = /^\s*\d+[.、)]\s+(.*)$/;

function isBlockStart(s: string): boolean {
  return (
    /^\s*$/.test(s) ||
    FENCE_RE.test(s) ||
    HEADING_RE.test(s) ||
    HR_RE.test(s) ||
    IMG_LINE_RE.test(s.trim()) ||
    QUOTE_RE.test(s) ||
    UL_RE.test(s) ||
    OL_RE.test(s)
  );
}

export function parseMarkdown(md: string): MdNode[] {
  keyCounter = 0;
  const nodes: MdNode[] = [];
  if (!md) return nodes;
  const lines = md.replace(/\r\n?/g, '\n').split('\n');
  const n = lines.length;
  let i = 0;

  while (i < n) {
    const line = lines[i];

    if (/^\s*$/.test(line)) {
      i += 1;
      continue;
    }

    // 围栏代码块
    const fence = FENCE_RE.exec(line);
    if (fence) {
      i += 1;
      const buf: string[] = [];
      while (i < n && !FENCE_END_RE.test(lines[i])) {
        buf.push(lines[i]);
        i += 1;
      }
      i += 1; // 跳过收尾 ```
      nodes.push({ type: 'codeblock', lang: fence[1] || '', text: buf.join('\n'), kk: nextKey() });
      continue;
    }

    // 标题
    const h = HEADING_RE.exec(line);
    if (h) {
      nodes.push({ type: 'heading', level: h[1].length, text: h[2].trim(), kk: nextKey() });
      i += 1;
      continue;
    }

    // 分隔线
    if (HR_RE.test(line)) {
      nodes.push({ type: 'hr', kk: nextKey() });
      i += 1;
      continue;
    }

    // 独立成行的图片（防盗链域名改写走后端代理）
    const img = IMG_LINE_RE.exec(line.trim());
    if (img) {
      nodes.push({ type: 'image', src: resolveImage(img[2]), alt: img[1], kk: nextKey() });
      i += 1;
      continue;
    }

    // 引用块（连续行合并）
    if (QUOTE_RE.test(line)) {
      const buf: string[] = [];
      while (i < n && QUOTE_RE.test(lines[i])) {
        buf.push(lines[i].replace(QUOTE_RE, ''));
        i += 1;
      }
      nodes.push({ type: 'quote', text: buf.join('\n').trim(), kk: nextKey() });
      continue;
    }

    // 列表（连续同类项；有序/无序不混排）
    const ul = UL_RE.exec(line);
    const ol = OL_RE.exec(line);
    if (ul || ol) {
      const ordered = !!ol;
      const items: MdInlineSeg[][] = [];
      while (i < n) {
        const l = lines[i];
        const mu = UL_RE.exec(l);
        const mo = OL_RE.exec(l);
        if (ordered && mo) items.push(parseInline(mo[1]));
        else if (!ordered && mu) items.push(parseInline(mu[1]));
        else break;
        i += 1;
      }
      nodes.push({ type: 'list', ordered, items, kk: nextKey() });
      continue;
    }

    // 段落：连续普通行合并
    const buf: string[] = [line];
    i += 1;
    while (i < n && !isBlockStart(lines[i])) {
      buf.push(lines[i]);
      i += 1;
    }
    nodes.push({ type: 'p', inlines: parseInline(buf.join('\n').trim()), kk: nextKey() });
  }

  return nodes;
}

/** 收集全部图片地址（预览时多图连播用） */
export function collectImages(nodes: MdNode[]): string[] {
  const urls: string[] = [];
  for (const node of nodes) {
    if (node.type === 'image' && node.src) urls.push(node.src);
  }
  return urls;
}
