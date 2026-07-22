from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import Base

_engine = None
_async_session_maker: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args = {}
        if settings.db_url.startswith("sqlite"):
            # 多人并发写：拉长 busy 等待，减少 "database is locked"
            connect_args = {"timeout": 30.0}
        _engine = create_async_engine(
            settings.db_url,
            echo=False,
            connect_args=connect_args,
        )
    return _engine


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    global _async_session_maker
    if _async_session_maker is None:
        _async_session_maker = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_maker


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_sqlite_columns)
        await conn.run_sync(_enable_sqlite_wal)


def _enable_sqlite_wal(sync_conn) -> None:
    try:
        sync_conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        sync_conn.exec_driver_sql("PRAGMA busy_timeout=30000")
        sync_conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
    except Exception:  # noqa: BLE001
        pass


def _migrate_sqlite_columns(sync_conn) -> None:
    """Add new columns to existing SQLite tables if missing."""
    rows = sync_conn.exec_driver_sql("PRAGMA table_info(documents)").fetchall()
    cols = {row[1] for row in rows}
    if "source_type" not in cols:
        sync_conn.exec_driver_sql(
            "ALTER TABLE documents ADD COLUMN source_type VARCHAR(40) DEFAULT 'text'"
        )
    if "file_path" not in cols:
        sync_conn.exec_driver_sql(
            "ALTER TABLE documents ADD COLUMN file_path VARCHAR(500) DEFAULT ''"
        )
    if "user_id" not in cols:
        sync_conn.exec_driver_sql(
            "ALTER TABLE documents ADD COLUMN user_id INTEGER DEFAULT NULL"
        )
        sync_conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_documents_user_id ON documents (user_id)"
        )

    conv_rows = sync_conn.exec_driver_sql("PRAGMA table_info(conversations)").fetchall()
    conv_cols = {row[1] for row in conv_rows}
    if "user_id" not in conv_cols:
        sync_conn.exec_driver_sql(
            "ALTER TABLE conversations ADD COLUMN user_id INTEGER DEFAULT NULL"
        )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    session_maker = get_session_maker()
    async with session_maker() as session:
        yield session
