# inFlow AI — Docker 运维手册

> 环境：腾讯云 + 宝塔 + Docker  
> 项目路径：`/www/wwwroot/inflow-ai`  
> 域名：`https://inflow.huituai.site`  
> 首次部署见：[DEPLOY_BAOTA_STEP_BY_STEP.md](./DEPLOY_BAOTA_STEP_BY_STEP.md)

每个场景均可**独立执行**——从该场景的起点到验证完成，无需先跑其他场景。  
涉及代码上线的场景（场景 1、2）内含 Mac 打包上传步骤；Git 拉取类（场景 11、12）在服务器直接 `git pull`；纯配置 / 运维类仅在服务器操作。

---

## 通用约定

**服务器项目根目录：**

```bash
cd /www/wwwroot/inflow-ai
```

**服务器：任意场景执行 Docker 命令前，先运行（路径为绝对路径，与当前目录无关）：**

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"
```

之后本文中的 `$COMPOSE exec …` / `$COMPOSE ps` 可直接使用（无需再次 `cd`，但建议保持 `cd /www/wwwroot/inflow-ai` 以免相对路径脚本出错）。

**本地项目根目录（下文** `$LOCAL_ROOT`**）：**

```bash
LOCAL_ROOT="/Users/zhouhanbao/Documents/01-CC/98-Content/g_20260615_inFlow-ai"
```

**压缩包约定（Mac → 服务器）：**

| 项 | 路径 |
| --- | --- |
| 本地打包输出 | `/tmp/inflow-ai-deploy.tar.gz` |
| 上传到服务器（固定） | `/www/wwwroot/inflow-ai-deploy.tar.gz` |
| 解压到项目目录 | `/www/wwwroot/inflow-ai/` |

压缩包**不含** `.env`、`03-src/backend/data`、`.git`（防泄露、防覆盖服务器密码、避免把本地数据打进包）。

**全局注意：**

- **不要改** `POSTGRES_PASSWORD`（首次部署后修改会导致与数据卷不一致）
- **不要用** `docker compose down -v`（会删 PostgreSQL 数据卷）
- **不要用** `docker compose restart` 代替发版（只重启容器，**不会**用新源码重新编译 frontend）
- 代码更新后必须用 `./start-docker.sh --restart --detach` 或 `./sync-env-docker.sh`（内含 `--build --force-recreate`）
- LLM Key 优先级：网页「设置」`config_store.json` > `.env` > 默认值
- Pipeline 文件（`01_ingest` / `02_parse` / `03_display`）由 `.env` 中 `INFLOW_PIPELINE_DATA_DIR` 挂载到容器 `/app/data`，**backend 与 wechat-bot 必须共享**；生产固定为 `/www/data/inflow/pipeline`（**在项目目录外**，清空 `inflow-ai/` 不会删掉 pipeline 文件）；架构见 [20260702_09_Pipeline存储架构与实施路线.md](./20260702_09_Pipeline存储架构与实施路线.md)

**清空 `/www/wwwroot/inflow-ai/` 时：**

| 会保留 | 会丢失（需先备份） |
| --- | --- |
| `/www/data/inflow/pipeline`（pipeline 采集文件） | `.env` |
| Docker 卷 `pgdata`（PostgreSQL 库） | `03-src/backend/app/config_store.json`（网页「设置」） |
| `/www/backup/` 下的 SQL 备份 | 项目内 `03-src/backend/data`（若未配置独立 pipeline 目录） |
| `/tmp/inflow.env.bak` 等手动备份 | 旧 Docker 镜像（需 `--build` 才会用新源码编译） |

> 执行 `docker compose` / `$COMPOSE exec` 前必须先 `cd /www/wwwroot/inflow-ai`，并设置上文 **export COMPOSE=…**（绝对路径）。在 `/root` 等其它目录直接运行会报 `open /root/docker-compose.yml`。
>
> **压缩包发版**推荐 [场景 2](#场景-2压缩包更新代码保留数据) 的一键脚本 `./deploy-update-server.sh`；手动步骤见该场景折叠区。

---



## 场景索引


| 场景                               | 说明                    | 操作位置      |
| -------------------------------- | --------------------- | --------- |
| [场景 1](#场景-1首次部署)                | 首次部署（打包上传 + 服务器初始化）   | Mac + 服务器 |
| [场景 2](#场景-2压缩包更新代码保留数据)         | 压缩包更新代码（打包上传 + 保留数据）  | Mac + 服务器 |
| [场景 3](#场景-3改-env-并同步--验证-key)   | 改 `.env` 并同步 + 验证 Key | 服务器       |
| [场景 4](#场景-4批量更换-api-key)        | 批量更换 API Key          | 服务器       |
| [场景 5](#场景-5全量更新-env)            | 全量更新 `.env`           | 服务器       |
| [场景 6](#场景-6轮换-secret_key)       | 轮换 SECRET_KEY         | 服务器       |
| [场景 7](#场景-7更换微信-bot-token)      | 更换微信 Bot Token        | 服务器       |
| [场景 8](#场景-8本地-env-同步到服务器)       | 本地 `.env` 同步到服务器      | Mac + 服务器 |
| [场景 9](#场景-9仅验证-key不重启)          | 仅验证 Key（不重启）          | 服务器       |
| [场景 10](#场景-10实时查看运行日志)          | 实时查看运行日志              | 服务器       |
| [场景 11](#场景-11git-更新代码无表结构变更)    | Git 更新代码（无表结构变更）      | 服务器       |
| [场景 12](#场景-12git-更新代码--数据库表结构)  | Git 更新代码 + 数据库表结构     | 服务器       |
| [场景 13](#场景-13启动--停止--健康检查)      | 启动 / 停止 / 健康检查        | 服务器       |
| [场景 14](#场景-14备份数据库)             | 备份数据库                 | 服务器       |
| [场景 15](#场景-15故障排查)              | 故障排查                  | 服务器       |
| [场景 16](#场景-16pipeline-存储迁移阶段-1) | Pipeline 存储迁移（阶段 1）   | 服务器       |


---



## 场景 1：首次部署

**何时使用：** 服务器上第一次部署 inFlow AI，尚无 `inflow-ai` 目录或尚无 `.env`。

### 步骤一：本地 Mac 打包并上传

```bash
LOCAL_ROOT="/Users/zhouhanbao/Documents/01-CC/98-Content/g_20260615_inFlow-ai"
cd "${LOCAL_ROOT}"

# 打包前抽检：若仍含开发向文案，说明本地文件未保存或目录不对，不要上传
grep -q 'start-local\.sh' 03-src/frontend/src/components/WechatBinding.tsx \
  && echo '❌ WechatBinding 仍是旧文案，请保存文件后重试' \
  || echo '✓ 前端文案检查通过'

rm -f /tmp/inflow-ai-deploy.tar.gz

tar czf /tmp/inflow-ai-deploy.tar.gz \
  --exclude='.venv' \
  --exclude='node_modules' \
  --exclude='03-src/frontend/node_modules' \
  --exclude='03-src/frontend/.next' \
  --exclude='04-log' \
  --exclude='02-docs/data' \
  --exclude='02-docs/data-' \
  --exclude='03-src/backend/data' \
  --exclude='.git' \
  --exclude='.env' \
  .

ls -lh /tmp/inflow-ai-deploy.tar.gz

tar tzf /tmp/inflow-ai-deploy.tar.gz deploy-update-server.sh start-docker.sh

# 固定上传到 /www/wwwroot/
scp /tmp/inflow-ai-deploy.tar.gz root@你的服务器IP:/www/wwwroot/inflow-ai-deploy.tar.gz
```

验证上传成功：

```bash
ssh root@你的服务器IP "ls -lh /www/wwwroot/inflow-ai-deploy.tar.gz"
```

### 步骤二：服务器解压并初始化部署

```bash
cd /www/wwwroot
mkdir -p inflow-ai
tar xzf /www/wwwroot/inflow-ai-deploy.tar.gz -C inflow-ai
cd inflow-ai

# 1. 从模板创建 .env
cp .env.example .env

# 2. 生成随机密码（复制输出，填入 .env）
openssl rand -base64 24 | tr -d '/+=' | head -c 32    # → POSTGRES_PASSWORD
openssl rand -base64 48 | tr -d '/+=' | head -c 48    # → SECRET_KEY

# 3. 编辑 .env
vi .env
```

`.env` 至少填写：

```env
POSTGRES_PASSWORD=上一步生成的数据库密码
SECRET_KEY=上一步生成的JWT密钥
inFlow_PUBLIC_BASE=https://inflow.huituai.site
INFLOW_PIPELINE_DATA_DIR=/www/data/inflow/pipeline
SILICONFLOW_API_KEY=sk-...
GROQ_API_KEY=gsk-...
ACCESS_TOKEN_EXPIRE_DAYS=30
```

```bash
# 4. 创建 pipeline 目录（生产数据与项目目录分离）
sudo mkdir -p /www/data/inflow/pipeline
sudo chown -R "$(whoami):$(whoami)" /www/data/inflow

# 5. 赋权并部署
chmod +x deploy-baota.sh start-docker.sh sync-env-docker.sh \
  verify-docker-keys.sh verify-docker-deploy.sh logs-docker.sh stop-docker.sh \
  deploy-update-server.sh
./deploy-baota.sh --detach --verify

# 6. 验证部署成功
curl -s http://127.0.0.1:8080/api/health
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"
$COMPOSE ps
```

**成功标志：**

- `curl` 返回 JSON 且含 `"status":"ok"` 或类似健康字段
- `$COMPOSE ps` 中 `backend`、`frontend`、`nginx`、`postgres`、`wechat-bot` 均为 `Up`
- `./verify-docker-keys.sh` 输出 `=== 全部通过：Key 已同步到 Docker 且可用 ===`
- `./verify-docker-deploy.sh` 输出 `=== 部署校验通过：Pipeline 路径与容器挂载一致 ===`

**部署后查看日志：**

```bash
cd /www/wwwroot/inflow-ai
./logs-docker.sh backend wechat-bot --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh backend  --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh frontend  --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh wechat-bot --tail 80

# 重点看 backend 启动与数据库迁移
./logs-docker.sh backend --tail 120 --grep 'migration|error|exception|Uvicorn'

# 验证 Key 与微信 bot
./logs-docker.sh backend --tail 50 --grep 'GROQ|SILICONFLOW|error'
./logs-docker.sh wechat-bot --tail 30
```

---



## 场景 2：压缩包更新代码（保留数据）

**何时使用：** 服务器已有运行环境，用新压缩包更新代码，保留 `.env`、数据库与 `/www/data/inflow/pipeline` 采集文件。

**推荐做法：** Mac 上传压缩包后，在服务器**只执行一条命令**（脚本内含备份、解压、恢复 `.env`、重建容器）：

```bash
cd /www/wwwroot/inflow-ai
chmod +x deploy-update-server.sh
./deploy-update-server.sh
```

脚本路径：`/www/wwwroot/inflow-ai/deploy-update-server.sh`（随压缩包下发）。失败时会打印明确错误并退出，不会半途中断留下无 `.env` 的目录。

**三层模型（为何必须 `--build`）：** 解压只更新磁盘源码；`./start-docker.sh --restart` 才会用新源码编译 frontend/backend 镜像。仅用 `docker compose restart` **不会**更新页面。

---

### A. Mac：打包并上传

```bash
cd /Users/zhouhanbao/Documents/01-CC/98-Content/g_20260615_inFlow-ai

rm -f /tmp/inflow-ai-deploy.tar.gz

tar czf /tmp/inflow-ai-deploy.tar.gz \
  --exclude='.venv' \
  --exclude='node_modules' \
  --exclude='03-src/frontend/node_modules' \
  --exclude='03-src/frontend/.next' \
  --exclude='04-log' \
  --exclude='02-docs/data' \
  --exclude='02-docs/data-' \
  --exclude='03-src/backend/data' \
  --exclude='.git' \
  --exclude='.env' \
  .

ls -lh /tmp/inflow-ai-deploy.tar.gz

# 确认发版脚本已打进包（必须有输出，否则不要上传）
tar tzf /tmp/inflow-ai-deploy.tar.gz deploy-update-server.sh start-docker.sh

scp /tmp/inflow-ai-deploy.tar.gz root@你的服务器IP:/www/wwwroot/inflow-ai-deploy.tar.gz

ssh root@你的服务器IP "ls -lh /www/wwwroot/inflow-ai-deploy.tar.gz"
```

把 `你的服务器IP` 换成真实 IP（如 `123.45.67.89`）。

---

### B. 服务器：发版

#### 先诊断（服务器执行）

```bash
ls -lh /www/wwwroot/inflow-ai-deploy.tar.gz
ls -l /www/wwwroot/inflow-ai/deploy-update-server.sh 2>&1
tar tzf /www/wwwroot/inflow-ai-deploy.tar.gz deploy-update-server.sh 2>&1 | head -3
```

| 结果 | 含义 |
| --- | --- |
| `tar tzf` **有** `deploy-update-server.sh` | 压缩包是新版，见下方「一键脚本」 |
| `tar tzf` **无输出** / `tar: … not found` | 压缩包是旧版，Mac 须重新打包上传（见 A） |
| 目录里没有脚本、但 `tar tzf` 有 | 从压缩包只解压脚本即可（见下方「从 tar 取出脚本」） |

#### 无脚本时：整段复制执行（不依赖 deploy-update-server.sh）

**在服务器 SSH 一次性粘贴整段**（须先有 `/www/wwwroot/inflow-ai/.env` 和 `/www/wwwroot/inflow-ai-deploy.tar.gz`）：

```bash
STAMP=$(date +%Y%m%d_%H%M%S)
ENV_BAK="/tmp/inflow.env.bak.${STAMP}"
CONFIG_BAK="/tmp/inflow.config.bak.${STAMP}"
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

cd /www/wwwroot/inflow-ai
test -f .env || { echo "缺少 .env，先备份恢复或 vi .env"; exit 1; }
test -f /www/wwwroot/inflow-ai-deploy.tar.gz || { echo "缺少压缩包"; exit 1; }

cp .env "${ENV_BAK}"
cp 03-src/backend/app/config_store.json "${CONFIG_BAK}" 2>/dev/null || true

mkdir -p /www/backup
if docker ps --format '{{.Names}}' | grep -qx 'inflow-db'; then
  ${COMPOSE} exec -T postgres pg_dump -U inflow inflow > "/www/backup/inflow_${STAMP}.sql"
fi

rm -rf /www/wwwroot/inflow-ai
mkdir -p /www/wwwroot/inflow-ai
tar xzf /www/wwwroot/inflow-ai-deploy.tar.gz -C /www/wwwroot/inflow-ai

cp "${ENV_BAK}" /www/wwwroot/inflow-ai/.env
test -f "${CONFIG_BAK}" && cp "${CONFIG_BAK}" /www/wwwroot/inflow-ai/03-src/backend/app/config_store.json || true

cd /www/wwwroot/inflow-ai
grep -q '^INFLOW_PIPELINE_DATA_DIR=' .env || echo 'INFLOW_PIPELINE_DATA_DIR=/www/data/inflow/pipeline' >> .env
sudo mkdir -p /www/data/inflow/pipeline

chmod +x deploy-baota.sh start-docker.sh sync-env-docker.sh verify-docker-keys.sh verify-docker-deploy.sh logs-docker.sh stop-docker.sh deploy-update-server.sh 2>/dev/null || true
./start-docker.sh --restart --detach --verify
```

#### 从 tar 取出脚本（压缩包已是新版、目录里缺文件时）

```bash
mkdir -p /www/wwwroot/inflow-ai
tar xzf /www/wwwroot/inflow-ai-deploy.tar.gz -C /www/wwwroot/inflow-ai deploy-update-server.sh
cd /www/wwwroot/inflow-ai
chmod +x deploy-update-server.sh
./deploy-update-server.sh
```

若 `tar xzf … deploy-update-server.sh` 报错 **not found in archive**，说明压缩包仍是旧版 → Mac 重新打包上传（A），或 Mac 单独 scp 脚本：

```bash
scp /Users/zhouhanbao/Documents/01-CC/98-Content/g_20260615_inFlow-ai/deploy-update-server.sh \
  root@你的服务器IP:/www/wwwroot/inflow-ai/deploy-update-server.sh
```

#### 一键脚本（目录里已有 deploy-update-server.sh 时）

**不要先手动 `rm -rf`**。在**仍有 `.env` 的旧目录**里执行：

```bash
cd /www/wwwroot/inflow-ai
chmod +x deploy-update-server.sh
./deploy-update-server.sh
```

**成功标志：** 末尾出现 `=== 全部通过：Key 已同步到 Docker 且可用 ===` 与 `=== 部署校验通过：Pipeline 路径与容器挂载一致 ===`；`curl http://127.0.0.1:8080/api/health` 返回 JSON。

**若已手动 `rm -rf` 整个项目目录**（常见于误操作）：先解压拿到脚本，再从 `/tmp` 恢复 `.env`，然后跑脚本：

```bash
mkdir -p /www/wwwroot/inflow-ai
tar xzf /www/wwwroot/inflow-ai-deploy.tar.gz -C /www/wwwroot/inflow-ai
ls -lt /tmp/inflow.env.bak.* 2>/dev/null | head -3
cp /tmp/inflow.env.bak.XXXXXXXX /www/wwwroot/inflow-ai/.env   # 换成上一步列出的最新备份
cd /www/wwwroot/inflow-ai
chmod +x deploy-update-server.sh
./deploy-update-server.sh
```

若无 `/tmp/inflow.env.bak.*`，只能新建 `.env`（**`POSTGRES_PASSWORD` 必须与线上一致**，否则数据库连不上）：

```bash
mkdir -p /www/wwwroot/inflow-ai
tar xzf /www/wwwroot/inflow-ai-deploy.tar.gz -C /www/wwwroot/inflow-ai
cd /www/wwwroot/inflow-ai
cp .env.example .env
vi .env
chmod +x deploy-update-server.sh
./deploy-update-server.sh
```

---

### C. 发版验收

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

grep '可向 bot 发送文章链接' 03-src/frontend/src/components/WechatBinding.tsx

docker exec inflow-frontend grep -r "start-local.sh" /app/.next 2>/dev/null | wc -l

docker inspect inflow-backend --format '{{range .Mounts}}{{if eq .Destination "/app/data"}}{{.Source}}{{end}}{{end}}'
grep '^INFLOW_PIPELINE_DATA_DIR=' .env
```

---

### D. 手动逐步发版（仅当脚本不可用时）

<details>
<summary>展开 S1～S20 手动步骤</summary>

**注意：** `STAMP`、`ENV_BAK` 必须在**同一次 SSH 会话**里先定义再使用；`docker compose` 必须使用[通用约定](#通用约定)中的**绝对路径** `COMPOSE`。

```bash
STAMP=$(date +%Y%m%d_%H%M%S)
ENV_BAK="/tmp/inflow.env.bak.${STAMP}"
CONFIG_BAK="/tmp/inflow.config.bak.${STAMP}"
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

cd /www/wwwroot/inflow-ai
test -f .env || { echo "缺少 .env"; exit 1; }
cp .env "${ENV_BAK}"
cp 03-src/backend/app/config_store.json "${CONFIG_BAK}" 2>/dev/null || true

mkdir -p /www/backup
if docker ps --format '{{.Names}}' | grep -qx 'inflow-db'; then
  ${COMPOSE} exec -T postgres pg_dump -U inflow inflow > "/www/backup/inflow_${STAMP}.sql"
fi

rm -rf /www/wwwroot/inflow-ai
mkdir -p /www/wwwroot/inflow-ai
tar xzf /www/wwwroot/inflow-ai-deploy.tar.gz -C /www/wwwroot/inflow-ai

cp "${ENV_BAK}" /www/wwwroot/inflow-ai/.env
test -f "${CONFIG_BAK}" && cp "${CONFIG_BAK}" /www/wwwroot/inflow-ai/03-src/backend/app/config_store.json || true

cd /www/wwwroot/inflow-ai
grep -q '^INFLOW_PIPELINE_DATA_DIR=' .env || echo 'INFLOW_PIPELINE_DATA_DIR=/www/data/inflow/pipeline' >> .env
sudo mkdir -p /www/data/inflow/pipeline

chmod +x deploy-baota.sh start-docker.sh sync-env-docker.sh verify-docker-keys.sh verify-docker-deploy.sh logs-docker.sh stop-docker.sh deploy-update-server.sh
./start-docker.sh --restart --detach --verify
```

</details>

**切勿：** 用 Mac 的 `.env` 覆盖服务器（除非 `POSTGRES_PASSWORD` 一致）；用 `docker compose restart` 代替发版。

---



## 场景 3：改 `.env` 并同步 + 验证 Key

**何时使用：** 修改了 `.env` 中任意配置项（API Key、超时、域名等），需同步到 Docker 容器。

**操作步骤（服务器）：**

```bash
cd /www/wwwroot/inflow-ai

cp .env .env.bak.$(date +%Y%m%d)
vi .env

./sync-env-docker.sh
```

**验证部署成功：**

```bash
cd /www/wwwroot/inflow-ai
curl -s http://127.0.0.1:8080/api/health
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"
$COMPOSE ps
```

输出 `=== 全部通过：Key 已同步到 Docker 且可用 ===` 即通过。

**部署后查看日志：**

```bash
cd /www/wwwroot/inflow-ai
./logs-docker.sh backend wechat-bot --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh backend  --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh frontend  --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh wechat-bot --tail 80

# 确认 backend / wechat-bot 重建后无报错
./logs-docker.sh backend wechat-bot --tail 80 --grep 'error|fail|exception'

# 确认新 Key 已生效（LLM / Embedding / Groq）
./logs-docker.sh backend --tail 50 --grep 'GROQ|SILICONFLOW|config'
```

---



## 场景 4：批量更换 API Key

**何时使用：** 同时更换多个 LLM / Embedding / Groq 等 API Key。

**操作步骤（服务器）：**

```bash
cd /www/wwwroot/inflow-ai

cp .env .env.bak.$(date +%Y%m%d)
vi .env
# 更新 SILICONFLOW_API_KEY / GROQ_API_KEY / DEEPSEEK_API_KEY 等
# POSTGRES_PASSWORD 保持不动

./sync-env-docker.sh
```

若曾在网页「设置」保存过 LLM Key，还需登录 [https://inflow.huituai.site](https://inflow.huituai.site) → **设置** → 填入新 Key → **保存**。

**验证部署成功：**

```bash
cd /www/wwwroot/inflow-ai
./verify-docker-keys.sh

curl -s -X POST http://127.0.0.1:8080/api/system/config/llm/test \
  -H 'Content-Type: application/json' -d '{}' | python3 -m json.tool

curl -s -X POST http://127.0.0.1:8080/api/system/config/embedding/test \
  -H 'Content-Type: application/json' -d '{}' | python3 -m json.tool
```

返回 `"ok": true` 即通过。

**部署后查看日志：**

```bash
cd /www/wwwroot/inflow-ai
./logs-docker.sh backend wechat-bot --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh backend  --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh frontend  --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh wechat-bot --tail 80

cd /www/wwwroot/inflow-ai

./logs-docker.sh backend --tail 100 --grep 'error|fail|401|403|GROQ|SILICONFLOW'
```

---



## 场景 5：全量更新 `.env`

**何时使用：** 对照 `.env.example` 全面检查并更新所有配置项。

**操作步骤（服务器）：**

```bash
cd /www/wwwroot/inflow-ai

cp .env .env.bak.$(date +%Y%m%d)
diff .env .env.example || true
vi .env
```

编辑时注意：

- `POSTGRES_PASSWORD`：**保持原值**
- `SECRET_KEY`：可轮换 → `openssl rand -base64 48 | tr -d '/+=' | head -c 48`
- `SERVICE_TOKEN_WECHAT_BOT` 与 `SERVICE_TOKENS` 必须一致，格式：`token:weaiw`

```bash
cd /www/wwwroot/inflow-ai
./sync-env-docker.sh
```

若改了 `SECRET_KEY`，浏览器需重新登录。

**验证部署成功：**

```bash
cd /www/wwwroot/inflow-ai
curl -s http://127.0.0.1:8080/api/health
./verify-docker-keys.sh
```

**部署后查看日志：**

```bash
cd /www/wwwroot/inflow-ai
./logs-docker.sh backend wechat-bot --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh backend  --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh frontend  --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh wechat-bot --tail 80

cd /www/wwwroot/inflow-ai

./logs-docker.sh backend wechat-bot --tail 100 --grep 'error|fail|password|database'
```

---



## 场景 6：轮换 SECRET_KEY

**何时使用：** JWT 密钥泄露或定期轮换，需使所有用户重新登录。

**操作步骤（服务器）：**

```bash
cd /www/wwwroot/inflow-ai

cp .env .env.bak.$(date +%Y%m%d)
NEW_SECRET=$(openssl rand -base64 48 | tr -d '/+=' | head -c 48)
sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${NEW_SECRET}|" .env

./sync-env-docker.sh
```

**验证部署成功：**

```bash
cd /www/wwwroot/inflow-ai
curl -s http://127.0.0.1:8080/api/health
grep '^SECRET_KEY=' .env | head -c 30
```

**部署后查看日志：**

```bash
cd /www/wwwroot/inflow-ai
./logs-docker.sh backend wechat-bot --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh backend  --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh frontend  --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh wechat-bot --tail 80

cd /www/wwwroot/inflow-ai

./logs-docker.sh backend --tail 50 --grep 'error|SECRET|auth|token'
```

---



## 场景 7：更换微信 Bot Token

**何时使用：** 微信 bot 鉴权 token 泄露或需轮换。

**操作步骤（服务器）：**

```bash
cd /www/wwwroot/inflow-ai

cp .env .env.bak.$(date +%Y%m%d)
NEW_TOKEN=$(openssl rand -hex 24)
ACT_AS=$(grep '^WECHAT_BOT_ACT_AS_USER=' .env | cut -d= -f2-)
ACT_AS=${ACT_AS:-weaiw}
sed -i "s|^SERVICE_TOKEN_WECHAT_BOT=.*|SERVICE_TOKEN_WECHAT_BOT=${NEW_TOKEN}|" .env
sed -i "s|^SERVICE_TOKENS=.*|SERVICE_TOKENS=${NEW_TOKEN}:${ACT_AS}|" .env

./sync-env-docker.sh
```

**验证部署成功：**

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"
$COMPOSE ps wechat-bot
curl -s http://127.0.0.1:8080/api/health
```

**部署后查看日志：**

```bash
cd /www/wwwroot/inflow-ai
./logs-docker.sh backend wechat-bot --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh backend  --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh frontend  --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh wechat-bot --tail 80

cd /www/wwwroot/inflow-ai

./logs-docker.sh wechat-bot --tail 50 --grep '401|Unauthorized|error|exception|started'
```

无 `401` / `Unauthorized` 即通过。

---



## 场景 8：本地 `.env` 同步到服务器

**何时使用：** 在 Mac 上改好 `.env`，需要同步到服务器（**慎用**，易覆盖 `POSTGRES_PASSWORD`）。

### 步骤一：本地 Mac 上传 `.env`

```bash
scp /Users/zhouhanbao/Documents/01-CC/98-Content/g_20260615_inFlow-ai/.env \
  root@你的服务器IP:/www/wwwroot/inflow-ai/.env
```



### 步骤二：服务器同步到容器

```bash
cd /www/wwwroot/inflow-ai

# 确认数据库密码与线上一致
grep POSTGRES_PASSWORD .env
# 若不同，从最近备份找回：ls -lt /tmp/inflow.env.bak.* /www/wwwroot/inflow-ai/.env.bak.* 2>/dev/null | head -3

./sync-env-docker.sh
```

**验证部署成功：**

```bash
cd /www/wwwroot/inflow-ai
curl -s http://127.0.0.1:8080/api/health
./verify-docker-keys.sh
```

**部署后查看日志：**

```bash
cd /www/wwwroot/inflow-ai
./logs-docker.sh backend wechat-bot --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh backend  --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh frontend  --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh wechat-bot --tail 80

cd /www/wwwroot/inflow-ai

./logs-docker.sh backend --tail 80 --grep 'password|database|error|fail'
./logs-docker.sh wechat-bot --tail 30
```

---



## 场景 9：仅验证 Key（不重启）

**何时使用：** 容器已在运行，只想确认 API Key 是否可用，不重启服务。

**操作步骤（服务器）：**

```bash
cd /www/wwwroot/inflow-ai

./verify-docker-keys.sh
```

或：

```bash
cd /www/wwwroot/inflow-ai
./sync-env-docker.sh --verify
```

HTTP 备用验证：

```bash
cd /www/wwwroot/inflow-ai
curl -s -X POST http://127.0.0.1:8080/api/system/config/llm/test \
  -H 'Content-Type: application/json' -d '{}' | python3 -m json.tool

curl -s -X POST http://127.0.0.1:8080/api/system/config/embedding/test \
  -H 'Content-Type: application/json' -d '{}' | python3 -m json.tool
```

**成功标志：** 返回 `"ok": true`。

**查看日志（验证失败时）：**

```bash
cd /www/wwwroot/inflow-ai
./logs-docker.sh backend wechat-bot --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh backend  --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh frontend  --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh wechat-bot --tail 80

cd /www/wwwroot/inflow-ai

./logs-docker.sh backend --tail 100 --grep 'error|fail|401|403|GROQ|SILICONFLOW'
```

---



## 场景 10：实时查看运行日志

**何时使用：** 日常运维、观察 pipeline、排查运行时问题。

**操作步骤（服务器）：**

```bash
cd /www/wwwroot/inflow-ai
./logs-docker.sh backend wechat-bot --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh backend  --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh frontend  --tail 80

cd /www/wwwroot/inflow-ai
./logs-docker.sh wechat-bot --tail 80

cd /www/wwwroot/inflow-ai

# 默认：backend + wechat-bot 实时滚动（Ctrl+C 不停止容器）
./logs-docker.sh
```

按用途（默认优先 backend + wechat-bot）：

```bash
cd /www/wwwroot/inflow-ai
./logs-docker.sh backend                              # 收藏 / pipeline / ASR
./logs-docker.sh wechat-bot                           # 微信 bot
./logs-docker.sh frontend                             # 前端（按需）
./logs-docker.sh nginx backend                        # 502 排查（按需）
./logs-docker.sh --all                                # 全部容器（按需）
./logs-docker.sh backend --grep 'error|fail|pipeline'
./logs-docker.sh backend --grep 'Groq|转录|ASR'
./logs-docker.sh backend --tail 200
./logs-docker.sh --since 10m
```

等价命令：

```bash
cd /www/wwwroot/inflow-ai
./start-docker.sh --logs
```

**常用过滤：**

```bash
cd /www/wwwroot/inflow-ai
# pipeline 全流程
./logs-docker.sh backend --grep 'pipeline|02-转录|03-解析'

# Groq ASR 转录
./logs-docker.sh backend --grep 'Groq|转录|ASR|error'

# 数据库问题
./logs-docker.sh backend --grep -i 'password|database|asyncpg'
```

---



## 场景 11：Git 更新代码（无表结构变更）

**何时使用：** 服务器已配置 Git 远程，通过 `git pull` 拉取代码更新，无新增 migration SQL。  
（若服务器无 Git 仓库，请改用 [场景 2](#场景-2压缩包更新代码保留数据)。）

**操作步骤（服务器）：**

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

git pull
./start-docker.sh --restart --detach --verify

curl -s http://127.0.0.1:8080/api/health
$COMPOSE ps
```

仅前端有改动、页面未更新时（`--restart` 已包含 frontend `--build`，一般无需单独执行）：

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

$COMPOSE build frontend
$COMPOSE up -d frontend
```

**验证部署成功：**

```bash
curl -s http://127.0.0.1:8080/api/health
curl -I https://inflow.huituai.site
```

**部署后查看日志：**

```bash
cd /www/wwwroot/inflow-ai

./logs-docker.sh backend wechat-bot --tail 100 --grep 'error|exception|Uvicorn|ready'
./logs-docker.sh backend --tail 50 --grep 'pipeline'
```

---



## 场景 12：Git 更新代码 + 数据库表结构

**何时使用：** 代码更新包含 `03-src/backend/app/core/migrations/` 下新增 SQL。  
（若服务器无 Git 仓库，请改用 [场景 2](#场景-2压缩包更新代码保留数据)，并在解压前备份数据库。）

**本地开发（提交前）：** 在 `03-src/backend/app/core/migrations/` 新增递增编号 SQL，必须幂等：

```sql
-- 018_xxx.sql 示例
ALTER TABLE articles ADD COLUMN IF NOT EXISTS new_field VARCHAR(50) NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS yyy (id UUID PRIMARY KEY DEFAULT gen_random_uuid());
CREATE INDEX IF NOT EXISTS idx_yyy_created ON yyy (created_at);
```

**操作步骤（服务器）：**

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

# 1. 备份数据库
mkdir -p /www/backup
$COMPOSE exec -T postgres \
  pg_dump -U inflow inflow > /www/backup/inflow_$(date +%Y%m%d_%H%M%S).sql
ls -lh /www/backup/

# 2. 拉代码并部署（含 migration 自动执行）
git pull
./start-docker.sh --restart --detach --verify

# 3. 验证
curl -s http://127.0.0.1:8080/api/health
$COMPOSE ps
```

验证迁移（将 `new_field` / `yyy` 换成你的表名/字段名）：

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

$COMPOSE exec -T postgres \
  psql -U inflow inflow -c "\d+ articles" | grep new_field

$COMPOSE exec -T postgres \
  psql -U inflow inflow -c "\dt yyy"
```

**部署后查看日志：**

```bash
cd /www/wwwroot/inflow-ai

./logs-docker.sh backend --tail 150 --grep 'migration|error|exception|init_db'
```

**回滚代码：**

```bash
cd /www/wwwroot/inflow-ai

git log --oneline -5
git checkout <上个正常commit>
./start-docker.sh --restart --detach --verify
```

**恢复数据库（用备份文件名替换）：**

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

$COMPOSE exec -T postgres \
  psql -U inflow inflow < /www/backup/inflow_20260702_xxxx.sql
```

---



## 场景 13：启动 / 停止 / 健康检查

**何时使用：** 日常启停服务或确认运行状态。

### 启动

```bash
cd /www/wwwroot/inflow-ai

./start-docker.sh --detach
```



### 停止

```bash
cd /www/wwwroot/inflow-ai

./stop-docker.sh
```



### 健康检查

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

curl -s http://127.0.0.1:8080/api/health
$COMPOSE ps
curl -I https://inflow.huituai.site
```



### 重启单个服务

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

$COMPOSE restart backend
$COMPOSE restart frontend
$COMPOSE restart nginx
$COMPOSE restart wechat-bot
```

**成功标志：** `$COMPOSE ps` 全部 `Up`；`curl` 健康检查通过。

**部署后查看日志：**

```bash
cd /www/wwwroot/inflow-ai

./logs-docker.sh backend wechat-bot --tail 80
./logs-docker.sh backend --tail 50 --grep 'error|exception|Uvicorn'
```

---



## 场景 14：备份数据库

**何时使用：** 定期备份或重大变更前手动备份。

**操作步骤（服务器）：**

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

mkdir -p /www/backup
$COMPOSE exec -T postgres \
  pg_dump -U inflow inflow > /www/backup/inflow_$(date +%Y%m%d_%H%M%S).sql

ls -lh /www/backup/
```

**验证备份成功：**

```bash
ls -lh /www/backup/inflow_*.sql | tail -3
LATEST_SQL=$(ls -t /www/backup/inflow_*.sql 2>/dev/null | head -1)
test -n "${LATEST_SQL}" && head -5 "${LATEST_SQL}"
```

**查看日志（备份失败时）：**

```bash
cd /www/wwwroot/inflow-ai

./logs-docker.sh postgres --tail 50 --grep 'error|FATAL'
```

**宝塔计划任务（每天凌晨，粘贴到 Shell 脚本）：**

```bash
mkdir -p /www/backup
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"
$COMPOSE exec -T postgres \
  pg_dump -U inflow inflow > /www/backup/inflow_$(date +\%Y\%m\%d).sql
find /www/backup -name "inflow_*.sql" -mtime +7 -delete
```

---



## 场景 15：故障排查

每个子场景均可独立执行。

### 15.1 502 Bad Gateway

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

curl -I http://127.0.0.1:8080
$COMPOSE ps
./logs-docker.sh nginx backend --tail 80 --grep 'error|502|upstream'
```



### 15.2 改 `.env` 后不生效

```bash
cd /www/wwwroot/inflow-ai

./sync-env-docker.sh
./verify-docker-keys.sh
./logs-docker.sh backend --tail 80 --grep 'error|config|GROQ|SILICONFLOW'
```



### 15.3 数据库连接失败 / `password authentication failed`

```bash
cd /www/wwwroot/inflow-ai

./logs-docker.sh backend --grep -i 'password|database|asyncpg'
```

**原因：** `.env` 里 `POSTGRES_PASSWORD` 与数据库卷初始化时不一致。

**修复（保留数据）：**

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

PG_PASS=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2- | tr -d '"' | tr -d "'")
$COMPOSE exec -T postgres \
  psql -U inflow -d postgres -c "ALTER ROLE inflow WITH PASSWORD '${PG_PASS}';"
$COMPOSE restart backend wechat-bot

curl -s http://127.0.0.1:8080/api/health
./logs-docker.sh backend --tail 50 --grep 'database|password|error'
```

**或改回旧密码：**

```bash
cd /www/wwwroot/inflow-ai
ls -lt /tmp/inflow.env.bak.* .env.bak.* 2>/dev/null | head -5
grep POSTGRES_PASSWORD /tmp/inflow.env.bak.* .env.bak.* 2>/dev/null | head -3
# 将正确密码写入 .env 后：
./start-docker.sh --restart --detach --verify
```



### 15.4 数据库不存在 / `database "inflow" does not exist`

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

./logs-docker.sh backend --tail 120 --grep 'InvalidCatalogNameError|does not exist|database'
```

**原因：** 早期环境可能把 Postgres 初始化为 `inFlow`（大小写混用），而当前后端 DSN 固定连接 `inflow`。

**修复（可保留数据）：**

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

$COMPOSE exec -T postgres psql -U inflow -d postgres -c "CREATE DATABASE inflow;" || true
$COMPOSE restart backend wechat-bot
curl -s http://127.0.0.1:8080/api/health
```

**修复（可清空数据，推荐统一环境）：**

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

$COMPOSE down -v
./start-docker.sh --detach
curl -s http://127.0.0.1:8080/api/health
```



### 15.5 build 失败 / 内存不足

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

free -h
./logs-docker.sh backend --tail 100
$COMPOSE build --no-cache backend
./start-docker.sh --restart --detach --verify
./logs-docker.sh backend --tail 80 --grep 'error|build'
```



### 15.6 收藏 / pipeline 无反应

```bash
cd /www/wwwroot/inflow-ai

./logs-docker.sh backend --tail 150 --grep 'pipeline|error|fail|exception'
```



### 15.7 音频转录失败（Groq ASR）

```bash
cd /www/wwwroot/inflow-ai

./logs-docker.sh backend --tail 200 --grep 'Groq|转录|ASR|403|error|fail'
./verify-docker-keys.sh
```

国内服务器 Groq 可能返回 403，需确认 `GROQ_API_KEY` 有效且网络可访问 Groq API。

### 15.8 微信 bot 不回复 / 提示“已绑定但消息服务未就绪”

**含义：** 微信账号已写入数据库，但 `wechat-bot` 尚未在 2 分钟内成功轮询 ilink（`last_seen_at` 为空或过期）。

```bash
cd /www/wwwroot/inflow-ai

export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"
$COMPOSE ps wechat-bot backend

# bot 是否已为该用户拉起 worker？
./logs-docker.sh wechat-bot --tail 120 --grep 'Spawning|poll err|401|session|timeout|Supervisor'

# backend 绑定与 token
./logs-docker.sh backend --tail 120 --grep 'wechat|bot|session|timeout|bind|token|error'

# 数据库：绑定记录与最近心跳（新用户绑定后约 30～90 秒内应出现 last_seen_at）
$COMPOSE exec -T postgres psql -U inflow -d inflow -c "
SELECT u.username, wa.account_id, wa.is_active, wa.last_seen_at, wa.created_at
FROM wechat_accounts wa
JOIN users u ON u.id = wa.user_id
WHERE wa.is_active = true
ORDER BY wa.created_at DESC
LIMIT 10;"

# token 是否一致（须含「SERVICE_TOKEN_WECHAT_BOT 的值:weaiw」）
grep -E '^(SERVICE_TOKEN_WECHAT_BOT|SERVICE_TOKENS|WECHAT_BOT_ACT_AS_USER)=' .env
```

**按日志处理：**


| 现象                                        | 处理                                                                            |
| ----------------------------------------- | ----------------------------------------------------------------------------- |
| `wechat-bot` 非 `Up`                       | `cd /www/wwwroot/inflow-ai && ./start-docker.sh --detach` 或 `$COMPOSE up -d wechat-bot` |
| 日志 `401` / `Unauthorized`                 | `cd /www/wwwroot/inflow-ai && ./sync-env-docker.sh`（重建 backend + wechat-bot 使 token 生效） |
| 日志 `session timeout` / `auth invalid`     | 前端解绑 → 重新扫码绑定                                                                 |
| 无 `Spawning worker` 且 `last_seen_at` 一直为空 | 查 wechat-bot 是否连不上库：`./logs-docker.sh wechat-bot --grep 'password\|database\|error'` |
| 绑定后 1～2 分钟内仍无心跳                           | 属旧版 bug（长轮询超时未写心跳），更新代码后 `cd /www/wwwroot/inflow-ai && ./start-docker.sh --restart --detach` |


若刚绑定完成，可等待约 1 分钟再刷新设置页（前端会自动每 12 秒刷新状态）。

### 15.9 同一篇文章出现两张卡片（重复入库）

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

# 先看是否存在同 URL 重复（同用户）
$COMPOSE exec -T postgres psql -U inflow -d inflow -c "
SELECT user_id, url, COUNT(*) AS cnt
FROM articles
WHERE url IS NOT NULL
GROUP BY user_id, url
HAVING COUNT(*) > 1
ORDER BY cnt DESC
LIMIT 20;"
```

**现象说明：**

- 旧版本或历史脏数据可能导致同 URL 有多条记录（常见一条“处理中”、一条“已完成”）。
- 新版前端已按 URL 去重展示，优先保留信息更完整的卡片（通常是封面/摘要更完整的那张）。

**一次性清理历史重复（保留每组最新一条）：**

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

$COMPOSE exec -T postgres psql -U inflow -d inflow -c "
WITH ranked AS (
  SELECT id,
         ROW_NUMBER() OVER (
           PARTITION BY user_id, url
           ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST, id DESC
         ) AS rn
  FROM articles
  WHERE url IS NOT NULL
)
DELETE FROM articles a
USING ranked r
WHERE a.id = r.id
  AND r.rn > 1;"
```



### 15.10 微信推送失败：`Card PNG not found`

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

# backend 里有 PNG？
$COMPOSE exec backend find data/03_display -name '0749ff39*.png' -ls

# wechat-bot 里同路径是否存在？（旧版未共享 data 卷时通常为空）
$COMPOSE exec wechat-bot find data/03_display -name '0749ff39*.png' -ls
```

**原因：** `backend` 生成卡片 PNG 写在容器内 `/app/data/…`，`wechat-bot` 是独立容器，若未挂载同一 `data` 目录，推送时读不到文件。

**修复（共享卷** `INFLOW_PIPELINE_DATA_DIR`**，详见 [Pipeline存储架构](./20260702_09_Pipeline存储架构与实施路线.md)）：**

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

# 1. 配置生产 pipeline 目录并迁移旧数据
sudo mkdir -p /www/data/inflow/pipeline
grep -q '^INFLOW_PIPELINE_DATA_DIR=' .env || \
  echo 'INFLOW_PIPELINE_DATA_DIR=/www/data/inflow/pipeline' >> .env
# 或 vi .env 设为 INFLOW_PIPELINE_DATA_DIR=/www/data/inflow/pipeline

chmod +x migrate-pipeline-data.sh
./migrate-pipeline-data.sh

# 2. 拉取/更新代码后重建 backend + wechat-bot
./start-docker.sh --restart --detach

# 3. 验证两个容器都能看到同一张 PNG
$COMPOSE exec backend  find data/03_display -name '*.png' | wc -l
$COMPOSE exec wechat-bot find data/03_display -name '*.png' | wc -l

# 4. 将失败队列改回 ready 以便重推（替换 job_id）
$COMPOSE exec -T postgres psql -U inflow -d inflow -c "
UPDATE wechat_callback_queue
SET status='ready', error=NULL
WHERE job_id='0749ff39-62bd-40aa-bbc4-9291c6dd9096' AND status='failed';"
```

两容器 `find … | wc -l` 数量一致后，bot 会在数秒内自动重推；或再发一条 URL 触发新收藏。

### 15.11 最后手段（⚠️ 删全部数据）

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

./stop-docker.sh
$COMPOSE down -v
./start-docker.sh --detach
./logs-docker.sh backend wechat-bot --tail 100
```

---



## 场景 16：Pipeline 存储迁移（阶段 1）

**何时使用：** 首次将 pipeline 数据从容器内迁到宿主机独立目录，或修复微信 `Card PNG not found`。完整架构见 [20260702_09_Pipeline存储架构与实施路线.md](./20260702_09_Pipeline存储架构与实施路线.md)。

**操作步骤（服务器）：**

```bash
cd /www/wwwroot/inflow-ai
export COMPOSE="docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml"

# 1. 创建目录
sudo mkdir -p /www/data/inflow/pipeline /www/data/inflow/backup
sudo chown -R "$(whoami):$(whoami)" /www/data/inflow

# 2. 配置 .env（生产路径）
grep '^INFLOW_PIPELINE_DATA_DIR=' .env || \
  echo 'INFLOW_PIPELINE_DATA_DIR=/www/data/inflow/pipeline' >> .env
# 若已存在但为旧值，请 vi .env 改为 /www/data/inflow/pipeline

# 3. 更新代码（含 docker-compose + migrate-pipeline-data.sh）后迁移
chmod +x migrate-pipeline-data.sh
./migrate-pipeline-data.sh

# 4. 重建服务
./start-docker.sh --restart --detach

# 5. 验证
$COMPOSE exec backend  find data/03_display -name '*.png' | wc -l
$COMPOSE exec wechat-bot find data/03_display -name '*.png' | wc -l
curl -s http://127.0.0.1:8080/api/health
```

**成功标志：** 两容器 PNG 数量一致；微信收藏可推送卡片。

**Mac 本地打包上传（若服务器无 Git）：** 按 [场景 2](#场景-2压缩包更新代码保留数据) 打包部署，再在服务器执行上述步骤 1～5。

---



## 运维脚本速查


| 脚本               | 命令                           |
| ---------------- | ---------------------------- |
| 压缩包发版（推荐）        | `./deploy-update-server.sh`（见 [场景 2](#场景-2压缩包更新代码保留数据)） |
| 改 `.env` 同步 + 验证 | `./sync-env-docker.sh`       |
| 仅验证 Key + 部署挂载   | `./sync-env-docker.sh --verify` |
| 仅验证 Key          | `./verify-docker-keys.sh`    |
| 仅验证 Pipeline 挂载  | `./verify-docker-deploy.sh`  |
| 实时日志             | `./logs-docker.sh`           |
| 发版 / rebuild     | `./start-docker.sh --restart --detach --verify` |
| 停止               | `./stop-docker.sh`           |
| 首次部署             | `./deploy-baota.sh --detach --verify` |
| Pipeline 数据迁移    | `./migrate-pipeline-data.sh` |


可选别名（执行一次）：

```bash
echo 'alias inflow="cd /www/wwwroot/inflow-ai && export COMPOSE=\"docker compose -f /www/wwwroot/inflow-ai/docker-compose.yml -f /www/wwwroot/inflow-ai/docker-compose.baota.yml\""' >> ~/.bashrc
source ~/.bashrc
```

