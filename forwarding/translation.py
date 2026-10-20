from dataclasses import dataclass

from forwarding.budget_index import BudgetIndex, YnabAccountRef
from models.up_models import UpTransaction
from models.ynab_models import YnabTransactionDetail
from utils.filters import TransactionFilter

_TRANSFER_FILTER = TransactionFilter()  # ticket 10 deletes


@dataclass(frozen=True)
class Skip:
    """The transaction should not be forwarded."""

    reason: str


def cleared_status(up_transaction: UpTransaction) -> str:
    """The single place cleared is decided (#111 changes only this)."""
    return "uncleared"


def _memo(tx: UpTransaction) -> str | None:
    a = tx.attributes
    if a.message:
        return a.message
    if a.raw_text and a.raw_text != a.description:
        return a.raw_text
    return None


def _date(tx: UpTransaction) -> str:
    # createdAt in its own offset; never settledAt
    return tx.attributes.created_at.date().isoformat()


def translate(tx: UpTransaction, index: BudgetIndex) -> YnabTransactionDetail | Skip:
    """Turn an Up transaction into a YNAB transaction, or say to skip it."""
    target = index.account(tx.account_id)
    if not isinstance(target, YnabAccountRef):
        return Skip("Up account not in YNAB")
    if not _TRANSFER_FILTER.should_process_transaction(tx):
        return Skip(_TRANSFER_FILTER.get_filtered_reason(tx))
    return YnabTransactionDetail(
        account_id=target.id,
        payee_name=tx.payee,
        category_id=index.category_match(tx.payee),
        memo=_memo(tx),
        amount=tx.amount_milliunits,
        date=_date(tx),
        cleared=cleared_status(tx),
        import_id=tx.id,
    )
