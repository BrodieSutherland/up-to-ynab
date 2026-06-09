"""
Mock-based integration tests for the transaction service pipeline.

These tests use pytest-httpserver to intercept real HTTP calls made by
UpService and YnabService, exercising the full service layer end-to-end
without hitting real APIs or needing Docker.
"""

import json
import os

import pytest
from pytest_httpserver import HTTPServer

# Ensure env vars are set before any app import
os.environ.setdefault("UP_API_TOKEN", "test-up-token")
os.environ.setdefault("YNAB_API_TOKEN", "test-ynab-token")
os.environ.setdefault("YNAB_BUDGET_ID", "test-budget-id")
os.environ.setdefault("YNAB_ACCOUNT_ID", "test-account-id")


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

TRANSACTION_ID = "txn-abc-123"

UP_TRANSACTION_PAYLOAD = {
    "data": {
        "type": "transactions",
        "id": TRANSACTION_ID,
        "attributes": {
            "status": "SETTLED",
            "rawText": "WOOLWORTHS 1234",
            "description": "Woolworths",
            "message": None,
            "isCategorizable": True,
            "holdInfo": None,
            "roundUp": None,
            "cashback": None,
            "amount": {
                "currencyCode": "AUD",
                "value": "-55.30",
                "valueInBaseUnits": -5530,
            },
            "foreignAmount": None,
            "currencyConversionFee": None,
            "settledAt": "2024-06-01T10:00:00+10:00",
            "createdAt": "2024-06-01T10:00:00+10:00",
        },
        "relationships": {
            "account": {"data": {"type": "accounts", "id": "acct-001"}},
            "category": None,
            "parentCategory": None,
            "tags": None,
            "attachment": None,
            "transferAccount": None,
        },
    }
}

YNAB_BUDGET_PAYLOAD = {
    "data": {
        "budget": {
            "id": "test-budget-id",
            "name": "Test Budget",
            "last_modified_on": "2024-01-01T00:00:00+00:00",
            "first_month": "2024-01-01",
            "last_month": "2024-12-01",
            "date_format": {"format": "DD/MM/YYYY"},
            "currency_format": {
                "iso_code": "AUD",
                "example_format": "123,456.78",
                "decimal_digits": 2,
                "decimal_separator": ".",
                "symbol_first": True,
                "group_separator": ",",
                "currency_symbol": "$",
                "display_symbol": True,
            },
            "accounts": [],
            "payees": [],
            "categories": [],
            "category_groups": [],
        }
    }
}

YNAB_CREATE_TRANSACTION_RESPONSE = {
    "data": {
        "transaction": {
            "id": "ynab-txn-xyz",
            "date": "2024-06-01",
            "amount": -55300,
            "memo": "WOOLWORTHS 1234",
            "cleared": "cleared",
            "approved": True,
            "flag_color": None,
            "account_id": "test-account-id",
            "payee_id": None,
            "category_id": None,
            "transfer_account_id": None,
            "transfer_transaction_id": None,
            "matched_transaction_id": None,
            "import_id": TRANSACTION_ID,
            "import_payee_name": "Woolworths",
            "import_payee_name_original": None,
            "debt_transaction_type": None,
            "deleted": False,
        }
    }
}

WEBHOOK_EVENT_PAYLOAD = {
    "data": {
        "type": "webhook-events",
        "id": "event-001",
        "attributes": {
            "eventType": "TRANSACTION_CREATED",
            "createdAt": "2024-06-01T10:00:00+10:00",
        },
        "relationships": {
            "transaction": {"data": {"type": "transactions", "id": TRANSACTION_ID}}
        },
    }
}

INTERNAL_TRANSFER_PAYLOAD = {
    "data": {
        "type": "transactions",
        "id": "txn-transfer-001",
        "attributes": {
            "status": "SETTLED",
            "rawText": "Transfer to savings",
            "description": "Transfer to Savings",
            "message": None,
            "isCategorizable": False,
            "holdInfo": None,
            "roundUp": None,
            "cashback": None,
            "amount": {
                "currencyCode": "AUD",
                "value": "-100.00",
                "valueInBaseUnits": -10000,
            },
            "foreignAmount": None,
            "currencyConversionFee": None,
            "settledAt": "2024-06-01T10:00:00+10:00",
            "createdAt": "2024-06-01T10:00:00+10:00",
        },
        "relationships": {
            "account": {"data": {"type": "accounts", "id": "acct-001"}},
            "category": None,
            "parentCategory": None,
            "tags": None,
            "attachment": None,
            "transferAccount": {"data": {"type": "accounts", "id": "acct-002"}},
        },
    }
}


# ---------------------------------------------------------------------------
# Helper: patch service base URLs to point at the local test server
# ---------------------------------------------------------------------------


def _patch_settings(monkeypatch, up_base_url: str, ynab_base_url: str):
    """Redirect service HTTP calls to the local pytest-httpserver."""
    from utils import config as cfg_module

    # Clear the lru_cache so a fresh Settings object is built each test
    cfg_module.get_settings.cache_clear()

    monkeypatch.setenv("UP_BASE_URL", up_base_url)
    monkeypatch.setenv("YNAB_BASE_URL", ynab_base_url)
    monkeypatch.setenv("UP_API_TOKEN", "test-up-token")
    monkeypatch.setenv("YNAB_API_TOKEN", "test-ynab-token")
    monkeypatch.setenv("YNAB_BUDGET_ID", "test-budget-id")
    monkeypatch.setenv("YNAB_ACCOUNT_ID", "test-account-id")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTransactionPipelineIntegration:
    """
    End-to-end tests for the full transaction pipeline using mock HTTP servers.
    Tests hit real service classes but intercept outbound HTTP calls.
    """

    @pytest.fixture(autouse=True)
    def clear_settings_cache(self):
        """Clear the settings LRU cache before and after each test."""
        from utils.config import get_settings

        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_process_webhook_event_creates_ynab_transaction(
        self, httpserver: HTTPServer, monkeypatch, tmp_path
    ):
        """
        Full happy path: TRANSACTION_CREATED event → fetches from Up →
        creates in YNAB → returns success message.

        We use two separate HTTPServer instances to avoid handler ordering
        conflicts between Up Bank and YNAB routes.
        """
        from pytest_httpserver import HTTPServer as HS

        # Separate server for YNAB so Up and YNAB routes don't cross-interfere
        ynab_server = HS()
        ynab_server.start()

        try:
            up_base_url = httpserver.url_for("") + "/"
            ynab_base_url = ynab_server.url_for("") + "/"
            _patch_settings(monkeypatch, up_base_url=up_base_url, ynab_base_url=ynab_base_url)
            monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

            # Mock: Up GET /transactions/{id}
            httpserver.expect_request(
                f"/transactions/{TRANSACTION_ID}", method="GET"
            ).respond_with_json(UP_TRANSACTION_PAYLOAD)

            # Mock: YNAB GET /budgets/{id} (called by get_categories / sync)
            ynab_server.expect_request(
                "/budgets/test-budget-id", method="GET"
            ).respond_with_json(YNAB_BUDGET_PAYLOAD)

            # Mock: YNAB POST /budgets/{id}/transactions
            ynab_server.expect_request(
                "/budgets/test-budget-id/transactions", method="POST"
            ).respond_with_json(YNAB_CREATE_TRANSACTION_RESPONSE)

            from database.connection import db_manager

            await db_manager.create_tables()

            from models.up_models import UpWebhookEvent
            from services.transaction_service import TransactionService

            event = UpWebhookEvent(**WEBHOOK_EVENT_PAYLOAD)
            service = TransactionService()
            result = await service.process_webhook_event(event)

            assert "Woolworths" in result or "55.30" in result, (
                f"Expected success message with payee/amount, got: {result!r}"
            )

            await db_manager.close()
        finally:
            ynab_server.clear()
            ynab_server.stop()


    @pytest.mark.asyncio
    async def test_process_webhook_ignores_non_transaction_event(
        self, httpserver: HTTPServer, monkeypatch
    ):
        """WEBHOOK_DELIVERY_STATUS events should be ignored without any API calls."""
        base_url = httpserver.url_for("")
        _patch_settings(monkeypatch, up_base_url=base_url + "/", ynab_base_url=base_url + "/")
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

        from database.connection import db_manager

        await db_manager.create_tables()

        non_transaction_event = {
            "data": {
                "type": "webhook-events",
                "id": "event-002",
                "attributes": {
                    "eventType": "WEBHOOK_DELIVERY_STATUS_CHANGED",
                    "createdAt": "2024-06-01T10:00:00+10:00",
                },
                "relationships": {},
            }
        }

        from models.up_models import UpWebhookEvent
        from services.transaction_service import TransactionService

        event = UpWebhookEvent(**non_transaction_event)
        service = TransactionService()
        result = await service.process_webhook_event(event)

        assert "ignored" in result.lower(), (
            f"Expected 'ignored' in result for non-transaction event, got: {result!r}"
        )
        # Verify no outbound HTTP calls were made
        httpserver.check_assertions()

        await db_manager.close()

    @pytest.mark.asyncio
    async def test_process_webhook_handles_up_api_failure(
        self, httpserver: HTTPServer, monkeypatch
    ):
        """When Up API returns 503, the pipeline should handle gracefully."""
        base_url = httpserver.url_for("")
        _patch_settings(monkeypatch, up_base_url=base_url + "/", ynab_base_url=base_url + "/")
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

        httpserver.expect_request(
            f"/transactions/{TRANSACTION_ID}", method="GET"
        ).respond_with_data("Service Unavailable", status=503)

        from database.connection import db_manager

        await db_manager.create_tables()

        from models.up_models import UpWebhookEvent
        from services.transaction_service import TransactionService

        event = UpWebhookEvent(**WEBHOOK_EVENT_PAYLOAD)
        service = TransactionService()
        result = await service.process_webhook_event(event)

        assert "failed" in result.lower() or "fetch" in result.lower(), (
            f"Expected failure message, got: {result!r}"
        )

        await db_manager.close()

    @pytest.mark.asyncio
    async def test_process_internal_transfer_is_skipped(
        self, httpserver: HTTPServer, monkeypatch
    ):
        """Internal transfers (e.g. 'Transfer to Savings') must be filtered out."""
        base_url = httpserver.url_for("")
        _patch_settings(monkeypatch, up_base_url=base_url + "/", ynab_base_url=base_url + "/")
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

        transfer_transaction_id = "txn-transfer-001"
        transfer_event = {
            "data": {
                "type": "webhook-events",
                "id": "event-transfer",
                "attributes": {
                    "eventType": "TRANSACTION_CREATED",
                    "createdAt": "2024-06-01T10:00:00+10:00",
                },
                "relationships": {
                    "transaction": {
                        "data": {"type": "transactions", "id": transfer_transaction_id}
                    }
                },
            }
        }

        httpserver.expect_request(
            f"/transactions/{transfer_transaction_id}", method="GET"
        ).respond_with_json(INTERNAL_TRANSFER_PAYLOAD)

        from database.connection import db_manager

        await db_manager.create_tables()

        from models.up_models import UpWebhookEvent
        from services.transaction_service import TransactionService

        event = UpWebhookEvent(**transfer_event)
        service = TransactionService()
        result = await service.process_webhook_event(event)

        assert "filter" in result.lower() or "transfer" in result.lower(), (
            f"Expected filter/transfer in result, got: {result!r}"
        )

        await db_manager.close()

    @pytest.mark.asyncio
    async def test_duplicate_transaction_is_skipped(
        self, httpserver: HTTPServer, monkeypatch
    ):
        """A transaction that was already processed should not be re-processed."""
        base_url = httpserver.url_for("")
        _patch_settings(monkeypatch, up_base_url=base_url + "/", ynab_base_url=base_url + "/")
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

        httpserver.expect_request(
            f"/transactions/{TRANSACTION_ID}", method="GET"
        ).respond_with_json(UP_TRANSACTION_PAYLOAD)

        httpserver.expect_ordered_request(
            "/budgets/test-budget-id", method="GET"
        ).respond_with_json(YNAB_BUDGET_PAYLOAD)

        httpserver.expect_request(
            "/budgets/test-budget-id/transactions", method="POST"
        ).respond_with_json(YNAB_CREATE_TRANSACTION_RESPONSE)

        from database.connection import db_manager

        await db_manager.create_tables()

        from models.up_models import UpWebhookEvent
        from services.transaction_service import TransactionService

        event = UpWebhookEvent(**WEBHOOK_EVENT_PAYLOAD)
        service = TransactionService()

        # First processing
        result_1 = await service.process_webhook_event(event)

        # Reset HTTP expectations for second call — no Up/YNAB calls should happen
        httpserver.clear()

        # Second processing — should be caught as duplicate
        service2 = TransactionService()
        result_2 = await service2.process_webhook_event(event)

        assert "already processed" in result_2.lower() or "processed" in result_2.lower(), (
            f"Expected duplicate detection, got: {result_2!r}"
        )
        # No HTTP calls should have been made on the second attempt
        httpserver.check_assertions()

        await db_manager.close()
