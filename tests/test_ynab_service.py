from unittest.mock import AsyncMock, patch

import httpx
import pytest

from models.up_models import UpTransaction
from models.ynab_models import YnabBudget, YnabTransactionResponse
from services.ynab_service import YnabService


class TestYnabService:
    """Test cases for YNAB service."""

    @pytest.fixture
    def ynab_service(self, test_settings):
        """Create YnabService instance with test settings."""
        with patch("services.ynab_service.get_settings", return_value=test_settings):
            return YnabService()

    @pytest.fixture
    def sample_up_transaction(self, sample_up_transaction_data):
        """Create sample UpTransaction for testing."""
        return UpTransaction(**sample_up_transaction_data["data"])

    @pytest.mark.asyncio
    async def test_create_transaction_success(
        self, ynab_service, sample_up_transaction, sample_ynab_transaction_response
    ):
        """Test successful transaction creation in YNAB."""
        mock_response = AsyncMock()
        mock_response.json.return_value = sample_ynab_transaction_response
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = (
                mock_response
            )

            result = await ynab_service.create_transaction(sample_up_transaction)

            assert result is not None
            assert result.id == "test-ynab-transaction-id"
            assert result.import_id == "up_test-transaction-id"

    @pytest.mark.asyncio
    async def test_create_transaction_with_category(
        self, ynab_service, sample_up_transaction, sample_ynab_transaction_response
    ):
        """Test transaction creation with category assignment."""
        # Modify response to include category
        response_data = sample_ynab_transaction_response.copy()
        response_data["data"]["transaction"]["category_id"] = "test-category-id"

        mock_response = AsyncMock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = (
                mock_response
            )

            result = await ynab_service.create_transaction(
                sample_up_transaction, category_id="test-category-id"
            )

            assert result is not None
            assert result.category_id == "test-category-id"

    @pytest.mark.asyncio
    async def test_create_transaction_http_error(
        self, ynab_service, sample_up_transaction
    ):
        """Test transaction creation with HTTP error."""
        mock_response = AsyncMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=AsyncMock(), response=mock_response
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = (
                mock_response
            )

            result = await ynab_service.create_transaction(sample_up_transaction)

            assert result is None

    @pytest.mark.asyncio
    async def test_get_budget_success(self, ynab_service, sample_ynab_budget_data):
        """Test successful budget retrieval."""
        mock_response = AsyncMock()
        mock_response.json.return_value = sample_ynab_budget_data
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get.return_value = (
                mock_response
            )

            budget = await ynab_service.get_budget()

            assert budget is not None
            assert budget.id == "test-budget-id"
            assert budget.name == "Test Budget"
            assert len(budget.category_groups) == 1

    @pytest.mark.asyncio
    async def test_get_budget_http_error(self, ynab_service):
        """Test budget retrieval with HTTP error."""
        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=AsyncMock(), response=mock_response
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get.return_value = (
                mock_response
            )

            budget = await ynab_service.get_budget()

            assert budget is None

    @pytest.mark.asyncio
    async def test_get_categories(self, ynab_service, sample_ynab_budget_data):
        """Test category retrieval from budget."""
        mock_response = AsyncMock()
        mock_response.json.return_value = sample_ynab_budget_data
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get.return_value = (
                mock_response
            )

            categories = await ynab_service.get_categories()

            assert len(categories) == 1
            assert categories[0].id == "test-category-id"
            assert categories[0].name == "Test Category"

    @pytest.mark.asyncio
    async def test_get_categories_no_budget(self, ynab_service):
        """Test category retrieval when budget fetch fails."""
        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=AsyncMock(), response=mock_response
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get.return_value = (
                mock_response
            )

            categories = await ynab_service.get_categories()

            assert len(categories) == 0

    @pytest.mark.asyncio
    async def test_get_payees(self, ynab_service, sample_ynab_budget_data):
        """Test payee retrieval from budget."""
        # Add sample payees to budget data
        budget_data = sample_ynab_budget_data.copy()
        budget_data["data"]["budget"]["payees"] = [
            {
                "id": "test-payee-id",
                "name": "Test Payee",
                "transfer_account_id": None,
                "deleted": False,
            }
        ]

        mock_response = AsyncMock()
        mock_response.json.return_value = budget_data
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get.return_value = (
                mock_response
            )

            payees = await ynab_service.get_payees()

            assert len(payees) == 1
            assert payees[0].id == "test-payee-id"
            assert payees[0].name == "Test Payee"

    @pytest.mark.asyncio
    async def test_find_category_for_payee_found(self, ynab_service):
        """Test finding category for payee - mapping exists."""
        payee_mappings = {"Test Merchant": "test-category-id"}

        category_id = await ynab_service.find_category_for_payee(
            "Test Merchant", payee_mappings
        )

        assert category_id == "test-category-id"

    @pytest.mark.asyncio
    async def test_find_category_for_payee_not_found(self, ynab_service):
        """Test finding category for payee - no mapping."""
        payee_mappings = {"Other Merchant": "other-category-id"}

        category_id = await ynab_service.find_category_for_payee(
            "Test Merchant", payee_mappings
        )

        assert category_id is None

    def test_create_import_id(self, ynab_service):
        """Test import ID creation."""
        # Test short ID gets prefix
        import_id = ynab_service.create_import_id("test-transaction-id")
        assert import_id == "up_test-transaction-id"

        # Test UUID gets used directly (36 chars)
        uuid_id = "384b3858-66bd-4721-a535-8def2d36da97"
        import_id_uuid = ynab_service.create_import_id(uuid_id)
        assert import_id_uuid == uuid_id
        assert len(import_id_uuid) == 36

        # Test long ID gets hashed
        long_id = "very-very-long-transaction-id-that-exceeds-the-limit"
        import_id_long = ynab_service.create_import_id(long_id)
        assert len(import_id_long) == 36
        assert import_id_long != long_id  # Should be hashed
