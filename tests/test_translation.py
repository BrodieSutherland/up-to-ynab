import json
from pathlib import Path

import pytest

from forwarding.budget_index import (
    BudgetIndex,
    NotInYnab,
    YnabAccountRef,
)
from forwarding.translation import Skip, cleared_status, translate
from models.up_models import UpTransaction

FIXTURES = Path(__file__).parent / "fixtures" / "up" / "transactions"
ACCOUNTS = {"accounts-1": YnabAccountRef("ynab-spending", "tp-spending")}
INDEX = BudgetIndex(ACCOUNTS)
MATCHED = BudgetIndex(ACCOUNTS, {"Payee 1": "cat-1"})


def load(name):
    return UpTransaction(**json.loads((FIXTURES / f"{name}.json").read_text())["data"])


def expected(payee_name, memo, amount, date, category_id, import_id):
    return {
        "account_id": "ynab-spending",
        "payee_name": payee_name,
        "category_id": category_id,
        "memo": memo,
        "amount": amount,
        "date": date,
        "cleared": "uncleared",
        "approved": True,
        "flag_color": None,
        "import_id": import_id,
    }


@pytest.mark.parametrize(
    "name, index, want",
    [
        pytest.param(
            "purchase_with_message_1",
            INDEX,
            expected(
                "Payee 4", "Message 1", -399030, "2026-10-15", None, "transactions-6"
            ),
            id="row11-message-wins",
        ),
        pytest.param(
            "purchase_plain_1",
            INDEX,
            expected(
                "Payee 1", "Raw text 1", -124100, "2026-10-20", None, "transactions-1"
            ),
            id="row12-rawtext-memo",
        ),
        pytest.param(
            "synthetic_rawtext_equals_description_1",
            INDEX,
            expected("Payee 1", None, -124100, "2026-10-20", None, "synthetic-1"),
            id="row13-rawtext-equals-description",
        ),
        pytest.param(
            "held_1",
            INDEX,
            expected(
                "Payee 3", "Raw text 3", -318470, "2026-10-17", None, "transactions-5"
            ),
            id="row15-held",
        ),
        pytest.param(
            "synthetic_created_late_evening_offset_1",
            INDEX,
            expected(
                "Payee 12", "Raw text 12", -50000, "2026-10-18", None, "synthetic-2"
            ),
            id="row16-created-date-own-offset",
        ),
        pytest.param(
            "purchase_foreign_currency_1",
            INDEX,
            expected(
                "Payee 10",
                "Raw text 8",
                -150450,
                "2026-08-05",
                None,
                "transactions-143",
            ),
            id="row17-foreign-currency",
        ),
        pytest.param(
            "purchase_plain_1",
            MATCHED,
            expected(
                "Payee 1",
                "Raw text 1",
                -124100,
                "2026-10-20",
                "cat-1",
                "transactions-1",
            ),
            id="row18a-category-matched",
        ),
        pytest.param(
            "purchase_plain_1",
            INDEX,
            expected(
                "Payee 1", "Raw text 1", -124100, "2026-10-20", None, "transactions-1"
            ),
            id="row18b-category-unmatched",
        ),
    ],
)
def test_parity_field_rules(name, index, want):
    assert translate(load(name), index).model_dump() == want


@pytest.mark.parametrize("name", ["held_1", "purchase_plain_1"])
def test_cleared_is_uncleared_for_held_and_settled(name):
    assert cleared_status(load(name)) == "uncleared"


def test_internal_transfer_is_skipped():
    tx = load("purchase_plain_1")
    tx.attributes.description = "Transfer to Savings"

    assert translate(tx, INDEX) == Skip("Internal transfer detected")


def test_account_not_in_ynab_is_skipped():
    result = translate(
        load("purchase_plain_1"), BudgetIndex({"accounts-1": NotInYnab()})
    )

    assert result == Skip("Up account not in YNAB")


def test_unknown_account_is_skipped():
    assert translate(load("purchase_plain_1"), BudgetIndex({})) == Skip(
        "Up account not in YNAB"
    )


def test_uses_matched_ynab_account_id():
    index = BudgetIndex({"accounts-1": YnabAccountRef("other-acct", "tp-9")})

    assert translate(load("purchase_plain_1"), index).account_id == "other-acct"
