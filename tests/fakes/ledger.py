from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from forwarding.ledger import (
    Deleted,
    Forwarded,
    LedgerEntryView,
    LedgerState,
    Outcome,
    Skipped,
    overwritable,
)


@dataclass
class Entry:
    status: str
    ynab_transaction_id: str | None
    reason: str | None
    attempts: int
    reason_code: str | None = None
    updated_at: datetime | None = None


class InMemoryLedger:
    """In-memory Ledger. `errors[method_name]` is raised when that method runs."""

    def __init__(
        self,
        errors: dict[str, Exception] | None = None,
        now: Callable[[], datetime] = lambda: datetime(
            2026, 10, 30, 1, 2, 3, tzinfo=UTC
        ),
    ):
        self._now = now
        self.entries: dict[str, Entry] = {}
        self.errors = dict(errors or {})

    def _maybe_raise(self, method: str) -> None:
        if method in self.errors:
            raise self.errors[method]

    async def is_handled(self, up_transaction_id: str) -> bool:
        self._maybe_raise("is_handled")
        entry = self.entries.get(up_transaction_id)
        return entry is not None and entry.status != "failed"

    async def lookup(self, up_transaction_id: str) -> LedgerState | None:
        self._maybe_raise("lookup")
        entry = self.entries.get(up_transaction_id)
        if entry is None:
            return None
        return LedgerState(entry.status, entry.ynab_transaction_id, entry.reason_code)

    async def entry(self, up_transaction_id: str) -> LedgerEntryView | None:
        self._maybe_raise("entry")
        e = self.entries.get(up_transaction_id)
        if e is None:
            return None
        return LedgerEntryView(
            up_transaction_id=up_transaction_id,
            status=e.status,
            reason=e.reason,
            reason_code=e.reason_code,
            ynab_transaction_id=e.ynab_transaction_id,
            attempts=e.attempts,
            updated_at=e.updated_at or self._now(),
        )

    async def attempts(self, up_transaction_id: str) -> int:
        entry = self.entries.get(up_transaction_id)
        return entry.attempts if entry else 0

    async def record(self, outcome: Outcome) -> None:
        self._maybe_raise("record")
        up_id = outcome.up_transaction_id
        if isinstance(outcome, Forwarded):
            fields = ("forwarded", outcome.ynab_transaction_id, None, None)
        elif isinstance(outcome, Skipped):
            fields = ("skipped", None, outcome.reason, outcome.reason_code)
        elif isinstance(outcome, Deleted):
            fields = ("deleted", outcome.ynab_transaction_id, outcome.reason, None)
        else:
            fields = ("failed", None, outcome.reason, None)
        entry = self.entries.get(up_id)
        if isinstance(outcome, Deleted):
            if entry is not None and entry.status == "forwarded":
                entry.status, entry.reason = fields[0], fields[2]
                entry.updated_at = self._now()
        elif entry is None:
            self.entries[up_id] = Entry(
                fields[0],
                fields[1],
                fields[2],
                attempts=1,
                reason_code=fields[3],
                updated_at=self._now(),
            )
        elif overwritable(entry.status, entry.reason_code):
            if entry.status == "skipped" and fields[0] == "failed":
                return
            (
                entry.status,
                entry.ynab_transaction_id,
                entry.reason,
                entry.reason_code,
            ) = fields
            entry.attempts += 1
            entry.updated_at = self._now()
