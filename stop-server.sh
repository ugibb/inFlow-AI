#!/usr/bin/env bash
# 停止直跑 backend / wechat-bot（基础设施容器不停止；停容器用 ./stop-docker.sh）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="${SCRIPT_DIR}/.server"

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
if pgrep -f 'uvicorn app.main:app' >/dev/null; then
  echo "[INFO] 按进程名停止 backend"
  pkill -f 'uvicorn app.main:app' || true
fi
if pgrep -f 'app.extensions.wechat.bot' >/dev/null; then
  echo "[INFO] 按进程名停止 wechat-bot"
  pkill -f 'app.extensions.wechat.bot' || true
fi

echo "[INFO] 直跑进程已停止；基础设施容器仍运行（./stop-docker.sh 停止容器）"
