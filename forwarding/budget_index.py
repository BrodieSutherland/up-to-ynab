import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Awaitable, Callable, Mapping

import structlog

from clients.up import UpClient
from clients.ynab import YnabClient
from models.up_models import UpAccount
from models.ynab_models import YnabAccount

logger = structlog.get_logger()

LAZY_REBUILD_INTERVAL_S = 60.0


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
    category_by_payee: Mapping[str, str] = MappingProxyType({})  # ticket 07 replaces

    def account(
        self, up_account_id: str
    ) -> YnabAccountRef | NotInYnab | UnknownUpAccount:
        found = self.accounts.get(up_account_id)
        return found if found is not None else UnknownUpAccount()

    def category_match(self, payee: str) -> str | None:
        return self.category_by_payee.get(payee)


def build_budget_index(
    up_accounts: list[UpAccount],
    ynab_accounts: list[YnabAccount],
    category_by_payee: Mapping[str, str] | None = None,
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
        MappingProxyType(accounts), MappingProxyType(dict(category_by_payee or {}))
    )


class BudgetIndexHolder:
    """Holds the current Budget Index and rebuilds it from Up and YNAB."""

    def __init__(
        self,
        up: UpClient,
        ynab: YnabClient,
        load_categories: Callable[[], Awaitable[Mapping[str, str]]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._up = up
        self._ynab = ynab
        self._load_categories = load_categories
        self._clock = clock
        self._index: BudgetIndex | None = None
        self._last_lazy: float | None = None

    async def rebuild(self) -> None:
        """Rebuild the index; on failure raise and keep the previous one."""
        up_accounts = await self._up.list_accounts()
        ynab_accounts = await self._ynab.list_accounts()
        categories = await self._load_categories() if self._load_categories else {}
        index = build_budget_index(up_accounts, ynab_accounts, categories)
        self._index = index
        logger.info(
            "Budget Index rebuilt",
            up_accounts=len(up_accounts),
            matched=sum(isinstance(a, YnabAccountRef) for a in index.accounts.values()),
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
