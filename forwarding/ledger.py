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
    reason_code: str


@dataclass(frozen=True)
class Failed:
    """Forwarding failed; Up redelivery will attempt it again."""

    up_transaction_id: str
    reason: str


@dataclass(frozen=True)
class Deleted:
    """Up deleted a forwarded transaction; its YNAB copy was deleted or flagged."""

    up_transaction_id: str
    ynab_transaction_id: str
    flagged: bool
    reason: str


Outcome = Forwarded | Skipped | Failed | Deleted


@dataclass(frozen=True)
class LedgerState:
    """What the Ledger holds for an Up transaction."""

    status: str  # forwarded, skipped, failed or deleted
    ynab_transaction_id: str | None
    reason_code: str | None = None


# Skips a backfill (and only a backfill) may retry: the account may have been
# added to YNAB since.
RETRYABLE_SKIP_CODES = frozenset({"account_not_in_ynab"})


def backfill_retryable(state: LedgerState | None) -> bool:
    """True if a backfill should (re)try this transaction."""
    if state is None or state.status == "failed":
        return True
    return state.status == "skipped" and state.reason_code in RETRYABLE_SKIP_CODES


def overwritable(status: str, reason_code: str | None) -> bool:
    """True if record() may replace a stored row with a new outcome."""
    return status == "failed" or (
        status == "skipped" and reason_code in RETRYABLE_SKIP_CODES
    )


class Ledger(Protocol):
    """Record of what happened to each Up transaction."""

    async def is_handled(self, up_transaction_id: str) -> bool:
        """True once forwarded, skipped or deleted; a failed one is not handled."""
        ...

    async def lookup(self, up_transaction_id: str) -> LedgerState | None:
        """The stored state, or None if nothing is recorded."""
        ...

    async def record(self, outcome: Outcome) -> None:
        """Store an outcome. A handled transaction is never overwritten, except
        that a forwarded one becomes deleted (a Deleted for any other row is
        not recorded) and a skipped one with a retryable reason_code
        (account_not_in_ynab) becomes forwarded or skipped. A failed outcome
        is not recorded over such a skip."""
        ...


def _fields(outcome: Outcome) -> tuple[str, str | None, str | None, str | None]:
    """Return (status, ynab_transaction_id, reason, reason_code) for an outcome.

    A Deleted keeps the stored reason_code, so it reports None here.
    """
    if isinstance(outcome, Forwarded):
        return "forwarded", outcome.ynab_transaction_id, None, None
    if isinstance(outcome, Skipped):
        return "skipped", None, outcome.reason, outcome.reason_code
    if isinstance(outcome, Deleted):
        return "deleted", outcome.ynab_transaction_id, outcome.reason, None
    return "failed", None, outcome.reason, None


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

    async def lookup(self, up_transaction_id: str) -> LedgerState | None:
        async with self._session_factory() as session:
            entry = await self._entry(session, up_transaction_id)
        if entry is None:
            return None
        return LedgerState(entry.status, entry.ynab_transaction_id, entry.reason_code)

    async def attempts(self, up_transaction_id: str) -> int:
        """How many attempts are recorded (0 if none); for inspection."""
        async with self._session_factory() as session:
            entry = await self._entry(session, up_transaction_id)
        return entry.attempts if entry else 0

    async def record(self, outcome: Outcome) -> None:
        status, ynab_id, reason, reason_code = _fields(outcome)
        up_id = outcome.up_transaction_id
        async with self._session_factory() as session:
            entry = await self._entry(session, up_id)
            if isinstance(outcome, Deleted):
                if entry is None or entry.status != "forwarded":
                    logger.warning(
                        "Ledger entry not forwarded; deletion not recorded",
                        up_transaction_id=up_id,
                    )
                else:
                    entry.status = status
                    entry.reason = reason
            elif entry is None:
                session.add(
                    LedgerEntry(
                        up_transaction_id=up_id,
                        status=status,
                        ynab_transaction_id=ynab_id,
                        reason=reason,
                        reason_code=reason_code,
                        attempts=1,
                    )
                )
            elif overwritable(entry.status, entry.reason_code):
                if entry.status == "skipped" and status == "failed":
                    logger.warning(
                        "Retry failed; skip kept for the next backfill",
                        up_transaction_id=up_id,
                    )
                else:
                    entry.status = status
                    entry.ynab_transaction_id = ynab_id
                    entry.reason = reason
                    entry.reason_code = reason_code
                    entry.attempts += 1
            else:
                logger.warning(
                    "Ledger entry already handled",
                    up_transaction_id=up_id,
                    status=entry.status,
                )
