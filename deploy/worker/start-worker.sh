#!/usr/bin/env bash
# inFlow AI 本地独立 worker 启动脚本
# 作用：连接云端 PostgreSQL（任务总线），轮询 external_processing 的外部 job，
#       本地跑完整 pipeline（采集→转录→parse→compose→index），PNG 经 SFTP 回传云端。
# 用法: ./deploy/worker/start-worker.sh [--detach]
#   默认    启动 worker 并 tail -F worker 日志（04-log/worker/YYYY-MM-DD.log）
#   --detach / -d  仅后台启动，不跟踪日志
# 停止：./deploy/worker/stop-worker.sh（或 pkill -f 'inflow_worker'）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "$REPO_ROOT"

FOLLOW_LOGS=true
for arg in "$@"; do
  case "$arg" in
    --detach|-d)
      FOLLOW_LOGS=false
      ;;
    -h|--help)
      echo "用法: ./deploy/worker/start-worker.sh [--detach]"
      echo ""
      echo "  默认    启动 worker 并跟踪日志（04-log/worker/YYYY-MM-DD.log）"
      echo "  --detach / -d  仅后台启动，不跟踪日志"
      echo ""
      echo "  配置：03-src/worker/.env.local-worker（DATABASE_URL / SFTP_HOST / SFTP_PIPELINE_DIR）"
      exit 0
      ;;
    *)
      echo "[ERROR] 未知参数: $arg（可用 --help 查看用法）" >&2
      exit 1
      ;;
  esac
done

WORKER_DIR="${REPO_ROOT}/03-src/worker"
WORKER_LOG_DIR="${REPO_ROOT}/04-log/worker"
PID_FILE="${REPO_ROOT}/.worker.pid"
ENV_WORKER="${WORKER_DIR}/.env.local-worker"

info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
error() { echo "[ERROR] $*" >&2; }

# ── 安全加载 .env.local-worker（Cookie/密码含分号、弯引号时不能用 shell source）──
load_env_file() {
  local env_file="$1"
  [ -f "$env_file" ] || return 0

  local python_bin="python3"
  for candidate in "${WORKER_DIR}/.venv/bin/python" python3.12 python3.11 python3; do
    if command -v "$candidate" &>/dev/null || [ -x "$candidate" ]; then
      python_bin="$candidate"
      break
    fi
  done

  eval "$("$python_bin" - "$env_file" <<'PY'
import shlex
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
items = {}
try:
    from dotenv import dotenv_values
    items = dotenv_values(env_path) or {}
except Exception:
    quote_chars = ('"', "'", "“", "”", "‘", "’")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        for q in quote_chars:
            if len(val) >= 2 and val[0] == val[-1] == q:
                val = val[1:-1]
                break
        items[key.strip()] = val

for key, val in items.items():
    if val is not None:
        print(f"export {key}={shlex.quote(val)}")
PY
)"
}

# ── 前置检查 ──────────────────────────────────────────────────────
if [ ! -f "${ENV_WORKER}" ]; then
  error "未找到 ${ENV_WORKER}"
  error "请从方案文档第六节复制模板，填入云端 PG 连接与 SFTP 配置后重试"
  exit 1
fi
if [ ! -d "${WORKER_DIR}/.venv" ]; then
  error "未找到 worker venv（${WORKER_DIR}/.venv），请先创建："
  error "  cd ${WORKER_DIR} && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi
if ! command -v sftp &>/dev/null; then
  error "未找到 sftp 命令（macOS/Linux 自带，确认已安装 openssh-client）"
  exit 1
fi

if ! "${WORKER_DIR}/.venv/bin/python" -m playwright --version &>/dev/null; then
  warn "Playwright 未安装，compose 渲染 PNG 将失败："
  warn "  ${WORKER_DIR}/.venv/bin/python -m playwright install chromium"
fi
if ! command -v ffmpeg &>/dev/null; then
  warn "未找到 ffmpeg（音频转码/下载可能用到）：brew install ffmpeg"
fi

# ── 加载 worker 配置到环境变量 ────────────────────────────────────
load_env_file "${ENV_WORKER}"
export LOG_TO_STDOUT="1"   # 前台运行也可在终端看日志

if [ -z "${DATABASE_URL:-}" ]; then
  error ".env.local-worker 缺少 DATABASE_URL（应指向云端 PostgreSQL 5432）"
  exit 1
fi

mkdir -p "${WORKER_LOG_DIR}"
TODAY="$(date +%F)"
LOG_FILE="${WORKER_LOG_DIR}/${TODAY}.log"

# 若已有 worker 在跑，先提示
if [ -f "${PID_FILE}" ] && kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; then
  warn "已有 worker 在运行（PID $(cat "${PID_FILE}")）。先执行 ./deploy/worker/stop-worker.sh 再启动。"
  exit 1
fi

info "启动本地 worker…"
info "  日志: ${LOG_FILE}"
info "  DB:   ${DATABASE_URL##*@}"

cd "${WORKER_DIR}"
.venv/bin/python -m inflow_worker >> "${LOG_FILE}" 2>&1 &
WORKER_PID=$!
echo "${WORKER_PID}" > "${PID_FILE}"
info "worker 已启动（PID ${WORKER_PID}）"

if [ "${FOLLOW_LOGS}" = true ]; then
  info "跟踪日志中（Ctrl+C 退出跟踪，worker 继续后台运行；停止用 ./deploy/worker/stop-worker.sh）"
  tail -F "${LOG_FILE}"
fi
