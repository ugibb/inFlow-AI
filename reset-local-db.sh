#!/usr/bin/env bash
# inFlow AI 本地数据库重置（唯一允许 DROP 库的入口）
# 用法: ./reset-local-db.sh --confirm
#
# 警告: 将删除 inFlow 库中的全部数据（文章、标签、用户等），不可恢复。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SRC_DIR="${SCRIPT_DIR}/03-src"
BACKEND_DIR="${SRC_DIR}/backend"
LOG_DIR="${SCRIPT_DIR}/04-log"

DB_USER="inFlow"
DB_PASS="inFlow"
DB_NAME="inFlow"
DB_HOST="localhost"
DB_PORT="5432"
# PostgreSQL 未加引号的标识符会折叠为小写（inFlow → inflow）
pg_ident() { echo "$1" | tr '[:upper:]' '[:lower:]'; }
DB_USER_PG="$(pg_ident "$DB_USER")"
DB_NAME_PG="$(pg_ident "$DB_NAME")"

info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
error() { echo "[ERROR] $*" >&2; }

usage() {
  cat <<'EOF'
用法: ./reset-local-db.sh --confirm

将 DROP 并重建本地 PostgreSQL 数据库 inFlow，然后重新执行 SQL 迁移。
此操作会永久删除库内所有数据，执行前请先备份:

  pg_dump -h localhost -U inFlow -d inFlow -F c -f inFlow_backup.dump

必须先停止本地服务（释放数据库连接）:

  ./stop-local.sh

EOF
}

if [ "${1:-}" != "--confirm" ]; then
  usage
  exit 1
fi

if ! pg_isready -h "$DB_HOST" -p "$DB_PORT" &>/dev/null; then
  error "PostgreSQL 未运行，请先启动: brew services start postgresql@16"
  exit 1
fi

# 检查是否有进程仍占用 inFlow 库连接
active_conns=$(
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$(whoami)" -d postgres -Atc \
    "SELECT count(*) FROM pg_stat_activity WHERE datname='${DB_NAME_PG}' AND pid <> pg_backend_pid();" \
    2>/dev/null || echo "0"
)
if [ "${active_conns:-0}" -gt 0 ]; then
  warn "检测到 ${active_conns} 个进程仍连接 ${DB_NAME}（通常是后端或微信 bot）"
  warn "请先执行: ./stop-local.sh"
  exit 1
fi

warn "即将删除数据库 ${DB_NAME} 中的全部数据"
read -r -p "输入 RESET 以继续: " confirm_text
if [ "$confirm_text" != "RESET" ]; then
  info "已取消"
  exit 0
fi

psql_admin=(psql -h "$DB_HOST" -p "$DB_PORT" -U "$(whoami)" -d postgres -v ON_ERROR_STOP=1)

if ! "${psql_admin[@]}" -tc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER_PG}'" | grep -q 1; then
  info "创建数据库用户 ${DB_USER}"
  "${psql_admin[@]}" -c "CREATE ROLE ${DB_USER_PG} WITH LOGIN PASSWORD '${DB_PASS}' CREATEDB;"
fi

info "DROP DATABASE ${DB_NAME}..."
"${psql_admin[@]}" -c "DROP DATABASE IF EXISTS ${DB_NAME_PG};"

info "CREATE DATABASE ${DB_NAME}..."
"${psql_admin[@]}" -c "CREATE DATABASE ${DB_NAME_PG} OWNER ${DB_USER_PG};"

psql -h "$DB_HOST" -p "$DB_PORT" -U "$(whoami)" -d "$DB_NAME_PG" -v ON_ERROR_STOP=1 -c \
  "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";" &>/dev/null

info "执行数据库迁移..."
mkdir -p "$LOG_DIR"
sql_file=""
for sql_file in "${BACKEND_DIR}"/app/migrations/*.sql; do
  [ -f "$sql_file" ] || continue
  PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER_PG" -d "$DB_NAME_PG" \
    -v ON_ERROR_STOP=0 -f "$sql_file" &>/dev/null || true
done

touch "${LOG_DIR}/.db-initialized"

info "数据库已重置 (${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME})"
info "请执行 ./start-local.sh 重新启动服务"
