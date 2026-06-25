"""Minimal async database access for Resource Registry (MVP 1).

Supports runtime database switching via database_admin_service + runtime JSON.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_engine: AsyncEngine | None = None
AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None
_engine_lock = asyncio.Lock()


def _create_engine_and_factory(database_url: str) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    settings = get_settings()
    engine = create_async_engine(
        database_url,
        echo=settings.db_echo,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, factory


def _bootstrap_engine() -> None:
    global _engine, AsyncSessionLocal
    from app.services.database_admin_service import resolve_active_database_url

    url = resolve_active_database_url()
    _engine, AsyncSessionLocal = _create_engine_and_factory(url)


_bootstrap_engine()


async def reload_database_engine(database: str) -> str:
    """Dispose current engine and bind to a new database. Called after runtime switch."""
    global _engine, AsyncSessionLocal
    settings = get_settings()
    new_url = settings.build_database_url(database=database)
    async with _engine_lock:
        if _engine is not None:
            await _engine.dispose()
        _engine, AsyncSessionLocal = _create_engine_and_factory(new_url)
    return new_url


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    if AsyncSessionLocal is None:
        _bootstrap_engine()
    async with AsyncSessionLocal() as session:  # type: ignore[misc]
        yield session
