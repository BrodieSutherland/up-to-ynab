from unittest.mock import patch

import pytest

from models.up_models import UpTransaction
from utils.filters import TransactionFilter


class TestTransactionFilter:
    """Test cases for transaction filtering."""

    @pytest.fixture
    def transaction_filter(self, test_settings):
        """Create TransactionFilter instance with test settings."""
        with patch("utils.filters.get_settings", return_value=test_settings):
            return TransactionFilter()

    @pytest.fixture
    def sample_up_transaction(self, sample_up_transaction_data):
        """Create sample UpTransaction for testing."""
        return UpTransaction(**sample_up_transaction_data["data"])

    def test_is_internal_transfer_true(
        self, transaction_filter, sample_up_transaction_data
    ):
        """Test internal transfer detection - should be filtered."""
        # Modify transaction to have transfer description
        transaction_data = sample_up_transaction_data.copy()
        transaction_data["data"]["attributes"][
            "description"
        ] = "Transfer to Savings Account"

        transaction = UpTransaction(**transaction_data["data"])

        is_transfer = transaction_filter.is_internal_transfer(transaction)

        assert is_transfer is True

    def test_is_internal_transfer_false(
        self, transaction_filter, sample_up_transaction
    ):
        """Test internal transfer detection - normal transaction."""
        is_transfer = transaction_filter.is_internal_transfer(
            sample_up_transaction
        )

        assert is_transfer is False

    def test_is_internal_transfer_cover(
        self, transaction_filter, sample_up_transaction_data
    ):
        """Test internal transfer detection - cover transfer."""
        # Modify transaction to have cover description
        transaction_data = sample_up_transaction_data.copy()
        transaction_data["data"]["attributes"][
            "description"
        ] = "Cover to Emergency Fund"

        transaction = UpTransaction(**transaction_data["data"])

        is_transfer = transaction_filter.is_internal_transfer(transaction)

        assert is_transfer is True

    def test_is_internal_transfer_quick_save(
        self, transaction_filter, sample_up_transaction_data
    ):
        """Test internal transfer detection - quick save transfer."""
        # Modify transaction to have quick save description
        transaction_data = sample_up_transaction_data.copy()
        transaction_data["data"]["attributes"][
            "description"
        ] = "Quick save transfer to Goal Account"

        transaction = UpTransaction(**transaction_data["data"])

        is_transfer = transaction_filter.is_internal_transfer(transaction)

        assert is_transfer is True

    def test_is_internal_transfer_forward(
        self, transaction_filter, sample_up_transaction_data
    ):
        """Test internal transfer detection - forward transfer."""
        # Modify transaction to have forward description
        transaction_data = sample_up_transaction_data.copy()
        transaction_data["data"]["attributes"][
            "description"
        ] = "Forward to Investment Account"

        transaction = UpTransaction(**transaction_data["data"])

        is_transfer = transaction_filter.is_internal_transfer(transaction)

        assert is_transfer is True

    def test_is_internal_transfer_partial_match(
        self, transaction_filter, sample_up_transaction_data
    ):
        """Test internal transfer detection - partial string match."""
        # Test that it doesn't match if string is not contained
        transaction_data = sample_up_transaction_data.copy()
        transaction_data["data"]["attributes"][
            "description"
        ] = "Transfer ABC Corp"  # "Transfer" not followed by " to "

        transaction = UpTransaction(**transaction_data["data"])

        is_transfer = transaction_filter.is_internal_transfer(transaction)

        assert is_transfer is False

    def test_should_process_transaction_true(
        self, transaction_filter, sample_up_transaction
    ):
        """Test should process transaction - normal transaction."""
        should_process = transaction_filter.should_process_transaction(
            sample_up_transaction
        )

        assert should_process is True

    def test_should_process_transaction_false_transfer(
        self, transaction_filter, sample_up_transaction_data
    ):
        """Test internal transfer filtering in transaction processing."""
        # Modify transaction to be internal transfer
        transaction_data = sample_up_transaction_data.copy()
        attrs = transaction_data["data"]["attributes"]
        attrs["description"] = "Transfer to Savings"

        transaction = UpTransaction(**transaction_data["data"])

        should_process = transaction_filter.should_process_transaction(
            transaction
        )

        assert should_process is False

    def test_get_filtered_reason_internal_transfer(
        self, transaction_filter, sample_up_transaction_data
    ):
        """Test getting filtered reason for internal transfer."""
        # Modify transaction to be internal transfer
        transaction_data = sample_up_transaction_data.copy()
        transaction_data["data"]["attributes"][
            "description"
        ] = "Transfer to Savings"

        transaction = UpTransaction(**transaction_data["data"])

        reason = transaction_filter.get_filtered_reason(transaction)

        assert reason == "Internal transfer detected"

    def test_get_filtered_reason_unknown(
        self, transaction_filter, sample_up_transaction
    ):
        """Test getting filtered reason for unknown case."""
        # This shouldn't happen in normal flow but test for completeness
        reason = transaction_filter.get_filtered_reason(sample_up_transaction)

        assert reason == "Unknown filter reason"
