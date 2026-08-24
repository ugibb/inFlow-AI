from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from backend.core.config import get_settings
from backend.core.utils.logger import get_logger
import re

settings = get_settings()
logger = get_logger("database")

engine = create_async_engine(
    settings.database_url,
    echo=settings.log_sql,
    pool_size=20,
    max_overflow=10,
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

class Base(DeclarativeBase):
    pass

async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def init_db():
    import os
    import glob
    from pathlib import Path

    # 确保所有 ORM 模型注册到 metadata，再 create_all
    import backend.core.models  # noqa: F401

    migrations_dir = os.path.join(os.path.dirname(__file__), 'migrations')

    # pgvector / uuid-ossp 必须在 create_all 之前启用（articles.embedding 依赖 vector 类型）
    async with engine.begin() as conn:
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 每条 SQL 独立事务，避免前一条失败导致同文件后续语句（如 CREATE users）回滚
    if os.path.isdir(migrations_dir):
        for sql_file in sorted(glob.glob(os.path.join(migrations_dir, '*.sql'))):
            statements = _split_sql(Path(sql_file).read_text(encoding='utf-8'))
            for statement in statements:
                statement = statement.strip()
                if not statement:
                    continue
                try:
                    async with engine.begin() as conn:
                        await conn.execute(text(statement))
                except Exception as e:
                    logger.warning(
                        "Migration warning (%s): %s",
                        os.path.basename(sql_file),
                        e,
                    )


def _strip_sql_comments(sql: str) -> str:
    """Remove -- line comments so semicolons inside comments don't split statements."""
    lines = []
    for line in sql.splitlines():
        if '--' in line:
            line = line[: line.index('--')]
        lines.append(line)
    return '\n'.join(lines)


def _split_sql(sql: str) -> list[str]:
    """Split SQL into statements, keeping DO $$...$$ blocks intact."""
    statements = []
    dollar_blocks = []

    def replace_dollar(m):
        dollar_blocks.append(m.group(0))
        return f'__DOLLAR_BLOCK_{len(dollar_blocks) - 1}__'

    sql_escaped = re.sub(r'\$\$.*?\$\$', replace_dollar, _strip_sql_comments(sql), flags=re.DOTALL)
    parts = sql_escaped.split(';')

    for part in parts:
        part = part.strip()
        if not part:
            continue
        for i, block in enumerate(dollar_blocks):
            part = part.replace(f'__DOLLAR_BLOCK_{i}__', block)
        statements.append(part)

    return statements
