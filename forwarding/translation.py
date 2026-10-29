from dataclasses import dataclass

from forwarding.budget_index import BudgetIndex, YnabAccountRef
from models.up_models import UpTransaction
from models.ynab_models import YnabTransactionDetail

ROUND_UP = "Round Up"
ACCOUNT_NOT_IN_YNAB = "account_not_in_ynab"
MIRROR_SIDE = "mirror_side"


@dataclass(frozen=True)
class Skip:
    """The transaction should not be forwarded."""

    reason: str
    code: str


def cleared_status(up_transaction: UpTransaction) -> str:
    """The single place cleared is decided: settled is cleared, a hold is not."""
    return "cleared" if up_transaction.attributes.status == "SETTLED" else "uncleared"


def _memo(tx: UpTransaction) -> str | None:
    a = tx.attributes
    if a.message:
        return a.message
    if a.raw_text and a.raw_text != a.description:
        return a.raw_text
    return None


def ynab_date(tx: UpTransaction) -> str:
    """The YNAB date of a transaction."""
    # createdAt in its own offset; never settledAt
    return tx.attributes.created_at.date().isoformat()


def _is_round_up(tx: UpTransaction) -> bool:
    """The Saver's "Round Up" half: exact description and money in."""
    return tx.attributes.description == ROUND_UP and tx.amount_milliunits > 0


def translate(
    tx: UpTransaction, index: BudgetIndex, transfers: bool = True
) -> YnabTransactionDetail | Skip:
    """Turn an Up transaction into a YNAB transaction, or say to skip it.

    A Transfer whose two accounts are both in YNAB is forwarded once, from the
    Originating side (money left: amount <= 0) as a YNAB transfer; the Mirror
    side is skipped. A Round Up is forwarded the same way. If the other account
    is not in YNAB, each half is an ordinary transaction. With `transfers=False`
    every transaction is ordinary (never a YNAB transfer, never a Mirror skip).
    """
    target = index.account(tx.account_id)
    if not isinstance(target, YnabAccountRef):
        return Skip("Up account not in YNAB", ACCOUNT_NOT_IN_YNAB)
    other_id = tx.transfer_account_id
    other = index.account(other_id) if other_id and transfers else None
    if isinstance(other, YnabAccountRef):
        if tx.amount_milliunits > 0 and not _is_round_up(tx):
            return Skip("Mirror side of a Transfer", MIRROR_SIDE)
        return YnabTransactionDetail(
            account_id=target.id,
            payee_id=other.transfer_payee_id,
            payee_name=None,
            category_id=None,
            memo=_memo(tx),
            amount=tx.amount_milliunits,
            date=ynab_date(tx),
            cleared=cleared_status(tx),
            import_id=tx.id,
        )
    return YnabTransactionDetail(
        account_id=target.id,
        payee_name=tx.payee,
        category_id=index.category_match(tx.payee),
        memo=_memo(tx),
        amount=tx.amount_milliunits,
        date=ynab_date(tx),
        cleared=cleared_status(tx),
        import_id=tx.id,
    )
