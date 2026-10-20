from dataclasses import dataclass
from typing import Mapping

from services.category_service import CategoryService
from utils.filters import TransactionFilter


@dataclass(frozen=True)
class LegacyIndex:
    """Routing data for forwarding: target account, categories, transfer rule."""

    account_id: str
    category_by_payee: Mapping[str, str]
    transfer_filter: TransactionFilter


class LegacyIndexHolder:
    """Stand-in budget index holder over today's routing rules (ticket 06 replaces)."""

    def __init__(
        self,
        category: CategoryService,
        transfer_filter: TransactionFilter,
        account_id: str,
    ):
        self._category = category
        self._transfer_filter = transfer_filter
        self._account_id = account_id

    async def current_for(self, up_account_id: str) -> LegacyIndex:
        mappings = await self._category.get_payee_category_mappings()
        return LegacyIndex(self._account_id, mappings, self._transfer_filter)

    async def rebuild(self) -> None:
        await self._category.sync_categories_from_ynab()
