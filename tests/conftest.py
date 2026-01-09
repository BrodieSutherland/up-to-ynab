import asyncio
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app import create_app
from database.models import Base
from utils.config import Settings

# Test database URL
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def test_settings() -> Settings:
    """Create test settings with mock values."""
    return Settings(
        port=5001,
        debug_mode=True,
        up_api_token="test_up_token",
        up_base_url="https://api.up.com.au/api/v1/",
        webhook_url="https://test.example.com/webhook",
        ynab_api_token="test_ynab_token",
        ynab_budget_id="test_budget_id",
        ynab_account_id="test_account_id",
        ynab_base_url="https://api.youneedabudget.com/v1/",
        database_url=TEST_DATABASE_URL,
        internal_transfer_strings=[
            "Transfer to ",
            "Cover to ",
            "Quick save transfer to ",
            "Forward to ",
        ],
    )


@pytest_asyncio.fixture
async def test_db_engine():
    """Create a test database engine."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture
async def test_db_session(
    test_db_engine,
) -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session."""
    async_session = async_sessionmaker(
        test_db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    app = create_app()
    return TestClient(app)


@pytest.fixture
def mock_httpx_client():
    """Create a mock httpx client for testing API calls."""
    return AsyncMock()


# Sample test data fixtures
@pytest.fixture
def sample_up_transaction_data():
    """Sample Up transaction data for testing."""
    return {
        "data": {
            "type": "transactions",
            "id": "test-transaction-id",
            "attributes": {
                "status": "SETTLED",
                "rawText": "Test Purchase",
                "description": "Test Merchant",
                "message": None,
                "isCategorizable": True,
                "holdInfo": None,
                "roundUp": None,
                "cashback": None,
                "amount": {
                    "currencyCode": "AUD",
                    "value": "-12.50",
                    "valueInBaseUnits": -1250,
                },
                "foreignAmount": None,
                "currencyConversionFee": None,
                "settledAt": "2024-01-01T12:00:00+00:00",
                "createdAt": "2024-01-01T12:00:00+00:00",
            },
            "relationships": {
                "account": {
                    "data": {"type": "accounts", "id": "test-account-id"}
                },
                "category": None,
                "parentCategory": None,
                "tags": None,
                "attachment": None,
                "transferAccount": None,
            },
        }
    }


@pytest.fixture
def sample_up_webhook_event_data():
    """Sample Up webhook event data for testing."""
    return {
        "data": {
            "type": "webhook-events",
            "id": "test-webhook-event-id",
            "attributes": {
                "eventType": "TRANSACTION_CREATED",
                "createdAt": "2024-01-01T12:00:00+00:00",
            },
            "relationships": {
                "transaction": {
                    "data": {
                        "type": "transactions",
                        "id": "test-transaction-id",
                    }
                }
            },
        }
    }


@pytest.fixture
def sample_ynab_transaction_response():
    """Sample YNAB transaction response for testing."""
    return {
        "data": {
            "transaction": {
                "id": "test-ynab-transaction-id",
                "date": "2024-01-01",
                "amount": -12500,
                "memo": "Test Purchase",
                "cleared": "cleared",
                "approved": True,
                "flag_color": None,
                "account_id": "test-account-id",
                "payee_id": None,
                "category_id": None,
                "transfer_account_id": None,
                "transfer_transaction_id": None,
                "matched_transaction_id": None,
                "import_id": "up_test-transaction-id",
                "import_payee_name": "Test Merchant",
                "import_payee_name_original": None,
                "debt_transaction_type": None,
                "deleted": False,
            }
        }
    }


@pytest.fixture
def sample_ynab_budget_data():
    """Sample YNAB budget data for testing."""
    return {
        "data": {
            "budget": {
                "id": "test-budget-id",
                "name": "Test Budget",
                "last_modified_on": "2024-01-01T12:00:00+00:00",
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
                "categories": [
                    {
                        "id": "test-category-id",
                        "name": "Test Category",
                        "category_group_id": "test-category-group-id",
                        "hidden": False,
                        "original_category_group_id": None,
                        "note": None,
                        "budgeted": 0,
                        "activity": 0,
                        "balance": 0,
                        "goal_type": None,
                        "goal_day": None,
                        "goal_cadence": None,
                        "goal_cadence_frequency": None,
                        "goal_creation_month": None,
                        "goal_target": None,
                        "goal_target_month": None,
                        "goal_percentage_complete": None,
                        "goal_months_to_budget": None,
                        "goal_under_funded": None,
                        "goal_overall_funded": None,
                        "goal_overall_left": None,
                        "deleted": False,
                    }
                ],
                "category_groups": [
                    {
                        "id": "test-category-group-id",
                        "name": "Test Category Group",
                        "hidden": False,
                        "deleted": False,
                    }
                ],
            }
        }
    }
