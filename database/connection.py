from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import AsyncGenerator, Callable

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from .migrate import upgrade_to_head

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def _is_memory_sqlite(database_url: str) -> bool:
    """True for SQLite URLs with no file behind them (`:memory:` or empty path)."""
    if "sqlite" not in database_url:
        return False
    path = database_url.split("///", 1)[1] if "///" in database_url else ""
    path = path.split("?", 1)[0]
    return path in ("", ":memory:") or "mode=memory" in database_url


class DatabaseManager:
    """Database connection and session management."""

    def __init__(self, database_url: str, echo: bool = False):
        self.database_url = database_url
        # One shared connection is only needed so an in-memory SQLite database
        # survives between sessions; file databases use the default pool.
        memory = _is_memory_sqlite(database_url)
        self.engine = create_async_engine(
            database_url,
            poolclass=StaticPool if memory else None,
            connect_args={"check_same_thread": False} if memory else {},
            echo=echo,
        )
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def migrate(self) -> None:
        """Bring the schema up to the latest revision."""
        async with self.engine.begin() as conn:
            await conn.run_sync(upgrade_to_head)

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get an async database session."""
        async with self.async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def close(self) -> None:
        """Close the database connection."""
        await self.engine.dispose()
