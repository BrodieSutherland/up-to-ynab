from typing import AsyncGenerator

import pytest
import pytest_asyncio

from app import Services, build_services
from database.connection import DatabaseManager
from models.up_models import UpTransaction
from tests.fakes.up import FakeUpClient, up_account
from tests.fakes.ynab import FakeYnabClient, ynab_account
from utils.config import Settings

# Test database URL
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
def test_settings() -> Settings:
    """Create test settings with mock values."""
    return Settings(
        _env_file=None,
        port=5001,
        debug_mode=True,
        up_api_token="test_up_token",
        up_base_url="https://api.up.com.au/api/v1/",
        webhook_url="https://test.example.com/webhook",
        ynab_api_token="test_ynab_token",
        ynab_budget_id="test_budget_id",
        ynab_base_url="https://api.youneedabudget.com/v1/",
        database_url=TEST_DATABASE_URL,
    )


@pytest_asyncio.fixture
async def database(
    test_settings: Settings,
) -> AsyncGenerator[DatabaseManager, None]:
    """In-memory database with tables created."""
    manager = DatabaseManager(test_settings.database_url)
    await manager.create_tables()
    yield manager
    await manager.close()


@pytest.fixture
def fake_up(sample_up_transaction_data) -> FakeUpClient:
    """Fake Up holding the sample transaction under its id."""
    transaction = UpTransaction(**sample_up_transaction_data["data"])
    return FakeUpClient(
        transactions={"test-transaction-id": transaction},
        accounts=[up_account("test-account-id", "Spending")],
    )


@pytest.fixture
def fake_ynab() -> FakeYnabClient:
    return FakeYnabClient(accounts=[ynab_account("ynab-acct-1", "Spending")])


@pytest.fixture
def services(
    test_settings: Settings,
    database: DatabaseManager,
    fake_up: FakeUpClient,
    fake_ynab: FakeYnabClient,
) -> Services:
    """Real services over the in-memory database and fake Up/YNAB clients."""
    return build_services(test_settings, database, fake_up, fake_ynab)


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
                "account": {"data": {"type": "accounts", "id": "test-account-id"}},
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
