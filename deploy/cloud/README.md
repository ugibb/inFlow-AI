# deploy/cloud — 云端（腾讯云）代码直跑部署

## 定位

inFlow 的云端部署单元：**infra 容器**（postgres / redis / nginx / frontend，由 docker compose 管理）+ **宿主机直跑进程**（backend uvicorn :8000、wechat-bot）。重计算 pipeline 由本地 worker 承接（见 `deploy/worker/`），云端只负责入口 / 存储 / 展示 / 推送。

> Docker 全容器部署形态已于 2026-08-20 移除（历史方案见 `02-docs/DEPLOY_BAOTA*.md` 废弃横幅，脚本可从 git 历史找回）。

## 脚本

| 命令（在仓库根执行） | 作用 |
|---|---|
| `./deploy/cloud/start-server.sh` | 启动/重建 infra 容器 + 直跑 backend/bot，跟踪日志 |
| `./deploy/cloud/start-server.sh --detach` | 仅后台启动 |
| `./deploy/cloud/start-server.sh --logs` | 只跟踪 backend 日志 |
| `./deploy/cloud/start-server.sh --restart` | 改 .env / git pull 后重建（默认行为即重建） |
| `./deploy/cloud/start-server.sh --verify` | 启动后额外验证健康状态 |
| `./deploy/cloud/stop-server.sh` | 停止直跑 backend/bot（infra 容器不停） |

配置：仓库根 `.env`（首次运行自动从 `.env.example` 生成并补齐密码/token）。
依赖（一次性）：`cd 03-src/server && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`（首行经 `-e ../core` 安装共享引擎）。
日志：`04-log/backend/`、`04-log/wechat-bot/`（按日期分文件）。PID：`.server/`。

## 日常更新流程

```bash
cd /www/wwwroot/inflow-ai && git pull
./deploy/cloud/start-server.sh --restart
```

## infra 容器运维（原生命令）

```bash
COMPOSE="docker compose -f docker-compose.yml -f deploy/cloud/docker-compose.baota.yml"
$COMPOSE ps                          # 容器状态
$COMPOSE logs --tail 100 postgres    # 某容器日志（backend/bot 是直跑进程，看 04-log/）
$COMPOSE restart nginx               # 重启单个 infra 容器
$COMPOSE down                        # 停全部 infra 容器（生产慎用）
```

数据库备份：

```bash
docker exec inflow-db pg_dump -U inflow inflow > /www/backup/inflow_$(date +%F).sql
```

## 从旧路径切换（一次性）

| 旧命令（仓库根） | 新命令 |
|---|---|
| `./start-server.sh [--restart\|--detach\|--logs\|--verify]` | `./deploy/cloud/start-server.sh …` |
| `./stop-server.sh` | `./deploy/cloud/stop-server.sh` |
| `./sync-env-docker.sh`（改 .env 后同步） | `./deploy/cloud/start-server.sh --restart` |
| `./deploy-update-server.sh`（整包更新） | `git pull && ./deploy/cloud/start-server.sh --restart` |

进程 / PID / 日志位置均未变化，仅命令路径更新。

## 架构说明

- `docker-compose.yml`（仓库根）+ 本目录 `docker-compose.baota.yml` 组合使用；**第一个 `-f` 必须是仓库根文件**（compose 相对路径以其所在目录解析）
- 仓库根 `docker-compose.yml` 与 `.env.example` 同时是后端定位仓库根的 marker（`03-src/core/inflow_core/core/paths.py`），不可移动
- 云端 `.env` 中 `EXTERNAL_PROCESSING=true` 开启 URL 任务分流给本地 worker
