#!/usr/bin/env bash
# inFlow AI — 服务器 Docker 一键启动（对标 ./start-local.sh）
#
# 用法:
#   ./start-docker.sh              启动并跟踪 backend 日志（Ctrl+C 不停止容器）
#   ./start-docker.sh --detach     仅后台启动
#   ./start-docker.sh --logs       只跟踪日志（服务已在跑）
#   ./start-docker.sh --restart    改 .env 后重建 backend + wechat-bot
#   ./stop-docker.sh               停止全部容器
#
# 首次运行会自动：复制 .env.example、生成密码/密钥、配置微信 bot token。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.baota.yml)
CONFIG_STORE="03-src/backend/app/config_store.json"
CONFIG_EXAMPLE="03-src/backend/app/config_store.example.json"

FOLLOW_LOGS=true
LOGS_ONLY=false
FORCE_RECREATE=false

for arg in "$@"; do
  case "$arg" in
    --detach|-d) FOLLOW_LOGS=false ;;
    --logs) LOGS_ONLY=true; FOLLOW_LOGS=true ;;
    --restart) FORCE_RECREATE=true ;;
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

  if ! grep -q '^TROVE_PUBLIC_BASE=.' .env 2>/dev/null; then
    warn "可选：在 .env 设置 TROVE_PUBLIC_BASE=https://你的域名"
  fi
}

follow_logs() {
  echo ""
  info "▶ 跟踪运行日志（backend + wechat-bot，Ctrl+C 退出，容器继续运行）"
  echo "    等价于本地: tail -F 04-log/backend/日期.log"
  echo ""
  "${COMPOSE[@]}" logs -f --tail 80 backend wechat-bot
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

info "启动 inFlow AI（Docker / 宝塔模式，127.0.0.1:8080）..."

if [ "$FORCE_RECREATE" = true ]; then
  "${COMPOSE[@]}" up -d --build --force-recreate backend wechat-bot
  "${COMPOSE[@]}" up -d nginx frontend postgres redis
else
  # 日常启动：不 down 全栈，避免误删数据卷感；仅 build + up
  "${COMPOSE[@]}" up -d --build
fi

for i in $(seq 1 45); do
  if curl -sf "http://127.0.0.1:8080/api/health" 2>/dev/null | grep -q '"status"'; then
    break
  fi
  [ "$i" -eq 45 ] && warn "健康检查超时，可执行: ${COMPOSE[*]} logs backend --tail 50"
  sleep 2
done

echo ""
info "inFlow AI 已运行"
echo "  本机: http://127.0.0.1:8080"
echo "  公网: 宝塔反向代理 → 127.0.0.1:8080"
echo "  默认账号: weaiw / Aa41312432（登录后请改密）"
echo ""
echo "  改 .env 后: ./start-docker.sh --restart"
echo "  只看日志:   ./start-docker.sh --logs"
echo "  停止:       ./stop-docker.sh"
echo ""

if [ "$FOLLOW_LOGS" = true ]; then
  follow_logs
fi
