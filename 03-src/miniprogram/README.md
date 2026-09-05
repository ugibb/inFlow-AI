# inFlow 微信小程序（浏览 + 阅读 MVP）

原生小程序（WXML/WXSS/TypeScript，运行时零 npm 依赖），API 100% 复用后端 `https://inflow.huituai.site`，后端零改动。方案见 `02-docs/20260905_微信小程序MVP方案.md`。

## 开发调试

1. 微信开发者工具 → 导入项目 → 选择本目录
2. AppID 选「测试号」（或使用 `project.config.json` 里的 `touristappid` 游客模式）；**正式注册后替换 `project.config.json` 的 `appid` 即可**
3. 详情 → 本地设置 → 勾选「不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书」（开发期）
4. TypeScript 由开发者工具直接编译（`useCompilerPlugins`），无需本地构建

本地类型检查（可选，需先 `npm install`）：

```bash
npm run typecheck
```

## 结构

```
config/index.ts          BASE_URL / 分页 / 代理域名白名单 / 平台文案与渐变（换环境只改这里）
typings/api.d.ts         全局类型（对齐 backend/core/schemas）
utils/request.ts         wx.request 封装：token 注入、401 统一跳登录、FastAPI detail 提取
utils/auth.ts            token 存取（inflow_token）、JWT exp 本地预检、启动鉴权
utils/api.ts             类型化 API 薄封装
utils/image-url.ts       resolveImage() —— 防盗链图片统一改写走后端代理（全项目唯一改写点）
utils/masonry.ts         瀑布流最短列分发（翻译 Web 算法）
utils/markdown.ts        简易 Markdown 解析器（md-view 用）
components/              article-card / md-view / chapter-list / transcript-view / empty-state
pages/                   library（首页 tab）/ read（阅读+分享）/ login / me
```

## 上线前置（个人主体）

1. 注册个人主体小程序（mp.weixin.qq.com）→ 替换 `project.config.json` 的 `appid`
2. 核实 `inflow.huituai.site` ICP 备案（request 合法域名强制要求）
3. 完成小程序自身备案（2023-09 起新注册小程序必须，约 1-2 周）
4. mp 平台 → 开发管理 → 开发设置 → 服务器域名 → request 合法域名加 `https://inflow.huituai.site`
5. 类目建议「工具 > 效率」，名称/简介规避「资讯/媒体/社区」字样
