import { api } from '../../utils/api';
import { getToken, getUser, clearAuth } from '../../utils/auth';
import { BASE_URL, APP_VERSION } from '../../config/index';

/** 我的：用户信息（/me 刷新）+ 退出登录 + 复制 Web 端地址 */
Page({
  data: {
    user: null as User | null,
    initial: '',
    version: APP_VERSION,
    webUrl: BASE_URL,
  },

  onShow() {
    if (!getToken()) {
      wx.reLaunch({ url: '/pages/login/login' });
      return;
    }
    const cached = getUser();
    this.applyUser(cached);
    // 静默刷新（失败用 storage 缓存兜底）
    api
      .getMe()
      .then((u) => {
        this.applyUser(u);
        getApp<IAppOption>().globalData.user = u;
      })
      .catch(() => {});
  },

  applyUser(u: User | null) {
    this.setData({
      user: u,
      initial: u ? u.username.charAt(0).toUpperCase() : '',
    });
  },

  onCopyWeb() {
    wx.setClipboardData({
      data: BASE_URL,
      success: () => wx.showToast({ title: '已复制', icon: 'success' }),
    });
  },

  onLogout() {
    wx.showModal({
      title: '退出登录',
      content: '确定要退出当前账号吗？',
      confirmColor: '#007aff',
      success: (r) => {
        if (!r.confirm) return;
        clearAuth();
        getApp<IAppOption>().globalData.user = null;
        wx.reLaunch({ url: '/pages/login/login' });
      },
    });
  },
});
