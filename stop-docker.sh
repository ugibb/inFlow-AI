#!/usr/bin/env bash
# inFlow AI — 停止 Docker 部署（宝塔 / 服务器）
# 用法: ./stop-docker.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.baota.yml)

info() { echo "[INFO]  $*"; }

info "停止 inFlow AI Docker 服务栈..."
"${COMPOSE[@]}" down
info "已停止"
