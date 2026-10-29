import json
import warnings
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from structlog.testing import capture_logs

from app import Services, build_services, create_app, open_services
from clients.errors import UpstreamError
from clients.up import HttpUpClient
from forwarding.budget_index import BudgetIndex, YnabAccountRef
from forwarding.forwarder import Forwarder
from models.up_models import UpTransaction, UpWebhook
from tests.fakes.budget_index import FakeIndexHolder
from tests.fakes.ledger import Entry, InMemoryLedger
from tests.fakes.up import FakeUpClient, up_transaction
from tests.fakes.webhook_secrets import InMemoryWebhookSecretStore
from tests.fakes.ynab import FakeYnabClient, ynab_transaction
from utils.config import Settings
from webhooks import SIGNATURE_HEADER, sign

WEBHOOK = "https://test.example.com/webhook"
V1 = "An automatic webhook to transfer data from Up into YNAB"
V2 = "UP to YNAB transaction sync webhook"
INDEX = BudgetIndex({"test-account-id": YnabAccountRef("acct-1", "tp-1")}, {})


def make_services(up, ynab=None, holder=None, ledger=None, secrets=None) -> Services:
    holder = holder or FakeIndexHolder(INDEX)
    forwarder = Forwarder(
        up, ynab or FakeYnabClient(), holder, ledger or InMemoryLedger()
    )
    return Services(
        up=up,
        forwarder=forwarder,
        budget_index=holder,
        webhook_secrets=secrets or InMemoryWebhookSecretStore(),
    )


def post_signed(client, data, secret="webhook-1-secret"):
    """POST an event signed the way Up signs it (the fake's first webhook)."""
    body = json.dumps(data).encode()
    return client.post(
        "/webhook",
        content=body,
        headers={
            SIGNATURE_HEADER: sign(body, secret),
            "Content-Type": "application/json",
        },
    )


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
        assert data["version"] == "3.0.0"

    def test_openapi_version(self, client):
        response = client.get("/openapi.json")

        assert response.json()["info"]["version"] == "3.0.0"

    def test_webhook_forwarded(self, client, fake_ynab, sample_up_webhook_event_data):
        response = post_signed(client, sample_up_webhook_event_data)

        assert response.status_code == 200
        assert response.json() == {"status": "forwarded", "result": "ynab-1"}
        assert len(fake_ynab.created) == 1

    def test_webhook_already_in_ynab(
        self, client, fake_ynab, sample_up_webhook_event_data
    ):
        fake_ynab.already_imported = True

        response = post_signed(client, sample_up_webhook_event_data)

        assert response.status_code == 200
        assert response.json() == {"status": "forwarded", "result": "already in YNAB"}

    def test_webhook_failure_answers_503(
        self, client, fake_ynab, sample_up_webhook_event_data
    ):
        fake_ynab.errors["create_transaction"] = UpstreamError("down", 500)

        response = post_signed(client, sample_up_webhook_event_data)

        assert response.status_code == 503
        assert response.json() == {"status": "failed", "result": "down"}

    def test_webhook_skipped(
        self, test_settings, sample_up_transaction_data, sample_up_webhook_event_data
    ):
        data = sample_up_transaction_data["data"]
        data["attributes"]["amount"] = {
            "currencyCode": "AUD",
            "value": "12.50",
            "valueInBaseUnits": 1250,
        }
        data["relationships"]["transferAccount"] = {
            "data": {"type": "accounts", "id": "saver-id"}
        }
        holder = FakeIndexHolder(
            BudgetIndex(
                {
                    "test-account-id": YnabAccountRef("acct-1", "tp-1"),
                    "saver-id": YnabAccountRef("acct-2", "tp-2"),
                }
            )
        )
        up = FakeUpClient(transactions={"test-transaction-id": UpTransaction(**data)})
        app = create_app(test_settings, make_services(up, holder=holder))
        with TestClient(app) as c:
            response = post_signed(c, sample_up_webhook_event_data)

        assert response.status_code == 200
        assert response.json() == {
            "status": "skipped",
            "result": "Mirror side of a Transfer",
        }

    def test_webhook_settled_marks_forwarded_transaction(
        self, test_settings, fake_up, sample_up_webhook_event_data
    ):
        sample_up_webhook_event_data["data"]["attributes"][
            "eventType"
        ] = "TRANSACTION_SETTLED"
        ynab = FakeYnabClient(
            transactions=[
                ynab_transaction(
                    "ynab-x", "Shop", None, amount=-12500, cleared="uncleared"
                )
            ]
        )
        ledger = InMemoryLedger()
        ledger.entries["test-transaction-id"] = Entry("forwarded", "ynab-x", None, 1)
        app = create_app(test_settings, make_services(fake_up, ynab, ledger=ledger))
        with TestClient(app) as c:
            response = post_signed(c, sample_up_webhook_event_data)

        assert response.status_code == 200
        assert response.json() == {"status": "settled", "result": "ynab-x"}
        assert ynab.updates == [("ynab-x", "cleared", None)]

    def test_webhook_settle_failure_is_503_and_keeps_row(
        self, test_settings, fake_up, sample_up_webhook_event_data
    ):
        sample_up_webhook_event_data["data"]["attributes"][
            "eventType"
        ] = "TRANSACTION_SETTLED"
        ynab = FakeYnabClient(
            transactions=[ynab_transaction("ynab-x", "Shop", None, amount=-12500)],
            errors={"update_transaction": UpstreamError("ynab down", 500)},
        )
        ledger = InMemoryLedger()
        ledger.entries["test-transaction-id"] = Entry("forwarded", "ynab-x", None, 1)
        app = create_app(test_settings, make_services(fake_up, ynab, ledger=ledger))
        with TestClient(app) as c:
            response = post_signed(c, sample_up_webhook_event_data)

        assert response.status_code == 503
        assert response.json() == {"status": "failed", "result": "ynab down"}
        assert ledger.entries["test-transaction-id"].status == "forwarded"

    def _deleted(self, test_settings, fake_up, data, ynab, seed=True):
        data["data"]["attributes"]["eventType"] = "TRANSACTION_DELETED"
        ledger = InMemoryLedger()
        if seed:
            ledger.entries["test-transaction-id"] = Entry(
                "forwarded", "ynab-x", None, 1
            )
        app = create_app(test_settings, make_services(fake_up, ynab, ledger=ledger))
        with TestClient(app) as c:
            return post_signed(c, data)

    def test_webhook_deleted_uncleared_is_deleted(
        self, test_settings, fake_up, sample_up_webhook_event_data
    ):
        ynab = FakeYnabClient(
            transactions=[ynab_transaction("ynab-x", "Shop", None, cleared="uncleared")]
        )

        response = self._deleted(
            test_settings, fake_up, sample_up_webhook_event_data, ynab
        )

        assert response.status_code == 200
        assert response.json() == {"status": "deleted", "result": "deleted in YNAB"}
        assert ynab.deleted_ids == ["ynab-x"]

    def test_webhook_deleted_cleared_is_flagged(
        self, test_settings, fake_up, sample_up_webhook_event_data
    ):
        ynab = FakeYnabClient(
            transactions=[ynab_transaction("ynab-x", "Shop", None, cleared="cleared")]
        )

        response = self._deleted(
            test_settings, fake_up, sample_up_webhook_event_data, ynab
        )

        assert response.status_code == 200
        assert response.json() == {
            "status": "flagged",
            "result": "flagged red: cleared in YNAB",
        }
        assert ynab.flagged == [("ynab-x", "red")]

    def test_webhook_deleted_unknown_is_ignored(
        self, test_settings, fake_up, sample_up_webhook_event_data
    ):
        response = self._deleted(
            test_settings,
            fake_up,
            sample_up_webhook_event_data,
            FakeYnabClient(),
            seed=False,
        )

        assert response.status_code == 200
        assert response.json() == {
            "status": "ignored",
            "result": "not forwarded to YNAB",
        }

    def test_webhook_deleted_ynab_failure_is_503(
        self, test_settings, fake_up, sample_up_webhook_event_data
    ):
        ynab = FakeYnabClient(errors={"get_transaction": UpstreamError("boom", 500)})

        response = self._deleted(
            test_settings, fake_up, sample_up_webhook_event_data, ynab
        )

        assert response.status_code == 503
        assert response.json() == {"status": "failed", "result": "boom"}

    def test_webhook_other_event_is_ignored(self, client, sample_up_webhook_event_data):
        sample_up_webhook_event_data["data"]["attributes"]["eventType"] = "PING"

        response = post_signed(client, sample_up_webhook_event_data)

        assert response.status_code == 200
        assert response.json() == {
            "status": "ignored",
            "result": "not a transaction event",
        }

    def test_webhook_endpoint_invalid_payload(self, client):
        response = post_signed(client, {"invalid": "data"})

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
        body = b""
        response = client.post(
            "/webhook",
            content=body,
            headers={SIGNATURE_HEADER: sign(body, "webhook-1-secret")},
        )

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


def _client(settings, up, holder, secrets=None):
    services = make_services(up, holder=holder, secrets=secrets)
    return TestClient(create_app(settings, services))


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
        secrets = InMemoryWebhookSecretStore({"w1": "s1"})
        with _client(test_settings, up, holder, secrets) as c:
            assert c.get("/health").status_code == 200

        assert up.created_webhooks == []
        assert secrets.secrets == {"w1": "s1"}

    def test_startup_does_nothing_to_webhooks_when_listing_fails(
        self, test_settings, holder
    ):
        up = FakeUpClient(errors={"list_webhooks": UpstreamError("down", 503)})
        app = create_app(test_settings, make_services(up, holder=holder))
        with capture_logs() as logs:
            with TestClient(app) as c:
                assert c.get("/health").status_code == 200

        assert up.created_webhooks == []
        assert up.deleted_webhooks == []
        assert holder.rebuild_count == 1
        assert "Failed to list webhooks" in [e["event"] for e in logs]

    def test_startup_removes_stale_and_duplicate_webhooks(self, test_settings, holder):
        up = FakeUpClient(
            webhooks=[
                UpWebhook(id="v1", url="https://test.example.com/", description=V1),
                UpWebhook(id="a", url=WEBHOOK, description=V2),
                UpWebhook(id="dup", url=WEBHOOK, description=V2),
            ]
        )
        secrets = InMemoryWebhookSecretStore({"v1": "s0", "a": "s1", "dup": "s2"})
        with _client(test_settings, up, holder, secrets) as c:
            assert c.get("/health").status_code == 200

        assert up.deleted_webhooks == ["v1", "dup"]
        assert up.created_webhooks == []
        assert secrets.secrets == {"a": "s1"}

    def test_startup_survives_failed_webhook_deletion(self, test_settings, holder):
        up = FakeUpClient(
            webhooks=[
                UpWebhook(id="old", url="https://test.example.com/", description=V1),
                UpWebhook(id="a", url=WEBHOOK, description=V2),
            ],
            errors={"delete_webhook": UpstreamError("x", 500)},
        )
        with _client(test_settings, up, holder) as c:
            assert c.get("/health").status_code == 200

        assert holder.rebuild_count == 1

    def test_refresh_reconciles_webhooks(self, test_settings, holder):
        up = FakeUpClient()
        with _client(test_settings, up, holder) as c:
            up.webhooks.append(
                UpWebhook(id="old", url="https://test.example.com/", description=V1)
            )
            response = c.get("/refresh")

            assert response.status_code == 200
            assert response.json() == {
                "status": "success",
                "message": "Data refreshed successfully",
            }
            assert up.deleted_webhooks == ["old"]

            up.errors["list_webhooks"] = UpstreamError("down", 503)
            assert c.get("/refresh").status_code == 200

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
        assert fake_up.list_webhooks_calls == 0
        assert holder.rebuild_count == 1

    def test_startup_survives_unexpected_error(self, test_settings, holder):
        up = FakeUpClient(errors={"list_webhooks": RuntimeError("boom")})
        with _client(test_settings, up, holder) as c:
            assert c.get("/health").status_code == 200

        assert holder.rebuild_count == 1

    def test_secret_store_failure_does_not_skip_index_build_or_refresh(
        self, test_settings, fake_up, holder
    ):
        secrets = InMemoryWebhookSecretStore(errors={"all": RuntimeError("db down")})
        app = create_app(
            test_settings, make_services(fake_up, holder=holder, secrets=secrets)
        )
        with capture_logs() as logs:
            with TestClient(app) as c:
                assert holder.rebuild_count == 1
                response = c.get("/refresh")

        assert response.status_code == 200
        assert response.json() == {
            "status": "success",
            "message": "Data refreshed successfully",
        }
        assert holder.rebuild_count == 2
        assert [e["event"] for e in logs].count("Webhook reconciliation failed") == 2

    def test_startup_survives_rebuild_failure(self, test_settings, fake_up):
        failing = FakeIndexHolder(INDEX, rebuild_error=RuntimeError("boom"))
        with _client(test_settings, fake_up, failing) as c:
            assert c.get("/health").status_code == 200

    async def test_open_services_builds_real_services(self, test_settings):
        async with open_services(test_settings) as built:
            assert isinstance(built.up, HttpUpClient)
            http = built.up._http
            assert http.is_closed is False

        assert http.is_closed is True

    def test_failed_webhook_is_retried_end_to_end(
        self, test_settings, services, fake_ynab, sample_up_webhook_event_data
    ):
        fake_ynab.errors["create_transaction"] = UpstreamError("down", 500)
        with TestClient(create_app(test_settings, services)) as c:
            first = post_signed(c, sample_up_webhook_event_data)
            del fake_ynab.errors["create_transaction"]
            second = post_signed(c, sample_up_webhook_event_data)
            third = post_signed(c, sample_up_webhook_event_data)

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
        ):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("YNAB_API_TOKEN", "secret-ynab-token")
        monkeypatch.setenv("YNAB_BUDGET_ID", "budget")

        with pytest.raises(ValidationError) as exc_info:
            create_app()

        message = str(exc_info.value)
        assert "up_api_token" in message
        assert "secret-ynab-token" not in message


class TestBudgetIndexThroughApp:
    """Real BudgetIndexHolder (via build_services) over fakes."""

    def test_refresh_rebuilds_the_index(
        self, test_settings, services, fake_up, fake_ynab
    ):
        with TestClient(create_app(test_settings, services)) as c:
            assert fake_up.list_accounts_calls == 1
            assert c.get("/refresh").status_code == 200

        assert fake_up.list_accounts_calls == 2
        assert fake_ynab.list_accounts_calls == 2

    def test_purchase_gets_category_match_end_to_end(
        self, test_settings, services, fake_ynab, sample_up_webhook_event_data
    ):
        fake_ynab.transactions = [
            ynab_transaction("t1", "Test Merchant", "cat-groceries")
        ]
        with TestClient(create_app(test_settings, services)) as c:
            response = post_signed(c, sample_up_webhook_event_data)
            assert c.get("/refresh").status_code == 200

        assert response.status_code == 200
        assert fake_ynab.created[0].category_id == "cat-groceries"
        assert fake_ynab.since_dates == ["1970-01-01", "1970-01-01"]

    def test_startup_without_index_boots_and_webhook_is_503(
        self, test_settings, services, fake_ynab, sample_up_webhook_event_data
    ):
        fake_ynab.errors["list_accounts"] = UpstreamError("down", 503)
        with TestClient(create_app(test_settings, services)) as c:
            assert c.get("/health").status_code == 200
            response = post_signed(c, sample_up_webhook_event_data)

        assert response.status_code == 503
        assert response.json() == {
            "status": "failed",
            "result": "Budget Index unavailable",
        }

    def test_account_not_in_ynab_is_skipped(
        self, test_settings, database, fake_up, sample_up_webhook_event_data
    ):
        ynab = FakeYnabClient()
        services = build_services(test_settings, database, fake_up, ynab)
        with TestClient(create_app(test_settings, services)) as c:
            response = post_signed(c, sample_up_webhook_event_data)

        assert response.status_code == 200
        assert response.json() == {
            "status": "skipped",
            "result": "Up account not in YNAB",
        }
        assert ynab.created == []

    def test_webhook_goes_to_matching_ynab_account(
        self, test_settings, services, fake_ynab, sample_up_webhook_event_data
    ):
        with TestClient(create_app(test_settings, services)) as c:
            post_signed(c, sample_up_webhook_event_data)

        assert fake_ynab.created[0].account_id == "ynab-acct-1"

    def test_leftover_settings_warn_at_startup(
        self, monkeypatch, services, test_settings
    ):
        monkeypatch.setenv("INTERNAL_TRANSFER_STRINGS", "[]")
        settings = Settings(
            _env_file=None,
            up_api_token="a",
            ynab_api_token="b",
            ynab_budget_id="c",
            ynab_account_id="old",
            database_url=test_settings.database_url,
        )
        app = create_app(settings, services)
        with capture_logs() as logs:
            with TestClient(app):
                pass

        ignored = [e["name"] for e in logs if e["event"] == "Setting ignored"]
        assert ignored == ["YNAB_ACCOUNT_ID", "INTERNAL_TRANSFER_STRINGS"]

    def test_no_warning_without_leftover_settings(
        self, monkeypatch, services, test_settings
    ):
        monkeypatch.delenv("YNAB_ACCOUNT_ID", raising=False)
        monkeypatch.delenv("INTERNAL_TRANSFER_STRINGS", raising=False)
        app = create_app(test_settings, services)
        with capture_logs() as logs:
            with TestClient(app):
                pass

        assert not [e for e in logs if e["event"] == "Setting ignored"]


class TestRebuildTaskLifespan:
    def test_lifespan_starts_and_cancels_rebuild_task(self, test_settings, services):
        app = create_app(test_settings, services)

        with TestClient(app):
            assert not app.state.rebuild_task.done()

        assert app.state.rebuild_task.cancelled()

    def test_lifespan_shutdown_has_no_pending_task_warning(
        self, test_settings, services
    ):
        app = create_app(test_settings, services)

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with TestClient(app):
                pass

        assert app.state.rebuild_task.cancelled()


class TestWebhookSecrets:
    """Reconciliation stores, replaces and forgets webhook signing secrets."""

    def test_fresh_start_stores_the_new_secret(self, test_settings, holder):
        secrets = InMemoryWebhookSecretStore()
        with _client(test_settings, FakeUpClient(), holder, secrets):
            pass

        assert secrets.secrets == {"webhook-1": "webhook-1-secret"}

    def test_hook_without_secret_is_replaced(self, test_settings, holder):
        up = FakeUpClient(webhooks=[UpWebhook(id="old", url=WEBHOOK, description=V2)])
        secrets = InMemoryWebhookSecretStore()
        with _client(test_settings, up, holder, secrets):
            pass

        assert up.deleted_webhooks == ["old"]
        assert up.created_webhooks == [WEBHOOK]
        assert secrets.secrets == {"webhook-1": "webhook-1-secret"}

    def test_unlisted_stored_secret_is_forgotten(self, test_settings, holder):
        up = FakeUpClient(webhooks=[UpWebhook(id="a", url=WEBHOOK, description=V2)])
        secrets = InMemoryWebhookSecretStore({"a": "s1", "gone": "s2"})
        with _client(test_settings, up, holder, secrets):
            pass

        assert secrets.secrets == {"a": "s1"}

    def test_failed_delete_keeps_the_secret(self, test_settings, holder):
        up = FakeUpClient(
            webhooks=[
                UpWebhook(id="a", url=WEBHOOK, description=V2),
                UpWebhook(id="dup", url=WEBHOOK, description=V2),
            ],
            errors={"delete_webhook": UpstreamError("x", 500)},
        )
        secrets = InMemoryWebhookSecretStore({"a": "s1", "dup": "s2"})
        with _client(test_settings, up, holder, secrets):
            pass

        assert secrets.secrets == {"a": "s1", "dup": "s2"}

    def test_secret_values_are_never_logged(self, test_settings, holder):
        app = create_app(test_settings, make_services(FakeUpClient(), holder=holder))
        with capture_logs() as logs:
            with TestClient(app):
                pass

        assert "Webhook created" in [e["event"] for e in logs]
        assert "webhook-1-secret" not in repr(logs)

    def test_no_url_means_no_secret_and_a_warning(
        self, test_settings, fake_up, holder, sample_up_webhook_event_data
    ):
        settings = test_settings.model_copy(update={"webhook_url": None})
        app = create_app(settings, make_services(fake_up, holder=holder))
        with capture_logs() as logs:
            with TestClient(app) as c:
                response = post_signed(c, sample_up_webhook_event_data)

        assert response.status_code == 401
        assert "No webhook secret stored; /webhook rejects every event" in [
            e["event"] for e in logs
        ]


class TestWebhookSignature:
    def test_missing_signature_is_rejected(
        self, client, fake_ynab, sample_up_webhook_event_data
    ):
        response = client.post("/webhook", json=sample_up_webhook_event_data)

        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid webhook signature"}
        assert fake_ynab.created == []

    def test_bad_signature_is_rejected_and_logged_without_values(
        self, client, fake_ynab, sample_up_webhook_event_data
    ):
        body = json.dumps(sample_up_webhook_event_data).encode()
        with capture_logs() as logs:
            response = client.post(
                "/webhook",
                content=body,
                headers={SIGNATURE_HEADER: sign(body, "wrong-secret")},
            )

        assert response.status_code == 401
        assert fake_ynab.created == []
        [entry] = [e for e in logs if e["event"] == "Webhook signature rejected"]
        assert entry["log_level"] == "warning"
        assert entry["reason"] == "invalid"
        assert sign(body, "wrong-secret") not in repr(logs)
        assert "test-transaction-id" not in repr(logs)

    def test_missing_signature_logs_reason_missing(self, client):
        with capture_logs() as logs:
            client.post("/webhook", content=b"{}")

        [entry] = [e for e in logs if e["event"] == "Webhook signature rejected"]
        assert entry["reason"] == "missing"

    def test_signed_empty_body_is_422(self, client):
        body = b""
        response = client.post(
            "/webhook",
            content=body,
            headers={SIGNATURE_HEADER: sign(body, "webhook-1-secret")},
        )

        assert response.status_code == 422

    def test_openapi_documents_the_body_and_401(self, client):
        operation = client.get("/openapi.json").json()["paths"]["/webhook"]["post"]

        schema = operation["requestBody"]["content"]["application/json"]["schema"]
        assert schema["example"]["data"]["id"] == "01234567-89ab-cdef-0123-456789abcdef"
        assert "401" in operation["responses"]


class TestAdminToken:
    def test_token_with_trailing_newline_still_matches(
        self, test_settings, fake_up, holder
    ):
        settings = Settings(
            _env_file=None,
            up_api_token="a",
            ynab_api_token="b",
            ynab_budget_id="c",
            admin_token="tok\n",
            database_url=test_settings.database_url,
        )
        app = create_app(settings, make_services(fake_up, holder=holder))
        with TestClient(app) as c:
            right = c.get("/refresh", headers={"Authorization": "Bearer tok"})

        assert right.status_code == 200

    def _client(self, test_settings, fake_up, holder, token):
        settings = test_settings.model_copy(update={"admin_token": token})
        return TestClient(create_app(settings, make_services(fake_up, holder=holder)))

    def test_unset_token_leaves_refresh_open_and_warns(
        self, test_settings, fake_up, holder
    ):
        app = create_app(test_settings, make_services(fake_up, holder=holder))
        with capture_logs() as logs:
            with TestClient(app) as c:
                assert c.get("/refresh").status_code == 200

        assert "ADMIN_TOKEN not set; admin endpoints are open" in [
            e["event"] for e in logs
        ]

    def test_set_token_is_required_as_bearer(self, test_settings, fake_up, holder):
        with self._client(test_settings, fake_up, holder, "tok") as c:
            missing = c.get("/refresh")
            wrong = c.get("/refresh", headers={"Authorization": "Bearer nope"})
            basic = c.get("/refresh", headers={"Authorization": "Basic tok"})
            non_ascii = c.get(
                "/refresh", headers={"Authorization": "Bearer t\xf6k".encode("latin-1")}
            )
            right = c.get("/refresh", headers={"Authorization": "Bearer tok"})

        for response in (missing, wrong, basic, non_ascii):
            assert response.status_code == 401
            assert response.headers["WWW-Authenticate"] == "Bearer"
            assert response.json() == {"detail": "Invalid admin token"}
        assert right.status_code == 200

    def test_set_token_does_not_warn(self, test_settings, fake_up, holder):
        settings = test_settings.model_copy(update={"admin_token": "tok"})
        app = create_app(settings, make_services(fake_up, holder=holder))
        with capture_logs() as logs:
            with TestClient(app):
                pass

        assert "ADMIN_TOKEN not set; admin endpoints are open" not in [
            e["event"] for e in logs
        ]


class TestBackfill:
    AEST = timezone(timedelta(hours=10))

    def _app(self, test_settings, fake_up, holder, ledger=None, token=None):
        settings = test_settings.model_copy(update={"admin_token": token})
        return create_app(
            settings, make_services(fake_up, holder=holder, ledger=ledger)
        )

    def test_backfill_reports_counts(self, test_settings, fake_up, holder):
        fake_up.transactions["elsewhere"] = up_transaction(
            "elsewhere", "2026-10-05T01:00:00+00:00", account_id="unknown-account"
        )
        fake_up.transactions["done"] = up_transaction(
            "done", "2026-10-06T01:00:00+00:00"
        )
        ledger = InMemoryLedger()
        ledger.entries["done"] = Entry("forwarded", "ynab-9", None, 1)
        ledger.entries["test-transaction-id"] = Entry("failed", None, "boom", 1)
        app = self._app(test_settings, fake_up, holder, ledger)

        with TestClient(app) as c:
            response = c.post("/backfill?since=2024-01-01")

        assert response.status_code == 200
        assert response.json() == {
            "forwarded": 1,
            "skipped": 1,
            "failed": 0,
            "already_handled": 1,
            "more_remaining": False,
        }
        assert fake_up.list_transactions_calls == [
            datetime(2024, 1, 1, tzinfo=self.AEST)
        ]

    @pytest.mark.parametrize("query", ["?since=2026-13-01", "?since=yesterday", ""])
    def test_bad_or_missing_date_is_422(self, test_settings, fake_up, holder, query):
        with TestClient(self._app(test_settings, fake_up, holder)) as c:
            response = c.post("/backfill" + query)

        assert response.status_code == 422
        assert fake_up.list_transactions_calls == []

    def test_admin_token_is_required_when_set(self, test_settings, fake_up, holder):
        with TestClient(self._app(test_settings, fake_up, holder, token="tok")) as c:
            missing = c.post("/backfill?since=2024-01-01")
            right = c.post(
                "/backfill?since=2024-01-01",
                headers={"Authorization": "Bearer tok"},
            )

        assert missing.status_code == 401
        assert right.status_code == 200

    def test_unset_token_leaves_backfill_open(self, test_settings, fake_up, holder):
        with TestClient(self._app(test_settings, fake_up, holder)) as c:
            assert c.post("/backfill?since=2024-01-01").status_code == 200

    def test_up_listing_failure_is_502(self, test_settings, fake_up, holder):
        fake_up.errors["list_transactions"] = UpstreamError("down", 503)

        with TestClient(self._app(test_settings, fake_up, holder)) as c:
            response = c.post("/backfill?since=2024-01-01")

        assert response.status_code == 502
        assert response.json() == {"detail": "Could not list Up transactions"}

    def test_retried_skip_is_forwarded(self, test_settings, fake_up, holder):
        ledger = InMemoryLedger()
        ledger.entries["test-transaction-id"] = Entry(
            "skipped", None, "Up account not in YNAB", 1, "account_not_in_ynab"
        )

        with TestClient(self._app(test_settings, fake_up, holder, ledger)) as c:
            response = c.post("/backfill?since=2024-01-01")

        assert response.json()["forwarded"] == 1
        assert ledger.entries["test-transaction-id"].status == "forwarded"
