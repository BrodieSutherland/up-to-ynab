from models.up_models import UpTransaction

INTERNAL_TRANSFER_STRINGS = (
    "Transfer to ",
    "Cover to ",
    "Quick save transfer to ",
    "Forward to ",
)


class TransactionFilter:
    """Filter transactions based on various criteria."""

    def __init__(self, internal_transfer_strings=INTERNAL_TRANSFER_STRINGS):
        self.internal_transfer_strings = internal_transfer_strings

    def is_internal_transfer(self, transaction: UpTransaction) -> bool:
        """Check if transaction matches internal transfer patterns."""
        payee = transaction.payee

        for transfer_string in self.internal_transfer_strings:
            if transfer_string in payee:
                return True

        return False

    def should_process_transaction(self, transaction: UpTransaction) -> bool:
        """Determine if a transaction should be processed and sent to YNAB."""
        # Filter out internal transfers
        if self.is_internal_transfer(transaction):
            return False

        # Other filters?

        return True

    def get_filtered_reason(self, transaction: UpTransaction) -> str:
        """Get the reason why a transaction was filtered out."""
        if self.is_internal_transfer(transaction):
            return "Internal transfer detected"

        return "Unknown filter reason"
