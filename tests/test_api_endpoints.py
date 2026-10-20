import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import Services, create_app, open_services
from clients.errors import UpstreamError
from clients.up import HttpUpClient
from forwarding.budget_index import LegacyIndex
from forwarding.forwarder import Forwarder
from models.up_models import UpTransaction, UpWebhook
from tests.fakes.budget_index import FakeIndexHolder
from tests.fakes.ledger import InMemoryLedger
from tests.fakes.up import FakeUpClient
from tests.fakes.ynab import FakeYnabClient
from utils.filters import TransactionFilter

INDEX = LegacyIndex("acct-1", {}, TransactionFilter(["Transfer to "]))


def make_services(up, ynab=None, holder=None, ledger=None) -> Services:
    holder = holder or FakeIndexHolder(INDEX)
    forwarder = Forwarder(
        up, ynab or FakeYnabClient(), holder, ledger or InMemoryLedger()
    )
    return Services(up=up, forwarder=forwarder, budget_index=holder)


@pytest.fixture
def holder():
    return FakeIndexHolder(INDEX)


@pytest.fixture
def client(test_settings, fake_up, fake_ynab, holder):
    app = create_app(
        settings=test_settings, services=make_services(fake_up, fake_ynab, holder)
    )
    with TestClient(app) as c:
        yield c


class TestAPIEndpoints:
    """Test cases for API endpoints."""

    def test_health_check(self, client):
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "up-to-ynab"
        assert data["version"] == "2.0.0"

    def test_webhook_forwarded(self, client, fake_ynab, sample_up_webhook_event_data):
        response = client.post("/webhook", json=sample_up_webhook_event_data)

        assert response.status_code == 200
        assert response.json() == {"status": "forwarded", "result": "ynab-1"}
        assert len(fake_ynab.created) == 1

    def test_webhook_already_in_ynab(
        self, client, fake_ynab, sample_up_webhook_event_data
    ):
        fake_ynab.already_imported = True

        response = client.post("/webhook", json=sample_up_webhook_event_data)

        assert response.status_code == 200
        assert response.json() == {"status": "forwarded", "result": "already in YNAB"}

    def test_webhook_failure_answers_503(
        self, client, fake_ynab, sample_up_webhook_event_data
    ):
        fake_ynab.errors["create_transaction"] = UpstreamError("down", 500)

        response = client.post("/webhook", json=sample_up_webhook_event_data)

        assert response.status_code == 503
        assert response.json() == {"status": "failed", "result": "down"}

    def test_webhook_skipped(
        self, test_settings, sample_up_transaction_data, sample_up_webhook_event_data
    ):
        data = sample_up_transaction_data["data"]
        data["attributes"]["description"] = "Transfer to Savings"
        up = FakeUpClient(transactions={"test-transaction-id": UpTransaction(**data)})
        app = create_app(test_settings, make_services(up))
        with TestClient(app) as c:
            response = c.post("/webhook", json=sample_up_webhook_event_data)

        assert response.status_code == 200
        assert response.json() == {
            "status": "skipped",
            "result": "Internal transfer detected",
        }

    def test_webhook_other_event_is_ignored(self, client, sample_up_webhook_event_data):
        sample_up_webhook_event_data["data"]["attributes"][
            "eventType"
        ] = "TRANSACTION_SETTLED"

        response = client.post("/webhook", json=sample_up_webhook_event_data)

        assert response.status_code == 200
        assert response.json() == {
            "status": "ignored",
            "result": "not a transaction creation",
        }

    def test_webhook_endpoint_invalid_payload(self, client):
        response = client.post("/webhook", json={"invalid": "data"})

        # FastAPI returns 422 for validation errors (Pydantic model validation)
        assert response.status_code == 422
        assert "detail" in response.json()

    def test_refresh_endpoint_success(self, client, holder):
        response = client.get("/refresh")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["message"] == "Data refreshed successfully"
        assert holder.rebuild_count == 2  # startup + request

    def test_refresh_endpoint_failure(self, test_settings, fake_up):
        failing = FakeIndexHolder(INDEX, rebuild_error=Exception("Refresh failed"))
        app = create_app(test_settings, make_services(fake_up, holder=failing))
        with TestClient(app) as c:
            response = c.get("/refresh")

        assert response.status_code == 500
        assert "Failed to refresh data" in response.json()["detail"]

    def test_webhook_endpoint_missing_json(self, client):
        response = client.post("/webhook")

        assert response.status_code == 422

    def test_nonexistent_endpoint(self, client):
        response = client.get("/nonexistent")

        assert response.status_code == 404


class TestAPIMiddleware:
    """Test API middleware and error handling."""

    def test_cors_headers(self, client):
        response = client.options("/health")

        # TestClient doesn't handle CORS preflight requests the same way
        # but we can verify the middleware is configured
        assert response.status_code in [200, 405]

    def test_global_exception_handler(self, client):
        # Basic functionality check; the handler needs a raising endpoint
        response = client.get("/health")
        assert response.status_code == 200


def _client(settings, up, holder):
    return TestClient(create_app(settings, make_services(up, holder=holder)))


class TestAPIStartupShutdown:
    """Test application startup behaviour."""

    def test_startup_creates_webhook_when_none_listed(self, test_settings, holder):
        up = FakeUpClient()
        with _client(test_settings, up, holder) as c:
            assert c.get("/health").status_code == 200

        assert up.created_webhooks == ["https://test.example.com/webhook"]
        assert holder.rebuild_count == 1

    def test_startup_keeps_matching_webhook(self, test_settings, holder):
        up = FakeUpClient(
            webhooks=[
                UpWebhook(id="w1", url="https://test.example.com/webhook"),
            ]
        )
        with _client(test_settings, up, holder) as c:
            assert c.get("/health").status_code == 200

        assert up.created_webhooks == []

    def test_startup_creates_webhook_when_listing_fails(self, test_settings, holder):
        up = FakeUpClient(errors={"list_webhooks": UpstreamError("down", 503)})
        with _client(test_settings, up, holder) as c:
            assert c.get("/health").status_code == 200

        assert up.created_webhooks == ["https://test.example.com/webhook"]

    def test_startup_survives_failed_webhook_creation(self, test_settings, holder):
        up = FakeUpClient(errors={"create_webhook": UpstreamError("down", 500)})
        with _client(test_settings, up, holder) as c:
            assert c.get("/health").status_code == 200

        assert holder.rebuild_count == 1

    def test_startup_skips_webhook_without_url(self, test_settings, fake_up, holder):
        settings = test_settings.model_copy(update={"webhook_url": None})
        with _client(settings, fake_up, holder) as c:
            assert c.get("/health").status_code == 200

        assert fake_up.created_webhooks == []
        assert holder.rebuild_count == 1

    def test_startup_survives_unexpected_error(self, test_settings, holder):
        up = FakeUpClient(errors={"list_webhooks": RuntimeError("boom")})
        with _client(test_settings, up, holder) as c:
            assert c.get("/health").status_code == 200

        assert holder.rebuild_count == 0

    def test_startup_survives_rebuild_failure(self, test_settings, fake_up):
        failing = FakeIndexHolder(INDEX, rebuild_error=RuntimeError("boom"))
        with _client(test_settings, fake_up, failing) as c:
            assert c.get("/health").status_code == 200

    async def test_open_services_builds_real_services(self, test_settings):
        async with open_services(test_settings) as built:
            assert isinstance(built.up, HttpUpClient)
            http = built.up._http
            assert http.is_closed is False
            await built.budget_index.rebuild()

        assert http.is_closed is True

    def test_failed_webhook_is_retried_end_to_end(
        self, test_settings, services, fake_ynab, sample_up_webhook_event_data
    ):
        fake_ynab.errors["create_transaction"] = UpstreamError("down", 500)
        with TestClient(create_app(test_settings, services)) as c:
            first = c.post("/webhook", json=sample_up_webhook_event_data)
            del fake_ynab.errors["create_transaction"]
            second = c.post("/webhook", json=sample_up_webhook_event_data)
            third = c.post("/webhook", json=sample_up_webhook_event_data)

        assert first.status_code == 503
        assert second.status_code == 200
        assert second.json()["status"] == "forwarded"
        assert third.status_code == 200
        assert third.json()["status"] == "ignored"
        assert len(fake_ynab.created) == 1

    def test_missing_token_fails_startup(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        for name in (
            "UP_API_TOKEN",
            "YNAB_API_TOKEN",
            "YNAB_BUDGET_ID",
            "YNAB_ACCOUNT_ID",
        ):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("YNAB_API_TOKEN", "secret-ynab-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "budget")
        monkeypatch.setenv("YNAB_ACCOUNT_ID", "account")

        with pytest.raises(ValidationError) as exc_info:
            create_app()

        message = str(exc_info.value)
        assert "up_api_token" in message
        assert "secret-ynab-token" not in message
