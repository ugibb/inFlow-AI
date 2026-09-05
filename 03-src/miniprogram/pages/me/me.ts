import { api } from '../../utils/api';
import { getToken, getUser, clearAuth, getWxProfile, setWxProfile } from '../../utils/auth';
import { BASE_URL, APP_VERSION } from '../../config/index';

/**
 * 我的：微信头像昵称（绑定资料，未设置回退账号用户名）+ 编辑资料
 * （官方「头像昵称填写能力」）+ 退出登录 + 复制 Web 端地址。
 */
Page({
  data: {
    user: null as User | null,
    initial: '',
    profile: null as WxProfile | null,
    version: APP_VERSION,
    webUrl: BASE_URL,

    editing: false,
    editNickname: '',
    editAvatarSrc: '',
    saving: false,
  },

  /** 编辑中用户重选的头像临时文件（提交时读成 base64；空 = 保留旧头像） */
  avatarTmp: '',

  onShow() {
    if (!getToken()) {
      wx.reLaunch({ url: '/pages/login/login' });
      return;
    }
    this.setData({ profile: getWxProfile() });
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

  // ── 编辑资料（头像昵称填写能力）────────────────────────────

  onEditProfile() {
    const p = this.data.profile;
    this.avatarTmp = '';
    this.setData({
      editing: true,
      editNickname: (p && p.nickname) || '',
      editAvatarSrc: (p && p.avatar) || '',
    });
  },

  onEditChooseAvatar(e: any) {
    const url = e && e.detail && e.detail.avatarUrl;
    if (!url) return;
    this.avatarTmp = url;
    this.setData({ editAvatarSrc: url });
  },

  onEditNickname(e: any) {
    this.setData({ editNickname: e.detail.value });
  },

  onCancelEdit() {
    this.setData({ editing: false });
  },

  /** 头像临时文件 → base64（≤1MB；超限忽略，不阻断保存） */
  readAvatarBase64(): Promise<string> {
    const p = this.avatarTmp;
    if (!p) return Promise.resolve('');
    return new Promise((resolve) => {
      wx.getFileInfo({
        filePath: p,
        success: (info) => {
          if (info.size > 1024 * 1024) {
            wx.showToast({ title: '头像超过 1MB，已忽略', icon: 'none' });
            resolve('');
            return;
          }
          wx.getFileSystemManager().readFile({
            filePath: p,
            encoding: 'base64',
            success: (r) => resolve(r.data || ''),
            fail: () => resolve(''),
          });
        },
        fail: () => resolve(''),
      });
    });
  },

  async onSaveProfile() {
    if (this.data.saving) return;
    this.setData({ saving: true });
    try {
      const avatarBase64 = await this.readAvatarBase64();
      const res = await api.updateWxProfile({
        nickname: this.data.editNickname.trim(),
        avatarBase64,
      });
      setWxProfile(res);
      this.setData({ profile: res, editing: false, saving: false });
      wx.showToast({ title: '已保存', icon: 'success' });
    } catch (e: any) {
      this.setData({ saving: false });
      wx.showToast({ title: (e && e.message) || '保存失败', icon: 'none' });
    }
  },

  // ── 其他 ──────────────────────────────────────────────────

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
        const app = getApp<IAppOption>();
        app.globalData.user = null;
        app.globalData.authReady = Promise.resolve(null);
        wx.reLaunch({ url: '/pages/login/login' });
      },
    });
  },
});
