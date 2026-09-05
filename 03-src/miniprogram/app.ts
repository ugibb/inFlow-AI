import { validateStored, silentWechatLogin, getUser } from './utils/auth';
import { logInfo } from './utils/log';

// app.ts —— 全局入口：onLaunch 启动鉴权（翻译 Web AuthContext 的乐观恢复时序）。
// 本地 token 缺失/失效时回落「静默微信登录」：已绑定 openid 自动换新 JWT
// 直进首页（无感）；要求邀请码/失败才由页面守卫带去登录页。
App<IAppOption>({
  globalData: {
    user: null,
    authReady: null,
    wechatNeedInvite: false,
  },

  onLaunch() {
    logInfo('app', 'launch');
    this.globalData.authReady = validateStored((u) => {
      this.globalData.user = u;
    }).then((token) => {
      if (token) return token;
      return silentWechatLogin().then((r) => {
        if (r && 'token' in r) {
          this.globalData.user = getUser();
          logInfo('app', 'silent wechat login ok');
          return r.token;
        }
        if (r && r.invite) this.globalData.wechatNeedInvite = true;
        return null;
      });
    });
  },
});
