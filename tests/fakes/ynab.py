from clients.ynab import AlreadyImported, Created
from models.ynab_models import YnabAccount, YnabTransaction, YnabTransactionDetail


class FakeYnabClient:
    """In-memory YnabClient. `errors[method_name]` is raised when that method runs."""

    def __init__(
        self,
        accounts=(),
        transactions=(),
        errors: dict[str, Exception] | None = None,
        already_imported: bool = False,
    ):
        self.accounts: list[YnabAccount] = list(accounts)
        self.transactions: list[YnabTransaction] = list(transactions)
        self.errors = dict(errors or {})
        self.already_imported = already_imported
        self.created: list[YnabTransactionDetail] = []
        self.since_dates: list[str] = []

    def _maybe_raise(self, method: str) -> None:
        if method in self.errors:
            raise self.errors[method]

    async def create_transaction(
        self, transaction: YnabTransactionDetail
    ) -> Created | AlreadyImported:
        self._maybe_raise("create_transaction")
        if self.already_imported:
            return AlreadyImported()
        self.created.append(transaction)
        return Created(f"ynab-{len(self.created)}")

    async def list_accounts(self) -> list[YnabAccount]:
        self._maybe_raise("list_accounts")
        return list(self.accounts)

    async def list_transactions(self, since_date: str) -> list[YnabTransaction]:
        self._maybe_raise("list_transactions")
        self.since_dates.append(since_date)
        return list(self.transactions)
