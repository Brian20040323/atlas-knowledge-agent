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
        _engine = create_async_engine(settings.db_url, echo=False)
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


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    session_maker = get_session_maker()
    async with session_maker() as session:
        yield session
