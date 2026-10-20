import json

import httpx2 as httpx
import pytest
import structlog

from clients.errors import UpstreamError
from clients.ynab import AlreadyImported, Created, HttpYnabClient
from models.ynab_models import YnabTransactionDetail

BASE = "https://api.ynab.test/v1"
TOKEN = "test_ynab_token"


def make_client(handler):
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(record))
    return HttpYnabClient(http, TOKEN, BASE + "/", "test_budget_id"), requests


def respond(status=200, body=None):
    return lambda request: httpx.Response(status, json=body)


@pytest.fixture
def detail():
    return YnabTransactionDetail(
        account_id="acct-1",
        payee_name="Shop",
        memo="memo",
        amount=-12500,
        date="2024-01-01",
        import_id="up_abc",
    )


class TestCreateTransaction:
    async def test_posts_to_plans_and_returns_created(self, detail):
        client, requests = make_client(
            respond(201, {"data": {"transaction": {"id": "ynab-tx-1"}}})
        )

        outcome = await client.create_transaction(detail)

        assert outcome == Created("ynab-tx-1")
        [request] = requests
        assert request.method == "POST"
        assert request.url.path == "/v1/plans/test_budget_id/transactions"
        assert "/budgets/" not in request.url.path
        assert request.headers["Authorization"] == "Bearer test_ynab_token"
        sent = json.loads(request.content)["transaction"]
        assert sent["import_id"] == "up_abc"
        assert sent["amount"] == -12500
        assert sent["account_id"] == "acct-1"

    async def test_409_is_already_imported(self, detail):
        body = {"error": {"id": "409", "name": "conflict", "detail": "dup"}}
        client, _ = make_client(respond(409, body))

        assert await client.create_transaction(detail) == AlreadyImported()

    @pytest.mark.parametrize("status", [429, 500])
    async def test_error_status_raises(self, detail, status):
        client, _ = make_client(respond(status, {"error": {}}))

        with pytest.raises(UpstreamError) as exc_info:
            await client.create_transaction(detail)

        assert exc_info.value.status_code == status

    async def test_timeout_raises(self, detail):
        def handler(request):
            raise httpx.ReadTimeout("slow", request=request)

        client, _ = make_client(handler)

        with pytest.raises(UpstreamError) as exc_info:
            await client.create_transaction(detail)

        assert exc_info.value.status_code is None

    async def test_unexpected_shape_raises(self, detail):
        client, _ = make_client(respond(201, {"data": {}}))

        with pytest.raises(UpstreamError):
            await client.create_transaction(detail)

    async def test_malformed_json_raises(self, detail):
        client, _ = make_client(lambda r: httpx.Response(201, content=b"nope"))

        with pytest.raises(UpstreamError):
            await client.create_transaction(detail)


class TestListings:
    async def test_list_accounts(self):
        account = {
            "id": "a1",
            "name": "Everyday",
            "type": "checking",
            "on_budget": True,
            "closed": False,
            "note": None,
            "balance": 1000,
            "cleared_balance": 1000,
            "uncleared_balance": 0,
            "transfer_payee_id": "payee-a1",
            "direct_import_linked": False,
            "direct_import_in_error": False,
            "deleted": False,
        }
        client, requests = make_client(respond(200, {"data": {"accounts": [account]}}))

        accounts = await client.list_accounts()

        assert requests[0].url.path == "/v1/plans/test_budget_id/accounts"
        assert accounts[0].id == "a1"
        assert accounts[0].transfer_payee_id == "payee-a1"

    async def test_list_transactions(self):
        item = {
            "id": "t1",
            "date": "2024-01-02",
            "amount": -5000,
            "payee_name": "Shop",
            "category_id": "cat-1",
            "transfer_account_id": None,
            "deleted": False,
            "subtransactions": [{"id": "s1", "amount": -5000}],
        }
        client, requests = make_client(respond(200, {"data": {"transactions": [item]}}))

        transactions = await client.list_transactions("1970-01-01")

        [request] = requests
        assert request.url.path == "/v1/plans/test_budget_id/transactions"
        assert request.url.params["since_date"] == "1970-01-01"
        assert transactions[0].payee_name == "Shop"
        assert transactions[0].category_id == "cat-1"
        assert transactions[0].subtransactions == [{"id": "s1", "amount": -5000}]

    async def test_bad_listing_raises(self):
        client, _ = make_client(respond(200, {"data": {"accounts": [{"id": "a"}]}}))

        with pytest.raises(UpstreamError):
            await client.list_accounts()

    async def test_listing_error_status_raises(self):
        client, _ = make_client(respond(401))

        with pytest.raises(UpstreamError):
            await client.list_transactions("1970-01-01")


async def test_token_never_logged_or_in_errors(detail):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    client, _ = make_client(handler)

    with structlog.testing.capture_logs() as logs:
        with pytest.raises(UpstreamError) as exc_info:
            await client.create_transaction(detail)

    assert TOKEN not in str(exc_info.value)
    assert TOKEN not in repr(logs)
