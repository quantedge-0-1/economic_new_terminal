from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@event.listens_for(engine.sync_engine, "connect")
def _set_wal_mode(dbapi_conn, _record):
    """Enable WAL so reads don't block during background writes."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")  # safe + faster than FULL with WAL
    cursor.close()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def init_db() -> None:
    from app.db.base import Base
    from app.db import models  # noqa: F401 — register all models

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("SQLite database initialized")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
