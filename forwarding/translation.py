import hashlib
from dataclasses import dataclass

from forwarding.budget_index import LegacyIndex
from models.up_models import UpTransaction
from models.ynab_models import YnabTransactionDetail


@dataclass(frozen=True)
class Skip:
    """The transaction should not be forwarded."""

    reason: str


def create_import_id(up_transaction_id: str) -> str:
    """Create a unique import ID for YNAB (max 36 characters)."""
    # For UUIDs (36 chars), just use the UUID without prefix to stay within
    # limit
    if len(up_transaction_id) == 36 and "-" in up_transaction_id:
        return up_transaction_id

    # For shorter IDs, add "up_" prefix if it fits
    prefixed_id = f"up_{up_transaction_id}"
    if len(prefixed_id) <= 36:
        return prefixed_id

    # For longer IDs, use a hash to ensure uniqueness while staying under
    # limit
    hash_hex = hashlib.sha256(up_transaction_id.encode()).hexdigest()
    return hash_hex[:36]  # Use first 36 characters of hash


def translate(tx: UpTransaction, index: LegacyIndex) -> YnabTransactionDetail | Skip:
    """Turn an Up transaction into a YNAB transaction, or say to skip it."""
    if not index.transfer_filter.should_process_transaction(tx):
        return Skip(index.transfer_filter.get_filtered_reason(tx))
    return YnabTransactionDetail(
        account_id=index.account_id,
        payee_name=tx.payee,
        category_id=index.category_by_payee.get(tx.payee),
        memo=tx.attributes.raw_text or tx.payee,
        amount=tx.amount_milliunits,
        date=tx.date,
        import_id=create_import_id(tx.id),
    )
