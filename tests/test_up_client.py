import json
from pathlib import Path

import httpx2 as httpx
import pytest
import structlog

from clients.errors import UpstreamError
from clients.up import HttpUpClient

FIXTURES = Path(__file__).parent / "fixtures" / "up"
BASE = "https://api.up.test/api/v1"
TOKEN = "test_up_token"


def make_client(handler):
    """Real HttpUpClient over a mock transport; requests are recorded."""
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(record))
    return HttpUpClient(http, TOKEN, BASE + "/"), requests


def respond(status=200, body=None):
    return lambda request: httpx.Response(status, json=body)


def fixture_json(*parts):
    return json.loads(FIXTURES.joinpath(*parts).read_text())


class TestGetTransaction:
    async def test_request_shape_and_parsing(self):
        body = fixture_json("transactions", "purchase_plain_1.json")
        client, requests = make_client(respond(200, body))

        transaction = await client.get_transaction("tx-1")

        [request] = requests
        assert request.method == "GET"
        assert str(request.url) == f"{BASE}/transactions/tx-1"
        assert request.headers["Authorization"] == "Bearer test_up_token"
        assert transaction.id == "transactions-1"
        assert transaction.payee == "Payee 1"

    async def test_404_raises_with_status(self):
        client, _ = make_client(respond(404, {"errors": []}))

        with pytest.raises(UpstreamError) as exc_info:
            await client.get_transaction("tx-1")

        assert exc_info.value.status_code == 404
        assert str(exc_info.value) == "GET /transactions/tx-1 -> 404"

    async def test_500_raises(self):
        client, _ = make_client(respond(500))

        with pytest.raises(UpstreamError) as exc_info:
            await client.get_transaction("tx-1")

        assert exc_info.value.status_code == 500

    async def test_timeout_raises_without_status(self):
        def handler(request):
            raise httpx.ReadTimeout("slow", request=request)

        client, _ = make_client(handler)

        with pytest.raises(UpstreamError) as exc_info:
            await client.get_transaction("tx-1")

        assert exc_info.value.status_code is None
        assert str(exc_info.value) == "GET /transactions/tx-1 failed: ReadTimeout"

    async def test_malformed_json_raises(self):
        client, _ = make_client(lambda r: httpx.Response(200, content=b"not json"))

        with pytest.raises(UpstreamError):
            await client.get_transaction("tx-1")

    async def test_unexpected_shape_raises(self):
        client, _ = make_client(respond(200, {"data": {"id": "x"}}))

        with pytest.raises(UpstreamError):
            await client.get_transaction("tx-1")


class TestListAccounts:
    async def test_parses_fixture(self):
        client, requests = make_client(respond(200, fixture_json("accounts.json")))

        accounts = await client.list_accounts()

        assert requests[0].url.path == "/api/v1/accounts"
        assert len(accounts) == 4
        assert accounts[0].id == "accounts-1"
        assert accounts[0].display_name == "Spending"

    async def test_follows_next_links(self):
        full = fixture_json("accounts.json")
        page2_url = f"{BASE}/accounts?page[after]=abc"
        pages = {
            f"{BASE}/accounts": {
                "data": full["data"][:2],
                "links": {"next": page2_url},
            },
            page2_url: {"data": full["data"][2:], "links": {"next": None}},
        }

        def handler(request):
            return httpx.Response(200, json=pages[str(request.url)])

        client, requests = make_client(handler)

        accounts = await client.list_accounts()

        assert [a.id for a in accounts] == [f"accounts-{n}" for n in (1, 2, 3, 4)]
        assert len(requests) == 2
        assert requests[1].headers["Authorization"] == "Bearer test_up_token"

    async def test_bad_account_raises(self):
        client, _ = make_client(respond(200, {"data": [{"id": "a"}]}))

        with pytest.raises(UpstreamError):
            await client.list_accounts()


class TestWebhooks:
    async def test_list_webhooks_parses(self):
        body = {
            "data": [
                {
                    "type": "webhooks",
                    "id": "w1",
                    "attributes": {"url": "https://a.test/hook", "description": "d"},
                },
                {
                    "type": "webhooks",
                    "id": "w2",
                    "attributes": {"url": "https://b.test/hook"},
                },
            ]
        }
        client, requests = make_client(respond(200, body))

        webhooks = await client.list_webhooks()

        assert requests[0].url.path == "/api/v1/webhooks"
        assert [(w.id, w.url, w.description) for w in webhooks] == [
            ("w1", "https://a.test/hook", "d"),
            ("w2", "https://b.test/hook", None),
        ]

    async def test_create_webhook_posts_and_returns_id(self):
        client, requests = make_client(
            respond(201, {"data": {"type": "webhooks", "id": "w9"}})
        )

        webhook_id = await client.create_webhook("https://a.test/hook")

        [request] = requests
        assert request.method == "POST"
        assert request.url.path == "/api/v1/webhooks"
        assert json.loads(request.content) == {
            "data": {
                "attributes": {
                    "url": "https://a.test/hook",
                    "description": "UP to YNAB transaction sync webhook",
                }
            }
        }
        assert webhook_id == "w9"

    async def test_create_webhook_failure_raises(self):
        client, _ = make_client(respond(401))

        with pytest.raises(UpstreamError) as exc_info:
            await client.create_webhook("https://a.test/hook")

        assert exc_info.value.status_code == 401


async def test_token_never_logged_or_in_errors():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    client, _ = make_client(handler)

    with structlog.testing.capture_logs() as logs:
        with pytest.raises(UpstreamError) as exc_info:
            await client.get_transaction("tx-1")

    assert TOKEN not in str(exc_info.value)
    assert TOKEN not in repr(logs)
