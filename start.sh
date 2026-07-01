#!/usr/bin/env bash
# inFlow AI 一键启动脚本
# 用法: ./start.sh
# 若端口 80 被占用，会先终止占用进程再启动

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 对外入口端口（Nginx，见 docker-compose.yml）
HTTP_PORT=80

info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
error() { echo "[ERROR] $*" >&2; }

# 终止占用指定端口的进程
kill_port() {
  local port="$1"
  local pids

  pids=$(lsof -ti ":${port}" -sTCP:LISTEN 2>/dev/null || true)
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

# 检查 Docker
if ! command -v docker &>/dev/null; then
  error "未检测到 Docker"
  echo ""
  echo "  本地开发无需 Docker，请运行:"
  echo "    ./start-local.sh"
  echo ""
  echo "  或使用 Docker 部署:"
  echo "    brew install --cask docker"
  exit 1
fi

if ! docker compose version &>/dev/null; then
  error "未检测到 Docker Compose v2，请升级 Docker"
  exit 1
fi

# 检查 .env
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    warn "未找到 .env，已从 .env.example 复制"
    cp .env.example .env
    error "请先编辑 .env，至少设置 POSTGRES_PASSWORD 和 SECRET_KEY，然后重新运行 ./start.sh"
    echo ""
    echo "  POSTGRES_PASSWORD=\$(openssl rand -base64 24)"
    echo "  SECRET_KEY=\$(openssl rand -base64 48)"
    exit 1
  else
    error "未找到 .env 和 .env.example"
    exit 1
  fi
fi

# 可选：预填 LLM 配置
if [ ! -f 03-src/backend/app/config_store.json ] && [ -f 03-src/backend/app/config_store.example.json ]; then
  info "初始化 config_store.json"
  cp 03-src/backend/app/config_store.example.json 03-src/backend/app/config_store.json
fi

info "停止已有 inFlow AI 容器..."
docker compose -f docker-compose.yml -f docker-compose.local.yml down 2>/dev/null || true

kill_port "${HTTP_PORT}"

info "启动 inFlow AI 服务栈..."
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d

info "等待服务就绪..."
for i in $(seq 1 30); do
  if curl -sf -o /dev/null "http://localhost:${HTTP_PORT}" 2>/dev/null; then
    break
  fi
  if [ "$i" -eq 30 ]; then
    warn "服务尚未在 30 秒内响应，请检查: docker compose -f docker-compose.yml -f docker-compose.local.yml logs -f"
    exit 1
  fi
  sleep 2
done

echo ""
info "inFlow AI 已启动"
echo "  访问地址: http://localhost:${HTTP_PORT}"
echo "  API 文档: http://localhost:${HTTP_PORT}/api/docs"
echo ""
info "首次登录请查看超管账号密码:"
docker compose logs backend 2>/dev/null | grep -i admin || warn "暂未生成 admin 日志，稍后再试: docker compose -f docker-compose.yml -f docker-compose.local.yml logs backend | grep -i admin"
echo ""
info "常用命令:"
echo "  查看日志: docker compose -f docker-compose.yml -f docker-compose.local.yml logs -f"
echo "  停止服务: docker compose -f docker-compose.yml -f docker-compose.local.yml down"
