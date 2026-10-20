from forwarding.budget_index import BudgetIndex, IndexUnavailable


class FakeIndexHolder:
    """In-memory index holder returning a fixed index (None: never built)."""

    def __init__(
        self, index: BudgetIndex | None, rebuild_error: Exception | None = None
    ):
        self.index = index
        self.rebuild_error = rebuild_error
        self.rebuild_count = 0

    async def current_for(self, up_account_id: str) -> BudgetIndex:
        if self.index is None:
            raise IndexUnavailable("No Budget Index has been built")
        return self.index

    async def rebuild(self) -> None:
        self.rebuild_count += 1
        if self.rebuild_error:
            raise self.rebuild_error
