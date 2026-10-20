from clients.errors import UpstreamError
from models.up_models import UpAccount, UpTransaction, UpWebhook


class FakeUpClient:
    """In-memory UpClient. `errors[method_name]` is raised when that method runs."""

    def __init__(
        self,
        transactions: dict[str, UpTransaction] | None = None,
        accounts=(),
        webhooks=(),
        errors: dict[str, Exception] | None = None,
    ):
        self.transactions = dict(transactions or {})
        self.accounts: list[UpAccount] = list(accounts)
        self.webhooks: list[UpWebhook] = list(webhooks)
        self.errors = dict(errors or {})
        self.created_webhooks: list[str] = []

    def _maybe_raise(self, method: str) -> None:
        if method in self.errors:
            raise self.errors[method]

    async def get_transaction(self, transaction_id: str) -> UpTransaction:
        self._maybe_raise("get_transaction")
        if transaction_id not in self.transactions:
            raise UpstreamError("not found", 404)
        return self.transactions[transaction_id]

    async def list_accounts(self) -> list[UpAccount]:
        self._maybe_raise("list_accounts")
        return list(self.accounts)

    async def list_webhooks(self) -> list[UpWebhook]:
        self._maybe_raise("list_webhooks")
        return list(self.webhooks)

    async def create_webhook(self, url: str) -> str:
        self._maybe_raise("create_webhook")
        self.created_webhooks.append(url)
        return f"webhook-{len(self.created_webhooks)}"
