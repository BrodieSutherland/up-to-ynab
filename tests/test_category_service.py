import pytest
from sqlalchemy import select

from database.connection import DatabaseManager
from database.models import PayeeCategoryMapping, ProcessedTransaction
from services.category_service import CategoryService


class TestCategoryService:
    """Test cases for Category service."""

    @pytest.fixture
    def category_service(self, services):
        """Real CategoryService over the in-memory database."""
        return services.transactions.category_service

    @pytest.mark.asyncio
    async def test_sync_categories_from_ynab(self, category_service):
        """Sync completes without touching YNAB (history analysis is a TODO)."""
        await category_service.sync_categories_from_ynab()

    @pytest.mark.asyncio
    async def test_get_payee_category_mappings(self, category_service, database):
        """Test retrieving payee category mappings."""
        async with database.get_session() as session:
            session.add(
                PayeeCategoryMapping(
                    payee_name="Test Merchant",
                    category_id="test-category-id",
                    category_name="Test Category",
                )
            )

        mappings = await category_service.get_payee_category_mappings()

        assert mappings == {"Test Merchant": "test-category-id"}

    @pytest.mark.asyncio
    async def test_update_payee_category_mapping_new(self, category_service, database):
        """Test creating new payee category mapping."""
        await category_service.update_payee_category_mapping(
            "New Merchant", "new-category-id", "New Category"
        )

        async with database.get_session() as session:
            result = await session.execute(
                select(PayeeCategoryMapping).where(
                    PayeeCategoryMapping.payee_name == "New Merchant"
                )
            )
            mapping = result.scalar_one_or_none()

        assert mapping is not None
        assert mapping.category_id == "new-category-id"
        assert mapping.category_name == "New Category"
        assert mapping.transaction_count == 1

    @pytest.mark.asyncio
    async def test_update_payee_category_mapping_existing(
        self, category_service, database
    ):
        """Test updating existing payee category mapping."""
        async with database.get_session() as session:
            session.add(
                PayeeCategoryMapping(
                    payee_name="Test Merchant",
                    category_id="old-category-id",
                    category_name="Old Category",
                    transaction_count=1,
                )
            )

        await category_service.update_payee_category_mapping(
            "Test Merchant", "new-category-id", "New Category"
        )

        async with database.get_session() as session:
            result = await session.execute(
                select(PayeeCategoryMapping).where(
                    PayeeCategoryMapping.payee_name == "Test Merchant"
                )
            )
            updated = result.scalar_one_or_none()

        assert updated is not None
        assert updated.category_id == "new-category-id"
        assert updated.category_name == "New Category"
        assert updated.transaction_count == 2

    @pytest.mark.asyncio
    async def test_record_processed_transaction(self, category_service, database):
        """Test recording processed transaction."""
        await category_service.record_processed_transaction(
            up_transaction_id="test-tx-id",
            ynab_transaction_id="test-ynab-tx-id",
            payee_name="Test Merchant",
            amount=-12500,
            transaction_date="2024-01-01",
            status="processed",
        )

        async with database.get_session() as session:
            result = await session.execute(
                select(ProcessedTransaction).where(
                    ProcessedTransaction.up_transaction_id == "test-tx-id"
                )
            )
            processed_tx = result.scalar_one_or_none()

        assert processed_tx is not None
        assert processed_tx.ynab_transaction_id == "test-ynab-tx-id"
        assert processed_tx.payee_name == "Test Merchant"
        assert processed_tx.amount == -12500
        assert processed_tx.status == "processed"

    @pytest.mark.asyncio
    async def test_record_processed_transaction_failed(
        self, category_service, database
    ):
        """Test recording failed transaction with error message."""
        await category_service.record_processed_transaction(
            up_transaction_id="failed-tx-id",
            ynab_transaction_id=None,
            payee_name="Test Merchant",
            amount=-12500,
            transaction_date="2024-01-01",
            status="failed",
            error_message="API error occurred",
        )

        async with database.get_session() as session:
            result = await session.execute(
                select(ProcessedTransaction).where(
                    ProcessedTransaction.up_transaction_id == "failed-tx-id"
                )
            )
            processed_tx = result.scalar_one_or_none()

        assert processed_tx is not None
        assert processed_tx.ynab_transaction_id is None
        assert processed_tx.status == "failed"
        assert processed_tx.error_message == "API error occurred"

    @pytest.mark.asyncio
    async def test_is_transaction_processed_true(self, category_service, database):
        """Test checking if transaction is processed - exists."""
        async with database.get_session() as session:
            session.add(
                ProcessedTransaction(
                    up_transaction_id="processed-tx-id",
                    ynab_transaction_id="ynab-tx-id",
                    payee_name="Test Merchant",
                    amount=-12500,
                    transaction_date="2024-01-01",
                    status="processed",
                )
            )

        assert await category_service.is_transaction_processed("processed-tx-id")

    @pytest.mark.asyncio
    async def test_is_transaction_processed_false(self, category_service):
        """Test checking if transaction is processed - doesn't exist."""
        assert await category_service.is_transaction_processed("new-tx-id") is False

    @pytest.mark.asyncio
    async def test_is_transaction_processed_error_handling(self, test_settings):
        """A real database error (no tables) returns False."""
        broken = DatabaseManager(test_settings.database_url)
        try:
            service = CategoryService(broken.get_session)

            assert await service.is_transaction_processed("test-tx-id") is False
        finally:
            await broken.close()
