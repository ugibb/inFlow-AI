#!/usr/bin/env bash
# inFlow AI — 服务器基础设施容器启动（直接代码部署模式下，backend/bot 由 ./start-server.sh 直跑）
#
# 用法:
#   ./start-docker.sh              启动基础设施容器（postgres/redis/nginx/frontend）
#   ./start-docker.sh --detach     仅后台启动
#   ./start-docker.sh --logs       只跟踪 backend 日志（直跑模式下请用 ./start-server.sh --logs）
#   ./start-docker.sh --restart    重建 frontend 容器（直跑 backend/bot 的重建用 ./start-server.sh）
#   ./start-docker.sh --verify     启动后自动验证 Key + 部署挂载（常与 --restart 合用）
#   ./sync-env-docker.sh           改 .env 后：同步 Docker + 验证 Key + 部署校验（推荐）
#   ./verify-docker-keys.sh        仅验证 Key，不重启
#   ./verify-docker-deploy.sh      仅校验 Pipeline 挂载与前后端一致性
#   ./logs-docker.sh               实时查看 Docker 运行日志
#   ./stop-docker.sh               停止全部容器
#
# ⚠️ 直接代码部署（推荐，日志好定位）：应用用 ./start-server.sh 直跑宿主机，
#    本脚本只负责基础设施容器。首次运行会自动：复制 .env.example、生成密码/密钥、配置微信 bot token。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.baota.yml)
CONFIG_STORE="03-src/backend/app/config_store.json"
CONFIG_EXAMPLE="03-src/backend/app/config_store.example.json"

FOLLOW_LOGS=true
LOGS_ONLY=false
FORCE_RECREATE=false
VERIFY_KEYS=false

for arg in "$@"; do
  case "$arg" in
    --detach|-d) FOLLOW_LOGS=false ;;
    --logs) LOGS_ONLY=true; FOLLOW_LOGS=true ;;
    --restart) FORCE_RECREATE=true ;;
    --verify) VERIFY_KEYS=true ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "[ERROR] 未知参数: $arg（./start-docker.sh --help）" >&2
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

# 生产环境自动使用独立 pipeline 目录，避免误挂到 03-src/backend/data
bootstrap_pipeline_dir() {
  local pipeline_dir
  pipeline_dir=$(env_get INFLOW_PIPELINE_DATA_DIR)
  local prod_dir="/www/data/inflow/pipeline"

  if [[ "$SCRIPT_DIR" == /www/wwwroot/* ]] || [[ -d /www/server/panel ]]; then
    if [ -z "$pipeline_dir" ] \
      || [[ "$pipeline_dir" == ./03-src/* ]] \
      || [[ "$pipeline_dir" == */03-src/backend/data ]]; then
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
    env_set INFLOW_PIPELINE_DATA_DIR "./03-src/backend/data"
    info "本地开发使用 INFLOW_PIPELINE_DATA_DIR=./03-src/backend/data"
  fi
}

follow_logs() {
  exec "$SCRIPT_DIR/logs-docker.sh" "$@"
}

if [ "$LOGS_ONLY" = true ]; then
  follow_logs
  exit 0
fi

if ! command -v docker &>/dev/null || ! docker compose version &>/dev/null; then
  error "需要 Docker + Compose v2（宝塔：软件商店 → Docker 管理器）"
  exit 1
fi

bootstrap_env

if [ ! -f "$CONFIG_STORE" ] && [ -f "$CONFIG_EXAMPLE" ]; then
  cp "$CONFIG_EXAMPLE" "$CONFIG_STORE"
  info "已初始化 config_store.json"
fi

info "启动基础设施容器（postgres / redis / nginx / frontend）…"

# 直接代码部署模式：backend / wechat-bot 已在 compose 中注释，改为宿主机直跑，
# 由 ./start-server.sh 管理（PID + 04-log 文本日志，改代码后重启即可，便于定位问题）。
# 本脚本只拉起基础设施容器。
"${COMPOSE[@]}" up -d --build --force-recreate frontend
"${COMPOSE[@]}" up -d nginx postgres redis

for i in $(seq 1 45); do
  if curl -sf "http://127.0.0.1:8080/api/health" 2>/dev/null | grep -q '"status"'; then
    break
  fi
  [ "$i" -eq 45 ] && warn "健康检查超时：请确认 backend 已直跑（./start-server.sh --restart），或查看 04-log/backend/$(date +%F).log"
  sleep 2
done

echo ""
info "inFlow AI 基础设施已运行（backend / bot 请用 ./start-server.sh 直跑）"
echo "  本机: http://127.0.0.1:8080"
echo "  公网: 宝塔反向代理 → 127.0.0.1:8080"
echo "  默认账号: weaiw / Aa41312432（登录后请改密）"
echo ""
echo "  启动应用（直跑 backend + wechat-bot）: ./start-server.sh"
echo "  改 .env / 拉代码后:                  ./start-server.sh --restart"
echo "  只看日志:                            ./start-server.sh --logs"
echo "  停止直跑:                            ./stop-server.sh"
echo "  停止容器:                            ./stop-docker.sh"
echo ""

if [ "$VERIFY_KEYS" = true ]; then
  "$SCRIPT_DIR/verify-docker-keys.sh"
  "$SCRIPT_DIR/verify-docker-deploy.sh"
fi

if [ "$FOLLOW_LOGS" = true ]; then
  follow_logs
fi
