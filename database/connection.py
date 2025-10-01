from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from utils.config import get_settings

from .models import Base


class DatabaseManager:
    """Database connection and session management."""

    def __init__(self):
        self.settings = get_settings()
        self.engine = create_async_engine(
            self.settings.database_url,
            # SQLite specific settings
            poolclass=StaticPool if "sqlite" in self.settings.database_url else None,
            connect_args=(
                {"check_same_thread": False}
                if "sqlite" in self.settings.database_url
                else {}
            ),
            echo=self.settings.debug_mode,
        )
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def create_tables(self) -> None:
        """Create all database tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

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


# Global database manager instance
db_manager = DatabaseManager()
