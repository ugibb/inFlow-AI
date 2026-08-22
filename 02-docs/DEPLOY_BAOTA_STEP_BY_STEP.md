# inFlow AI — 腾讯云宝塔部署「逐步操作手册」


> ⚠️ **本流程已废弃（2026-08-20）**：Docker 全容器部署形态已移除。
> 当前部署形态为「云端代码直跑 + 本地 worker」两个单元，见 [README「部署与运维」](../README.md#部署与运维云端)(云端)与独立仓库 [ugibb/inflow-worker](https://github.com/ugibb/inflow-worker)(本地 worker)。
> 本文档仅作历史参考；相关脚本可从 git 历史找回。

> **适用环境**：腾讯云 CVM / Lighthouse · **OpenCloudOS 9** · 宝塔 Linux 面板 **11.4.0 腾讯云专享版**  
> **预计耗时**：首次部署约 30–60 分钟（含 Docker 镜像构建 10–20 分钟）

本文档按时间顺序编写，**每一步都有具体操作**。请从上到下依次执行，不要跳步。

---

## 目录

1. [购买与登录服务器](#第-1-步购买并登录服务器)
2. [腾讯云安全组放行端口](#第-2-步腾讯云安全组放行端口)
3. [安装宝塔面板（若未安装）](#第-3-步安装宝塔面板若未安装)
4. [登录宝塔并完成初始化](#第-4-步登录宝塔并完成初始化)
5. [服务器本机防火墙放行](#第-5-步服务器本机防火墙放行)
6. [安装 Docker 与 Git](#第-6-步安装-docker-与-git)
7. [上传项目代码到服务器](#第-7-步上传项目代码到服务器)
8. [配置环境变量 .env](#第-8-步配置环境变量-env)
9. [构建并启动 Docker 服务](#第-9-步构建并启动-docker-服务)
10. [验证服务本机可访问](#第-10-步验证服务本机可访问)
11. [域名解析（有域名时）](#第-11-步域名解析有域名时)
12. [宝塔添加网站与反向代理](#第-12-步宝塔添加网站与反向代理)
13. [申请 SSL 证书并开启 HTTPS](#第-13-步申请-ssl-证书并开启-https)
14. [浏览器首次登录与配置](#第-14-步浏览器首次登录与配置)
15. [日常运维命令速查](#第-15-步日常运维命令速查)（详见 [DOCKER_OPS_GUIDE.md](./DOCKER_OPS_GUIDE.md)）
16. [故障排查](#第-16-步故障排查)

---

## 前置准备清单

开始前请确认：

| 项目 | 你是否已有 |
|------|-----------|
| 腾讯云账号 | ✅ |
| 一台 OpenCloudOS 9 云服务器（建议 4核 8GB，磁盘 ≥ 40GB） | ✅ |
| 服务器 root 密码或 SSH 密钥 | ✅ |
| 已备案域名（国内服务器访问需要） | 可选，也可用 IP 临时测试 |
| Git 仓库地址，或本地项目压缩包 | 二选一 |
| DeepSeek / SiliconFlow 等 API Key | 可部署后再在网页配置 |

---

## 第 1 步：购买并登录服务器

### 1.1 腾讯云控制台购买 CVM（若已有服务器跳过）

1. 打开 [腾讯云 CVM 控制台](https://console.cloud.tencent.com/cvm)
2. 点击 **新建** → 选择地域（建议选离你近的，如「上海」）
3. 镜像选择：**OpenCloudOS 9**
4. 规格：**4核 8GB** 内存（最低 4GB，但 8GB 更稳）
5. 系统盘：**50GB** 及以上 SSD
6. 设置 **root 密码** 并牢记
7. 完成购买，记录 **公网 IP**（下文用 `你的服务器IP` 代替）

### 1.2 SSH 登录服务器

**Mac / Linux 终端执行：**

```bash
ssh root@你的服务器IP
```

首次连接提示 `Are you sure you want to continue connecting?` 输入 `yes` 回车，再输入 root 密码。

**登录成功后，先确认系统版本：**

```bash
cat /etc/opencloudos-release
```

应看到类似 `OpenCloudOS release 9.x`。

**更新系统（建议执行一次）：**

```bash
dnf update -y
```

---

## 第 2 步：腾讯云安全组放行端口

### 2.1 控制台操作

1. 打开 [云服务器控制台](https://console.cloud.tencent.com/cvm/instance)
2. 找到你的实例 → 点击实例 ID 进入详情
3. 左侧或下方找到 **安全组** → 点击安全组 ID
4. 点击 **入站规则** → **添加规则**
5. 依次添加以下规则（来源均填 `0.0.0.0/0`，策略「允许」）：

| 类型 | 端口 | 说明 |
|------|------|------|
| 自定义 TCP | 22 | SSH |
| 自定义 TCP | 80 | HTTP |
| 自定义 TCP | 443 | HTTPS |
| 自定义 TCP | 8888 | 宝塔面板（安装后可能改端口，以实际为准） |

6. 点击 **保存**

> ⚠️ **不要**放行 8080、5432、6379、8000、3000 — 这些端口仅供服务器本机 Docker 内部使用。

---

## 第 3 步：安装宝塔面板（若未安装）

> 若宝塔 **11.4.0 已安装**，跳到 [第 4 步](#第-4-步登录宝塔并完成初始化)。

在 **SSH 终端**（已登录服务器）执行：

```bash
# 安装 wget
dnf install -y wget

# 下载并运行宝塔官方安装脚本（腾讯云专享版）
wget -O install.sh https://download.bt.cn/install/install_panel.sh && bash install.sh ed8484bec
```

安装过程约 5–10 分钟。完成后终端会输出类似：

```
==================================================================
Congratulations! Installed successfully!
==================================================================
外网面板地址: http://你的服务器IP:8888/xxxxxxxx
内网面板地址: http://10.x.x.x:8888/xxxxxxxx
username: xxxxxxxx
password: xxxxxxxx
```

**请立即复制并保存**：面板地址、用户名、密码。

---

## 第 4 步：登录宝塔并完成初始化

### 4.1 浏览器打开宝塔

在本地电脑浏览器访问：

```
http://你的服务器IP:8888/xxxxxxxx
```

（`xxxxxxxx` 为安装时给出的安全入口路径）

输入用户名和密码登录。

### 4.2 首次初始化向导

1. 弹出「推荐安装套件」时，选择 **LNMP** 或 **只装 Nginx**
2. **不要勾选 MySQL / PHP**（本项目不需要，数据库在 Docker 里）
3. 若已自动装了 MySQL 也没关系，不影响本项目，只是占资源
4. 等待 Nginx 安装完成（约 1–3 分钟）

### 4.3 绑定宝塔账号（可选）

按提示注册/绑定宝塔账号，可跳过。

---

## 第 5 步：服务器本机防火墙放行

回到 **SSH 终端** 执行：

```bash
# 查看 firewalld 状态
systemctl status firewalld

# 放行 Web 和宝塔端口
firewall-cmd --permanent --add-port=22/tcp
firewall-cmd --permanent --add-port=80/tcp
firewall-cmd --permanent --add-port=443/tcp
firewall-cmd --permanent --add-port=8888/tcp
firewall-cmd --reload

# 确认已放行
firewall-cmd --list-ports
```

**或在宝塔面板操作（二选一）：**

宝塔 → 左侧 **安全** → 添加端口规则：`80`、`443`、`8888` → 保存。

---

## 第 6 步：安装 Docker 与 Git

### 方式 A：宝塔图形界面（推荐）

1. 宝塔 → 左侧 **软件商店**
2. 搜索 **Docker 管理器** → 点击 **安装** → 等待完成
3. 搜索 **Git** → 点击 **安装** → 等待完成

### 方式 B：SSH 命令行（宝塔安装失败时用）

```bash
dnf install -y docker docker-compose-plugin git
systemctl enable --now docker
```

### 6.1 验证安装

```bash
docker --version
docker compose version
git --version
```

期望输出示例：

```
Docker version 26.x.x
Docker Compose version v2.x.x
git version 2.x.x
```

### 6.2 确认 Docker 服务运行中

```bash
systemctl status docker
docker info | head -5
```

若 `docker info` 报错，执行：

```bash
systemctl start docker
systemctl enable docker
```

### 6.3 配置 Docker 镜像加速（腾讯云必做）

国内 CVM 直连 `docker.io` 常超时（`i/o timeout`），构建前必须配置镜像加速与 DNS。

```bash
# 若已有 /etc/docker/daemon.json，先备份
cp /etc/docker/daemon.json /etc/docker/daemon.json.bak 2>/dev/null || true

cat > /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": [
    "https://mirror.ccs.tencentyun.com"
  ],
  "dns": ["119.29.29.29", "223.5.5.5", "8.8.8.8"]
}
EOF

systemctl daemon-reload
systemctl restart docker
```

验证加速是否生效：

```bash
docker info | grep -A3 "Registry Mirrors"
```

测试拉取基础镜像（应能在 30 秒内完成）：

```bash
docker pull node:20-alpine
docker pull python:3.11-slim
```

若仍超时，在腾讯云控制台检查：
- 安全组是否放行 **出站** 全部流量（或至少 TCP 443）
- 实例是否有公网 IP / 已绑定 NAT 网关

---

## 第 7 步：上传项目代码到服务器

### 方式 A：Git 克隆（推荐，有 Git 仓库时）

```bash
# 进入宝塔网站根目录
cd /www/wwwroot

# 克隆项目（把下面的地址换成你的仓库地址）
git clone https://github.com/你的用户名/你的仓库名.git inflow-ai

# 进入项目目录
cd inflow-ai

# 确认关键文件存在
ls -la docker-compose.yml deploy-baota.sh .env.example
ls -la 03-src/backend/Dockerfile 03-src/frontend/Dockerfile
```

### 方式 B：本地上传压缩包

**在你本地 Mac 终端执行**（把路径和 IP 换成你的）：

```bash
# 进入本地项目目录
cd /Users/你的用户名/Documents/01-CC/98-Content/g_20260615_ inFlow-ai

# 打包（排除大目录与本地数据）
tar czf /tmp/inflow-ai.tar.gz \
  --exclude='.venv' \
  --exclude='node_modules' \
  --exclude='03-src/frontend/.next' \
  --exclude='04-log' \
  --exclude='02-docs/data' \
  --exclude='02-docs/data-' \
  --exclude='03-src/backend/data' \
  --exclude='.git' \
  .

# 上传到服务器
scp /tmp/inflow-ai.tar.gz root@你的服务器IP:/www/wwwroot/
```

**回到服务器 SSH 执行：**

```bash
cd /www/wwwroot
mkdir -p inflow-ai
tar xzf inflow-ai.tar.gz -C inflow-ai
cd inflow-ai
ls -la docker-compose.yml deploy-baota.sh
```

---

## 第 8 步：配置环境变量 .env

在 **服务器 SSH** 中，确保当前目录为 `/www/wwwroot/inflow-ai`：

```bash
cd /www/wwwroot/inflow-ai
```

### 8.1 复制模板

```bash
cp .env.example .env
```

### 8.2 生成随机密码

```bash
# 生成数据库密码（复制输出结果备用）
openssl rand -base64 24

# 生成 JWT 密钥（复制输出结果备用）
openssl rand -base64 48
```

假设输出分别为：
- 数据库密码：`AbCdEf1234567890XyZ`
- JWT 密钥：`XyZ9876543210AbCdEfGhIjKlMnOpQrStUvWxYz`

### 8.3 编辑 .env 文件

```bash
vi .env
```

> vi 基本操作：按 `i` 进入编辑模式 → 改完后按 `Esc` → 输入 `:wq` 回车保存退出。  
> 若更习惯 nano：`nano .env`

找到并修改以下行（把占位符换成你刚生成的值）：

```env
POSTGRES_PASSWORD=AbCdEf1234567890XyZ
SECRET_KEY=XyZ9876543210AbCdEfGhIjKlMnOpQrStUvWxYz
```

可选，建议加上（登录 30 天不过期）：

```env
ACCESS_TOKEN_EXPIRE_DAYS=30
```

若有域名且已确定，可加（微信 Bot 用，暂时不用可不加）：

```env
inFlow_PUBLIC_BASE=https://你的域名.com
```

保存退出。

### 8.4 验证 .env 已正确设置

```bash
grep POSTGRES_PASSWORD .env
grep SECRET_KEY .env
```

确认不是 `change_me` 开头的占位符。

### 8.5（可选）初始化 LLM 配置文件

```bash
cp 03-src/backend/app/config_store.example.json 03-src/backend/app/config_store.json
```

> API Key 也可跳过此步，部署后在网页「设置」里配置。

---

## 第 9 步：构建并启动 Docker 服务

```bash
cd /www/wwwroot/inflow-ai

# 赋予部署脚本执行权限
chmod +x deploy-baota.sh

# 一键部署（首次会 build 镜像，约 10–20 分钟，请耐心等待）
./deploy-baota.sh
```

**或手动分步执行（与脚本等效）：**

```bash
cd /www/wwwroot/inflow-ai

docker compose -f docker-compose.yml -f docker-compose.baota.yml build

docker compose -f docker-compose.yml -f docker-compose.baota.yml up -d
```

构建过程中若看到 Playwright 下载 Chromium，属于正常现象，等待即可。

### 9.1 查看构建/启动进度

另开一个 SSH 窗口，实时看日志：

```bash
cd /www/wwwroot/inflow-ai
docker compose -f docker-compose.yml -f docker-compose.baota.yml logs -f
```

看到 backend、frontend 无报错后，按 `Ctrl+C` 退出日志跟踪。

---

## 第 10 步：验证服务本机可访问

```bash
cd /www/wwwroot/inflow-ai

# 查看所有容器状态（期望 5 个都是 Up）
docker compose -f docker-compose.yml -f docker-compose.baota.yml ps
```

期望看到：

```
NAME             STATUS
inFlow-nginx      Up
inFlow-backend    Up
inFlow-frontend   Up
inFlow-db         Up
inFlow-redis      Up
```

```bash
# 测试 HTTP 响应（期望返回 HTTP/1.1 200 或 307）
curl -I http://127.0.0.1:8080
```

**默认超管账号**（由数据库迁移 `001_add_user_auth.sql` 自动创建，**不会出现在 backend 日志**）：

| 用户名 | 密码 |
|--------|------|
| `weaiw` | `Aa41312432` |

登录后请立即修改密码。

若无法登录，在数据库中检查用户；若 `users` 表不存在，手动触发迁移：

```bash
docker compose -f docker-compose.yml -f docker-compose.baota.yml exec backend python -c "
import asyncio
import app.core.models
from app.core.database import init_db
asyncio.run(init_db())
"

docker compose -f docker-compose.yml -f docker-compose.baota.yml exec postgres \
  psql -U inFlow -d inFlow -c "SELECT username, is_super_admin, is_active FROM users;"
```

---

## 第 11 步：域名解析（有域名时）

> 若暂时没有域名，可先用 `http://你的服务器IP` 测试（需在第 12 步把站点绑定 IP）。有域名强烈建议配置。

### 11.1 在域名服务商添加 DNS 记录

登录你的域名注册商（腾讯云 DNSPod、阿里云万网等）：

| 记录类型 | 主机记录 | 记录值 |
|----------|----------|--------|
| A | `@` | 你的服务器IP |
| A | `www` | 你的服务器IP |

（若只用子域名，如 `inflow.example.com`，主机记录填 `inflow`）

### 11.2 验证解析生效

在本地 Mac 终端：

```bash
ping 你的域名.com
```

应解析到你的服务器 IP。

---

## 第 12 步：宝塔添加网站与反向代理

### 12.1 添加站点

1. 宝塔面板 → 左侧 **网站**
2. 点击 **添加站点**
3. 填写：
   - **域名**：`你的域名.com`（无域名则填 `你的服务器IP`）
   - **备注**：inFlow AI
   - **根目录**：默认 `/www/wwwroot/你的域名.com` 即可（不会直接用到，走反代）
   - **FTP**：不创建
   - **数据库**：不创建
   - **PHP 版本**：纯静态
4. 点击 **提交**

### 12.2 添加反向代理

1. 在网站列表找到刚创建的站点 → 点击 **设置**
2. 左侧菜单 → **反向代理**
3. 点击 **添加反向代理**
4. 填写：
   - **代理名称**：`inflow`
   - **目标 URL**：`http://127.0.0.1:8080`
   - **发送域名**：`$host`
   - 其余保持默认
5. 点击 **保存**

### 12.3 修改 Nginx 配置（大文件上传 + 长超时，必做）

1. 仍在站点 **设置** 中 → 左侧 **配置文件**
2. 在 `server { ... }` 块内找到 `location /` 或反代相关段落
3. 确保包含以下内容（若没有则添加；若已有 `location /` 则替换为下面版本）：

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

4. 点击 **保存**
5. 若提示重载 Nginx，点击 **重载配置**

### 12.4 验证反代是否生效

在本地浏览器访问：

```
http://你的域名.com
```

或

```
http://你的服务器IP
```

应看到 inFlow AI 登录页面。

若出现 **502**，回到 SSH 执行：

```bash
curl -I http://127.0.0.1:8080
docker compose -f docker-compose.yml -f docker-compose.baota.yml ps
```

---

## 第 13 步：申请 SSL 证书并开启 HTTPS

> 需要已备案域名。Let's Encrypt 无法给纯 IP 签发证书。

### 13.1 宝塔申请证书

1. 站点 **设置** → 左侧 **SSL**
2. 选择 **Let's Encrypt**
3. 勾选你的域名（如 `你的域名.com` 和 `www.你的域名.com`）
4. 点击 **申请**
5. 申请成功后，打开 **强制 HTTPS** 开关

### 13.2 验证 HTTPS

浏览器访问：

```
https://你的域名.com
```

地址栏应显示锁标志，页面正常加载。

---

## 第 14 步：浏览器首次登录与配置

### 14.1 登录

1. 打开 `https://你的域名.com`
2. 输入默认超管账号 **`weaiw` / `Aa41312432`**（见第 10 步）
3. 登录成功进入首页

### 14.2 配置 AI 模型（必做）

1. 点击右上角 **设置**（或侧边栏设置入口）
2. **AI 对话模型**：
   - 提供商：DeepSeek（或其他）
   - API Key：填入你的 Key
   - API Base：`https://api.deepseek.com/v1`
   - 模型：`deepseek-chat`
   - 点击 **测试连接** → 成功后 **保存**
3. **嵌入模型**：
   - 推荐 SiliconFlow 或本地模型
   - 填入 API Key → 测试 → 保存

### 14.3（可选）插件设置

**设置 → 插件设置**：

- YouTube 解析：按需开启
- 代理地址：国内访问 YouTube 需填代理
- ASR 语音转录：按需开启

### 14.4 测试核心功能

1. 在首页粘贴一篇文章链接 → 点击收藏
2. 等待 10–30 秒处理
3. 在 **书库** 中查看是否出现，是否有 AI 摘要

---

## 第 15 步：日常运维命令速查

> **完整运维手册**（改 Key、同步 Docker、验证、实时日志等 15 个独立场景）：见 **[DOCKER_OPS_GUIDE.md](./DOCKER_OPS_GUIDE.md)**

### 运维脚本速查

| 场景 | 命令 |
|------|------|
| 改 `.env` → 同步 Docker → 验证 Key | `./sync-env-docker.sh` |
| 仅验证 Key 是否生效 | `./verify-docker-keys.sh` |
| 实时查看运行日志 | `./logs-docker.sh` |
| 启动 / 更新部署 | `./start-docker.sh` |
| 停止全部容器 | `./stop-docker.sh` |

改 Key 标准流程：

```bash
cd /www/wwwroot/inflow-ai
vi .env && ./sync-env-docker.sh
```

两个 SSH 窗口（改配置 + 盯日志）：

```bash
# 窗口 1
vi .env && ./sync-env-docker.sh

# 窗口 2
./logs-docker.sh
```

### 设置别名（可选）

建议先设置别名，以后操作更方便。在 SSH 执行：

```bash
echo 'alias inflow="cd /www/wwwroot/inflow-ai && docker compose -f docker-compose.yml -f docker-compose.baota.yml"' >> ~/.bashrc
source ~/.bashrc
```

之后可用 `inflow` 代替长命令，例如 `inflow ps`、`inflow logs -f backend`。

### 查看状态

```bash
cd /www/wwwroot/inflow-ai
docker compose -f docker-compose.yml -f docker-compose.baota.yml ps
```

### 查看日志

```bash
# 推荐：项目脚本（默认 backend + wechat-bot 实时滚动）
./logs-docker.sh

# 仅后端
./logs-docker.sh backend

# 全部容器
./logs-docker.sh --all
```

等价于：

```bash
docker compose -f docker-compose.yml -f docker-compose.baota.yml logs -f backend
```

更多过滤、按容器查看见 [DOCKER_OPS_GUIDE.md 场景 10](./DOCKER_OPS_GUIDE.md#场景-10实时查看运行日志)。

### 改 `.env` 后同步配置

```bash
./sync-env-docker.sh
```

会自动重建 backend/wechat-bot 并验证 LLM / Embedding / GROQ Key。

### 重启服务

```bash
# 改 .env / Key 后（推荐）
./sync-env-docker.sh

# 仅重启 backend（不涉及 .env 变更时）
docker compose -f docker-compose.yml -f docker-compose.baota.yml restart backend

# 重启全部
docker compose -f docker-compose.yml -f docker-compose.baota.yml restart
```

### 停止 / 启动

```bash
./stop-docker.sh
./start-docker.sh --detach
```

### 更新版本

```bash
cd /www/wwwroot/inflow-ai
git pull
docker compose -f docker-compose.yml -f docker-compose.baota.yml build
docker compose -f docker-compose.yml -f docker-compose.baota.yml up -d
```

### 备份数据库

```bash
mkdir -p /www/backup
cd /www/wwwroot/inflow-ai
docker compose -f docker-compose.yml -f docker-compose.baota.yml exec -T postgres \
  pg_dump -U inflow inflow > /www/backup/inflow_$(date +%Y%m%d).sql
ls -lh /www/backup/
```

### 宝塔自动备份（计划任务）

1. 宝塔 → **计划任务** → **添加任务**
2. 任务类型：**Shell 脚本**
3. 任务名称：`inFlow 数据库备份`
4. 执行周期：每天凌晨 3 点
5. 脚本内容：

```bash
mkdir -p /www/backup
cd /www/wwwroot/inflow-ai
docker compose -f docker-compose.yml -f docker-compose.baota.yml exec -T postgres \
  pg_dump -U inflow inflow > /www/backup/inflow_$(date +\%Y\%m\%d).sql
find /www/backup -name "inflow_*.sql" -mtime +7 -delete
```

6. 保存

---

## 第 16 步：故障排查

### 问题：502 Bad Gateway

```bash
# 0. 确认 nginx 容器在运行（应有 5 个容器，含 inFlow-nginx）
cd /www/wwwroot/inflow-ai
docker compose -f docker-compose.yml -f docker-compose.baota.yml ps -a

# 若 inFlow-nginx 为 Exited 或未列出：
docker pull nginx:alpine
ls -la 03-src/nginx/nginx.conf
docker compose -f docker-compose.yml -f docker-compose.baota.yml up -d nginx
docker compose -f docker-compose.yml -f docker-compose.baota.yml logs --tail 50 nginx

# 1. 检查 Docker 容器
cd /www/wwwroot/inflow-ai
docker compose -f docker-compose.yml -f docker-compose.baota.yml ps

# 2. 检查本机 8080
curl -I http://127.0.0.1:8080

# 3. 查看后端错误
docker compose -f docker-compose.yml -f docker-compose.baota.yml logs --tail 100 backend
```

### 问题：容器 build 失败 / 内存不足

```bash
# 查看内存
free -h

# 若内存 < 4GB 可用，考虑升级配置，或降低 worker 数：
vi /www/wwwroot/inflow-ai/docker-compose.yml
# 将 backend 的 --workers 2 改为 --workers 1
```

### 问题：拉取镜像超时 `registry-1.docker.io ... i/o timeout`

说明 Docker 无法访问 Docker Hub，按 [第 6.3 步](#63-配置-docker-镜像加速腾讯云必做) 配置 `registry-mirrors` 后重试：

```bash
systemctl restart docker
cd /www/wwwroot/inflow-ai
docker pull node:20-alpine
docker pull python:3.11-slim
docker compose -f docker-compose.yml -f docker-compose.baota.yml build --no-cache
```

### 问题：`apk add` / DNS `transient error`

构建容器内 DNS 解析失败，确认 `daemon.json` 含 `dns` 字段（见第 6.3 步），重启 Docker 后重建。

### 问题：数据库连接失败

```bash
# 查看 backend 日志中的 database 相关错误
docker compose -f docker-compose.yml -f docker-compose.baota.yml logs backend | grep -i database
```

若 `.env` 中 `POSTGRES_PASSWORD` 改过但数据库 volume 是旧的，需重建（⚠️ **会删除所有数据**）：

```bash
cd /www/wwwroot/inflow-ai
docker compose -f docker-compose.yml -f docker-compose.baota.yml down -v
./deploy-baota.sh
```

### 问题：上传大文件失败

确认宝塔站点 Nginx 配置中有 `client_max_body_size 500m;`（见第 12.3 步）。

### 问题：LLM 测试连接失败

```bash
# 在容器内测试能否访问 DeepSeek
docker compose -f docker-compose.yml -f docker-compose.baota.yml exec backend \
  curl -I https://api.deepseek.com
```

---

## 部署完成检查清单

全部打勾即部署成功：

- [ ] `docker compose ps` 五个容器均为 Up
- [ ] `curl -I http://127.0.0.1:8080` 返回 200/307
- [ ] 浏览器可通过 `https://你的域名.com` 打开登录页
- [ ] 能用 admin 账号登录
- [ ] 设置页 AI 模型测试连接成功
- [ ] 收藏一篇测试文章能正常入库

---

## 相关文档

- [DEPLOY_BAOTA.md](./DEPLOY_BAOTA.md) — 架构说明与常见问题
- [SELF_HOST.md](./SELF_HOST.md) — 通用自托管指南
- Nginx 反代模板：`03-src/nginx/baota-site.conf`
