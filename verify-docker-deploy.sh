#!/usr/bin/env bash
# inFlow AI — 部署后校验：Pipeline 共享卷 + 前后端容器一致性
#
# 用法: ./verify-docker-deploy.sh
# 通常在 ./sync-env-docker.sh 或 ./start-docker.sh --verify 之后自动调用。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.baota.yml)
PROD_PIPELINE="/www/data/inflow/pipeline"

info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
error() { echo "[ERROR] $*" >&2; }

env_get() {
  local key="$1"
  grep "^${key}=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' || true
}

is_production_host() {
  [[ "$SCRIPT_DIR" == /www/wwwroot/* ]] || [[ -d /www/server/panel ]]
}

container_data_mount() {
  local name="$1"
  docker inspect "$name" --format '{{range .Mounts}}{{if eq .Destination "/app/data"}}{{.Source}}{{end}}{{end}}' 2>/dev/null || true
}

resolve_path() {
  local p="$1"
  if command -v readlink &>/dev/null && readlink -f "$p" &>/dev/null; then
    readlink -f "$p"
  elif command -v realpath &>/dev/null; then
    realpath "$p"
  else
    echo "$p"
  fi
}

if ! command -v docker &>/dev/null; then
  error "需要 Docker"
  exit 1
fi

FAIL=0

echo ""
info "── Pipeline 存储校验 ──"

configured="$(env_get INFLOW_PIPELINE_DATA_DIR)"
if [ -z "$configured" ]; then
  error ".env 缺少 INFLOW_PIPELINE_DATA_DIR（请执行 ./start-docker.sh 会自动补齐）"
  FAIL=1
else
  info ".env INFLOW_PIPELINE_DATA_DIR=$configured"
fi

if is_production_host; then
  if [[ "$configured" == ./03-src/* ]] || [[ "$configured" == */03-src/backend/data ]]; then
    error "生产环境不应使用项目内 data 目录，应为 $PROD_PIPELINE"
    error "修复: echo 'INFLOW_PIPELINE_DATA_DIR=$PROD_PIPELINE' >> .env && ./start-docker.sh --restart"
    FAIL=1
  fi
  if [ -n "$configured" ] && [ "$configured" != "$PROD_PIPELINE" ]; then
    warn "生产环境推荐 INFLOW_PIPELINE_DATA_DIR=$PROD_PIPELINE（当前: $configured）"
  fi
fi

for svc in inflow-backend inflow-wechat-bot; do
  if ! docker ps --format '{{.Names}}' | grep -qx "$svc"; then
    warn "容器未运行: $svc（跳过挂载检查）"
    continue
  fi
  mount="$(container_data_mount "$svc")"
  if [ -z "$mount" ]; then
    error "$svc 未挂载 /app/data"
    FAIL=1
    continue
  fi
  info "$svc → $mount"
done

backend_mount="$(container_data_mount inflow-backend)"
bot_mount="$(container_data_mount inflow-wechat-bot)"
if [ -n "$backend_mount" ] && [ -n "$bot_mount" ]; then
  b_resolved="$(resolve_path "$backend_mount")"
  w_resolved="$(resolve_path "$bot_mount")"
  if [ "$b_resolved" != "$w_resolved" ]; then
    error "backend 与 wechat-bot 的 data 挂载不一致"
    error "  backend:     $b_resolved"
    error "  wechat-bot:  $w_resolved"
    FAIL=1
  else
    info "backend / wechat-bot 共享同一 data 目录 ✓"
  fi
  if [ -n "$configured" ]; then
    cfg_resolved="$(resolve_path "$configured")"
    if [ "$b_resolved" != "$cfg_resolved" ]; then
      error "容器挂载与 .env 不一致"
      error "  .env 期望: $(resolve_path "$configured")"
      error "  实际挂载:  $b_resolved"
      error "修复: ./start-docker.sh --restart --detach"
      FAIL=1
    fi
  fi
fi

echo ""
info "── 前端发版校验 ──"
if docker ps --format '{{.Names}}' | grep -qx inflow-frontend; then
  fe_image="$(docker inspect inflow-frontend --format '{{.Image}}' 2>/dev/null || true)"
  fe_created="$(docker inspect inflow-frontend --format '{{.Created}}' 2>/dev/null || true)"
  info "inflow-frontend 镜像: ${fe_image:0:19}…"
  info "容器创建时间: $fe_created"
  if [ -d .git ] && command -v git &>/dev/null; then
    head_sha="$(git rev-parse --short HEAD 2>/dev/null || true)"
    if [ -n "$head_sha" ]; then
      info "当前代码 commit: $head_sha（若刚 git pull，请确认已 --build frontend）"
    fi
  fi
else
  warn "inflow-frontend 未运行"
fi

echo ""
if [ "$FAIL" -eq 0 ]; then
  echo "=== 部署校验通过：Pipeline 路径与容器挂载一致 ==="
else
  echo "=== 部署校验未通过：请按上方提示修复后重跑 ./sync-env-docker.sh ==="
  exit 1
fi
