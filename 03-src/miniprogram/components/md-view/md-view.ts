import { parseMarkdown, collectImages } from '../../utils/markdown';

/**
 * Markdown 渲染器：utils/markdown.ts 解析为类型化节点，WXML 分类型渲染。
 * - 图片：点击 wx.previewImage 多图连播
 * - 链接：小程序不能外跳，点击复制到剪贴板
 */
Component({
  properties: {
    md: {
      type: String,
      value: '',
    },
  },

  data: {
    nodes: [] as MdNode[],
    images: [] as string[],
  },

  observers: {
    md(v: string) {
      const nodes = parseMarkdown(v || '');
      this.setData({ nodes, images: collectImages(nodes) });
    },
  },

  methods: {
    onImageTap(e: any) {
      const src = String(e.currentTarget.dataset.src || '');
      if (!src || !this.data.images.length) return;
      wx.previewImage({ current: src, urls: this.data.images });
    },
    onSegTap(e: any) {
      const d = e.currentTarget.dataset;
      if (d.t !== 'link' || !d.href) return;
      wx.setClipboardData({
        data: String(d.href),
        success: () => wx.showToast({ title: '链接已复制', icon: 'none' }),
      });
    },
  },
});
