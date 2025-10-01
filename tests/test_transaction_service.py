from unittest.mock import AsyncMock, patch

import pytest

from models.up_models import UpTransaction, UpWebhookEvent
from models.ynab_models import YnabTransactionResponse
from services.transaction_service import TransactionService


class TestTransactionService:
    """Test cases for Transaction service."""

    @pytest.fixture
    def transaction_service(self):
        """Create TransactionService instance."""
        return TransactionService()

    @pytest.fixture
    def sample_up_transaction(self, sample_up_transaction_data):
        """Create sample UpTransaction for testing."""
        return UpTransaction(**sample_up_transaction_data["data"])

    @pytest.fixture
    def sample_webhook_event(self, sample_up_webhook_event_data):
        """Create sample webhook event for testing."""
        return UpWebhookEvent(**sample_up_webhook_event_data)

    @pytest.mark.asyncio
    async def test_process_webhook_event_success(
        self, transaction_service, sample_webhook_event, sample_up_transaction
    ):
        """Test successful webhook event processing."""
        with patch.object(
            transaction_service.up_service,
            "should_process_transaction",
            return_value=True,
        ), patch.object(
            transaction_service.category_service,
            "is_transaction_processed",
            return_value=False,
        ), patch.object(
            transaction_service.up_service,
            "get_transaction",
            return_value=sample_up_transaction,
        ), patch.object(
            transaction_service,
            "process_transaction",
            return_value="Transaction processed",
        ):

            result = await transaction_service.process_webhook_event(
                sample_webhook_event
            )

            assert result == "Transaction processed"

    @pytest.mark.asyncio
    async def test_process_webhook_event_should_not_process(
        self, transaction_service, sample_webhook_event
    ):
        """Test webhook event that shouldn't be processed."""
        with patch.object(
            transaction_service.up_service,
            "should_process_transaction",
            return_value=False,
        ):

            result = await transaction_service.process_webhook_event(
                sample_webhook_event
            )

            assert result == "Event ignored - not a transaction creation"

    @pytest.mark.asyncio
    async def test_process_webhook_event_already_processed(
        self, transaction_service, sample_webhook_event
    ):
        """Test webhook event for already processed transaction."""
        with patch.object(
            transaction_service.up_service,
            "should_process_transaction",
            return_value=True,
        ), patch.object(
            transaction_service.category_service,
            "is_transaction_processed",
            return_value=True,
        ):

            result = await transaction_service.process_webhook_event(
                sample_webhook_event
            )

            assert "already processed" in result

    @pytest.mark.asyncio
    async def test_process_webhook_event_failed_fetch(
        self, transaction_service, sample_webhook_event
    ):
        """Test webhook event when transaction fetch fails."""
        with patch.object(
            transaction_service.up_service,
            "should_process_transaction",
            return_value=True,
        ), patch.object(
            transaction_service.category_service,
            "is_transaction_processed",
            return_value=False,
        ), patch.object(
            transaction_service.up_service, "get_transaction", return_value=None
        ), patch.object(
            transaction_service.category_service, "record_processed_transaction"
        ) as mock_record:

            result = await transaction_service.process_webhook_event(
                sample_webhook_event
            )

            assert "Failed to fetch transaction" in result
            mock_record.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_transaction_success(
        self, transaction_service, sample_up_transaction
    ):
        """Test successful transaction processing."""
        mock_ynab_transaction = YnabTransactionResponse(
            id="test-ynab-tx-id",
            date="2024-01-01",
            amount=-12500,
            cleared="cleared",
            approved=True,
            account_id="test-account-id",
            deleted=False,
        )

        with patch.object(
            transaction_service.transaction_filter,
            "should_process_transaction",
            return_value=True,
        ), patch.object(
            transaction_service.category_service,
            "get_payee_category_mappings",
            return_value={},
        ), patch.object(
            transaction_service.ynab_service,
            "find_category_for_payee",
            return_value=None,
        ), patch.object(
            transaction_service.ynab_service,
            "create_transaction",
            return_value=mock_ynab_transaction,
        ), patch.object(
            transaction_service.category_service, "record_processed_transaction"
        ) as mock_record:

            result = await transaction_service.process_transaction(
                sample_up_transaction
            )

            assert "Test Merchant" in result
            assert "$-12.50" in result
            mock_record.assert_called_once_with(
                up_transaction_id="test-transaction-id",
                ynab_transaction_id="test-ynab-tx-id",
                payee_name="Test Merchant",
                amount=-12500,
                transaction_date="2024-01-01",
                status="processed",
            )

    @pytest.mark.asyncio
    async def test_process_transaction_filtered(
        self, transaction_service, sample_up_transaction
    ):
        """Test transaction processing when transaction is filtered out."""
        with patch.object(
            transaction_service.transaction_filter,
            "should_process_transaction",
            return_value=False,
        ), patch.object(
            transaction_service.transaction_filter,
            "get_filtered_reason",
            return_value="Internal transfer detected",
        ), patch.object(
            transaction_service.category_service, "record_processed_transaction"
        ) as mock_record:

            result = await transaction_service.process_transaction(
                sample_up_transaction
            )

            assert "Transaction filtered: Internal transfer detected" == result
            mock_record.assert_called_once()
            # Verify it was recorded as skipped
            call_args = mock_record.call_args
            assert call_args[1]["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_process_transaction_with_category(
        self, transaction_service, sample_up_transaction
    ):
        """Test transaction processing with category assignment."""
        mock_ynab_transaction = YnabTransactionResponse(
            id="test-ynab-tx-id",
            date="2024-01-01",
            amount=-12500,
            cleared="cleared",
            approved=True,
            account_id="test-account-id",
            category_id="test-category-id",
            deleted=False,
        )

        payee_mappings = {"Test Merchant": "test-category-id"}

        with patch.object(
            transaction_service.transaction_filter,
            "should_process_transaction",
            return_value=True,
        ), patch.object(
            transaction_service.category_service,
            "get_payee_category_mappings",
            return_value=payee_mappings,
        ), patch.object(
            transaction_service.ynab_service,
            "find_category_for_payee",
            return_value="test-category-id",
        ), patch.object(
            transaction_service.ynab_service,
            "create_transaction",
            return_value=mock_ynab_transaction,
        ), patch.object(
            transaction_service.category_service, "record_processed_transaction"
        ):

            result = await transaction_service.process_transaction(
                sample_up_transaction
            )

            assert "Test Merchant" in result
            # Verify category was passed to create_transaction
            transaction_service.ynab_service.create_transaction.assert_called_once_with(
                sample_up_transaction, "test-category-id"
            )

    @pytest.mark.asyncio
    async def test_process_transaction_ynab_creation_failed(
        self, transaction_service, sample_up_transaction
    ):
        """Test transaction processing when YNAB creation fails."""
        with patch.object(
            transaction_service.transaction_filter,
            "should_process_transaction",
            return_value=True,
        ), patch.object(
            transaction_service.category_service,
            "get_payee_category_mappings",
            return_value={},
        ), patch.object(
            transaction_service.ynab_service,
            "find_category_for_payee",
            return_value=None,
        ), patch.object(
            transaction_service.ynab_service, "create_transaction", return_value=None
        ), patch.object(
            transaction_service.category_service, "record_processed_transaction"
        ) as mock_record:

            result = await transaction_service.process_transaction(
                sample_up_transaction
            )

            assert "Failed to create YNAB transaction" in result
            # Verify it was recorded as failed
            call_args = mock_record.call_args
            assert call_args[1]["status"] == "failed"
            assert call_args[1]["ynab_transaction_id"] is None

    @pytest.mark.asyncio
    async def test_process_transaction_exception(
        self, transaction_service, sample_up_transaction
    ):
        """Test transaction processing with unexpected exception."""
        with patch.object(
            transaction_service.transaction_filter,
            "should_process_transaction",
            side_effect=Exception("Unexpected error"),
        ), patch.object(
            transaction_service.category_service, "record_processed_transaction"
        ) as mock_record:

            result = await transaction_service.process_transaction(
                sample_up_transaction
            )

            assert "Error processing transaction: Unexpected error" == result
            # Verify error was recorded
            call_args = mock_record.call_args
            assert call_args[1]["status"] == "failed"
            assert call_args[1]["error_message"] == "Unexpected error"

    @pytest.mark.asyncio
    async def test_refresh_data_success(self, transaction_service):
        """Test successful data refresh."""
        with patch.object(
            transaction_service.category_service, "sync_categories_from_ynab"
        ) as mock_sync:

            result = await transaction_service.refresh_data()

            assert result == "Data refreshed successfully"
            mock_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_data_failure(self, transaction_service):
        """Test data refresh failure."""
        with patch.object(
            transaction_service.category_service,
            "sync_categories_from_ynab",
            side_effect=Exception("Sync failed"),
        ):

            result = await transaction_service.refresh_data()

            assert "Failed to refresh data: Sync failed" == result
