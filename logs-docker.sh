#!/usr/bin/env bash
# inFlow AI — 实时查看 Docker 运行日志
#
# 用法:
#   ./logs-docker.sh                    跟踪 backend + wechat-bot（默认）
#   ./logs-docker.sh --all              跟踪全部容器
#   ./logs-docker.sh backend            只跟踪 backend
#   ./logs-docker.sh backend frontend   跟踪多个指定服务
#   ./logs-docker.sh --tail 200         先显示最近 200 行再实时跟踪
#   ./logs-docker.sh --grep error       实时过滤含 error 的行
#   ./logs-docker.sh --since 10m        只看最近 10 分钟起的日志
#
# Ctrl+C 只退出日志跟踪，不会停止容器。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.baota.yml)

TAIL=80
GREP=""
SINCE=""
ALL=false
SERVICES=()

info()  { echo "[INFO]  $*"; }

usage() {
  sed -n '2,14p' "$0" | sed 's/^# \?//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --all|-a)
      ALL=true
      ;;
    --tail)
      TAIL="${2:?缺少 --tail 行数}"
      shift
      ;;
    --grep)
      GREP="${2:?缺少 --grep 关键词}"
      shift
      ;;
    --since)
      SINCE="${2:?缺少 --since 时长，如 10m、1h}"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --*)
      echo "[ERROR] 未知参数: $1（./logs-docker.sh --help）" >&2
      exit 1
      ;;
    *)
      SERVICES+=("$1")
      ;;
  esac
  shift
done

if [ "$ALL" = true ]; then
  SERVICES=()
elif [ "${#SERVICES[@]}" -eq 0 ]; then
  SERVICES=(backend wechat-bot)
fi

if ! command -v docker &>/dev/null || ! docker compose version &>/dev/null; then
  echo "[ERROR] 需要 Docker + Compose v2" >&2
  exit 1
fi

log_args=(-f --tail "$TAIL")
if [ -n "$SINCE" ]; then
  log_args=(--since "$SINCE" -f)
fi

echo ""
if [ "$ALL" = true ]; then
  info "▶ 实时日志：全部容器  |  Ctrl+C 退出（容器继续运行）"
else
  info "▶ 实时日志：${SERVICES[*]}  |  Ctrl+C 退出（容器继续运行）"
fi
if [ -n "$GREP" ]; then
  info "   过滤: grep -i '${GREP}'"
fi
echo ""

if [ "$ALL" = true ]; then
  if [ -n "$GREP" ]; then
    "${COMPOSE[@]}" logs "${log_args[@]}" 2>&1 | grep --line-buffered -Ei "$GREP" || true
  else
    "${COMPOSE[@]}" logs "${log_args[@]}"
  fi
elif [ -n "$GREP" ]; then
  "${COMPOSE[@]}" logs "${log_args[@]}" "${SERVICES[@]}" 2>&1 | grep --line-buffered -Ei "$GREP" || true
else
  "${COMPOSE[@]}" logs "${log_args[@]}" "${SERVICES[@]}"
fi
