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
