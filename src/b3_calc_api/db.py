"""
B3 CALC API async database session factory.

Creates an AsyncEngine reading B3_CALC_DATABASE_URL from environment.
Exposes get_db() as a FastAPI dependency — injects AsyncSession per request.

Pool settings (QUERY-04):
  pool_size=5, max_overflow=10 -> max 15 concurrent connections from this service.
  With 3 services: 3 x 15 = 45 peak connections, well within POSTGRES_MAX_CONNECTIONS=200.
"""
import os
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)

# Raises KeyError on startup if env var is missing — fail fast, no silent misconfiguration
DATABASE_URL = os.environ["B3_CALC_DATABASE_URL"]

engine = create_async_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,   # test connection health before checkout
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # REQUIRED for async — prevents MissingGreenlet after commit
)


async def get_db() -> AsyncSession:  # type: ignore[override]
    """FastAPI dependency: yields a per-request AsyncSession."""
    async with AsyncSessionLocal() as session:
        yield session
