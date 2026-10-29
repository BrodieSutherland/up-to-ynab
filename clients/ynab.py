from dataclasses import dataclass
from typing import Any, Protocol

import httpx2 as httpx
from pydantic import ValidationError

from clients.errors import UpstreamError
from models.ynab_models import YnabAccount, YnabTransaction, YnabTransactionDetail


@dataclass(frozen=True)
class Created:
    """YNAB accepted the transaction."""

    ynab_id: str


@dataclass(frozen=True)
class AlreadyImported:
    """YNAB answered 409: a transaction with this import_id already exists."""


class YnabClient(Protocol):
    """What the app needs from YNAB. Failures raise UpstreamError."""

    async def create_transaction(
        self, transaction: YnabTransactionDetail
    ) -> Created | AlreadyImported: ...

    async def list_accounts(self) -> list[YnabAccount]: ...

    async def list_transactions(self, since_date: str) -> list[YnabTransaction]: ...

    async def get_transaction(self, ynab_id: str) -> YnabTransaction: ...

    async def update_transaction(
        self, ynab_id: str, cleared: str, amount: int | None
    ) -> None: ...

    async def delete_transaction(self, ynab_id: str) -> None: ...

    async def flag_transaction(self, ynab_id: str, flag_color: str = "red") -> None: ...


class HttpYnabClient:
    """YnabClient over an injected httpx2.AsyncClient (the caller closes it)."""

    def __init__(
        self, http: httpx.AsyncClient, token: str, base_url: str, plan_id: str
    ):
        self._http = http
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._plan = f"/plans/{plan_id}"

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            return await self._http.request(
                method, self._base_url + path, headers=headers, **kwargs
            )
        except httpx.HTTPError as exc:
            raise UpstreamError(
                f"{method} {path} failed: {type(exc).__name__}"
            ) from exc

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Send a request and return the decoded JSON body, or raise."""
        response = await self._send(method, path, **kwargs)
        return self._decode(method, path, response)

    @staticmethod
    def _decode(method: str, path: str, response: httpx.Response) -> Any:
        if response.is_error:
            raise UpstreamError(
                f"{method} {path} -> {response.status_code}",
                status_code=response.status_code,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamError(f"{method} {path} returned invalid JSON") from exc

    async def create_transaction(
        self, transaction: YnabTransactionDetail
    ) -> Created | AlreadyImported:
        path = f"{self._plan}/transactions"
        response = await self._send(
            "POST", path, json={"transaction": transaction.model_dump()}
        )
        if response.status_code == 409:
            return AlreadyImported()
        body = self._decode("POST", path, response)
        try:
            return Created(ynab_id=str(body["data"]["transaction"]["id"]))
        except (KeyError, TypeError) as exc:
            raise UpstreamError(f"POST {path} returned unexpected shape") from exc

    async def list_accounts(self) -> list[YnabAccount]:
        path = f"{self._plan}/accounts"
        body = await self._request("GET", path)
        try:
            return [YnabAccount(**item) for item in body["data"]["accounts"]]
        except (ValidationError, KeyError, TypeError) as exc:
            raise UpstreamError(f"GET {path} returned unexpected shape") from exc

    async def list_transactions(self, since_date: str) -> list[YnabTransaction]:
        path = f"{self._plan}/transactions"
        body = await self._request("GET", path, params={"since_date": since_date})
        try:
            return [YnabTransaction(**item) for item in body["data"]["transactions"]]
        except (ValidationError, KeyError, TypeError) as exc:
            raise UpstreamError(f"GET {path} returned unexpected shape") from exc

    async def get_transaction(self, ynab_id: str) -> YnabTransaction:
        path = f"{self._plan}/transactions/{ynab_id}"
        body = await self._request("GET", path)
        try:
            return YnabTransaction(**body["data"]["transaction"])
        except (ValidationError, KeyError, TypeError) as exc:
            raise UpstreamError(f"GET {path} returned unexpected shape") from exc

    async def update_transaction(
        self, ynab_id: str, cleared: str, amount: int | None
    ) -> None:
        """Set cleared (and amount unless None); the date is never sent."""
        change: dict[str, Any] = {"id": ynab_id, "cleared": cleared}
        if amount is not None:
            change["amount"] = amount
        await self._patch_transactions(change)

    async def flag_transaction(self, ynab_id: str, flag_color: str = "red") -> None:
        """Set the flag colour, leaving everything else as it is."""
        await self._patch_transactions({"id": ynab_id, "flag_color": flag_color})

    async def delete_transaction(self, ynab_id: str) -> None:
        await self._request("DELETE", f"{self._plan}/transactions/{ynab_id}")

    async def _patch_transactions(self, change: dict[str, Any]) -> None:
        await self._request(
            "PATCH", f"{self._plan}/transactions", json={"transactions": [change]}
        )
