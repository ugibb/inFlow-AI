#!/usr/bin/env bash
# inFlow AI — 云端（腾讯云）代码直跑部署一键启动（deploy/cloud/）
#
# 部署形态：保留 infra 容器（postgres / redis / nginx / frontend），
#            backend 与 wechat-bot 直接跑在宿主机（uvicorn / python -m bot），
#            日志写 04-log/backend、04-log/wechat-bot，PID 管理在 .server/。
#            好处：改代码 git pull 后只需重启两个直跑进程，日志 tail 文本文件即可定位问题。
#
# 用法（在仓库根执行）:
#   ./deploy/cloud/start-server.sh              启动/重建基础设施容器 + 直跑 backend/bot，并跟踪日志
#   ./deploy/cloud/start-server.sh --detach     仅后台启动，不跟踪日志
#   ./deploy/cloud/start-server.sh --logs       只跟踪日志（服务已在跑，不重建）
#   ./deploy/cloud/start-server.sh --restart    改 .env / 拉代码后重建（默认行为就是重建）
#   ./deploy/cloud/start-server.sh --verify     启动后额外验证健康状态
#   ./deploy/cloud/stop-server.sh               停止直跑 backend/bot（容器不停止）
#
# 首次运行会自动：复制 .env.example、生成密码/密钥、配置微信 bot token。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "$REPO_ROOT"

# 第一个 -f 必须是仓库根的 docker-compose.yml：compose 相对路径以其所在目录（仓库根）解析
COMPOSE=(docker compose -f docker-compose.yml -f deploy/cloud/docker-compose.baota.yml)
SERVER_DIR="${REPO_ROOT}/03-src/server"
PID_DIR="${REPO_ROOT}/.server"
BACKEND_PID_FILE="${PID_DIR}/backend.pid"
BOT_PID_FILE="${PID_DIR}/wechat-bot.pid"
CONFIG_STORE="${REPO_ROOT}/03-src/core/inflow_core/config_store.json"
CONFIG_EXAMPLE="${REPO_ROOT}/03-src/core/inflow_core/config_store.example.json"

FOLLOW_LOGS=true
LOGS_ONLY=false
VERIFY_KEYS=false

for arg in "$@"; do
  case "$arg" in
    --detach|-d) FOLLOW_LOGS=false ;;
    --logs) FOLLOW_LOGS=true; LOGS_ONLY=true ;;
    --restart) : ;;  # 默认即重建，flag 为语义明确保留
    --verify) VERIFY_KEYS=true ;;
    -h|--help)
      sed -n '2,18p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "[ERROR] 未知参数: $arg（./deploy/cloud/start-server.sh --help）" >&2
      exit 1
      ;;
  esac
done

info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
error() { echo "[ERROR] $*" >&2; }

env_set() {
  local key="$1" val="$2"
  if grep -q "^${key}=" .env 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" .env
  else
    printf '%s=%s\n' "$key" "$val" >> .env
  fi
}

env_get() {
  local key="$1"
  grep "^${key}=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' || true
}

# 自动补齐 .env（仅需 POSTGRES_PASSWORD + SECRET_KEY + API Key，其余脚本处理）
bootstrap_env() {
  if [ ! -f .env ]; then
    if [ -f .env.example ]; then
      cp .env.example .env
      info "已从 .env.example 创建 .env"
    else
      error "未找到 .env"
      exit 1
    fi
  fi

  local pg sec
  pg=$(env_get POSTGRES_PASSWORD)
  sec=$(env_get SECRET_KEY)
  if [ -z "$pg" ] || [[ "$pg" == change_me* ]]; then
    pg=$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)
    env_set POSTGRES_PASSWORD "$pg"
    warn "已自动生成 POSTGRES_PASSWORD（首次部署后请勿修改，否则与数据库卷不一致）"
  fi
  if [ -z "$sec" ] || [[ "$sec" == change_me* ]]; then
    sec=$(openssl rand -base64 48 | tr -d '/+=' | head -c 48)
    env_set SECRET_KEY "$sec"
    warn "已自动生成 SECRET_KEY"
  fi

  # 微信 bot：token 与 SERVICE_TOKENS 必须一致，否则 401
  local token
  token=$(env_get SERVICE_TOKEN_WECHAT_BOT)
  if [ -z "$token" ]; then
    token=$(openssl rand -hex 24)
    env_set SERVICE_TOKEN_WECHAT_BOT "$token"
    warn "已自动生成 SERVICE_TOKEN_WECHAT_BOT"
  fi
  local act_as
  act_as=$(env_get WECHAT_BOT_ACT_AS_USER)
  [ -n "$act_as" ] || act_as="weaiw"
  env_set SERVICE_TOKENS "${token}:${act_as}"

  if ! grep -q '^inFlow_PUBLIC_BASE=.' .env 2>/dev/null; then
    warn "可选：在 .env 设置 inFlow_PUBLIC_BASE=https://你的域名"
  fi

  bootstrap_pipeline_dir
}

# 生产环境自动使用独立 pipeline 目录，避免误用源码树内相对路径
bootstrap_pipeline_dir() {
  local pipeline_dir
  pipeline_dir=$(env_get INFLOW_PIPELINE_DATA_DIR)
  local prod_dir="/www/data/inflow/pipeline"

  if [[ "$REPO_ROOT" == /www/wwwroot/* ]] || [[ -d /www/server/panel ]]; then
    if [ -z "$pipeline_dir" ] \
      || [[ "$pipeline_dir" == ./03-src/* ]] \
      || [[ "$pipeline_dir" == */03-src/backend/data ]] \
      || [[ "$pipeline_dir" == */03-src/server/data ]]; then
      pipeline_dir="$prod_dir"
      env_set INFLOW_PIPELINE_DATA_DIR "$pipeline_dir"
      warn "生产环境已自动设置 INFLOW_PIPELINE_DATA_DIR=$pipeline_dir"
    fi
    if [ ! -d "$pipeline_dir" ]; then
      if command -v sudo &>/dev/null; then
        sudo mkdir -p "$pipeline_dir" && sudo chown -R "$(whoami):$(whoami)" "$pipeline_dir" 2>/dev/null \
          || mkdir -p "$pipeline_dir" 2>/dev/null || true
      else
        mkdir -p "$pipeline_dir" 2>/dev/null || true
      fi
    fi
  elif [ -z "$pipeline_dir" ]; then
    env_set INFLOW_PIPELINE_DATA_DIR "./03-src/server/data"
    info "本地开发使用 INFLOW_PIPELINE_DATA_DIR=./03-src/server/data"
  fi
}

# ── 安全加载 .env（Cookie/密码含分号、弯引号时不能用 shell source）──
load_env_file() {
  local env_file="$1"
  [ -f "$env_file" ] || return 0

  local python_bin="python3"
  for candidate in "${SERVER_DIR}/.venv/bin/python" python3.12 python3.11 python3; do
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

# 停止直跑进程（按 PID 文件，超时强杀）
stop_pidfile() {
  local pidfile="$1" name="$2"
  [ -f "$pidfile" ] || return 0
  local pid
  pid="$(cat "$pidfile")"
  if kill -0 "$pid" 2>/dev/null; then
    info "停止旧 ${name}（PID ${pid}）"
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.5
    done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$pidfile"
}

# ── 只跟日志，不重建 ──────────────────────────────────────────────
if [ "$LOGS_ONLY" = true ]; then
  TODAY="$(date +%F)"
  exec tail -F "${REPO_ROOT}/04-log/backend/${TODAY}.log"
fi

# ── 前置检查 ──────────────────────────────────────────────────────
if ! command -v docker &>/dev/null || ! docker compose version &>/dev/null; then
  error "需要 Docker + Compose v2（宝塔：软件商店 → Docker 管理器）"
  exit 1
fi
if [ ! -d "${SERVER_DIR}/.venv" ]; then
  error "未找到 server venv（${SERVER_DIR}/.venv），请先创建："
  error "  cd ${SERVER_DIR} && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

bootstrap_env
load_env_file .env

if [ ! -f "$CONFIG_STORE" ] && [ -f "$CONFIG_EXAMPLE" ]; then
  cp "$CONFIG_EXAMPLE" "$CONFIG_STORE"
  info "已初始化 config_store.json"
fi

# ── 构造直跑环境（backend/bot 直连宿主回环的 postgres/redis 容器）──
export DATABASE_URL="postgresql+asyncpg://inflow:${POSTGRES_PASSWORD}@127.0.0.1:5432/inflow"
export DATABASE_URL_SYNC="postgresql://inflow:${POSTGRES_PASSWORD}@127.0.0.1:5432/inflow"
export REDIS_URL="redis://127.0.0.1:6379/0"
export LOG_TO_STDOUT="1"
# 不设 LOG_DIR：默认 log_dir="04-log/backend" 由 get_log_dir_path 相对仓库根解析，
# 即 <仓库>/04-log/backend，与本脚本日志重定向目标一致。
export inFlow_ENV="${inFlow_ENV:-production}"
if [ -n "${INFLOW_PIPELINE_DATA_DIR:-}" ]; then
  local_data_abs="$INFLOW_PIPELINE_DATA_DIR"
  case "$local_data_abs" in
    /*) : ;;
    *) local_data_abs="${REPO_ROOT}/${local_data_abs#./}" ;;
  esac
  export DATA_ROOT="$local_data_abs"
  info "DATA_ROOT=$local_data_abs"
fi

mkdir -p "${REPO_ROOT}/04-log/backend" "${REPO_ROOT}/04-log/wechat-bot" "${PID_DIR}"
TODAY="$(date +%F)"

# ── 基础设施容器（backend / wechat-bot 已在 compose 注释，直跑替代）──
info "启动基础设施容器（postgres / redis / nginx / frontend）…"
"${COMPOSE[@]}" up -d --build --force-recreate frontend
"${COMPOSE[@]}" up -d nginx postgres redis

stop_pidfile "${BACKEND_PID_FILE}" "backend"
stop_pidfile "${BOT_PID_FILE}" "wechat-bot"

# ── backend 直跑 ─────────────────────────────────────────────────
info "启动 backend（直跑 uvicorn :8000）…"
cd "${SERVER_DIR}"
nohup .venv/bin/uvicorn inflow_server.main:app --host 0.0.0.0 --port 8000 --workers 1 \
  >> "${REPO_ROOT}/04-log/backend/${TODAY}.log" 2>&1 &
echo $! > "${BACKEND_PID_FILE}"
info "  backend PID $(cat "${BACKEND_PID_FILE}")（日志 04-log/backend/${TODAY}.log）"

# ── wechat-bot 直跑（有 token 才起）──────────────────────────────
if [ -n "${SERVICE_TOKEN_WECHAT_BOT:-}" ]; then
  export inFlow_BASE="${inFlow_BASE:-http://127.0.0.1:8000}"
  export inFlow_TOKEN="${SERVICE_TOKEN_WECHAT_BOT}"
  export inFlow_PUBLIC_BASE="${inFlow_PUBLIC_BASE:-http://127.0.0.1:8080}"
  # bot 日志独立目录（bot.py 用 get_log_dir_path()，绝对路径直接生效）
  export LOG_DIR="${REPO_ROOT}/04-log/wechat-bot"
  info "启动 wechat-bot（直跑 python -m inflow_server.extensions.wechat.bot）…"
  nohup "${SERVER_DIR}/.venv/bin/python" -m inflow_server.extensions.wechat.bot \
    >> "${REPO_ROOT}/04-log/wechat-bot/${TODAY}.log" 2>&1 &
  echo $! > "${BOT_PID_FILE}"
  info "  wechat-bot PID $(cat "${BOT_PID_FILE}")（日志 04-log/wechat-bot/${TODAY}.log）"
else
  warn "未配置 SERVICE_TOKEN_WECHAT_BOT，跳过 wechat-bot"
fi

cd "${REPO_ROOT}"

# ── 健康检查（nginx → host.docker.internal → backend:8000）───────
for i in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:8080/api/health" 2>/dev/null | grep -q '"status"'; then
    break
  fi
  [ "$i" -eq 60 ] && warn "健康检查超时，请查看 04-log/backend/${TODAY}.log"
  sleep 2
done

echo ""
info "inFlow AI 已运行（直接代码部署）"
echo "  本机: http://127.0.0.1:8080"
echo "  公网: 宝塔反向代理 → 127.0.0.1:8080"
echo "  后端日志: 04-log/backend/$(date +%F).log"
echo "  Bot 日志: 04-log/wechat-bot/$(date +%F).log"
echo "  改 .env / 拉代码后: ./deploy/cloud/start-server.sh --restart"
echo "  只看日志:           ./deploy/cloud/start-server.sh --logs"
echo "  停止直跑:           ./deploy/cloud/stop-server.sh"
echo ""

if [ "$VERIFY_KEYS" = true ]; then
  info "验证后端健康:"
  curl -s "http://127.0.0.1:8080/api/health" || true
  echo ""
  info "运行中进程:"
  ps -p "$(cat "${BACKEND_PID_FILE}")" -o pid,etime,cmd 2>/dev/null || true
  [ -f "${BOT_PID_FILE}" ] && ps -p "$(cat "${BOT_PID_FILE}")" -o pid,etime,cmd 2>/dev/null || true
fi

if [ "$FOLLOW_LOGS" = true ]; then
  info "跟踪 backend 日志中（Ctrl+C 退出跟踪，服务继续后台运行；停止用 ./deploy/cloud/stop-server.sh）"
  tail -F "${REPO_ROOT}/04-log/backend/${TODAY}.log"
fi
