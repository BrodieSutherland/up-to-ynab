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


class DatabaseManager:
    """Database connection and session management."""

    def __init__(self, database_url: str, echo: bool = False):
        self.database_url = database_url
        self.engine = create_async_engine(
            database_url,
            # SQLite specific settings
            poolclass=(StaticPool if "sqlite" in database_url else None),
            connect_args=(
                {"check_same_thread": False} if "sqlite" in database_url else {}
            ),
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
