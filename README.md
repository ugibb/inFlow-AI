<div align="center">

# inFlow AI — 入流


[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)]
[![后端: FastAPI](https://img.shields.io/badge/后端-FastAPI-009688)](https://fastapi.tiangolo.com)
[![前端: Next.js 14](https://img.shields.io/badge/前端-Next.js%2014-black)](https://nextjs.org)
[![pgvector](https://img.shields.io/badge/向量-pgvector-336791)](https://github.com/pgvector/pgvector)
[![全端兼容: PC · Pad · 移动端](https://img.shields.io/badge/全端兼容-PC%20·%20Pad%20·%20移动端-007aff)]()
[![Status: active](https://img.shields.io/badge/状态-持续更新-success.svg)]()

[部署与运维](#部署与运维云端) · [Obsidian 插件](https://github.com/weaiw/inFlow-sync-obsidian)

</div>

---

## 为什么用 inFlow AI?

---

## 核心亮点


---

## 截图

> ⚠️ 截图待补,放到 `docs/screenshots/` 即可。


---

## 适合谁用?

- **产品经理 / 研究者** —— 收藏夹堆成山,真正读过的不到 5%
- **工程师 / 终身学习者** —— 希望每周收藏的标签最终能沉淀成体系
- **隐私敏感的用户** —— 不想阅读习惯被存在某个创业公司服务器上
- **内容策展者** —— 想搭建结构化个人知识库
- **自部署爱好者** —— 喜欢自己跑自己基础设施的人
- **跨设备阅读者** —— 手机通勤、iPad 沙发、笔记本桌前来回切,希望三端都顺手

---

## 与同类产品对比


---

## 快速开始(5 分钟)

### 前置要求

inFlow 的部署形态为两个物理独立的单元:

- **云端单元**(本仓库根,启停脚本 `./start-server.sh` / `./stop-server.sh`):服务器代码直跑 backend + wechat-bot,仅基础设施(postgres / redis / nginx / frontend)走容器;后端单包 `03-src/backend`(core 引擎已并入,import 前缀 `backend.*`)
- **本地 worker**(**独立仓库** [ugibb/inflow-worker](https://github.com/ugibb/inflow-worker),可选):Mac 直连云端 PostgreSQL 轮询认领任务,承接播客等重计算 pipeline;与本仓库无代码依赖,见独立仓库 README

**云端单元**

- **Python 3.10+**(跑 backend / bot)、**Docker** ≥ 24.0 带 Compose v2(仅跑 infra 容器)
- 约 **4 GB 内存**、**5 GB 磁盘**

**本地 worker(可选)**

- macOS + **Python 3.10+**、ffmpeg;可访问外网 AI API(Groq 等)
- 详见独立仓库 **[ugibb/inflow-worker](https://github.com/ugibb/inflow-worker)** 的 README

### 步骤(云端)

---

## 架构

```
        ┌──────────────────────────────────────────────────────┐
        │      任意设备 — PC · iPad · 手机 · 浏览器             │
        │   • 网页 App · 微信 Bot · Obsidian 插件               │
        └─────────────────────────┬────────────────────────────┘
                                  │
                          ┌───────▼───────┐
                          │  Nginx :80    │
                          └───┬────────┬──┘
                              │        │
                  ┌───────────▼──┐  ┌──▼────────────┐
                  │  前端        │  │  后端         │
                  │  Next.js 14  │  │  FastAPI      │
                  │  响应式      │  │  async        │
                  └──────────────┘  └───┬────────────┘
                                        │
                  ┌─────────────────────┼─────────────────────┐
                  │                     │                     │
        ┌─────────▼──────────┐ ┌────────▼───────┐  ┌──────────▼────────┐
        │  PostgreSQL 16     │ │  Redis 7       │  │ 外部 API          │
        │  + pgvector        │ │  (缓存)        │  │ LLM + 嵌入        │
        │  • articles        │ │                │  │ • DeepSeek        │
        │  • embeddings 1024 │ │                │  │ • 讯飞 / OpenAI   │
        │  • knowledge_edges │ │                │  │ • SiliconFlow     │
        │  • users + tokens  │ │                │  │ • 任意 兼容厂商   │
        └────────────────────┘ └────────────────┘  └───────────────────┘
```

### 技术栈



---

## 配置

所有用户面对的配置都通过网页 UI 完成:

**设置页** → AI 对话模型 / 嵌入模型 / 系统缓存

| 什么 | 在哪里 |
|------|--------|

### 环境变量

| 变量 | 必填 | 用途 |
|------|------|------|

完整模板见 `.env.example`。

### 登录与会话


---

## API 端点速查

| 端点 | 用途 |


---

## Obsidian 同步插件

插件仓库:**[weaiw/inFlow-sync-obsidian](https://github.com/weaiw/inFlow-sync-obsidian)**(MIT)

**一次性快照到本地 vault。** 永不覆盖你的本地修改。哪天产品没了,你的数据还在。

使用流程:

1. 网页 → **个人设置 → Obsidian 备份 → 生成本地同步 Token**
2. 从 [Releases](https://github.com/weaiw/inFlow-sync-obsidian/releases/latest) 下载插件
3. 解压到 `<your-vault>/.obsidian/plugins/inFlow-sync/`
4. Obsidian → 社区插件 → 启用 **inFlow AI Sync**
5. 粘贴 Token + 服务器地址 → 点 **Sync Now**

插件用「sync_state.json ∪ frontmatter 扫描」双重 OR 判定"已同步",两边丢任意一边都不会重复同步。

---

## 文档

- 本 README [部署与运维](#部署与运维云端) 章节 — 云端部署;本地 worker 部署见独立仓库 [ugibb/inflow-worker](https://github.com/ugibb/inflow-worker)
- API 文档:`/api/docs`(FastAPI 自动生成)

---

## 路线图

### v1.0 — 当前版本
- ✅ 全平台采集(8+ 来源)
- ✅ AI 处理流水线(摘要 / 关键点 / 标签 / 嵌入 / 思维导图)
- ✅ RAG 问答 + 语义搜索
- ✅ 自动知识图谱 + 学习路径
- ✅ 微信 Bot 入口
- ✅ Obsidian 同步插件
- ✅ 多租户 + 可撤销同步 Token
- ✅ Docker 自部署
- ✅ PC / pad / 移动端响应式 UI

### v1.1
- 🔜 浏览器扩展(任意标签一键收藏)
- 🔜 图片本地下载(完全离线备份)
- 🔜 Pocket / Omnivore 导入
- 🔜 文章去重增强
- 🔜 PWA 支持(手机"添加到主屏幕")

### v1.2
- 更多 LLM 厂商(Claude · Gemini · 豆包原生)
- 用户主题与语言偏好
- 批量重新处理文章(用新 AI Prompt)
- 文章版本历史

### v2 — 研究中
- Obsidian 社区市场提交
- 多 vault Obsidian 同步
- Notion · Logseq · Reflect 导出
- 音频播客生成
- 每日 / 每周摘要邮件

---

## 常见问题


---

## 贡献

欢迎开 issue / PR。特别欢迎:
- 新平台解析器(parser_service.py)
- 翻译(English · 日本語 · 其他)
- UI 打磨与无障碍优化
- 带复现步骤的 bug 报告
- 不同 LLM 厂商的对比测试

---

## 致谢

- 用 **[Hermes](https://hermes.ai)** AI 编程助手 + **[DeepSeek](https://www.deepseek.com)** 作为 LLM 大脑 vibe-code 出来——共消耗 **27 亿 token**,0 行人写代码
- 后端:[FastAPI](https://fastapi.tiangolo.com) · [SQLAlchemy](https://www.sqlalchemy.org) · [pgvector](https://github.com/pgvector/pgvector) · [Playwright](https://playwright.dev) · [curl_cffi](https://github.com/lexiforest/curl_cffi)
- 前端:[Next.js](https://nextjs.org) · [Tailwind](https://tailwindcss.com) · [lucide-react](https://lucide.dev) · [react-flow](https://reactflow.dev)
- 嵌入:[BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) · [fastembed](https://github.com/qdrant/fastembed)
- 灵感来自 **Pocket** · **Omnivore** · **Readwise**——也因为前两个的关停而暴起做这件事

---

## License

主仓:**AGPL-3.0**。
Obsidian 插件:[MIT](https://github.com/weaiw/inFlow-sync-obsidian/blob/main/LICENSE)。

闭源 SaaS 商业部署,联系维护者获取商业授权。

---

<div align="center">

</div>
