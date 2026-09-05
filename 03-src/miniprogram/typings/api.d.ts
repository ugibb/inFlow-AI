/**
 * 全局类型声明（ambient，无 import/export）——字段与 backend/core/schemas 对齐，
 * 是 frontend/lib/types.ts 的 MVP 子集翻译。
 */

interface User {
  id: string;
  username: string;
  is_super_admin: boolean;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
}

interface TagItem {
  id: string;
  name: string;
  color: string;
}

interface Article {
  id: string;
  title: string;
  url?: string;
  content_type?: 'article' | 'note' | 'audio';
  source_platform?: string;
  author?: string;
  published_at?: string;
  summary?: string;
  key_points?: string[];
  reading_time: number;
  word_count: number;
  cover_image?: string;
  status: string;
  fetch_status?: 'completed' | 'pending_agent' | 'failed' | 'ingesting';
  is_favorited: boolean;
  folder_id?: string;
  tags: TagItem[];
  created_at?: string;
  updated_at?: string;
}

interface ContentBlockState {
  applicable: boolean;
  present: boolean;
}

type ContentBlockKey = 'raw' | 'transcript' | 'chapters' | 'deepRead' | 'ai';

interface ContentBlocks {
  raw?: ContentBlockState;
  transcript?: ContentBlockState;
  chapters?: ContentBlockState;
  deepRead?: ContentBlockState;
  ai?: ContentBlockState;
}

interface ArticleDetail extends Article {
  clean_content?: string;
  raw_content?: string;
  media_url?: string;
  /** read 页各内容块存在性快照（detail 路由计算） */
  content_blocks?: ContentBlocks;
}

interface ArticleListResponse {
  items: Article[];
  total: number;
  page: number;
  page_size: number;
}

interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}

/** 微信绑定的用户主动填写资料（「头像昵称填写能力」产物；avatar 为 data URI） */
interface WxProfile {
  nickname: string | null;
  avatar: string | null;
}

interface WechatLoginResponse extends LoginResponse {
  wx_profile: WxProfile;
}

interface PlatformCount {
  platform: string;
  count: number;
}

interface AuthorCount {
  author: string;
  count: number;
}

interface ArticleChapter {
  index: number;
  title: string;
  start_time: number;
  end_time: number;
  summary: string;
}

interface ArticleChaptersResponse {
  version: string;
  total_duration: number;
  chapters: ArticleChapter[];
}

interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
}

interface JobTranscript {
  language: string | null;
  duration: number | null;
  segments: TranscriptSegment[];
}

/** ── md-view 渲染节点（utils/markdown.ts 产出）── */

interface MdInlineSeg {
  t: 'text' | 'bold' | 'italic' | 'code' | 'link';
  text: string;
  href?: string;
  /** WXML wx:key 用 */
  kk: string;
}

interface MdNode {
  type: 'heading' | 'p' | 'image' | 'list' | 'quote' | 'codeblock' | 'hr';
  kk: string;
  level?: number;
  text?: string;
  inlines?: MdInlineSeg[];
  src?: string;
  alt?: string;
  ordered?: boolean;
  items?: MdInlineSeg[][];
  lang?: string;
}

/** App getApp() 的类型 */
interface IAppOption {
  globalData: {
    user: User | null;
    /** 启动鉴权 Promise：resolve token（有效/乐观放行/静默微信登录成功）或 null（需跳登录） */
    authReady: Promise<string | null> | null;
    /** 后端要求邀请码时置 true（登录页据此显示邀请码输入框） */
    wechatNeedInvite: boolean;
  };
}
