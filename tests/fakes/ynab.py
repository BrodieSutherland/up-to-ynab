from clients.errors import UpstreamError
from clients.ynab import AlreadyImported, Created
from models.ynab_models import YnabAccount, YnabTransaction, YnabTransactionDetail


def ynab_account(
    id: str,
    name: str,
    closed: bool = False,
    deleted: bool = False,
    transfer_payee_id: str | None = None,
) -> YnabAccount:
    return YnabAccount(
        id=id,
        name=name,
        type="checking",
        on_budget=True,
        closed=closed,
        balance=0,
        cleared_balance=0,
        uncleared_balance=0,
        transfer_payee_id=transfer_payee_id or f"tp-{id}",
        direct_import_linked=False,
        direct_import_in_error=False,
        deleted=deleted,
    )


def ynab_transaction(
    id: str,
    payee_name: str | None,
    category_id: str | None,
    *,
    transfer_account_id: str | None = None,
    deleted: bool = False,
    subtransactions=(),
    amount: int = -1000,
    date: str = "2024-01-01",
    cleared: str | None = None,
    import_id: str | None = None,
) -> YnabTransaction:
    return YnabTransaction(
        id=id,
        date=date,
        amount=amount,
        cleared=cleared,
        import_id=import_id,
        payee_name=payee_name,
        category_id=category_id,
        transfer_account_id=transfer_account_id,
        deleted=deleted,
        subtransactions=list(subtransactions),
    )


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
        self.updates: list[tuple[str, str, int | None]] = []
        self.list_accounts_calls = 0

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
        self.list_accounts_calls += 1
        self._maybe_raise("list_accounts")
        return list(self.accounts)

    async def list_transactions(self, since_date: str) -> list[YnabTransaction]:
        self._maybe_raise("list_transactions")
        self.since_dates.append(since_date)
        return list(self.transactions)

    async def get_transaction(self, ynab_id: str) -> YnabTransaction:
        self._maybe_raise("get_transaction")
        for transaction in self.transactions:
            if transaction.id == ynab_id:
                return transaction
        raise UpstreamError("not found", 404)

    async def update_transaction(
        self, ynab_id: str, cleared: str, amount: int | None
    ) -> None:
        self._maybe_raise("update_transaction")
        self.updates.append((ynab_id, cleared, amount))
