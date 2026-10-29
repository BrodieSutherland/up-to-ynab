class InMemoryWebhookSecretStore:
    """In-memory WebhookSecretStore. `errors[method_name]` is raised on that call."""

    def __init__(
        self,
        secrets: dict[str, str] | None = None,
        errors: dict[str, Exception] | None = None,
    ):
        self.secrets = dict(secrets or {})
        self.errors = dict(errors or {})

    def _maybe_raise(self, method: str) -> None:
        if method in self.errors:
            raise self.errors[method]

    async def all(self) -> dict[str, str]:
        self._maybe_raise("all")
        return dict(self.secrets)

    async def save(self, webhook_id: str, secret_key: str) -> None:
        self._maybe_raise("save")
        self.secrets[webhook_id] = secret_key

    async def delete(self, webhook_id: str) -> None:
        self._maybe_raise("delete")
        self.secrets.pop(webhook_id, None)
