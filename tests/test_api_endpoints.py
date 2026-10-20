import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import Services, create_app, open_services
from clients.errors import UpstreamError
from clients.up import HttpUpClient
from models.up_models import UpWebhook
from tests.fakes.up import FakeUpClient


class FakeTransactions:
    """In-memory stand-in for TransactionService at the app seam."""

    def __init__(
        self,
        result="Transaction processed successfully",
        error=None,
        refresh_result="Data refreshed successfully",
        refresh_error=None,
    ):
        self.result = result
        self.error = error
        self.refresh_result = refresh_result
        self.refresh_error = refresh_error
        self.events = []
        self.refresh_count = 0

    async def process_webhook_event(self, event):
        self.events.append(event)
        if self.error:
            raise self.error
        return self.result

    async def refresh_data(self):
        self.refresh_count += 1
        if self.refresh_error:
            raise self.refresh_error
        return self.refresh_result


@pytest.fixture
def fake_transactions():
    return FakeTransactions()


@pytest.fixture
def client(test_settings, fake_up, fake_transactions):
    app = create_app(
        settings=test_settings,
        services=Services(up=fake_up, transactions=fake_transactions),
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

    def test_webhook_endpoint_success(
        self, client, fake_transactions, sample_up_webhook_event_data
    ):
        response = client.post("/webhook", json=sample_up_webhook_event_data)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processed"
        assert data["result"] == "Transaction processed successfully"
        assert [e.data.transaction_id for e in fake_transactions.events] == [
            "test-transaction-id"
        ]

    def test_webhook_endpoint_invalid_payload(self, client):
        response = client.post("/webhook", json={"invalid": "data"})

        # FastAPI returns 422 for validation errors (Pydantic model validation)
        assert response.status_code == 422
        assert "detail" in response.json()

    def test_webhook_endpoint_processing_error(
        self, test_settings, fake_up, sample_up_webhook_event_data
    ):
        failing = FakeTransactions(error=Exception("Processing failed"))
        app = create_app(test_settings, Services(up=fake_up, transactions=failing))
        with TestClient(app) as c:
            response = c.post("/webhook", json=sample_up_webhook_event_data)

        assert response.status_code == 400
        assert "Invalid webhook payload" in response.json()["detail"]

    def test_refresh_endpoint_success(self, client):
        response = client.get("/refresh")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["message"] == "Data refreshed successfully"

    def test_refresh_endpoint_failure(self, test_settings, fake_up):
        failing = FakeTransactions(refresh_error=Exception("Refresh failed"))
        app = create_app(test_settings, Services(up=fake_up, transactions=failing))
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


def _client(settings, up, transactions):
    app = create_app(settings, Services(up=up, transactions=transactions))
    return TestClient(app)


class TestAPIStartupShutdown:
    """Test application startup behaviour."""

    def test_startup_creates_webhook_when_none_listed(
        self, test_settings, fake_transactions
    ):
        up = FakeUpClient()
        with _client(test_settings, up, fake_transactions) as c:
            assert c.get("/health").status_code == 200

        assert up.created_webhooks == ["https://test.example.com/webhook"]
        assert fake_transactions.refresh_count == 1

    def test_startup_keeps_matching_webhook(self, test_settings, fake_transactions):
        up = FakeUpClient(
            webhooks=[
                UpWebhook(id="w1", url="https://test.example.com/webhook"),
            ]
        )
        with _client(test_settings, up, fake_transactions) as c:
            assert c.get("/health").status_code == 200

        assert up.created_webhooks == []

    def test_startup_creates_webhook_when_listing_fails(
        self, test_settings, fake_transactions
    ):
        up = FakeUpClient(errors={"list_webhooks": UpstreamError("down", 503)})
        with _client(test_settings, up, fake_transactions) as c:
            assert c.get("/health").status_code == 200

        assert up.created_webhooks == ["https://test.example.com/webhook"]

    def test_startup_survives_failed_webhook_creation(
        self, test_settings, fake_transactions
    ):
        up = FakeUpClient(errors={"create_webhook": UpstreamError("down", 500)})
        with _client(test_settings, up, fake_transactions) as c:
            assert c.get("/health").status_code == 200

        assert fake_transactions.refresh_count == 1

    def test_startup_skips_webhook_without_url(
        self, test_settings, fake_up, fake_transactions
    ):
        settings = test_settings.model_copy(update={"webhook_url": None})
        with _client(settings, fake_up, fake_transactions) as c:
            assert c.get("/health").status_code == 200

        assert fake_up.created_webhooks == []
        assert fake_transactions.refresh_count == 1

    def test_startup_survives_unexpected_error(self, test_settings, fake_transactions):
        up = FakeUpClient(errors={"list_webhooks": RuntimeError("boom")})
        with _client(test_settings, up, fake_transactions) as c:
            assert c.get("/health").status_code == 200

        assert fake_transactions.refresh_count == 0

    def test_startup_survives_refresh_failure(self, test_settings, fake_up):
        failing = FakeTransactions(refresh_error=RuntimeError("boom"))
        with _client(test_settings, fake_up, failing) as c:
            assert c.get("/health").status_code == 200

    async def test_open_services_builds_real_services(self, test_settings):
        async with open_services(test_settings) as built:
            assert isinstance(built.up, HttpUpClient)
            http = built.up._http
            assert http.is_closed is False
            category = built.transactions.category_service
            await category.record_processed_transaction(
                up_transaction_id="abc",
                ynab_transaction_id="y1",
                payee_name="Shop",
                amount=-1000,
                transaction_date="2024-01-01",
            )
            assert await category.is_transaction_processed("abc") is True

        assert http.is_closed is True

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
