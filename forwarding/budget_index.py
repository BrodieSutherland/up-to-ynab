import asyncio
import time
from collections.abc import Awaitable, Iterable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping

import structlog

from clients.up import UpClient
from clients.ynab import YnabClient
from models.up_models import UpAccount
from models.ynab_models import YnabAccount, YnabTransaction

logger = structlog.get_logger()

LAZY_REBUILD_INTERVAL_S = 60.0
TIMED_REBUILD_INTERVAL_S = 6 * 60 * 60
ALL_TIME = "1970-01-01"


@dataclass(frozen=True)
class YnabAccountRef:
    """The YNAB account an Up account maps to."""

    id: str
    transfer_payee_id: str


@dataclass(frozen=True)
class NotInYnab:
    """The Up account has no (single, open) YNAB account of the same name."""


@dataclass(frozen=True)
class UnknownUpAccount:
    """The index was built without ever seeing this Up account."""


class IndexUnavailable(Exception):
    """No Budget Index has ever been built."""


@dataclass(frozen=True)
class BudgetIndex:
    """Routing data: YNAB account per Up account, and category per payee."""

    accounts: Mapping[str, YnabAccountRef | NotInYnab]
    category_by_payee: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def account(
        self, up_account_id: str
    ) -> YnabAccountRef | NotInYnab | UnknownUpAccount:
        found = self.accounts.get(up_account_id)
        return found if found is not None else UnknownUpAccount()

    def matched_count(self) -> int:
        return sum(isinstance(a, YnabAccountRef) for a in self.accounts.values())

    def category_match(self, payee: str) -> str | None:
        return self.category_by_payee.get(payee)


def build_budget_index(
    up_accounts: list[UpAccount],
    ynab_accounts: list[YnabAccount],
    ynab_transactions: Iterable[YnabTransaction] = (),
) -> BudgetIndex:
    """Match each Up account to the open YNAB account with exactly its name."""
    by_name: dict[str, list[YnabAccount]] = {}
    for account in ynab_accounts:
        if not account.closed and not account.deleted:
            by_name.setdefault(account.name, []).append(account)

    accounts: dict[str, YnabAccountRef | NotInYnab] = {}
    for up_account in up_accounts:
        candidates = by_name.get(up_account.display_name, [])
        if len(candidates) == 1:
            accounts[up_account.id] = YnabAccountRef(
                candidates[0].id, candidates[0].transfer_payee_id
            )
            continue
        if candidates:
            logger.warning(
                "Duplicate YNAB account name",
                up_account_id=up_account.id,
                name=up_account.display_name,
            )
        else:
            logger.warning(
                "Up account not in YNAB",
                up_account_id=up_account.id,
                name=up_account.display_name,
            )
        accounts[up_account.id] = NotInYnab()
    return BudgetIndex(
        MappingProxyType(accounts),
        MappingProxyType(_category_by_payee(ynab_transactions)),
    )


def _category_by_payee(transactions: Iterable[YnabTransaction]) -> dict[str, str]:
    """Names whose counted transactions all share exactly one category.

    Each transaction is keyed by its YNAB payee name and, when recorded, its
    import payee name (the name before YNAB rename rules, i.e. the Up
    description this app sent). A key seen with two categories, from either
    source, has no match. Deleted transactions, transfers, splits and
    uncategorised or payee-less transactions are not counted. Names match
    exactly.
    """
    seen: dict[str, set[str]] = {}
    for t in transactions:
        if (
            t.deleted
            or t.transfer_account_id
            or t.subtransactions
            or t.category_id is None
            or t.payee_name is None
        ):
            continue
        keys = [t.payee_name]
        if t.import_payee_name:
            keys.append(t.import_payee_name)
        for key in keys:
            seen.setdefault(key, set()).add(t.category_id)
    return {payee: next(iter(c)) for payee, c in seen.items() if len(c) == 1}


class BudgetIndexHolder:
    """Holds the current Budget Index and rebuilds it from Up and YNAB."""

    def __init__(
        self,
        up: UpClient,
        ynab: YnabClient,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._up = up
        self._ynab = ynab
        self._clock = clock
        self._index: BudgetIndex | None = None
        self._last_lazy: float | None = None

    async def rebuild(self) -> None:
        """Rebuild the index; on failure raise and keep the previous one."""
        up_accounts = await self._up.list_accounts()
        ynab_accounts = await self._ynab.list_accounts()
        history = await self._ynab.list_transactions(since_date=ALL_TIME)
        index = build_budget_index(up_accounts, ynab_accounts, history)
        self._index = index
        logger.info(
            "Budget Index rebuilt",
            up_accounts=len(up_accounts),
            matched=index.matched_count(),
            categorised_payees=len(index.category_by_payee),
        )
        if index.matched_count() == 0:
            logger.warning(
                "No Up account matched a YNAB account",
                up_accounts=len(up_accounts),
                hint="YNAB account names must equal Up account names exactly",
            )

    async def current_for(self, up_account_id: str) -> BudgetIndex:
        """The index, rebuilt lazily (at most once a minute) for an unknown account."""
        if self._index is None or isinstance(
            self._index.account(up_account_id), UnknownUpAccount
        ):
            await self._lazy_rebuild()
        if self._index is None:
            raise IndexUnavailable("No Budget Index has been built")
        return self._index

    async def _lazy_rebuild(self) -> None:
        now = self._clock()
        if self._last_lazy is not None and now - self._last_lazy < (
            LAZY_REBUILD_INTERVAL_S
        ):
            return
        self._last_lazy = now
        try:
            await self.rebuild()
        except Exception as e:
            logger.warning("Lazy Budget Index rebuild failed", error=str(e))


async def rebuild_periodically(
    rebuild: Callable[[], Awaitable[None]],
    interval_s: float = TIMED_REBUILD_INTERVAL_S,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Sleep, then rebuild, forever; a failed rebuild is logged, old index kept."""
    while True:
        await sleep(interval_s)
        try:
            await rebuild()
        except Exception as e:  # CancelledError is BaseException, still propagates
            logger.error("Timed Budget Index rebuild failed", error=str(e))
