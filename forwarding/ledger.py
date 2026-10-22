from dataclasses import dataclass
from typing import Protocol

import structlog
from sqlalchemy import select

from database.connection import SessionFactory
from database.models import LedgerEntry

logger = structlog.get_logger()


@dataclass(frozen=True)
class Forwarded:
    """The transaction is in YNAB (ynab_transaction_id is None if it already was)."""

    up_transaction_id: str
    ynab_transaction_id: str | None


@dataclass(frozen=True)
class Skipped:
    """The transaction was deliberately not forwarded."""

    up_transaction_id: str
    reason: str


@dataclass(frozen=True)
class Failed:
    """Forwarding failed; Up redelivery will attempt it again."""

    up_transaction_id: str
    reason: str


Outcome = Forwarded | Skipped | Failed


class Ledger(Protocol):
    """Record of what happened to each Up transaction."""

    async def is_handled(self, up_transaction_id: str) -> bool:
        """True once forwarded or skipped; a failed transaction is not handled."""
        ...

    async def record(self, outcome: Outcome) -> None:
        """Store an outcome. A handled transaction is never overwritten."""
        ...


def _fields(outcome: Outcome) -> tuple[str, str | None, str | None]:
    """Return (status, ynab_transaction_id, reason) for an outcome."""
    if isinstance(outcome, Forwarded):
        return "forwarded", outcome.ynab_transaction_id, None
    if isinstance(outcome, Skipped):
        return "skipped", None, outcome.reason
    return "failed", None, outcome.reason


class SqlLedger:
    """Ledger over the ledger_entries table."""

    def __init__(self, session_factory: SessionFactory):
        self._session_factory = session_factory

    async def _entry(self, session, up_transaction_id: str) -> LedgerEntry | None:
        result = await session.execute(
            select(LedgerEntry).where(
                LedgerEntry.up_transaction_id == up_transaction_id
            )
        )
        return result.scalar_one_or_none()

    async def is_handled(self, up_transaction_id: str) -> bool:
        async with self._session_factory() as session:
            entry = await self._entry(session, up_transaction_id)
        return entry is not None and entry.status != "failed"

    async def attempts(self, up_transaction_id: str) -> int:
        """How many attempts are recorded (0 if none); for inspection."""
        async with self._session_factory() as session:
            entry = await self._entry(session, up_transaction_id)
        return entry.attempts if entry else 0

    async def record(self, outcome: Outcome) -> None:
        status, ynab_id, reason = _fields(outcome)
        up_id = outcome.up_transaction_id
        async with self._session_factory() as session:
            entry = await self._entry(session, up_id)
            if entry is None:
                session.add(
                    LedgerEntry(
                        up_transaction_id=up_id,
                        status=status,
                        ynab_transaction_id=ynab_id,
                        reason=reason,
                        attempts=1,
                    )
                )
            elif entry.status != "failed":
                logger.warning(
                    "Ledger entry already handled",
                    up_transaction_id=up_id,
                    status=entry.status,
                )
            else:
                entry.status = status
                entry.ynab_transaction_id = ynab_id
                entry.reason = reason
                entry.attempts += 1
