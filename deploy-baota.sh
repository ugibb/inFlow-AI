#!/usr/bin/env bash
# inFlow AI — 宝塔面板一键部署（兼容入口，实际逻辑见 start-docker.sh）
# 用法: ./deploy-baota.sh [--detach]

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/start-docker.sh" "$@"
