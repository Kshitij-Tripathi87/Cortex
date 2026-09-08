"""Database infrastructure — SQLAlchemy declarative base and session management."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


_engine = None
_session_factory = None


async def init_db(dsn: str) -> None:
    global _engine, _session_factory
    settings = get_settings()
    if "sqlite" in dsn:
        _engine = create_async_engine(
            dsn,
            echo=False,
        )
    else:
        _engine = create_async_engine(
            dsn,
            echo=False,
            pool_size=settings.db_pool_min,
            max_overflow=settings.db_pool_max - settings.db_pool_min,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

    # Import all Nexus models to register them with SQLAlchemy metadata,
    # then create tables (idempotent; safe for dev; Alembic migrations for prod).
    import app.modules.nexus_spine.persistence.models  # noqa: F401 — registers tables on Base.metadata

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db first.")
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency — yields a DB session per request."""
    async with get_session() as session:
        yield session
