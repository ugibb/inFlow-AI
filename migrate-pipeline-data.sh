#!/usr/bin/env bash
# 将 inflow-backend 容器内 /app/data 迁移到宿主机 pipeline 目录
# 用于阶段 1：首次启用 INFLOW_PIPELINE_DATA_DIR 共享卷前执行
#
# 用法（服务器）:
#   cd /www/wwwroot/inflow-ai
#   ./migrate-pipeline-data.sh
#
# 可选环境变量:
#   INFLOW_PIPELINE_DATA_DIR  目标目录（默认读 .env，否则 /www/data/inflow/pipeline）
#   INFLOW_BACKEND_CONTAINER  源容器名（默认 inflow-backend）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CONTAINER="${INFLOW_BACKEND_CONTAINER:-inflow-backend}"

env_get() {
  local key="$1"
  grep "^${key}=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' || true
}

TARGET="${INFLOW_PIPELINE_DATA_DIR:-}"
if [ -z "$TARGET" ] && [ -f .env ]; then
  TARGET="$(env_get INFLOW_PIPELINE_DATA_DIR)"
fi
TARGET="${TARGET:-/www/data/inflow/pipeline}"

info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
error() { echo "[ERROR] $*" >&2; }

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  error "容器不存在: $CONTAINER（请先启动 backend）"
  exit 1
fi

if ! docker exec "$CONTAINER" test -d /app/data 2>/dev/null; then
  warn "容器内 /app/data 不存在，将只创建宿主机目录"
  mkdir -p "$TARGET"
  info "已创建: $TARGET"
  exit 0
fi

FILE_COUNT="$(docker exec "$CONTAINER" sh -c 'find /app/data -type f 2>/dev/null | wc -l' | tr -d ' ')"

mkdir -p "$TARGET"

if [ "${FILE_COUNT:-0}" -eq 0 ]; then
  info "容器内 /app/data 无文件，已创建空目录: $TARGET"
  exit 0
fi

info "从 $CONTAINER:/app/data 复制 $FILE_COUNT 个文件到 $TARGET …"
docker cp "${CONTAINER}:/app/data/." "$TARGET/"

HOST_COUNT="$(find "$TARGET" -type f 2>/dev/null | wc -l | tr -d ' ')"
PNG_COUNT="$(find "$TARGET/03_display" -name '*.png' 2>/dev/null | wc -l | tr -d ' ')"

info "迁移完成: 宿主机 $HOST_COUNT 个文件, 03_display PNG $PNG_COUNT 个"
info "下一步:"
echo "  1. 确认 .env: INFLOW_PIPELINE_DATA_DIR=$TARGET"
echo "  2. ./start-docker.sh --restart --detach"
echo "  3. docker compose -f docker-compose.yml -f docker-compose.baota.yml exec backend  find data/03_display -name '*.png' | wc -l"
echo "  4. docker compose -f docker-compose.yml -f docker-compose.baota.yml exec wechat-bot find data/03_display -name '*.png' | wc -l"
