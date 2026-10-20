import pytest
from sqlalchemy import select

from database.models import PayeeCategoryMapping
from services.category_service import CategoryService


class TestCategoryService:
    """Test cases for Category service."""

    @pytest.fixture
    def category_service(self, database):
        """Real CategoryService over the in-memory database."""
        return CategoryService(database.get_session)

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
