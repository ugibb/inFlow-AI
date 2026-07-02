#!/usr/bin/env bash
# inFlow AI 本地开发停止脚本（按端口 + 进程名，不依赖 .pid 文件）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/04-log"

BACKEND_PORT=8000
FRONTEND_PORT=3000

info() { echo "[INFO] $*"; }

kill_port() {
  local port="$1"
  local pids
  pids=$(lsof -ti ":${port}" 2>/dev/null | sort -u || true)
  if [ -z "$pids" ]; then
    return 0
  fi
  info "释放端口 ${port}"
  echo "$pids" | xargs kill -9 2>/dev/null || true
}

stop_wechat_bot() {
  local pids
  # macOS 进程名为 Python（大写），勿只用 'python -m'
  pids=$(pgrep -f 'app\.extensions\.wechat\.bot' 2>/dev/null || true)
  if [ -z "$pids" ]; then
    return 0
  fi
  info "停止微信 bot"
  echo "$pids" | xargs kill 2>/dev/null || true
  sleep 1
  echo "$pids" | xargs kill -9 2>/dev/null || true
}

# 清理旧版 pid / 根目录 log 文件（若存在）
rm -f \
  "${LOG_DIR}/backend.pid" \
  "${LOG_DIR}/frontend.pid" \
  "${LOG_DIR}/wechat-bot.pid" \
  "${LOG_DIR}/backend.log" \
  "${LOG_DIR}/frontend.log" \
  "${LOG_DIR}/wechat-bot.log"

kill_port "$BACKEND_PORT"
kill_port "$FRONTEND_PORT"
stop_wechat_bot

info "本地服务已停止"
