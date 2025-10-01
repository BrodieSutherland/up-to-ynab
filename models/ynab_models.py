from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class YnabTransactionDetail(BaseModel):
    """YNAB transaction detail for creation."""

    account_id: str
    payee_name: Optional[str] = None
    category_id: Optional[str] = None
    memo: Optional[str] = None
    amount: int  # In milliunits
    date: str  # YYYY-MM-DD format
    cleared: str = "cleared"  # cleared, uncleared, reconciled
    approved: bool = True
    flag_color: Optional[str] = None
    import_id: Optional[str] = None


class YnabTransactionRequest(BaseModel):
    """YNAB transaction creation request."""

    transaction: YnabTransactionDetail


class YnabTransactionResponse(BaseModel):
    """YNAB transaction response."""

    id: str
    date: str
    amount: int
    memo: Optional[str] = None
    cleared: str
    approved: bool
    flag_color: Optional[str] = None
    account_id: str
    payee_id: Optional[str] = None
    category_id: Optional[str] = None
    transfer_account_id: Optional[str] = None
    transfer_transaction_id: Optional[str] = None
    matched_transaction_id: Optional[str] = None
    import_id: Optional[str] = None
    import_payee_name: Optional[str] = None
    import_payee_name_original: Optional[str] = None
    debt_transaction_type: Optional[str] = None
    deleted: bool


class YnabCategory(BaseModel):
    """YNAB category model."""

    id: str
    name: str
    category_group_id: str
    hidden: bool
    original_category_group_id: Optional[str] = None
    note: Optional[str] = None
    budgeted: int
    activity: int
    balance: int
    goal_type: Optional[str] = None
    goal_day: Optional[int] = None
    goal_cadence: Optional[int] = None
    goal_cadence_frequency: Optional[int] = None
    goal_creation_month: Optional[str] = None
    goal_target: Optional[int] = None
    goal_target_month: Optional[str] = None
    goal_percentage_complete: Optional[int] = None
    goal_months_to_budget: Optional[int] = None
    goal_under_funded: Optional[int] = None
    goal_overall_funded: Optional[int] = None
    goal_overall_left: Optional[int] = None
    goal_needs_whole_amount: Optional[bool] = None
    goal_snoozed_at: Optional[datetime] = None
    deleted: bool


class YnabCategoryGroup(BaseModel):
    """YNAB category group model."""

    id: str
    name: str
    hidden: bool
    deleted: bool


class YnabPayee(BaseModel):
    """YNAB payee model."""

    id: str
    name: str
    transfer_account_id: Optional[str] = None
    deleted: bool


class YnabAccount(BaseModel):
    """YNAB account model."""

    id: str
    name: str
    type: str
    on_budget: bool
    closed: bool
    note: Optional[str] = None
    balance: int
    cleared_balance: int
    uncleared_balance: int
    transfer_payee_id: str
    direct_import_linked: bool
    direct_import_in_error: bool
    last_reconciled_at: Optional[datetime] = None
    debt_original_balance: Optional[int] = None
    debt_interest_rates: Optional[Dict[str, Any]] = None
    debt_minimum_payments: Optional[Dict[str, Any]] = None
    debt_escrow_amounts: Optional[Dict[str, Any]] = None
    deleted: bool


class YnabBudget(BaseModel):
    """YNAB budget model."""

    id: str
    name: str
    last_modified_on: datetime
    first_month: str
    last_month: str
    date_format: Dict[str, str]
    currency_format: Dict[str, Any]
    accounts: List[YnabAccount]
    payees: List[YnabPayee]
    categories: List[YnabCategory]
    category_groups: List[YnabCategoryGroup]
