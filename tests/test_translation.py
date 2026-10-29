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
SP = YnabAccountRef("ynab-spending", "tp-spending")
S1 = YnabAccountRef("ynab-saver-1", "tp-saver-1")
S3 = YnabAccountRef("ynab-saver-3", "tp-saver-3")
CATS = {"Transfer to Spending": "cat-1"}
ALL = BudgetIndex({"accounts-1": SP, "accounts-2": S1, "accounts-4": S3}, CATS)
S3_ONLY = BudgetIndex({"accounts-4": S3, "accounts-1": NotInYnab()}, CATS)
SP_ONLY = BudgetIndex({"accounts-1": SP, "accounts-4": NotInYnab()})
SP_ONLY_UNKNOWN = BudgetIndex({"accounts-1": SP})
INDEX = BudgetIndex({"accounts-1": SP})
MATCHED = BudgetIndex({"accounts-1": SP}, {"Payee 1": "cat-1"})
MIRROR = Skip("Mirror side of a Transfer")
NOT_IN_YNAB = Skip("Up account not in YNAB")


def load(name):
    return UpTransaction(**json.loads((FIXTURES / f"{name}.json").read_text())["data"])


def ordinary(
    account_id,
    payee_name,
    memo,
    amount,
    date,
    category_id,
    import_id="x",
    cleared="cleared",
):
    return {
        "account_id": account_id,
        "payee_id": None,
        "payee_name": payee_name,
        "category_id": category_id,
        "memo": memo,
        "amount": amount,
        "date": date,
        "cleared": cleared,
        "approved": True,
        "flag_color": None,
        "import_id": import_id,
    }


def transfer(account_id, payee_id, amount, date, import_id, cleared="cleared"):
    return {
        "account_id": account_id,
        "payee_id": payee_id,
        "payee_name": None,
        "category_id": None,
        "memo": None,
        "amount": amount,
        "date": date,
        "cleared": cleared,
        "approved": True,
        "flag_color": None,
        "import_id": import_id,
    }


XFER_ORIG = transfer(
    "ynab-saver-3", "tp-spending", -171000, "2026-09-05", "transactions-87"
)


@pytest.mark.parametrize(
    "name, index, want",
    [
        pytest.param("transfer_originating_1", ALL, XFER_ORIG, id="row1-originating"),
        pytest.param("transfer_mirror_1", ALL, MIRROR, id="row2-mirror-skipped"),
        pytest.param(
            "round_up_saver_side_1",
            ALL,
            transfer(
                "ynab-saver-3", "tp-spending", 67780, "2026-10-17", "transactions-2"
            ),
            id="row3-round-up-is-transfer",
        ),
        pytest.param(
            "transfer_originating_1",
            S3_ONLY,
            ordinary(
                "ynab-saver-3",
                "Transfer to Spending",
                None,
                -171000,
                "2026-09-05",
                "cat-1",
                "transactions-87",
            ),
            id="row4-other-not-in-ynab-originating",
        ),
        pytest.param(
            "round_up_saver_side_1",
            S3_ONLY,
            ordinary(
                "ynab-saver-3",
                "Round Up",
                None,
                67780,
                "2026-10-17",
                None,
                "transactions-2",
            ),
            id="row4b-other-not-in-ynab-round-up",
        ),
        pytest.param(
            "transfer_mirror_1",
            SP_ONLY,
            ordinary(
                "ynab-spending",
                "Transfer from Other party 1",
                None,
                171000,
                "2026-09-05",
                None,
                "transactions-86",
            ),
            id="row5a-other-not-in-ynab-mirror",
        ),
        pytest.param(
            "transfer_mirror_1",
            SP_ONLY_UNKNOWN,
            ordinary(
                "ynab-spending",
                "Transfer from Other party 1",
                None,
                171000,
                "2026-09-05",
                None,
                "transactions-86",
            ),
            id="row5b-other-unknown-mirror",
        ),
        pytest.param(
            "transfer_originating_1", SP_ONLY, NOT_IN_YNAB, id="row6a-own-not-in-ynab"
        ),
        pytest.param(
            "transfer_mirror_1",
            BudgetIndex({"accounts-4": S3}),
            NOT_IN_YNAB,
            id="row6b-own-unknown",
        ),
        pytest.param(
            "synthetic_transfer_text_no_transfer_account_1",
            ALL,
            ordinary(
                "ynab-saver-3",
                "Transfer to Spending",
                None,
                -171000,
                "2026-09-05",
                "cat-1",
                "synthetic-3",
            ),
            id="row7-text-without-transfer-account",
        ),
        pytest.param(
            "synthetic_round_up_typed_transfer_mirror_1",
            ALL,
            MIRROR,
            id="row8-round-up-type-is-not-round-up",
        ),
        pytest.param(
            "synthetic_cover_originating_1",
            ALL,
            transfer(
                "ynab-saver-1", "tp-spending", -25000, "2026-10-01", "synthetic-5"
            ),
            id="row9-cover-originating",
        ),
        pytest.param("synthetic_cover_mirror_1", ALL, MIRROR, id="row9-cover-mirror"),
        pytest.param(
            "synthetic_forward_originating_1",
            ALL,
            transfer(
                "ynab-spending", "tp-saver-1", -25000, "2026-10-01", "synthetic-7"
            ),
            id="row9-forward-originating",
        ),
        pytest.param(
            "synthetic_forward_mirror_1", ALL, MIRROR, id="row9-forward-mirror"
        ),
        pytest.param(
            "synthetic_quick_save_originating_1",
            ALL,
            transfer(
                "ynab-spending", "tp-saver-1", -25000, "2026-10-01", "synthetic-9"
            ),
            id="row9-quick-save-originating",
        ),
        pytest.param(
            "synthetic_quick_save_mirror_1", ALL, MIRROR, id="row9-quick-save-mirror"
        ),
        pytest.param(
            "purchase_plain_1",
            ALL,
            ordinary(
                "ynab-spending",
                "Payee 1",
                "Raw text 1",
                -124100,
                "2026-10-20",
                None,
                "transactions-1",
            ),
            id="row10-purchase",
        ),
        pytest.param(
            "purchase_with_message_1",
            INDEX,
            ordinary(
                "ynab-spending",
                "Payee 4",
                "Message 1",
                -399030,
                "2026-10-15",
                None,
                "transactions-6",
            ),
            id="row11-message-wins",
        ),
        pytest.param(
            "purchase_plain_1",
            INDEX,
            ordinary(
                "ynab-spending",
                "Payee 1",
                "Raw text 1",
                -124100,
                "2026-10-20",
                None,
                "transactions-1",
            ),
            id="row12-rawtext-memo",
        ),
        pytest.param(
            "synthetic_rawtext_equals_description_1",
            INDEX,
            ordinary(
                "ynab-spending",
                "Payee 1",
                None,
                -124100,
                "2026-10-20",
                None,
                "synthetic-1",
            ),
            id="row13-rawtext-equals-description",
        ),
        pytest.param(
            "transfer_originating_1",
            ALL,
            XFER_ORIG,
            id="row14-transfer-memo-and-import-id",
        ),
        pytest.param(
            "held_1",
            INDEX,
            ordinary(
                "ynab-spending",
                "Payee 3",
                "Raw text 3",
                -318470,
                "2026-10-17",
                None,
                "transactions-5",
                "uncleared",
            ),
            id="row15-held",
        ),
        pytest.param(
            "synthetic_created_late_evening_offset_1",
            INDEX,
            ordinary(
                "ynab-spending",
                "Payee 12",
                "Raw text 12",
                -50000,
                "2026-10-18",
                None,
                "synthetic-2",
            ),
            id="row16-created-date-own-offset",
        ),
        pytest.param(
            "purchase_foreign_currency_1",
            INDEX,
            ordinary(
                "ynab-spending",
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
            ordinary(
                "ynab-spending",
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
            ordinary(
                "ynab-spending",
                "Payee 1",
                "Raw text 1",
                -124100,
                "2026-10-20",
                None,
                "transactions-1",
            ),
            id="row18b-category-unmatched",
        ),
    ],
)
def test_parity_field_rules(name, index, want):
    result = translate(load(name), index)

    assert (result if isinstance(result, Skip) else result.model_dump()) == want


@pytest.mark.parametrize(
    "name, want", [("held_1", "uncleared"), ("purchase_plain_1", "cleared")]
)
def test_cleared_follows_up_status(name, want):
    assert cleared_status(load(name)) == want


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
