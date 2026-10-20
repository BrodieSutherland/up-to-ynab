from forwarding.budget_index import LegacyIndex


class FakeIndexHolder:
    """In-memory index holder returning a fixed index."""

    def __init__(self, index: LegacyIndex, rebuild_error: Exception | None = None):
        self.index = index
        self.rebuild_error = rebuild_error
        self.rebuild_count = 0

    async def current_for(self, up_account_id: str) -> LegacyIndex:
        return self.index

    async def rebuild(self) -> None:
        self.rebuild_count += 1
        if self.rebuild_error:
            raise self.rebuild_error
