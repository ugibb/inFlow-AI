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

if ! docker info 2>/dev/null | grep -q "Registry Mirrors"; then
  warn "未检测到 Docker 镜像加速，国内 CVM 拉取 docker.io 可能超时"
  echo "  请配置 /etc/docker/daemon.json 后执行 systemctl restart docker"
  echo "  详见 02-docs/DEPLOY_BAOTA_STEP_BY_STEP.md 第 6.3 步"
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

# 微信 bot 需要独立 worker + service token（绑定只存凭证，不处理消息）
ensure_wechat_bot_config() {
  local token="${SERVICE_TOKEN_WECHAT_BOT:-}"
  if [ -z "$token" ] && grep -q '^SERVICE_TOKEN_WECHAT_BOT=.' .env 2>/dev/null; then
    token="$(grep '^SERVICE_TOKEN_WECHAT_BOT=' .env | head -1 | cut -d= -f2- | tr -d '"')"
  fi
  if [ -z "$token" ]; then
    token="$(openssl rand -hex 24)"
    warn "未配置 SERVICE_TOKEN_WECHAT_BOT，已自动生成并写入 .env"
    if grep -q '^SERVICE_TOKEN_WECHAT_BOT=' .env 2>/dev/null; then
      sed -i "s|^SERVICE_TOKEN_WECHAT_BOT=.*|SERVICE_TOKEN_WECHAT_BOT=${token}|" .env
    else
      printf '\nSERVICE_TOKEN_WECHAT_BOT=%s\n' "$token" >> .env
    fi
  fi

  local mapped="${token}:weaiw"
  if ! grep -q '^SERVICE_TOKENS=.' .env 2>/dev/null; then
    if grep -q '^SERVICE_TOKENS=' .env 2>/dev/null; then
      sed -i "s|^SERVICE_TOKENS=.*|SERVICE_TOKENS=${mapped}|" .env
    else
      printf 'SERVICE_TOKENS=%s\n' "$mapped" >> .env
    fi
  fi

  if ! grep -q '^TROVE_PUBLIC_BASE=.' .env 2>/dev/null; then
    warn "建议在 .env 设置 TROVE_PUBLIC_BASE=https://你的域名（微信精华卡外链）"
  fi
}

ensure_wechat_bot_config

info "构建并启动 inFlow AI（宝塔模式，监听 127.0.0.1:8080）..."
docker compose "${COMPOSE_FILES[@]}" down 2>/dev/null || true
if ! docker compose "${COMPOSE_FILES[@]}" build; then
  error "镜像构建失败。查看 frontend 详细日志："
  echo "  docker compose ${COMPOSE_FILES[*]} build frontend --progress=plain 2>&1 | tail -80"
  echo ""
  echo "  常见原因：内存不足（free -h 查看，建议 ≥4GB 可用）；可临时加 swap 后重试"
  exit 1
fi
info "拉取运行时基础镜像（nginx / postgres / redis）..."
docker pull nginx:alpine
docker compose "${COMPOSE_FILES[@]}" pull postgres redis 2>/dev/null || true
docker compose "${COMPOSE_FILES[@]}" up -d
# 确保 nginx 端口映射为 127.0.0.1:8080（避免与宝塔 80 端口冲突的旧容器残留）
docker compose "${COMPOSE_FILES[@]}" up -d --force-recreate nginx

REQUIRED_SERVICES=(nginx backend frontend postgres redis wechat-bot)
missing=()
for svc in "${REQUIRED_SERVICES[@]}"; do
  if ! docker compose "${COMPOSE_FILES[@]}" ps --status running --services | grep -qx "$svc"; then
    missing+=("$svc")
  fi
done
if [ "${#missing[@]}" -gt 0 ]; then
  error "以下服务未运行: ${missing[*]}"
  for svc in "${missing[@]}"; do
    echo ""
    echo "── ${svc} 日志 ──"
    docker compose "${COMPOSE_FILES[@]}" logs --tail 40 "$svc" 2>/dev/null || true
  done
  if printf '%s\n' "${missing[@]}" | grep -qx nginx; then
    echo ""
    echo "  常见原因: nginx:alpine 未拉取、8080 被占用、03-src/nginx/nginx.conf 缺失"
    echo "  尝试: docker pull nginx:alpine"
    echo "        docker compose ${COMPOSE_FILES[*]} up -d nginx"
  fi
  if printf '%s\n' "${missing[@]}" | grep -qx wechat-bot; then
    echo ""
    echo "  微信 bot 未运行：检查 .env 中 SERVICE_TOKEN_WECHAT_BOT 是否已设置"
    echo "  尝试: docker compose ${COMPOSE_FILES[*]} logs wechat-bot --tail 40"
    echo "        docker compose ${COMPOSE_FILES[*]} up -d wechat-bot"
  fi
  exit 1
fi

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

if ! curl -sf "http://127.0.0.1:8080/api/health" 2>/dev/null | grep -q '"status"'; then
  warn "前端可访问，但后端 /api/health 未就绪"
  echo "  查看后端日志: docker compose ${COMPOSE_FILES[*]} logs backend --tail 80"
  echo "  容器内日志文件: docker compose ${COMPOSE_FILES[*]} exec backend ls -la log/ 2>/dev/null || true"
  exit 1
fi

echo ""
info "inFlow AI 已启动（宝塔模式）"
echo "  本机访问: http://127.0.0.1:8080"
echo "  公网访问: 通过宝塔反向代理 + 域名 + HTTPS"
echo ""
info "首次登录默认超管账号（数据库迁移自动创建，不会写入日志）："
echo "  用户名: weaiw"
echo "  密码:   Aa41312432"
echo "  登录后请立即在「设置」中修改密码。"
echo ""
echo "  若 users 表不存在，手动触发数据库迁移："
echo "  docker compose ${COMPOSE_FILES[*]} exec backend python -c \"import asyncio, app.core.models; from app.core.database import init_db; asyncio.run(init_db())\""
echo "  docker compose ${COMPOSE_FILES[*]} exec postgres psql -U trove -d trove -c \"SELECT username, is_super_admin, is_active FROM users;\""
echo ""
info "常用命令:"
echo "  查看日志: docker compose ${COMPOSE_FILES[*]} logs -f"
echo "  微信 bot: docker compose ${COMPOSE_FILES[*]} logs wechat-bot --tail 50"
echo "  停止服务: docker compose ${COMPOSE_FILES[*]} down"
echo "  更新部署: git pull && docker compose ${COMPOSE_FILES[*]} build && docker compose ${COMPOSE_FILES[*]} up -d"
