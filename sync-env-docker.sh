#!/usr/bin/env bash
# inFlow AI — 改 .env 后：同步到 Docker 并验证 Key 是否生效
#
# 用法:
#   ./sync-env-docker.sh           重建 backend/wechat-bot + 探测 Key
#   ./sync-env-docker.sh --verify  仅验证（不重启容器）
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
      sed -n '2,12p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "[ERROR] 未知参数: $arg（./sync-env-docker.sh --help）" >&2
      exit 1
      ;;
  esac
done

if [ "$VERIFY_ONLY" = true ]; then
  exec "$SCRIPT_DIR/verify-docker-keys.sh"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Step 1/2  同步 .env → Docker（重建 backend + wechat-bot）"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

"$SCRIPT_DIR/start-docker.sh" --restart --detach

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Step 2/2  验证 Key 是否生效"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

"$SCRIPT_DIR/verify-docker-keys.sh"
