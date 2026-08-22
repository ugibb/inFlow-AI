#!/usr/bin/env bash
# 停止直跑 backend / wechat-bot（基础设施容器不停止）
set -euo pipefail

# 脚本位于仓库根（2026-08-22 由 deploy/cloud/ 上移），REPO_ROOT 即脚本所在目录
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="${REPO_ROOT}/.server"

stop_pidfile() {
  local pidfile="$1" name="$2"
  [ -f "$pidfile" ] || return 0
  local pid
  pid="$(cat "$pidfile")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    echo "[INFO] 已停止 ${name}（PID ${pid}）"
    for _ in $(seq 1 20); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.5
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid"
      echo "[WARN] 已强制结束 ${name}（${pid}）"
    fi
  else
    echo "[WARN] ${name} PID ${pid} 已不存在"
  fi
  rm -f "$pidfile"
}

stop_pidfile "${PID_DIR}/backend.pid" "backend"
stop_pidfile "${PID_DIR}/wechat-bot.pid" "wechat-bot"

# 兜底：按进程名
if pgrep -f 'uvicorn inflow_server.main:app' >/dev/null; then
  echo "[INFO] 按进程名停止 backend"
  pkill -f 'uvicorn inflow_server.main:app' || true
fi
if pgrep -f 'inflow_server.extensions.wechat.bot' >/dev/null; then
  echo "[INFO] 按进程名停止 wechat-bot"
  pkill -f 'inflow_server.extensions.wechat.bot' || true
fi

echo "[INFO] 直跑进程已停止；基础设施容器仍运行（停容器：docker compose down）"
