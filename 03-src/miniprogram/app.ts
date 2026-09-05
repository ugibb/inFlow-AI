import { validateStored } from './utils/auth';
import { logInfo } from './utils/log';

// app.ts —— 全局入口：onLaunch 里做一次启动鉴权（翻译 Web AuthContext 的乐观恢复时序）
App<IAppOption>({
  globalData: {
    user: null,
    authReady: null,
  },

  onLaunch() {
    logInfo('app', 'launch');
    this.globalData.authReady = validateStored((u) => {
      this.globalData.user = u;
    });
  },
});
