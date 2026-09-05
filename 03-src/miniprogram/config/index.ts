/** 小程序全局配置 —— 换环境只需改这个文件 */

/** 后端基址：正式号需在 mp 平台把它配进 request 合法域名 */
export const BASE_URL = 'https://inflow.huituai.site';

/** 列表分页大小（后端 page_size 上限 100，与 Web 端一致取 24） */
export const PAGE_SIZE = 24;

/** 请求超时（ms）——语义搜索需走向量召回，放宽到 20s */
export const REQUEST_TIMEOUT = 20000;

/** 小程序版本号（「我的」页展示） */
export const APP_VERSION = '0.1.0';

/**
 * 防盗链图片域名（镜像 backend/main.py ALLOWED_IMAGE_DOMAINS）：
 * 这些域名的图片必须改写走后端 /api/images/proxy 代理——小程序 <image> 带
 * 不了 Referer，直连必 403。后端新增域名时同步这里。
 */
export const PROXY_IMAGE_HOSTS = [
  'mmbiz.qpic.cn',
  'mmbiz.qlogo.cn',
  'mmecoa.qpic.cn',
  'xhscdn.com',
  'douyinpic.com',
  'douyinvod.com',
];

/** 平台 slug → 展示名（对齐 Web 端 library/ArticleCard） */
export const PLATFORM_LABELS: Record<string, string> = {
  wechat: '微信公众号', bilibili: 'B 站', xiaoyuzhou: '小宇宙',
  xhs: '小红书', douyin: '抖音', youtube: 'YouTube',
  toutiao: '今日头条', juejin: '掘金', csdn: 'CSDN',
  '36kr': '36 氪', sspai: '少数派', jianshu: '简书',
  weibo: '微博', douban: '豆瓣', medium: 'Medium',
  feishu: '飞书', upload: '上传文件', generic: '网页',
  note: '笔记', spark: 'AI 生成', other: '其他',
};

/** 平台 slug → 无封面时的占位渐变（对齐 Web 端 PLATFORM_GRADIENTS） */
export const PLATFORM_GRADIENTS: Record<string, string> = {
  xiaoyuzhou: 'linear-gradient(135deg, #ff9500 0%, #e07800 100%)',
  bilibili: 'linear-gradient(135deg, #fb7299 0%, #e0507a 100%)',
  wechat: 'linear-gradient(135deg, #34c759 0%, #22a344 100%)',
  youtube: 'linear-gradient(135deg, #ff3b30 0%, #c0392b 100%)',
  xhs: 'linear-gradient(135deg, #ff2d55 0%, #cc1f44 100%)',
  douyin: 'linear-gradient(135deg, #444 0%, #111 100%)',
  feishu: 'linear-gradient(135deg, #3370ff 0%, #1a53cc 100%)',
  note: 'linear-gradient(135deg, #5856d6 0%, #3a38b0 100%)',
  upload: 'linear-gradient(135deg, #8e8e93 0%, #636366 100%)',
  juejin: 'linear-gradient(135deg, #007fff 0%, #0055cc 100%)',
  generic: 'linear-gradient(135deg, #007aff 0%, #0055cc 100%)',
};
