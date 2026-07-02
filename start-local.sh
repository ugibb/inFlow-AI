#!/usr/bin/env bash
# inFlow AI 本地开发启动脚本（无需 Docker）
# 用法: ./start-local.sh [--detach]
#   默认启动后自动 tail -F 业务日志；加 --detach 则仅后台启动并退出

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

FOLLOW_LOGS=true
for arg in "$@"; do
  case "$arg" in
    --logs)
      FOLLOW_LOGS=true
      ;;
    --detach|-d)
      FOLLOW_LOGS=false
      ;;
    -h|--help)
      echo "用法: ./start-local.sh [--detach]"
      echo ""
      echo "  默认    启动后自动跟踪业务日志（04-log/backend/YYYY-MM-DD.log）"
      echo "  --detach / -d  仅后台启动，不跟踪日志"
      echo "  --logs         同默认（兼容旧参数）"
      echo ""
      echo "  Ctrl+C 退出日志跟踪时，后台服务继续运行；停止服务请用 ./stop-local.sh"
      exit 0
      ;;
    *)
      echo "[ERROR] 未知参数: $arg（可用 --help 查看用法）" >&2
      exit 1
      ;;
  esac
done

SRC_DIR="${SCRIPT_DIR}/03-src"
BACKEND_DIR="${SRC_DIR}/backend"
FRONTEND_DIR="${SRC_DIR}/frontend"

BACKEND_PORT=8000
FRONTEND_PORT=3000
LOG_DIR="${SCRIPT_DIR}/04-log"
BACKEND_LOG_DIR="${LOG_DIR}/backend"
WECHAT_BOT_LOG_DIR="${LOG_DIR}/wechat-bot"

# 本地数据库默认连接（与 backend/app/config.py 一致）
DB_USER="inFlow"
DB_PASS="inFlow"
DB_NAME="inFlow"
DB_HOST="localhost"
DB_PORT="5432"
# PostgreSQL 未加引号的标识符会折叠为小写（inFlow → inflow）
pg_ident() { echo "$1" | tr '[:upper:]' '[:lower:]'; }
DB_USER_PG="$(pg_ident "$DB_USER")"
DB_NAME_PG="$(pg_ident "$DB_NAME")"

info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
error() { echo "[ERROR] $*" >&2; }

_log_banner_line() {
  printf '%*s\n' 72 '' | tr ' ' '#'
}

# 终端与日志文件写入同一条分隔线，区分「启动脚本输出」与「业务运行日志」
print_log_section() {
  local title="$1"
  local subtitle="${2:-}"
  local log_file="${3:-}"

  echo ""
  _log_banner_line
  info "$title"
  if [ -n "$subtitle" ]; then
    echo "        $subtitle"
  fi
  _log_banner_line
  echo ""

  if [ -n "$log_file" ]; then
    {
      echo ""
      _log_banner_line | tr '#' '#'
      echo "# ${title}"
      [ -n "$subtitle" ] && echo "# ${subtitle}"
      _log_banner_line | tr '#' '#'
      echo ""
    } >> "$log_file"
  fi
}

# 终止占用指定端口的进程（含 LISTEN / CLOSE_WAIT 等非监听态占用）
kill_port() {
  local port="$1"
  local pids

  pids=$(lsof -ti ":${port}" 2>/dev/null | sort -u || true)
  if [ -z "$pids" ]; then
    return 0
  fi

  warn "端口 ${port} 已被占用，正在释放..."
  while IFS= read -r pid; do
    [ -z "$pid" ] && continue
    if kill -9 "$pid" 2>/dev/null; then
      info "已终止进程 ${pid}"
    elif sudo kill -9 "$pid" 2>/dev/null; then
      info "已终止进程 ${pid} (sudo)"
    else
      error "无法终止进程 ${pid}，请手动处理后重试"
      exit 1
    fi
  done <<< "$pids"
  sleep 1
}

backend_daily_log() {
  echo "${BACKEND_LOG_DIR}/$(date +%Y-%m-%d).log"
}

wechat_bot_daily_log() {
  echo "${WECHAT_BOT_LOG_DIR}/$(date +%Y-%m-%d).log"
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

# 停止旧进程（端口 + 微信 bot，不依赖 .pid）
stop_previous() {
  kill_port "$BACKEND_PORT"
  kill_port "$FRONTEND_PORT"
  stop_wechat_bot
  rm -f \
    "${LOG_DIR}/backend.pid" \
    "${LOG_DIR}/frontend.pid" \
    "${LOG_DIR}/wechat-bot.pid" \
    "${LOG_DIR}/backend.log" \
    "${LOG_DIR}/frontend.log" \
    "${LOG_DIR}/wechat-bot.log" 2>/dev/null || true
}

# 检查命令是否存在
require_cmd() {
  if ! command -v "$1" &>/dev/null; then
    error "未找到 $1，请先安装"
    exit 1
  fi
}

# 确保 pgvector 扩展可用
ensure_pgvector() {
  if psql -h "$DB_HOST" -p "$DB_PORT" -U "$(whoami)" -d postgres -c "CREATE EXTENSION IF NOT EXISTS vector;" &>/dev/null; then
    return 0
  fi

  warn "PostgreSQL 缺少 pgvector 扩展，正在尝试安装..."

  if command -v brew &>/dev/null; then
    brew install pgvector 2>/dev/null || true
    brew services restart postgresql@16 2>/dev/null || brew services restart postgresql 2>/dev/null || true
    sleep 2
  fi

  if psql -h "$DB_HOST" -p "$DB_PORT" -U "$(whoami)" -d postgres -c "CREATE EXTENSION IF NOT EXISTS vector;" &>/dev/null; then
    return 0
  fi

  # Homebrew pgvector 可能只支持 PG17+，为 PG16 从源码编译
  local pg_config
  pg_config=$(command -v pg_config 2>/dev/null || true)
  if [ -z "$pg_config" ] && [ -x "/opt/homebrew/opt/postgresql@16/bin/pg_config" ]; then
    pg_config="/opt/homebrew/opt/postgresql@16/bin/pg_config"
  fi

  if [ -n "$pg_config" ] && command -v git &>/dev/null && command -v make &>/dev/null; then
    info "从源码为当前 PostgreSQL 编译 pgvector（约 1 分钟）..."
    local build_dir
    build_dir=$(mktemp -d)
    if git clone --depth 1 --branch v0.8.2 https://github.com/pgvector/pgvector.git "$build_dir/pgvector" &>/dev/null; then
      make -C "$build_dir/pgvector" PG_CONFIG="$pg_config" &>/dev/null
      make -C "$build_dir/pgvector" PG_CONFIG="$pg_config" install &>/dev/null
      rm -rf "$build_dir"
      brew services restart postgresql@16 2>/dev/null || brew services restart postgresql 2>/dev/null || true
      sleep 2
    fi
  fi

  if psql -h "$DB_HOST" -p "$DB_PORT" -U "$(whoami)" -d postgres -c "CREATE EXTENSION IF NOT EXISTS vector;" &>/dev/null; then
    return 0
  fi

  error "pgvector 安装失败。可手动执行: brew install pgvector，或升级到 postgresql@17"
  exit 1
}

# 初始化本地数据库（永不 DROP；重置请用 ./reset-local-db.sh --confirm）
setup_database() {
  if [ "${inFlow_FRESH_DB:-}" = "1" ]; then
    warn "inFlow_FRESH_DB 已弃用，启动脚本不会删除数据库。"
    warn "如需重置，请先 ./stop-local.sh，再执行 ./reset-local-db.sh --confirm"
  fi

  info "检查本地数据库..."

  if ! pg_isready -h "$DB_HOST" -p "$DB_PORT" &>/dev/null; then
    if command -v brew &>/dev/null; then
      warn "PostgreSQL 未运行，正在启动..."
      brew services start postgresql@16 2>/dev/null || brew services start postgresql 2>/dev/null || true
      sleep 2
    fi
    if ! pg_isready -h "$DB_HOST" -p "$DB_PORT" &>/dev/null; then
      error "PostgreSQL 未运行，请先启动: brew services start postgresql@16"
      exit 1
    fi
  fi

  ensure_pgvector

  local psql_admin=(psql -h "$DB_HOST" -p "$DB_PORT" -U "$(whoami)" -d postgres -v ON_ERROR_STOP=1)

  if ! "${psql_admin[@]}" -tc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER_PG}'" | grep -q 1; then
    info "创建数据库用户 ${DB_USER}"
    "${psql_admin[@]}" -c "CREATE ROLE ${DB_USER_PG} WITH LOGIN PASSWORD '${DB_PASS}' CREATEDB;"
  fi

  mkdir -p "$LOG_DIR"

  if ! "${psql_admin[@]}" -tc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME_PG}'" | grep -q 1; then
    info "创建数据库 ${DB_NAME}"
    "${psql_admin[@]}" -c "CREATE DATABASE ${DB_NAME_PG} OWNER ${DB_USER_PG};"
  fi

  psql -h "$DB_HOST" -p "$DB_PORT" -U "$(whoami)" -d "$DB_NAME_PG" -v ON_ERROR_STOP=1 -c \
    "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";" &>/dev/null

  # 像 Docker entrypoint 一样先跑 SQL 迁移（幂等，每次启动都执行）
  info "执行数据库迁移..."
  local sql_file
  for sql_file in "${BACKEND_DIR}"/app/migrations/*.sql; do
    PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER_PG" -d "$DB_NAME_PG" \
      -v ON_ERROR_STOP=0 -f "$sql_file" &>/dev/null || true
  done

  info "数据库就绪 (${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME})"
}

# 安全加载 .env（Cookie 含分号、弯引号时不能用 shell source）
load_env_file() {
  local env_file="${1:-${SCRIPT_DIR}/.env}"
  [ -f "$env_file" ] || return 0

  local python_bin="python3"
  for candidate in "${BACKEND_DIR}/.venv/bin/python" python3.12 python3.11 python3; do
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
    quote_chars = ('"', "'", "\u201c", "\u201d", "\u2018", "\u2019")
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

# 加载 .env
load_env() {
  if [ ! -f .env ]; then
    if [ -f .env.example ]; then
      warn "未找到 .env，已从 .env.example 复制"
      cp .env.example .env
    fi
  fi
  load_env_file "${SCRIPT_DIR}/.env"
  export SECRET_KEY="${SECRET_KEY:-dev-local-secret-change-me-at-least-32-chars}"
  export DATABASE_URL="postgresql+asyncpg://${DB_USER_PG}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME_PG}"
  export DATABASE_URL_SYNC="postgresql://${DB_USER_PG}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME_PG}"
}

# 读取 config.py 中的布尔配置（与 Python 默认值保持一致）
read_config_bool() {
  local field="$1"
  cd "${BACKEND_DIR}" && source .venv/bin/activate && \
    python3 -c "from app.core.config import get_settings; print(getattr(get_settings(), '${field}'))" \
    2>/dev/null || echo "False"
}

# 微信 bot 消息服务需要独立 worker + service token（绑定只存凭证，不处理消息）
# 必须在启动后端之前调用，否则后端不认可 bot 的 Bearer token。
ensure_wechat_bot_config() {
  if [ -z "${SERVICE_TOKEN_WECHAT_BOT:-}" ]; then
    SERVICE_TOKEN_WECHAT_BOT="$(python3 -c 'import secrets; print(secrets.token_hex(24))' 2>/dev/null || openssl rand -hex 24)"
    export SERVICE_TOKEN_WECHAT_BOT
    warn "未配置 SERVICE_TOKEN_WECHAT_BOT，已自动生成"
    persist_wechat_token_to_env "${SERVICE_TOKEN_WECHAT_BOT}"
  fi

  local mapped="${SERVICE_TOKEN_WECHAT_BOT}:weaiw"
  if [ -z "${SERVICE_TOKENS:-}" ]; then
    export SERVICE_TOKENS="$mapped"
  elif [[ ",${SERVICE_TOKENS}," != *",${mapped},"* ]]; then
    export SERVICE_TOKENS="${SERVICE_TOKENS},${mapped}"
  fi
}

# 将自动生成的 token 写入 .env，避免后端与 bot 使用不同 token
persist_wechat_token_to_env() {
  local token="$1"
  [ -f .env ] || return 0
  if grep -q '^SERVICE_TOKEN_WECHAT_BOT=.' .env; then
    return 0
  fi
  if grep -q '^SERVICE_TOKEN_WECHAT_BOT=' .env; then
    # shellcheck disable=SC2016
    sed -i '' "s|^SERVICE_TOKEN_WECHAT_BOT=.*|SERVICE_TOKEN_WECHAT_BOT=${token}|" .env
  else
    printf '\nSERVICE_TOKEN_WECHAT_BOT=%s\n' "$token" >> .env
  fi
  local mapped="${token}:weaiw"
  if grep -q '^SERVICE_TOKENS=.' .env; then
    return 0
  fi
  if grep -q '^SERVICE_TOKENS=' .env; then
  # shellcheck disable=SC2016
    sed -i '' "s|^SERVICE_TOKENS=.*|SERVICE_TOKENS=${mapped}|" .env
  else
    printf 'SERVICE_TOKENS=%s\n' "$mapped" >> .env
  fi
  info "已写入 .env：SERVICE_TOKEN_WECHAT_BOT / SERVICE_TOKENS"
}

# 选择兼容的 Python 版本（3.13 与 asyncpg/psycopg2 不兼容）
pick_python() {
  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" &>/dev/null; then
      local ver
      ver=$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
      local major minor
      major=${ver%%.*}
      minor=${ver#*.}
      if [ "$major" -eq 3 ] && [ "$minor" -ge 11 ] && [ "$minor" -le 12 ]; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  error "需要 Python 3.11 或 3.12（当前 3.13 与部分依赖不兼容）"
  error "可安装: brew install python@3.12"
  exit 1
}

setup_backend() {
  if [ ! -d "$BACKEND_DIR" ]; then
    error "未找到后端目录: ${BACKEND_DIR}"
    exit 1
  fi

  local python_bin
  python_bin=$(pick_python)
  info "使用 ${python_bin} ($(${python_bin} --version))"

  info "准备后端环境..."
  cd "${BACKEND_DIR}"

  # 目录搬迁后 venv 内 shebang 可能仍指向旧路径，需重建
  if [ -d .venv ] && ! .venv/bin/pip --version &>/dev/null; then
    warn "虚拟环境已失效（可能因目录搬迁），正在重建..."
    rm -rf .venv
  fi

  # 若 venv 用了不兼容的 Python 版本则重建
  if [ -d .venv ]; then
    local venv_py
    venv_py=$(.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "unknown")
    if [ "$venv_py" != "3.11" ] && [ "$venv_py" != "3.12" ]; then
      warn "删除不兼容的虚拟环境 (Python ${venv_py})"
      rm -rf .venv
    fi
  fi

  if [ ! -d .venv ]; then
    info "创建 Python 虚拟环境..."
    "$python_bin" -m venv .venv
  fi

  # shellcheck disable=SC1091
  source .venv/bin/activate

  info "检查后端依赖..."
  pip install -q --upgrade pip
  if ! pip install -q -r requirements.txt; then
    error "后端依赖安装失败"
    exit 1
  fi

  if [ ! -f app/config_store.json ] && [ -f app/config_store.example.json ]; then
    cp app/config_store.example.json app/config_store.json
  fi

  cd "$SCRIPT_DIR"
}

setup_frontend() {
  if [ ! -d "$FRONTEND_DIR" ]; then
    error "未找到前端目录: ${FRONTEND_DIR}"
    exit 1
  fi

  info "准备前端环境..."
  cd "${FRONTEND_DIR}"

  if [ ! -d node_modules ]; then
    info "安装前端依赖（首次较慢）..."
    npm install --legacy-peer-deps
  fi

  cd "$SCRIPT_DIR"
}

start_services() {
  local daily_log
  daily_log=$(backend_daily_log)
  mkdir -p "$BACKEND_LOG_DIR"
  touch "$daily_log"
  printf '\n=== %s backend start ===\n' "$(date '+%Y-%m-%d %H:%M:%S')" >> "$daily_log"

  local uvicorn_access_flag="--no-access-log"
  if [ "$(read_config_bool log_access)" = "True" ]; then
    uvicorn_access_flag=""
  fi

  info "启动后端 (端口 ${BACKEND_PORT})..."
  nohup bash -c "
    cd '${BACKEND_DIR}' && \
    source .venv/bin/activate && \
    export SECRET_KEY='${SECRET_KEY}' && \
    export DATABASE_URL='${DATABASE_URL}' && \
    export DATABASE_URL_SYNC='${DATABASE_URL_SYNC}' && \
    export SERVICE_TOKENS='${SERVICE_TOKENS}' && \
    export SERVICE_TOKEN_WECHAT_BOT='${SERVICE_TOKEN_WECHAT_BOT}' && \
    exec uvicorn app.main:app --host 0.0.0.0 --port '${BACKEND_PORT}' ${uvicorn_access_flag}
  " >> "$daily_log" 2>&1 &
  disown

  info "启动前端 (端口 ${FRONTEND_PORT})..."
  nohup bash -c "
    cd '${FRONTEND_DIR}' && \
    exec npm run dev -- -p '${FRONTEND_PORT}'
  " > /dev/null 2>&1 &
  disown
}

start_wechat_bot() {
  local daily_log
  daily_log=$(backend_daily_log)
  mkdir -p "$BACKEND_LOG_DIR"
  touch "$daily_log"
  printf '\n=== %s wechat-bot start ===\n' "$(date '+%Y-%m-%d %H:%M:%S')" >> "$daily_log"

  info "启动微信 bot 消息服务..."
  nohup bash -c "
    cd '${BACKEND_DIR}' && \
    source .venv/bin/activate && \
    export NO_PROXY='localhost,127.0.0.1' && \
    export no_proxy='localhost,127.0.0.1' && \
    export DATABASE_URL='${DATABASE_URL}' && \
    export DATABASE_URL_SYNC='${DATABASE_URL_SYNC}' && \
    export inFlow_BASE='http://localhost:${BACKEND_PORT}' && \
    export inFlow_TOKEN='${SERVICE_TOKEN_WECHAT_BOT}' && \
    exec python -m app.extensions.wechat.bot
  " >> "$daily_log" 2>&1 &
  disown
}

wait_for_services() {
  local daily_log
  daily_log=$(backend_daily_log)
  info "等待服务就绪..."
  for i in $(seq 1 60); do
    local backend_ok=false
    local frontend_ok=false
    curl -sf "http://localhost:${BACKEND_PORT}/api/health" &>/dev/null && backend_ok=true
    curl -sf "http://localhost:${FRONTEND_PORT}" &>/dev/null && frontend_ok=true
    if [ "$backend_ok" = true ] && [ "$frontend_ok" = true ]; then
      return 0
    fi
    if [ $((i % 5)) -eq 0 ]; then
      warn "仍在等待... 后端:${backend_ok} 前端:${frontend_ok} (${i}/60)"
      if [ "$backend_ok" = false ] && grep -q "address already in use" "$daily_log" 2>/dev/null; then
        error "后端端口 ${BACKEND_PORT} 被占用，请执行: lsof -ti :${BACKEND_PORT} | xargs kill -9"
        exit 1
      fi
    fi
    if [ "$i" -eq 60 ]; then
      warn "服务启动超时，请查看日志:"
      echo "  tail -F ${daily_log}"
      exit 1
    fi
    sleep 2
  done
}

follow_logs() {
  local backend_daily
  backend_daily=$(backend_daily_log)

  mkdir -p "$BACKEND_LOG_DIR"
  touch "$backend_daily"

  # 仅打印到终端；勿写入日志文件，否则 tail -F 会再显示一遍
  print_log_section \
    "▶ 系统运行日志（后端 pipeline + 微信 bot + 精华卡）" \
    "${backend_daily}  |  Ctrl+C 退出跟踪，服务继续后台运行"

  tail -F "$backend_daily"
}

# ── 主流程 ──────────────────────────────────────────────
print_log_section "▶ 系统启动日志" "数据库 / 依赖 / 服务拉起"

if ! command -v psql &>/dev/null; then
  if command -v docker &>/dev/null && docker compose version &>/dev/null; then
    error "未找到 psql。本脚本仅用于 Mac 本地开发（本机 PostgreSQL + Node）。"
    echo ""
    echo "  服务器 / Docker 部署请改用："
    echo "    ./deploy-baota.sh          # 宝塔生产环境（推荐）"
    echo "    ./start.sh                 # 通用 Docker 启动"
    echo ""
    echo "  若坚持本机直跑（不推荐服务器），需先安装 PostgreSQL 客户端："
    echo "    OpenCloudOS: dnf install -y postgresql"
    exit 1
  fi
  error "未找到 psql，请先安装 PostgreSQL 客户端（Mac: brew install postgresql@16）"
  exit 1
fi

require_cmd node
require_cmd npm

load_env
stop_previous
setup_database
setup_backend
setup_frontend
ensure_wechat_bot_config
start_services
wait_for_services
start_wechat_bot

BACKEND_DAILY_LOG=$(backend_daily_log)

print_log_section "■ 系统启动完成" \
  "前端 http://localhost:${FRONTEND_PORT}  |  后端 http://localhost:${BACKEND_PORT}/api/docs"

echo ""
info "默认账号: weaiw"
info "默认密码: Aa41312432"
echo ""
info "统一日志: ${BACKEND_DAILY_LOG}（含 pipeline / 微信 bot / 精华卡渲染）"
echo ""
info "停止服务: ./stop-local.sh"

if [ "$FOLLOW_LOGS" = true ]; then
  follow_logs
else
  info "跟踪日志: tail -F ${BACKEND_DAILY_LOG}"
fi
