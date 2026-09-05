/**
 * 瀑布流分列（翻译 Web frontend/app/library/page.tsx 的
 * estimateCardHeight + 最短列分发算法，aa2e363）。
 */

export interface MasonryColumn {
  /** WXML wx:key 用 */
  k: number;
  items: Article[];
}

/** 列数：宽屏（iPad / 折叠屏展开）3 列，手机 2 列 */
export function columnCount(): number {
  try {
    return wx.getSystemInfoSync().windowWidth >= 600 ? 3 : 2;
  } catch {
    return 2;
  }
}

/**
 * 估算卡片高度（px）。数值无需精确——只用于把卡片塞进当前最短列、
 * 让各列大致均衡；主要区分封面有无 / 摘要有无 / 标签有无几类高度差。
 */
export function estimateCardHeight(a: Article): number {
  let h = 32; // info 区上下 padding
  h += a.cover_image ? 180 : 144; // 自然比例封面(估) vs 固定高度占位
  h += 40; // 标题两行
  if (a.summary) h += 32; // 摘要两行
  else if (a.fetch_status === 'pending_agent' || a.fetch_status === 'failed') h += 28; // 状态条
  else if (a.content_type !== 'note') h += 28; // 「AI 处理中」条
  if (a.tags && a.tags.length > 0) h += 26; // 标签一行
  h += 20; // 底部 author / 阅读时长
  return h;
}

/**
 * 最短列分发：items 按发布时间倒序进来，高度相近时自然形成「从左到右」
 * 的阅读顺序，最新卡片落在左上角（与 Web 端一致）。
 */
export function distributeColumns(items: Article[]): MasonryColumn[] {
  const n = columnCount();
  const cols: MasonryColumn[] = [];
  const heights: number[] = [];
  for (let i = 0; i < n; i += 1) {
    cols.push({ k: i, items: [] });
    heights.push(0);
  }
  for (const it of items) {
    let min = 0;
    for (let i = 1; i < n; i += 1) {
      if (heights[i] < heights[min]) min = i;
    }
    cols[min].items.push(it);
    heights[min] += estimateCardHeight(it);
  }
  return cols;
}
