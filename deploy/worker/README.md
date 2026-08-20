# deploy/worker — 本地 Mac 独立 worker

## 定位

inFlow 的本地计算单元：直连**云端 PostgreSQL**（任务总线）轮询认领 `external_processing` 任务，在本地跑完整 pipeline（采集 → 转录 → chapters → parse → compose → index），精华卡 PNG 经 SFTP 直传云端。本地可访问外网 AI（Groq 等），这是 worker 存在的意义。

与云端的关系：只通过 PG + SFTP 交互，不依赖云端任何 HTTP API。详见 `02-docs/20260819_11_本地Worker重构方案.md`。

## 前置依赖（一次性）

```bash
cd 03-src/backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium   # compose 渲染 PNG
brew install ffmpeg                      # 音频转码/下载
```

配置：复制 `deploy/worker/.env.local-worker.example` 到 `03-src/backend/.env.local-worker`，填入云端 PG 连接、SFTP 与 API Key。

云端侧：本地 Mac 的 `~/.ssh/id_ed25519.pub` 加入云端 `authorized_keys`；腾讯云安全组放行 5432（仅本机 IP）。

## 日常启停

```bash
./deploy/worker/start-worker.sh            # 启动并跟踪日志
./deploy/worker/start-worker.sh --detach   # 后台启动
./deploy/worker/stop-worker.sh             # 停止
tail -F 04-log/worker/$(date +%F).log      # 手动看日志
```

日志：`04-log/worker/YYYY-MM-DD.log`；PID：仓库根 `.worker.pid`。

## 验证与排障

- 启动后微信发一条播客 URL → bot 回「已加入队列」→ worker 认领并全流程处理 → job `ready`、云端收到 PNG、bot 推卡
- worker 不认领：查云端 `.env` 是否 `EXTERNAL_PROCESSING=true`；查 `nc -vz <云端IP> 5432` 连通性
- 卡在 `composing failed`：SFTP 通道/目录权限问题，对照方案文档第七节风险 1/9
- kill 重启：租约自动回收（`reclaim_own_host`），在途 job 断点续跑，不重复处理
- 长转录（听悟数小时）：心跳每 120s 续租约，不会被其他实例抢占

## 从旧路径切换（一次性）

| 旧命令 | 新命令 |
|---|---|
| `./start-worker.sh` | `./deploy/worker/start-worker.sh` |
| `./stop-worker.sh` | `./deploy/worker/stop-worker.sh` |

进程 / PID / 日志位置均未变化。
