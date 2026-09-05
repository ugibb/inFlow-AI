import { api } from '../../utils/api';
import { setAuth, setWxProfile, wxLoginCode } from '../../utils/auth';
import { logInfo } from '../../utils/log';
import { BASE_URL } from '../../config/index';

/**
 * 登录页：微信一键登录为主（首次绑定可顺手填头像昵称——官方「填写能力」），
 * 账号密码折叠保留（管理员兜底，与 Web 端同一账号体系）。
 * 默认（后端未设邀请码）形态下静默链直接成功，本页几乎不会被看到。
 */
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
    // 微信一键登录（首次绑定：头像昵称选填）
    nickname: '',
    avatarTmp: '',
    avatarInitial: '',
    inviteCode: '',
    needInvite: false,
    wxSubmitting: false,

    // 账号密码（折叠）
    showPw: false,
    username: '',
    password: '',
    submitting: false,

    error: '',
    serverUrl: BASE_URL,
  },

  redirect: '',
  /** chooseAvatar 给的临时文件路径（提交时读成 base64） */
  avatarTmp: '',

  onLoad(options: Record<string, string | undefined>) {
    this.redirect = decodeRedirect((options && options.redirect) || '');
    // 静默登录被要求邀请码时，app 已置 flag —— 直接展开邀请码输入
    if (getApp<IAppOption>().globalData.wechatNeedInvite) {
      this.setData({ needInvite: true });
    }
  },

  // ── 微信一键登录 ────────────────────────────────────────────

  onChooseAvatar(e: any) {
    const url = e && e.detail && e.detail.avatarUrl;
    if (!url) return;
    this.avatarTmp = url;
    this.setData({ avatarTmp: url });
  },

  onNickname(e: any) {
    const v = String(e.detail.value || '');
    this.setData({ nickname: v, avatarInitial: v.trim().charAt(0).toUpperCase() });
  },

  onInvite(e: any) {
    this.setData({ inviteCode: e.detail.value, error: '' });
  },

  /** 头像临时文件 → base64（≤1MB；超限忽略，头像为选填不阻断） */
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

  async onWechatLogin() {
    if (this.data.wxSubmitting) return;
    this.setData({ wxSubmitting: true, error: '' });
    try {
      const code = await wxLoginCode();
      const avatarBase64 = await this.readAvatarBase64();
      const res = await api.wechatLogin(code, {
        inviteCode: this.data.inviteCode.trim(),
        nickname: this.data.nickname.trim(),
        avatarBase64,
      });
      logInfo('auth', 'wechat login ok', { user: res.user && res.user.username });
      setAuth(res.access_token, res.user);
      setWxProfile(res.wx_profile || null);
      // 启动 authReady 可能已 settle 为 null，必须刷新（否则 reLaunch 回来的页面误弹回登录页）
      const app = getApp<IAppOption>();
      app.globalData.user = res.user;
      app.globalData.authReady = Promise.resolve(res.access_token);
      app.globalData.wechatNeedInvite = false;
      wx.reLaunch({ url: this.redirect || '/pages/library/library' });
    } catch (e: any) {
      const msg = (e && e.message) || '登录失败';
      const patch: Record<string, unknown> = { wxSubmitting: false };
      if (msg === 'invite_required') {
        patch.needInvite = true;
        patch.error = '首次使用请输入邀请码';
      } else if (msg === 'invite_invalid') {
        patch.needInvite = true;
        patch.error = '邀请码不正确';
      } else {
        patch.error = msg;
      }
      this.setData(patch);
    }
  },

  // ── 账号密码（折叠兜底）────────────────────────────────────

  onTogglePw() {
    this.setData({ showPw: !this.data.showPw, error: '' });
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
      logInfo('auth', 'login ok', { user: res.user && res.user.username });
      setAuth(res.access_token, res.user);
      const app = getApp<IAppOption>();
      app.globalData.user = res.user;
      app.globalData.authReady = Promise.resolve(res.access_token);
      wx.reLaunch({ url: this.redirect || '/pages/library/library' });
    } catch (e: any) {
      this.setData({ submitting: false, error: (e && e.message) || '登录失败' });
    }
  },
});
