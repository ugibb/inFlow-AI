#!/usr/bin/env bash
# inFlow AI — 改 .env 后：重启直跑 backend/bot + 健康检查
#
# 直接代码部署模式下，改 .env 后调用 ./start-server.sh --restart 即可
#（backend/wechat-bot 直跑宿主机，自动重新加载 .env；frontend 容器一并重建）。
#
# 用法:
#   ./sync-env-docker.sh           重启直跑 backend/bot + 验证
#   ./sync-env-docker.sh --verify  仅验证（不重启）
#
# 典型流程:
#   1. vi .env          # 修改 API Key 等
#   2. ./sync-env-docker.sh
#   3. 看到「全部通过」即可

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VERIFY_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --verify-only|--verify)
      VERIFY_ONLY=true
      ;;
    -h|--help)
      sed -n '2,13p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "[ERROR] 未知参数: $arg（./sync-env-docker.sh --help）" >&2
      exit 1
      ;;
  esac
done

if [ "$VERIFY_ONLY" = true ]; then
  echo "[INFO] 健康检查…"
  curl -sf "http://127.0.0.1:8080/api/health" || { echo "[ERROR] 后端不可达"; exit 1; }
  echo ""
  echo "[INFO] backend 进程:"
  [ -f .server/backend.pid ] && ps -p "$(cat .server/backend.pid)" -o pid,etime,cmd 2>/dev/null || true
  [ -f .server/wechat-bot.pid ] && ps -p "$(cat .server/wechat-bot.pid)" -o pid,etime,cmd 2>/dev/null || true
  exit 0
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Step 1/3  重启直跑 backend/bot + 重建 frontend 容器"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

"$SCRIPT_DIR/start-server.sh" --restart --detach

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Step 2/3  健康检查"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

curl -sf "http://127.0.0.1:8080/api/health" || { echo "[ERROR] 后端不可达"; exit 1; }
echo "健康检查通过 ✔"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Step 3/3  确认直跑进程与日志"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

TODAY="$(date +%F)"
ps -p "$(cat .server/backend.pid 2>/dev/null)" -o pid,etime,cmd 2>/dev/null \
  && echo "backend 日志: 04-log/backend/${TODAY}.log" || true
[ -f .server/wechat-bot.pid ] \
  && ps -p "$(cat .server/wechat-bot.pid)" -o pid,etime,cmd 2>/dev/null \
  && echo "bot 日志:     04-log/wechat-bot/${TODAY}.log" || true
grep started "04-log/backend/${TODAY}.log" 2>/dev/null | tail -1 || true

echo ""
echo "全部通过 ✔（有问题 tail -f 04-log/backend/${TODAY}.log）"
