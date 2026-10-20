from typing import Any, Protocol

import httpx2 as httpx
from pydantic import ValidationError

from clients.errors import UpstreamError
from models.up_models import (
    UpAccount,
    UpTransaction,
    UpTransactionResponse,
    UpWebhook,
)

WEBHOOK_DESCRIPTION = "UP to YNAB transaction sync webhook"


class UpClient(Protocol):
    """What the app needs from Up. Every method raises UpstreamError on failure."""

    async def get_transaction(self, transaction_id: str) -> UpTransaction: ...

    async def list_accounts(self) -> list[UpAccount]: ...

    async def list_webhooks(self) -> list[UpWebhook]: ...

    async def create_webhook(self, url: str) -> str:
        """Create a webhook and return its id."""
        ...


class HttpUpClient:
    """UpClient over an injected httpx2.AsyncClient (the caller closes it)."""

    def __init__(self, http: httpx.AsyncClient, token: str, base_url: str):
        self._http = http
        self._token = token
        self._base_url = base_url.rstrip("/")

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Send a request and return the decoded JSON body, or raise."""
        url = path if path.startswith("http") else self._base_url + path
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            response = await self._http.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise UpstreamError(
                f"{method} {path} failed: {type(exc).__name__}"
            ) from exc
        if response.is_error:
            raise UpstreamError(
                f"{method} {path} -> {response.status_code}",
                status_code=response.status_code,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamError(f"{method} {path} returned invalid JSON") from exc

    async def _list(self, path: str) -> list[dict[str, Any]]:
        """Collect `data` across every page, following links.next."""
        items: list[dict[str, Any]] = []
        next_path: str | None = path
        while next_path:
            body = await self._request("GET", next_path)
            try:
                items.extend(body["data"])
                next_path = (body.get("links") or {}).get("next")
            except (KeyError, TypeError, AttributeError) as exc:
                raise UpstreamError(f"GET {path} returned unexpected shape") from exc
        return items

    async def get_transaction(self, transaction_id: str) -> UpTransaction:
        path = f"/transactions/{transaction_id}"
        body = await self._request("GET", path)
        try:
            return UpTransactionResponse(**body).data
        except (ValidationError, TypeError) as exc:
            raise UpstreamError(f"GET {path} returned unexpected shape") from exc

    async def list_accounts(self) -> list[UpAccount]:
        items = await self._list("/accounts")
        try:
            return [
                UpAccount.model_validate({"id": item["id"], **item["attributes"]})
                for item in items
            ]
        except (ValidationError, KeyError, TypeError) as exc:
            raise UpstreamError("GET /accounts returned unexpected shape") from exc

    async def list_webhooks(self) -> list[UpWebhook]:
        items = await self._list("/webhooks")
        try:
            return [
                UpWebhook(
                    id=item["id"],
                    url=item["attributes"]["url"],
                    description=item["attributes"].get("description"),
                )
                for item in items
            ]
        except (ValidationError, KeyError, TypeError) as exc:
            raise UpstreamError("GET /webhooks returned unexpected shape") from exc

    async def create_webhook(self, url: str) -> str:
        payload = {
            "data": {"attributes": {"url": url, "description": WEBHOOK_DESCRIPTION}}
        }
        body = await self._request("POST", "/webhooks", json=payload)
        try:
            return str(body["data"]["id"])
        except (KeyError, TypeError) as exc:
            raise UpstreamError("POST /webhooks returned unexpected shape") from exc
