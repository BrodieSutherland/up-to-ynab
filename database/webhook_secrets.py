from typing import Protocol

from sqlalchemy import select

from database.connection import SessionFactory
from database.models import WebhookSecret


class WebhookSecretStore(Protocol):
    """Signing secrets of the Up webhooks this app created, by webhook id."""

    async def all(self) -> dict[str, str]: ...

    async def save(self, webhook_id: str, secret_key: str) -> None: ...

    async def delete(self, webhook_id: str) -> None:
        """Forget a secret; a no-op if none is stored."""
        ...


class SqlWebhookSecretStore:
    """WebhookSecretStore over the webhook_secrets table."""

    def __init__(self, session_factory: SessionFactory):
        self._session_factory = session_factory

    async def all(self) -> dict[str, str]:
        async with self._session_factory() as session:
            result = await session.execute(select(WebhookSecret))
            return {row.webhook_id: row.secret_key for row in result.scalars()}

    async def save(self, webhook_id: str, secret_key: str) -> None:
        async with self._session_factory() as session:
            await session.merge(
                WebhookSecret(webhook_id=webhook_id, secret_key=secret_key)
            )

    async def delete(self, webhook_id: str) -> None:
        async with self._session_factory() as session:
            row = await session.get(WebhookSecret, webhook_id)
            if row is not None:
                await session.delete(row)
