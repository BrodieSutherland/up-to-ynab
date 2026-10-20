from unittest.mock import patch

import pytest
from sqlalchemy import select

from clients.errors import UpstreamError
from database.models import ProcessedTransaction
from models.up_models import UpTransaction, UpWebhookEvent
from services.transaction_service import create_import_id


@pytest.fixture
def transaction_service(services):
    return services.transactions


@pytest.fixture
def up_transaction(sample_up_transaction_data):
    return UpTransaction(**sample_up_transaction_data["data"])


@pytest.fixture
def webhook_event(sample_up_webhook_event_data):
    return UpWebhookEvent(**sample_up_webhook_event_data)


async def rows(database):
    async with database.get_session() as session:
        result = await session.execute(select(ProcessedTransaction))
        return list(result.scalars().all())


class TestProcessWebhookEvent:
    async def test_success_creates_ynab_transaction(
        self, transaction_service, webhook_event, fake_ynab, database
    ):
        result = await transaction_service.process_webhook_event(webhook_event)

        assert result == "$-12.50 paid to Test Merchant at 2024-01-01"
        [created] = fake_ynab.created
        assert created.account_id == "test_account_id"
        assert created.amount == -12500
        assert created.import_id == "up_test-transaction-id"
        assert created.memo == "Test Purchase"
        assert created.payee_name == "Test Merchant"
        assert created.date == "2024-01-01"
        [row] = await rows(database)
        assert row.up_transaction_id == "test-transaction-id"
        assert row.ynab_transaction_id == "ynab-1"
        assert row.status == "processed"

    async def test_non_created_event_is_ignored(
        self, transaction_service, sample_up_webhook_event_data, fake_ynab
    ):
        sample_up_webhook_event_data["data"]["attributes"][
            "eventType"
        ] = "TRANSACTION_SETTLED"
        event = UpWebhookEvent(**sample_up_webhook_event_data)

        result = await transaction_service.process_webhook_event(event)

        assert result == "Event ignored - not a transaction creation"
        assert fake_ynab.created == []

    async def test_event_without_transaction_id_is_ignored(
        self, transaction_service, sample_up_webhook_event_data
    ):
        sample_up_webhook_event_data["data"]["relationships"] = None
        event = UpWebhookEvent(**sample_up_webhook_event_data)

        result = await transaction_service.process_webhook_event(event)

        assert result == "Event ignored - not a transaction creation"

    async def test_already_processed(
        self, transaction_service, webhook_event, fake_ynab
    ):
        await transaction_service.process_webhook_event(webhook_event)

        result = await transaction_service.process_webhook_event(webhook_event)

        assert result == "Transaction test-transaction-id already processed"
        assert len(fake_ynab.created) == 1

    async def test_up_fetch_failure_is_recorded(
        self, transaction_service, webhook_event, fake_up, fake_ynab, database
    ):
        fake_up.errors["get_transaction"] = UpstreamError("boom", 500)

        result = await transaction_service.process_webhook_event(webhook_event)

        assert result == "Failed to fetch transaction test-transaction-id from Up API"
        [row] = await rows(database)
        assert row.status == "failed"
        assert row.error_message == "Failed to fetch transaction from Up API"
        assert fake_ynab.created == []

    async def test_unknown_transaction_is_a_failed_fetch(
        self, transaction_service, webhook_event, fake_up
    ):
        fake_up.transactions.clear()

        result = await transaction_service.process_webhook_event(webhook_event)

        assert "Failed to fetch transaction" in result


class TestProcessTransaction:
    async def test_ynab_failure_is_recorded(
        self, transaction_service, up_transaction, fake_ynab, database
    ):
        fake_ynab.errors["create_transaction"] = UpstreamError("boom", 500)

        result = await transaction_service.process_transaction(up_transaction)

        assert result == "Failed to create YNAB transaction for Test Merchant"
        [row] = await rows(database)
        assert row.status == "failed"
        assert row.ynab_transaction_id is None
        assert row.error_message == "Failed to create YNAB transaction"

    async def test_already_imported_is_still_a_failure(
        self, transaction_service, up_transaction, fake_ynab, database
    ):
        fake_ynab.already_imported = True

        result = await transaction_service.process_transaction(up_transaction)

        assert result == "Failed to create YNAB transaction for Test Merchant"
        [row] = await rows(database)
        assert row.status == "failed"

    async def test_payee_mapping_sets_category(
        self, transaction_service, up_transaction, fake_ynab
    ):
        await transaction_service.category_service.update_payee_category_mapping(
            "Test Merchant", "cat-1", "Groceries"
        )

        await transaction_service.process_transaction(up_transaction)

        assert fake_ynab.created[0].category_id == "cat-1"

    async def test_no_mapping_leaves_category_empty(
        self, transaction_service, up_transaction, fake_ynab
    ):
        await transaction_service.process_transaction(up_transaction)

        assert fake_ynab.created[0].category_id is None

    async def test_internal_transfer_is_skipped(
        self, transaction_service, sample_up_transaction_data, fake_ynab, database
    ):
        data = sample_up_transaction_data["data"]
        data["attributes"]["description"] = "Transfer to Savings"
        transfer = UpTransaction(**data)

        result = await transaction_service.process_transaction(transfer)

        assert result.startswith("Transaction filtered: ")
        assert fake_ynab.created == []
        [row] = await rows(database)
        assert row.status == "skipped"

    async def test_unexpected_exception_is_recorded(
        self, transaction_service, up_transaction, fake_ynab, database
    ):
        fake_ynab.errors["create_transaction"] = RuntimeError("Unexpected error")

        result = await transaction_service.process_transaction(up_transaction)

        assert result == "Error processing transaction: Unexpected error"
        [row] = await rows(database)
        assert row.status == "failed"
        assert row.error_message == "Unexpected error"


class TestRefreshData:
    async def test_success(self, transaction_service):
        result = await transaction_service.refresh_data()

        assert result == "Data refreshed successfully"

    async def test_failure(self, transaction_service):
        with patch.object(
            transaction_service.category_service,
            "sync_categories_from_ynab",
            side_effect=Exception("Sync failed"),
        ):
            result = await transaction_service.refresh_data()

        assert result == "Failed to refresh data: Sync failed"


class TestCreateImportId:
    def test_uuid_is_used_unchanged(self):
        uuid = "01234567-89ab-cdef-0123-456789abcdef"

        assert create_import_id(uuid) == uuid

    def test_short_id_gets_prefix(self):
        assert create_import_id("abc") == "up_abc"

    def test_long_id_is_hashed_to_36_chars(self):
        result = create_import_id("x" * 60)

        assert len(result) == 36
        assert not result.startswith("up_")
