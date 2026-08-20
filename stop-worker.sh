#!/usr/bin/env bash
# 停止本地 worker（按 .worker.pid 或进程名）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/.worker.pid"

if [ -f "${PID_FILE}" ]; then
  PID="$(cat "${PID_FILE}")"
  if kill -0 "${PID}" 2>/dev/null; then
    kill "${PID}"
    echo "[INFO] 已发送停止信号给 worker（PID ${PID}）"
    for _ in $(seq 1 20); do
      kill -0 "${PID}" 2>/dev/null || break
      sleep 0.5
    done
    kill -0 "${PID}" 2>/dev/null && kill -9 "${PID}" && echo "[WARN] 已强制结束 ${PID}"
    rm -f "${PID_FILE}"
  else
    echo "[WARN] PID ${PID} 已不存在，清理 PID 文件"
    rm -f "${PID_FILE}"
  fi
else
  # 兜底：按进程名
  if pgrep -f 'app.local_worker' >/dev/null; then
    echo "[INFO] 未找到 PID 文件，按进程名停止 app.local_worker"
    pkill -f 'app.local_worker'
  else
    echo "[INFO] 没有正在运行的 worker"
  fi
fi
