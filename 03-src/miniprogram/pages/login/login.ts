import { api } from '../../utils/api';
import { setAuth } from '../../utils/auth';
import { BASE_URL } from '../../config/index';

/** 登录页：账号密码 → JWT（30 天）→ reLaunch 回 redirect 或首页 */
function decodeRedirect(raw: string): string {
  if (!raw) return '';
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

Page({
  data: {
    username: '',
    password: '',
    submitting: false,
    error: '',
    serverUrl: BASE_URL,
  },

  redirect: '',

  onLoad(options: Record<string, string | undefined>) {
    this.redirect = decodeRedirect((options && options.redirect) || '');
  },

  onUsername(e: any) {
    this.setData({ username: e.detail.value, error: '' });
  },

  onPassword(e: any) {
    this.setData({ password: e.detail.value, error: '' });
  },

  async onSubmit() {
    if (this.data.submitting) return;
    const username = this.data.username.trim();
    const { password } = this.data;
    if (!username || !password) {
      this.setData({ error: '请输入账号和密码' });
      return;
    }
    this.setData({ submitting: true, error: '' });
    try {
      const res = await api.login(username, password);
      setAuth(res.access_token, res.user);
      getApp<IAppOption>().globalData.user = res.user;
      wx.reLaunch({ url: this.redirect || '/pages/library/library' });
    } catch (e: any) {
      this.setData({ submitting: false, error: (e && e.message) || '登录失败' });
    }
  },
});
