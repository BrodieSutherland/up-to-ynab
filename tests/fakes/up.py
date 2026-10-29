import json
from pathlib import Path

from clients.errors import UpstreamError
from clients.up import WEBHOOK_DESCRIPTION, CreatedWebhook
from models.up_models import UpAccount, UpTransaction, UpWebhook


def up_accounts_fixture() -> list[UpAccount]:
    """The recorded Up /accounts response, parsed as HttpUpClient does."""
    path = Path(__file__).parent.parent / "fixtures" / "up" / "accounts.json"
    return [
        UpAccount.model_validate({"id": item["id"], **item["attributes"]})
        for item in json.loads(path.read_text())["data"]
    ]


def up_account(id: str, name: str) -> UpAccount:
    """A fixture account with its id and display name replaced."""
    base = up_accounts_fixture()[0]
    return base.model_copy(update={"id": id, "display_name": name})


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
        self.deleted_webhooks: list[str] = []
        self.list_accounts_calls = 0
        self.list_webhooks_calls = 0

    def _maybe_raise(self, method: str) -> None:
        if method in self.errors:
            raise self.errors[method]

    async def get_transaction(self, transaction_id: str) -> UpTransaction:
        self._maybe_raise("get_transaction")
        if transaction_id not in self.transactions:
            raise UpstreamError("not found", 404)
        return self.transactions[transaction_id]

    async def list_accounts(self) -> list[UpAccount]:
        self.list_accounts_calls += 1
        self._maybe_raise("list_accounts")
        return list(self.accounts)

    async def list_webhooks(self) -> list[UpWebhook]:
        self.list_webhooks_calls += 1
        self._maybe_raise("list_webhooks")
        return list(self.webhooks)

    async def create_webhook(self, url: str) -> CreatedWebhook:
        self._maybe_raise("create_webhook")
        self.created_webhooks.append(url)
        webhook_id = f"webhook-{len(self.created_webhooks)}"
        self.webhooks.append(
            UpWebhook(id=webhook_id, url=url, description=WEBHOOK_DESCRIPTION)
        )
        return CreatedWebhook(webhook_id, f"{webhook_id}-secret")

    async def delete_webhook(self, webhook_id: str) -> None:
        self._maybe_raise("delete_webhook")
        self.deleted_webhooks.append(webhook_id)
        self.webhooks = [w for w in self.webhooks if w.id != webhook_id]
