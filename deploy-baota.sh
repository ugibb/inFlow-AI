#!/usr/bin/env bash
# inFlow AI — 宝塔面板一键部署脚本
# 用法: ./deploy-baota.sh
#
# 前置条件：
#   - 已安装 Docker + Docker Compose v2（宝塔「软件商店 → Docker 管理器」）
#   - 已配置 .env（POSTGRES_PASSWORD、SECRET_KEY）
#   - 宝塔 Nginx 反向代理已指向 127.0.0.1:8080（见 02-docs/DEPLOY_BAOTA.md）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.baota.yml)
CONFIG_STORE="03-src/backend/app/config_store.json"
CONFIG_EXAMPLE="03-src/backend/app/config_store.example.json"

info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
error() { echo "[ERROR] $*" >&2; }

# 检查 Docker
if ! command -v docker &>/dev/null; then
  error "未检测到 Docker，请先在宝塔「软件商店」安装 Docker 管理器"
  exit 1
fi

if ! docker compose version &>/dev/null; then
  error "未检测到 Docker Compose v2"
  exit 1
fi

# 检查 .env
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    error "已从 .env.example 复制 .env，请先编辑 POSTGRES_PASSWORD 和 SECRET_KEY 后重试"
    exit 1
  fi
  error "未找到 .env"
  exit 1
fi

# 初始化 LLM 配置
if [ ! -f "$CONFIG_STORE" ] && [ -f "$CONFIG_EXAMPLE" ]; then
  info "初始化 config_store.json"
  cp "$CONFIG_EXAMPLE" "$CONFIG_STORE"
fi

info "构建并启动 inFlow AI（宝塔模式，监听 127.0.0.1:8080）..."
docker compose "${COMPOSE_FILES[@]}" down 2>/dev/null || true
docker compose "${COMPOSE_FILES[@]}" build
docker compose "${COMPOSE_FILES[@]}" up -d

info "等待服务就绪..."
for i in $(seq 1 60); do
  if curl -sf -o /dev/null "http://127.0.0.1:8080" 2>/dev/null; then
    break
  fi
  if [ "$i" -eq 60 ]; then
    warn "60 秒内未响应，请检查: docker compose ${COMPOSE_FILES[*]} logs -f"
    exit 1
  fi
  sleep 2
done

echo ""
info "inFlow AI 已启动（宝塔模式）"
echo "  本机访问: http://127.0.0.1:8080"
echo "  公网访问: 通过宝塔反向代理 + 域名 + HTTPS"
echo ""
info "首次登录请查看超管账号:"
docker compose "${COMPOSE_FILES[@]}" logs backend 2>/dev/null | grep -i admin || warn "稍后再试: docker compose logs backend | grep -i admin"
echo ""
info "常用命令:"
echo "  查看日志: docker compose ${COMPOSE_FILES[*]} logs -f"
echo "  停止服务: docker compose ${COMPOSE_FILES[*]} down"
echo "  更新部署: git pull && docker compose ${COMPOSE_FILES[*]} build && docker compose ${COMPOSE_FILES[*]} up -d"
