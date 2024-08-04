from dataclasses import dataclass
from typing import Optional, List

@dataclass
class Subtransaction:
    id: str
    transaction_id: str
    amount: int
    memo: Optional[str]
    payee_id: Optional[str]
    payee_name: Optional[str]
    category_id: Optional[str]
    category_name: Optional[str]
    transfer_account_id: Optional[str]
    transfer_transaction_id: Optional[str]
    deleted: bool

@dataclass
class Transaction:
    id: str
    date: str
    amount: int
    memo: Optional[str]
    cleared: str
    approved: bool
    flag_color: Optional[str]
    flag_name: Optional[str]
    account_id: str
    payee_id: Optional[str]
    category_id: Optional[str]
    transfer_account_id: Optional[str]
    transfer_transaction_id: Optional[str]
    matched_transaction_id: Optional[str]
    import_id: Optional[str]
    import_payee_name: Optional[str]
    import_payee_name_original: Optional[str]
    debt_transaction_type: Optional[str]
    deleted: bool
    account_name: Optional[str]
    payee_name: Optional[str]
    category_name: Optional[str]
    subtransactions: List[Subtransaction]

@dataclass
class Data:
    transaction: Transaction

@dataclass
class YNAB:
    data: Data
