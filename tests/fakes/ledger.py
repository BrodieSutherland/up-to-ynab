from dataclasses import dataclass

from forwarding.ledger import Deleted, Forwarded, LedgerState, Outcome, Skipped


@dataclass
class Entry:
    status: str
    ynab_transaction_id: str | None
    reason: str | None
    attempts: int


class InMemoryLedger:
    """In-memory Ledger. `errors[method_name]` is raised when that method runs."""

    def __init__(self, errors: dict[str, Exception] | None = None):
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
        return LedgerState(entry.status, entry.ynab_transaction_id)

    async def attempts(self, up_transaction_id: str) -> int:
        entry = self.entries.get(up_transaction_id)
        return entry.attempts if entry else 0

    async def record(self, outcome: Outcome) -> None:
        self._maybe_raise("record")
        up_id = outcome.up_transaction_id
        if isinstance(outcome, Forwarded):
            fields = ("forwarded", outcome.ynab_transaction_id, None)
        elif isinstance(outcome, Skipped):
            fields = ("skipped", None, outcome.reason)
        elif isinstance(outcome, Deleted):
            fields = ("deleted", outcome.ynab_transaction_id, outcome.reason)
        else:
            fields = ("failed", None, outcome.reason)
        entry = self.entries.get(up_id)
        if isinstance(outcome, Deleted):
            if entry is not None and entry.status == "forwarded":
                entry.status, entry.reason = fields[0], fields[2]
        elif entry is None:
            self.entries[up_id] = Entry(*fields, attempts=1)
        elif entry.status == "failed":
            entry.status, entry.ynab_transaction_id, entry.reason = fields
            entry.attempts += 1
