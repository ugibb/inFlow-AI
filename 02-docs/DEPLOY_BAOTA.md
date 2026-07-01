# inFlow AI — 腾讯云宝塔面板部署指南

适用于 **宝塔 Linux 面板 11.4.0 腾讯云专享版**（及其他 11.x 版本）。

> **OpenCloudOS 9 用户**：腾讯云 CVM 默认系统，与宝塔官方兼容列表一致（RHEL 9 系）。本项目数据库跑在 Docker 内的 PostgreSQL，**无需**在宝塔安装 MySQL/MariaDB，可避开 OpenCloudOS 9 上宝塔数据库软件的兼容性问题。详见下方 [OpenCloudOS 9 专项说明](#opencloudos-9-专项说明)。

## 架构说明

```
用户浏览器
    │
    ▼
宝塔 Nginx (:443 HTTPS)  ← 申请 SSL、域名绑定
    │  反向代理
    ▼
Docker Nginx (127.0.0.1:8080)  ← 不占用 80 端口，避免与宝塔冲突
    ├── Frontend (Next.js :3000)
    └── Backend  (FastAPI :8000)
            ├── PostgreSQL + pgvector
            └── Redis
```

**为什么不用宝塔直接跑 Node/Python？**  
本项目依赖 Playwright、pgvector、Redis 等组件，官方推荐 Docker 一键部署。Dockerfile 已内置腾讯云镜像源，在腾讯云 CVM 上构建速度更快。

---

## 一、服务器要求

| 项目 | 最低配置 | 推荐配置 |
|------|----------|----------|
| 云产品 | 腾讯云 Lighthouse / CVM | 4核 8GB |
| 内存 | **4 GB** | 8 GB |
| 磁盘 | **40 GB** | 80 GB SSD |
| 系统 | CentOS 7+ / Ubuntu 20.04+ / Debian 11+ / **OpenCloudOS 9** | **OpenCloudOS 9**（腾讯云默认） |
| 宝塔 | 11.x 腾讯云专享版 | 已安装 |

> 首次 `docker compose build` 约需 10–20 分钟（Playwright Chromium 下载占主要时间）。

---

## 二、腾讯云安全组

在 [腾讯云控制台](https://console.cloud.tencent.com/) → 云服务器 → 安全组，放行：

| 端口 | 用途 |
|------|------|
| 22 | SSH |
| 80 | HTTP（宝塔 Nginx / Let's Encrypt 验证） |
| 443 | HTTPS |
| 8888 | 宝塔面板（建议改端口并限制 IP） |

**不要**对公网开放 8080、5432、6379、8000、3000 — 这些仅本机 Docker 内部使用。

### OpenCloudOS 9 防火墙（firewalld）

OpenCloudOS 9 基于 RHEL 9，默认使用 `firewalld`。除腾讯云安全组外，还需在服务器本机放行：

```bash
# 查看已开放端口
firewall-cmd --list-ports

# 放行 Web 与宝塔面板（若尚未开放）
firewall-cmd --permanent --add-port=80/tcp
firewall-cmd --permanent --add-port=443/tcp
firewall-cmd --permanent --add-port=8888/tcp
firewall-cmd --reload
```

也可在宝塔 → **安全** 中一键放行，效果等同。

---

## 三、宝塔面板准备

### 3.1 安装 Docker

1. 宝塔面板 → **软件商店**
2. 搜索 **Docker 管理器** → 安装
3. SSH 验证：

```bash
docker --version
docker compose version
```

若宝塔安装 Docker 失败，可 SSH 手动安装（OpenCloudOS 9 用 `dnf`）：

```bash
dnf install -y docker docker-compose-plugin
systemctl enable --now docker
docker compose version
```

### 3.2 安装 Git（如未安装）

软件商店 → 搜索 **Git** → 安装；或：

```bash
dnf install -y git
```

> **无需安装**宝塔里的 MySQL / MariaDB / PostgreSQL — 数据库由 Docker 容器提供。

---

## 四、上传项目代码

### 方式 A：Git 克隆（推荐）

```bash
cd /www/wwwroot
git clone <你的仓库地址> inflow-ai
cd inflow-ai
```

### 方式 B：本地上传

1. 本地打包项目（排除 `.venv`、`node_modules`、`.next`）
2. 宝塔 → **文件** → 上传到 `/www/wwwroot/inflow-ai`
3. 解压

---

## 五、配置环境变量

```bash
cd /www/wwwroot/inflow-ai
cp .env.example .env
```

编辑 `.env`，**至少**设置：

```bash
# 生成强密码
openssl rand -base64 24   # → POSTGRES_PASSWORD
openssl rand -base64 48   # → SECRET_KEY
```

```env
POSTGRES_PASSWORD=你生成的数据库密码
SECRET_KEY=你生成的JWT密钥

# 可选：登录 Token 有效期（天），自托管建议 30
ACCESS_TOKEN_EXPIRE_DAYS=30

# 可选：公网访问地址（微信 Bot 深链接用）
TROVE_PUBLIC_BASE=https://你的域名.com
```

可选：预填 LLM 配置

```bash
cp 03-src/backend/app/config_store.example.json 03-src/backend/app/config_store.json
# 也可跳过，启动后在网页「设置」里配置
```

---

## 六、启动服务（宝塔模式）

```bash
cd /www/wwwroot/inflow-ai
chmod +x deploy-baota.sh
./deploy-baota.sh
```

或手动执行：

```bash
docker compose -f docker-compose.yml -f docker-compose.baota.yml build
docker compose -f docker-compose.yml -f docker-compose.baota.yml up -d
```

验证本机可访问：

```bash
curl -I http://127.0.0.1:8080
docker compose -f docker-compose.yml -f docker-compose.baota.yml ps
```

查看首次管理员账号：

```bash
docker compose -f docker-compose.yml -f docker-compose.baota.yml logs backend | grep -i admin
```

---

## 七、宝塔配置域名 + HTTPS

### 7.1 添加站点

1. 宝塔 → **网站** → **添加站点**
2. 域名：填写你的域名（如 `inflow.example.com`）
3. PHP 版本：选 **纯静态** 或不创建 PHP
4. 数据库：不需要（数据库在 Docker 内）

### 7.2 配置反向代理

1. 站点 → **设置** → **反向代理** → **添加反向代理**
2. 代理名称：`inflow`
3. 目标 URL：`http://127.0.0.1:8080`
4. 发送域名：`$host`
5. 保存

### 7.3 高级配置（重要）

站点 → **设置** → **配置文件**，在 `server { }` 块内确保包含：

```nginx
client_max_body_size 500m;

location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_cache_bypass $http_upgrade;
    proxy_read_timeout 600s;
    proxy_connect_timeout 600s;
    proxy_send_timeout 600s;
}
```

完整模板见：`03-src/nginx/baota-site.conf`

### 7.4 申请 SSL 证书

1. 站点 → **设置** → **SSL**
2. 选择 **Let's Encrypt** → 申请
3. 开启 **强制 HTTPS**

### 7.5 域名解析

在域名服务商添加 A 记录，指向服务器公网 IP。

---

## 八、首次使用

1. 浏览器访问 `https://你的域名.com`
2. 用 `docker compose logs backend | grep admin` 中的账号登录
3. **设置 → AI 对话模型**：配置 DeepSeek / 讯飞等 API Key
4. **设置 → 嵌入模型**：推荐 SiliconFlow 或本地模型
5. （可选）**设置 → 插件设置**：YouTube 代理、ASR 转录开关

---

## 九、日常运维

```bash
cd /www/wwwroot/inflow-ai
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.baota.yml"

# 查看日志
$COMPOSE logs -f backend
$COMPOSE logs -f frontend

# 重启单个服务
$COMPOSE restart backend

# 更新版本
git pull
$COMPOSE build
$COMPOSE up -d

# 备份数据库
$COMPOSE exec postgres pg_dump -U trove trove > backup_$(date +%Y%m%d).sql

# 恢复数据库
$COMPOSE exec -T postgres psql -U trove trove < backup_20260701.sql

# 停止服务
$COMPOSE down
```

### 宝塔计划任务（自动备份）

宝塔 → **计划任务** → 添加 Shell 脚本，每天执行：

```bash
cd /www/wwwroot/inflow-ai
docker compose -f docker-compose.yml -f docker-compose.baota.yml exec -T postgres \
  pg_dump -U trove trove > /www/backup/inflow_$(date +\%Y\%m\%d).sql
```

---

## 十、常见问题

| 现象 | 原因与处理 |
|------|-----------|
| OpenCloudOS 9 宝塔装 MySQL 失败 | **与本项目无关** — 我们用 Docker 内 PostgreSQL，跳过宝塔数据库即可 |
| Docker 构建报权限错误 | `sudo usermod -aG docker $USER` 后重新登录；或 `sudo ./deploy-baota.sh` |
| SELinux 阻止容器挂载 | 少见；若遇 `Permission denied` 挂载 volume：`setenforce 0`（临时）或配置 SELinux 上下文 |
| 502 Bad Gateway | `curl http://127.0.0.1:8080` 失败 → 检查 Docker 容器是否运行；`$COMPOSE logs backend` |
| 宝塔 80 端口冲突 | 必须使用 `docker-compose.baota.yml`，不要直接 `docker compose up`（会占 80 端口） |
| 上传大文件失败 | 宝塔 Nginx 和 Docker Nginx 均需 `client_max_body_size 500m` |
| 构建超时 / 极慢 | Dockerfile 已配置腾讯云镜像；确认服务器在腾讯云境内 |
| 数据库连接失败 | `.env` 中 `POSTGRES_PASSWORD` 与已有 volume 不一致 → 需 `down -v` 重建（⚠️ 丢数据） |
| LLM 测试失败 | 容器内测试：`$COMPOSE exec backend curl -I https://api.deepseek.com` |
| 内存不足 OOM | 升级至 8GB；或减少 backend workers（docker-compose.yml 中 `--workers 1`） |

---

## OpenCloudOS 9 专项说明

腾讯云 CVM 默认系统 **OpenCloudOS Server 9**（RHEL 9 系）部署本项目的要点：

| 项目 | 说明 |
|------|------|
| 包管理器 | 使用 `dnf`（`yum` 通常为 dnf 别名） |
| 宝塔兼容性 | 官方兼容列表包含 OpenCloudOS 9，11.4 腾讯云专享版可直接用 |
| 数据库 | **只用 Docker 内 PostgreSQL**，不要在宝塔装 MySQL — OpenCloudOS 9 上部分 MySQL 版本有兼容报错 |
| 防火墙 | 腾讯云安全组 + 本机 `firewalld` 双重放行 80/443 |
| Docker 镜像加速 | Dockerfile 已配置 `mirrors.tencent.com`，境内构建无需额外设置 |
| 系统更新 | 建议部署前执行 `dnf update -y`，保持内核与依赖最新 |

**推荐最小软件栈（宝塔侧）**：

- ✅ Nginx（宝塔自带，做反向代理 + SSL）
- ✅ Docker 管理器
- ✅ Git
- ❌ MySQL / MariaDB / PHP（不需要）
- ❌ 宝塔 PostgreSQL（不需要，用 Docker 内的）

**一键检查环境**（SSH 执行）：

```bash
# 系统版本
cat /etc/opencloudos-release 2>/dev/null || cat /etc/os-release

# Docker 是否就绪
docker info >/dev/null 2>&1 && echo "Docker OK" || echo "Docker 未安装或未启动"

# 端口 8080 是否被占用（部署前应为空）
ss -tlnp | grep 8080 || echo "8080 可用"
```

---

## 十一、微信 Bot（可选）

1. 在 `.env` 设置 `SERVICE_TOKEN_WECHAT_BOT` 和 `TROVE_PUBLIC_BASE`
2. 编辑 `docker-compose.yml`，取消 `wechat-bot` 服务注释
3. `$COMPOSE up -d wechat-bot`

---

## 十二、卸载

```bash
cd /www/wwwroot/inflow-ai
docker compose -f docker-compose.yml -f docker-compose.baota.yml down -v  # ⚠️ -v 删除数据库
```

宝塔中删除对应站点和反向代理配置。

---

## 相关文档

- **[DEPLOY_BAOTA_STEP_BY_STEP.md](./DEPLOY_BAOTA_STEP_BY_STEP.md)** — ⭐ 逐步操作手册（含每一步命令与面板点击）
- [SELF_HOST.md](./SELF_HOST.md) — 通用自托管指南
- [README.zh.md](../README.zh.md) — 项目功能说明
