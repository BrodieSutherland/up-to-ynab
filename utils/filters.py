from typing import List

from models.up_models import UpTransaction
from utils.config import get_settings


class TransactionFilter:
    """Filter transactions based on various criteria."""

    def __init__(self):
        self.settings = get_settings()

    def is_internal_transfer(self, transaction: UpTransaction) -> bool:
        """Check if transaction matches internal transfer patterns."""
        payee = transaction.payee

        for transfer_string in self.settings.internal_transfer_strings:
            if transfer_string in payee:
                return True

        return False

    def should_process_transaction(self, transaction: UpTransaction) -> bool:
        """Determine if a transaction should be processed and sent to YNAB."""
        # Filter out internal transfers
        if self.is_internal_transfer(transaction):
            return False

        # Could add more filters here (e.g., amount thresholds, account types, etc.)

        return True

    def get_filtered_reason(self, transaction: UpTransaction) -> str:
        """Get the reason why a transaction was filtered out."""
        if self.is_internal_transfer(transaction):
            return "Internal transfer detected"

        return "Unknown filter reason"
