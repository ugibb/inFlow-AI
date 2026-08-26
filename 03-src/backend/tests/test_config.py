"""数据库连接串自动拼接 —— resolved_database_url / resolved_database_url_sync 单测。

背景：DATABASE_URL 拆为 POSTGRES_* 组件后，由代码自动拼 URL，避免
「POSTGRES_PASSWORD 与 DATABASE_URL 密码不一致」的部署坑（502/认证失败）。
规则：
  1. 显式 DATABASE_URL（非 change_me 占位符）优先 → 兼容旧部署
  2. DATABASE_URL 是 .env.example 占位符（change_me）→ 忽略，改走组件拼
  3. 无 DATABASE_URL → POSTGRES_* 组件自动拼，密码特殊字符 URL 编码
"""
from backend.core.config import Settings


def test_component_build_when_no_dsn() -> None:
    # 无显式 DSN：组件拼 URL，密码特殊字符（@、空格、/）URL 编码
    s = Settings(postgres_password="p@ss word/ok", database_url="", database_url_sync="")
    assert s.resolved_database_url == (
        "postgresql+asyncpg://inflow:p%40ss+word%2Fok@localhost:5432/inflow"
    )
    assert s.resolved_database_url_sync == (
        "postgresql://inflow:p%40ss+word%2Fok@localhost:5432/inflow"
    )


def test_explicit_dsn_wins_over_components() -> None:
    # 显式非占位符 DSN 优先（旧部署：.env 直接配了完整连接串）
    s = Settings(
        postgres_password="component_pw",
        database_url="postgresql+asyncpg://user:real@db.host:5432/mydb",
    )
    assert s.resolved_database_url == "postgresql+asyncpg://user:real@db.host:5432/mydb"

    s2 = Settings(
        postgres_password="component_pw",
        database_url_sync="postgresql://user:sync@db.host:5432/mydb",
    )
    assert s2.resolved_database_url_sync == "postgresql://user:sync@db.host:5432/mydb"


def test_placeholder_dsn_falls_back_to_components() -> None:
    # .env.example 占位符（change_me）被忽略：
    # start-server.sh 已自动生成真实 POSTGRES_PASSWORD，组件拼应胜出
    s = Settings(
        postgres_password="real_pw",
        database_url="postgresql+asyncpg://inflow:change_me@127.0.0.1:5432/inflow",
        database_url_sync="postgresql://inflow:change_me@127.0.0.1:5432/inflow",
    )
    assert s.resolved_database_url == "postgresql+asyncpg://inflow:real_pw@localhost:5432/inflow"
    assert s.resolved_database_url_sync == "postgresql://inflow:real_pw@localhost:5432/inflow"


def test_component_overrides() -> None:
    # 全组件覆盖：host/user/port/db 均可按需指定
    s = Settings(
        postgres_user="alice",
        postgres_password="pw",
        postgres_host="db.internal",
        postgres_port=5433,
        postgres_db="kb",
        database_url="",  # 覆盖仓库根 .env 的显式 DSN，隔离测试
        database_url_sync="",
    )
    assert s.resolved_database_url == "postgresql+asyncpg://alice:pw@db.internal:5433/kb"
