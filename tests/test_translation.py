import pytest

from forwarding.budget_index import LegacyIndex
from forwarding.translation import Skip, create_import_id, translate
from models.up_models import UpTransaction
from utils.filters import TransactionFilter


@pytest.fixture
def up_transaction(sample_up_transaction_data):
    return UpTransaction(**sample_up_transaction_data["data"])


def index(mappings=None):
    return LegacyIndex("acct-1", mappings or {}, TransactionFilter(["Transfer to "]))


def test_translates_all_fields(up_transaction):
    result = translate(up_transaction, index())

    assert result.account_id == "acct-1"
    assert result.payee_name == "Test Merchant"
    assert result.category_id is None
    assert result.memo == "Test Purchase"
    assert result.amount == -12500
    assert result.date == "2024-01-01"
    assert result.import_id == "up_test-transaction-id"


def test_mapped_payee_gets_category(up_transaction):
    result = translate(up_transaction, index({"Test Merchant": "cat-1"}))

    assert result.category_id == "cat-1"


def test_internal_transfer_is_skipped(sample_up_transaction_data):
    data = sample_up_transaction_data["data"]
    data["attributes"]["description"] = "Transfer to Savings"

    result = translate(UpTransaction(**data), index())

    assert result == Skip("Internal transfer detected")


def test_uuid_is_used_unchanged():
    uuid = "01234567-89ab-cdef-0123-456789abcdef"

    assert create_import_id(uuid) == uuid


def test_short_id_gets_prefix():
    assert create_import_id("abc") == "up_abc"


def test_long_id_is_hashed_to_36_chars():
    result = create_import_id("x" * 60)

    assert len(result) == 36
    assert not result.startswith("up_")
