import { request } from './request';

/** 类型化 API 薄封装（MVP 用到的接口全集，出参类型见 typings/api.d.ts） */

export interface ArticleListParams {
  page?: number;
  page_size?: number;
  search?: string;
  search_mode?: 'semantic' | 'keyword';
  source_platform?: string;
  author?: string;
  sort?: string;
}

export const api = {
  login(username: string, password: string) {
    return request<LoginResponse>('/api/auth/login', {
      method: 'POST',
      data: { username, password },
      skipAuth: true,
    });
  },

  /** 微信一键登录：wx.login 的一次性 code + 选填（邀请码/昵称/头像 base64） */
  wechatLogin(
    code: string,
    opts?: { inviteCode?: string; nickname?: string; avatarBase64?: string },
  ) {
    return request<WechatLoginResponse>('/api/auth/wechat', {
      method: 'POST',
      skipAuth: true,
      data: {
        code,
        invite_code: (opts && opts.inviteCode) || '',
        nickname: (opts && opts.nickname) || '',
        avatar_base64: (opts && opts.avatarBase64) || '',
      },
    });
  },

  /** 更新当前微信的昵称/头像（空字段 = 不变） */
  updateWxProfile(payload: { nickname?: string; avatarBase64?: string }) {
    return request<WxProfile>('/api/auth/wechat/profile', {
      method: 'PATCH',
      data: {
        nickname: payload.nickname || '',
        avatar_base64: payload.avatarBase64 || '',
      },
    });
  },

  getMe() {
    return request<User>('/api/auth/me');
  },

  getArticles(params: ArticleListParams) {
    const q: Record<string, string> = {};
    Object.keys(params).forEach((key) => {
      const v = (params as Record<string, unknown>)[key];
      if (v !== undefined && v !== null && v !== '') q[key] = String(v);
    });
    return request<ArticleListResponse>('/api/articles', { method: 'GET', data: q });
  },

  getPlatformCounts() {
    return request<PlatformCount[]>('/api/articles/platforms');
  },

  getAuthorCounts() {
    return request<AuthorCount[]>('/api/articles/authors');
  },

  getArticle(id: string) {
    return request<ArticleDetail>('/api/articles/' + id);
  },

  getChapters(id: string) {
    return request<ArticleChaptersResponse>('/api/articles/' + id + '/chapters');
  },

  getTranscript(id: string) {
    return request<JobTranscript>('/api/articles/' + id + '/transcript');
  },
};
