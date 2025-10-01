from datetime import datetime
from unittest.mock import AsyncMock, patch
import pytest

from database.models import PayeeCategoryMapping, ProcessedTransaction
from services.category_service import CategoryService
from services.ynab_service import YnabService


class TestCategoryService:
    """Test cases for Category service."""

    @pytest.fixture
    def category_service(self):
        """Create CategoryService instance."""
        return CategoryService()

    @pytest.mark.asyncio
    async def test_sync_categories_from_ynab(self, category_service, sample_ynab_budget_data):
        """Test syncing categories from YNAB."""
        # Mock YNAB service methods
        with patch.object(category_service.ynab_service, 'get_categories') as mock_get_categories, \
             patch.object(category_service.ynab_service, 'get_payees') as mock_get_payees, \
             patch('database.connection.db_manager.get_session') as mock_session:

            # Setup mocks
            from models.ynab_models import YnabCategory
            mock_categories = [
                YnabCategory(
                    id="test-category-id",
                    name="Test Category",
                    hidden=False,
                    budgeted=0,
                    activity=0,
                    balance=0,
                    deleted=False
                )
            ]
            mock_get_categories.return_value = mock_categories
            mock_get_payees.return_value = []

            mock_session.return_value.__aenter__.return_value = AsyncMock()

            # Execute
            await category_service.sync_categories_from_ynab()

            # Verify
            mock_get_categories.assert_called_once()
            mock_get_payees.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_payee_category_mappings(self, category_service, test_db_session):
        """Test retrieving payee category mappings."""
        # Setup test data
        mapping = PayeeCategoryMapping(
            payee_name="Test Merchant",
            category_id="test-category-id",
            category_name="Test Category"
        )
        test_db_session.add(mapping)
        await test_db_session.commit()

        with patch('database.connection.db_manager.get_session') as mock_session:
            mock_session.return_value.__aenter__.return_value = test_db_session

            mappings = await category_service.get_payee_category_mappings()

            assert "Test Merchant" in mappings
            assert mappings["Test Merchant"] == "test-category-id"

    @pytest.mark.asyncio
    async def test_update_payee_category_mapping_new(self, category_service, test_db_session):
        """Test creating new payee category mapping."""
        with patch('database.connection.db_manager.get_session') as mock_session:
            mock_session.return_value.__aenter__.return_value = test_db_session

            await category_service.update_payee_category_mapping(
                "New Merchant",
                "new-category-id",
                "New Category"
            )

            # Verify mapping was created
            from sqlalchemy import select
            stmt = select(PayeeCategoryMapping).where(
                PayeeCategoryMapping.payee_name == "New Merchant"
            )
            result = await test_db_session.execute(stmt)
            mapping = result.scalar_one_or_none()

            assert mapping is not None
            assert mapping.category_id == "new-category-id"
            assert mapping.category_name == "New Category"
            assert mapping.transaction_count == 1

    @pytest.mark.asyncio
    async def test_update_payee_category_mapping_existing(self, category_service, test_db_session):
        """Test updating existing payee category mapping."""
        # Setup existing mapping
        mapping = PayeeCategoryMapping(
            payee_name="Test Merchant",
            category_id="old-category-id",
            category_name="Old Category",
            transaction_count=1
        )
        test_db_session.add(mapping)
        await test_db_session.commit()

        with patch('database.connection.db_manager.get_session') as mock_session:
            mock_session.return_value.__aenter__.return_value = test_db_session

            await category_service.update_payee_category_mapping(
                "Test Merchant",
                "new-category-id",
                "New Category"
            )

            # Verify mapping was updated
            from sqlalchemy import select
            stmt = select(PayeeCategoryMapping).where(
                PayeeCategoryMapping.payee_name == "Test Merchant"
            )
            result = await test_db_session.execute(stmt)
            updated_mapping = result.scalar_one_or_none()

            assert updated_mapping is not None
            assert updated_mapping.category_id == "new-category-id"
            assert updated_mapping.category_name == "New Category"
            assert updated_mapping.transaction_count == 2

    @pytest.mark.asyncio
    async def test_record_processed_transaction(self, category_service, test_db_session):
        """Test recording processed transaction."""
        with patch('database.connection.db_manager.get_session') as mock_session:
            mock_session.return_value.__aenter__.return_value = test_db_session

            await category_service.record_processed_transaction(
                up_transaction_id="test-tx-id",
                ynab_transaction_id="test-ynab-tx-id",
                payee_name="Test Merchant",
                amount=-12500,
                transaction_date="2024-01-01",
                status="processed"
            )

            # Verify transaction was recorded
            from sqlalchemy import select
            stmt = select(ProcessedTransaction).where(
                ProcessedTransaction.up_transaction_id == "test-tx-id"
            )
            result = await test_db_session.execute(stmt)
            processed_tx = result.scalar_one_or_none()

            assert processed_tx is not None
            assert processed_tx.ynab_transaction_id == "test-ynab-tx-id"
            assert processed_tx.payee_name == "Test Merchant"
            assert processed_tx.amount == -12500
            assert processed_tx.status == "processed"

    @pytest.mark.asyncio
    async def test_record_processed_transaction_failed(self, category_service, test_db_session):
        """Test recording failed transaction with error message."""
        with patch('database.connection.db_manager.get_session') as mock_session:
            mock_session.return_value.__aenter__.return_value = test_db_session

            await category_service.record_processed_transaction(
                up_transaction_id="failed-tx-id",
                ynab_transaction_id=None,
                payee_name="Test Merchant",
                amount=-12500,
                transaction_date="2024-01-01",
                status="failed",
                error_message="API error occurred"
            )

            # Verify transaction was recorded with error
            from sqlalchemy import select
            stmt = select(ProcessedTransaction).where(
                ProcessedTransaction.up_transaction_id == "failed-tx-id"
            )
            result = await test_db_session.execute(stmt)
            processed_tx = result.scalar_one_or_none()

            assert processed_tx is not None
            assert processed_tx.ynab_transaction_id is None
            assert processed_tx.status == "failed"
            assert processed_tx.error_message == "API error occurred"

    @pytest.mark.asyncio
    async def test_is_transaction_processed_true(self, category_service, test_db_session):
        """Test checking if transaction is processed - exists."""
        # Setup existing processed transaction
        processed_tx = ProcessedTransaction(
            up_transaction_id="processed-tx-id",
            ynab_transaction_id="ynab-tx-id",
            payee_name="Test Merchant",
            amount=-12500,
            transaction_date="2024-01-01",
            status="processed"
        )
        test_db_session.add(processed_tx)
        await test_db_session.commit()

        with patch('database.connection.db_manager.get_session') as mock_session:
            mock_session.return_value.__aenter__.return_value = test_db_session

            is_processed = await category_service.is_transaction_processed("processed-tx-id")

            assert is_processed is True

    @pytest.mark.asyncio
    async def test_is_transaction_processed_false(self, category_service, test_db_session):
        """Test checking if transaction is processed - doesn't exist."""
        with patch('database.connection.db_manager.get_session') as mock_session:
            mock_session.return_value.__aenter__.return_value = test_db_session

            is_processed = await category_service.is_transaction_processed("new-tx-id")

            assert is_processed is False

    @pytest.mark.asyncio
    async def test_is_transaction_processed_error_handling(self, category_service):
        """Test error handling in transaction processed check."""
        with patch('database.connection.db_manager.get_session') as mock_session:
            mock_session.return_value.__aenter__.return_value.execute.side_effect = Exception("DB Error")

            # Should return False on error (err on side of caution)
            is_processed = await category_service.is_transaction_processed("test-tx-id")

            assert is_processed is False