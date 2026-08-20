#!/usr/bin/env bash
# inFlow AI — 服务器：从 /www/wwwroot/inflow-ai-deploy.tar.gz 全量更新代码（保留 .env / 数据库 / pipeline）
#
# 前置：Mac 已上传压缩包到 /www/wwwroot/inflow-ai-deploy.tar.gz
# 用法（在服务器上）:
#   cd /www/wwwroot/inflow-ai && chmod +x deploy-update-server.sh && ./deploy-update-server.sh
#
# 若已手动 rm -rf 项目目录：先把 .env 备份放在 /tmp/inflow.env.bak.*，再执行本脚本（会新建目录）。

set -euo pipefail

PROJECT_DIR="/www/wwwroot/inflow-ai"
TARBALL="/www/wwwroot/inflow-ai-deploy.tar.gz"
PIPELINE_DIR="/www/data/inflow/pipeline"
export COMPOSE="docker compose -f ${PROJECT_DIR}/docker-compose.yml -f ${PROJECT_DIR}/docker-compose.baota.yml"

info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

STAMP=$(date +%Y%m%d_%H%M%S)
ENV_BAK="/tmp/inflow.env.bak.${STAMP}"
CONFIG_BAK="/tmp/inflow.config.bak.${STAMP}"

info "发版时间戳: ${STAMP}"

[ -f "${TARBALL}" ] || error "压缩包不存在: ${TARBALL}（请先从 Mac 执行 scp 到该路径）"

# ── 1. 备份 .env ──
if [ -f "${PROJECT_DIR}/.env" ]; then
  cp "${PROJECT_DIR}/.env" "${ENV_BAK}"
  info "已备份 .env → ${ENV_BAK}"
elif LATEST_ENV="$(ls -t /tmp/inflow.env.bak.* 2>/dev/null | head -1)" && [ -n "${LATEST_ENV}" ] && [ -f "${LATEST_ENV}" ]; then
  ENV_BAK="${LATEST_ENV}"
  warn "项目目录无 .env，使用已有备份: ${ENV_BAK}"
else
  error "找不到 .env 且无 /tmp/inflow.env.bak.*。请先: cp .env.example ${PROJECT_DIR}/.env && vi ${PROJECT_DIR}/.env"
fi

# ── 2. 备份 config_store（可选）──
if [ -f "${PROJECT_DIR}/03-src/backend/app/config_store.json" ]; then
  cp "${PROJECT_DIR}/03-src/backend/app/config_store.json" "${CONFIG_BAK}"
  info "已备份 config_store → ${CONFIG_BAK}"
fi

# ── 3. 备份数据库 ──
mkdir -p /www/backup
if docker ps --format '{{.Names}}' | grep -qx 'inflow-db'; then
  if [ -d "${PROJECT_DIR}" ] && [ -f "${PROJECT_DIR}/docker-compose.yml" ]; then
    cd "${PROJECT_DIR}"
    ${COMPOSE} exec -T postgres pg_dump -U inflow inflow > "/www/backup/inflow_${STAMP}.sql"
    info "已备份数据库 → /www/backup/inflow_${STAMP}.sql"
  else
    warn "项目目录不完整，跳过数据库备份（容器仍在运行）"
  fi
else
  warn "inflow-db 未运行，跳过数据库备份"
fi

# ── 4. 清空并解压 ──
info "清空 ${PROJECT_DIR} 并解压…"
rm -rf "${PROJECT_DIR}"
mkdir -p "${PROJECT_DIR}"
tar xzf "${TARBALL}" -C "${PROJECT_DIR}"

# ── 5. 恢复配置 ──
cp "${ENV_BAK}" "${PROJECT_DIR}/.env"
if [ -f "${CONFIG_BAK}" ]; then
  cp "${CONFIG_BAK}" "${PROJECT_DIR}/03-src/backend/app/config_store.json"
fi
if ! grep -q '^INFLOW_PIPELINE_DATA_DIR=' "${PROJECT_DIR}/.env"; then
  echo "INFLOW_PIPELINE_DATA_DIR=${PIPELINE_DIR}" >> "${PROJECT_DIR}/.env"
fi
sudo mkdir -p "${PIPELINE_DIR}"
sudo chown -R "$(whoami):$(whoami)" /www/data/inflow 2>/dev/null || true

info "INFLOW_PIPELINE_DATA_DIR=$(grep '^INFLOW_PIPELINE_DATA_DIR=' "${PROJECT_DIR}/.env" | cut -d= -f2-)"

# ── 6. 部署 ──
cd "${PROJECT_DIR}"
chmod +x deploy-baota.sh start-docker.sh sync-env-docker.sh \
  verify-docker-keys.sh verify-docker-deploy.sh logs-docker.sh stop-docker.sh \
  deploy-update-server.sh 2>/dev/null || true

info "重建容器（约 5～15 分钟）…"
./start-docker.sh --restart --detach --verify

info "发版完成"
curl -s http://127.0.0.1:8080/api/health || true
echo ""
${COMPOSE} ps
