import pytest
from structlog.testing import capture_logs

from clients.errors import UpstreamError
from forwarding.budget_index import (
    BudgetIndexHolder,
    IndexUnavailable,
    NotInYnab,
    UnknownUpAccount,
    YnabAccountRef,
    build_budget_index,
)
from tests.fakes.up import FakeUpClient, up_account, up_accounts_fixture
from tests.fakes.ynab import FakeYnabClient, ynab_account, ynab_transaction

UP = up_accounts_fixture()  # accounts-1 "Spending", accounts-2..4 "🙂 Saver 1..3"


@pytest.mark.parametrize(
    "ynab_accounts, up_id, expected",
    [
        (
            [ynab_account("y2", "🙂 Saver 1", transfer_payee_id="tp2")],
            "accounts-2",
            YnabAccountRef("y2", "tp2"),
        ),
        (
            [ynab_account("y1", "Spending", transfer_payee_id="tp1")],
            "accounts-1",
            YnabAccountRef("y1", "tp1"),
        ),
        ([ynab_account("y1", "spending")], "accounts-1", NotInYnab()),
        ([ynab_account("y1", "Saver 1")], "accounts-2", NotInYnab()),
        ([ynab_account("y1", "Spending", closed=True)], "accounts-1", NotInYnab()),
        ([ynab_account("y1", "Spending", deleted=True)], "accounts-1", NotInYnab()),
        (
            [
                ynab_account("y0", "Spending", closed=True),
                ynab_account("y1", "Spending", transfer_payee_id="tp1"),
            ],
            "accounts-1",
            YnabAccountRef("y1", "tp1"),
        ),
        (
            [ynab_account("y1", "Spending"), ynab_account("y9", "Spending")],
            "accounts-1",
            NotInYnab(),
        ),
        ([], "no-such-account", UnknownUpAccount()),
    ],
)
def test_account_matching(ynab_accounts, up_id, expected):
    index = build_budget_index(UP, ynab_accounts)

    assert index.account(up_id) == expected


def test_duplicate_name_is_logged():
    ynab = [ynab_account("y1", "Spending"), ynab_account("y9", "Spending")]

    with capture_logs() as logs:
        build_budget_index(UP[:1], ynab)

    assert {
        "event": "Duplicate YNAB account name",
        "up_account_id": "accounts-1",
        "name": "Spending",
        "log_level": "warning",
    } in logs


def test_unmatched_accounts_are_logged():
    with capture_logs() as logs:
        build_budget_index(UP, [ynab_account("y1", "Spending")])

    unmatched = [
        entry["up_account_id"]
        for entry in logs
        if entry["event"] == "Up account not in YNAB"
    ]
    assert unmatched == ["accounts-2", "accounts-3", "accounts-4"]


SPLIT = [
    {
        "id": "s1",
        "transaction_id": "t3",
        "amount": -500,
        "category_id": "cat-a",
        "deleted": False,
    }
]


@pytest.mark.parametrize(
    "transactions, expected",
    [
        (
            [
                ynab_transaction("t1", "Cafe", "cat-a"),
                ynab_transaction("t2", "Cafe", "cat-a"),
            ],
            "cat-a",
        ),
        (
            [
                ynab_transaction("t1", "Cafe", "cat-a"),
                ynab_transaction("t2", "Cafe", "cat-b"),
            ],
            None,
        ),
        (
            [
                ynab_transaction("t1", "Cafe", "cat-a"),
                ynab_transaction("t2", "Cafe", "cat-b", transfer_account_id="y9"),
            ],
            "cat-a",
        ),
        (
            [
                ynab_transaction("t1", "Cafe", "cat-a"),
                ynab_transaction("t3", "Cafe", "split-cat", subtransactions=SPLIT),
            ],
            "cat-a",
        ),
        (
            [
                ynab_transaction("t1", "Cafe", "cat-a"),
                ynab_transaction("t2", "Cafe", None),
            ],
            "cat-a",
        ),
        (
            [
                ynab_transaction("t1", "Cafe", "cat-a"),
                ynab_transaction("t2", "Cafe", "cat-b", deleted=True),
            ],
            "cat-a",
        ),
        (
            [
                ynab_transaction("t1", "Cafe", "cat-a", transfer_account_id="y9"),
                ynab_transaction("t2", "Cafe", None),
                ynab_transaction("t3", "Cafe", "cat-b", deleted=True),
            ],
            None,
        ),
        ([ynab_transaction("t1", "Other", "cat-a")], None),
    ],
)
def test_category_match(transactions, expected):
    index = build_budget_index(UP, [], transactions)

    assert index.category_match("Cafe") == expected


def test_payee_name_none_is_ignored():
    index = build_budget_index(UP, [], [ynab_transaction("t1", None, "cat-a")])

    assert dict(index.category_by_payee) == {}


def test_exact_payee_name():
    index = build_budget_index(UP, [], [ynab_transaction("t1", "Cafe", "cat-a")])

    assert index.category_match("Cafe") == "cat-a"
    assert index.category_match("cafe") is None


class Harness:
    def __init__(self, up_accounts, ynab_accounts):
        self.now = [1000.0]
        self.up = FakeUpClient(accounts=up_accounts)
        self.ynab = FakeYnabClient(accounts=ynab_accounts)
        self.holder = BudgetIndexHolder(self.up, self.ynab, clock=lambda: self.now[0])


async def test_startup_failure_leaves_index_unavailable():
    h = Harness([up_account("u1", "Spending")], [])
    h.ynab.errors["list_accounts"] = UpstreamError("down", 503)

    with pytest.raises(UpstreamError):
        await h.holder.rebuild()
    with pytest.raises(IndexUnavailable):
        await h.holder.current_for("u1")


async def test_failed_rebuild_keeps_previous_index():
    h = Harness([up_account("u1", "Spending")], [ynab_account("y1", "Spending")])
    await h.holder.rebuild()
    h.ynab.errors["list_accounts"] = UpstreamError("down", 503)

    with pytest.raises(UpstreamError):
        await h.holder.rebuild()
    index = await h.holder.current_for("u1")

    assert index.account("u1") == YnabAccountRef("y1", "tp-y1")


async def test_unknown_account_triggers_one_lazy_rebuild():
    h = Harness([up_account("u1", "Spending")], [ynab_account("y1", "Spending")])
    await h.holder.rebuild()
    h.up.accounts.append(up_account("u2", "Bills"))
    h.ynab.accounts.append(ynab_account("y2", "Bills", transfer_payee_id="tp2"))

    index = await h.holder.current_for("u2")

    assert index.account("u2") == YnabAccountRef("y2", "tp2")
    assert h.up.list_accounts_calls == 2


async def test_lazy_rebuild_is_throttled_to_once_a_minute():
    h = Harness([up_account("u1", "Spending")], [ynab_account("y1", "Spending")])
    await h.holder.rebuild()

    await h.holder.current_for("missing")
    assert h.up.list_accounts_calls == 2
    h.now[0] += 59
    index = await h.holder.current_for("missing")
    assert h.up.list_accounts_calls == 2
    assert index.account("missing") == UnknownUpAccount()
    h.now[0] += 2
    await h.holder.current_for("missing")
    assert h.up.list_accounts_calls == 3


async def test_unbuilt_index_with_failing_lazy_rebuild_is_unavailable():
    h = Harness([up_account("u1", "Spending")], [])
    h.up.errors["list_accounts"] = UpstreamError("down", 503)

    with capture_logs() as logs:
        with pytest.raises(IndexUnavailable):
            await h.holder.current_for("u1")

    assert any(e["event"] == "Lazy Budget Index rebuild failed" for e in logs)


async def test_rebuild_fetches_all_time_history():
    h = Harness([up_account("u1", "Spending")], [ynab_account("y1", "Spending")])
    h.ynab.transactions = [ynab_transaction("t1", "Cafe", "cat-a")]

    await h.holder.rebuild()
    index = await h.holder.current_for("u1")

    assert h.ynab.since_dates == ["1970-01-01"]
    assert index.category_match("Cafe") == "cat-a"


async def test_failed_history_fetch_keeps_previous_index():
    h = Harness([up_account("u1", "Spending")], [ynab_account("y1", "Spending")])
    h.ynab.transactions = [ynab_transaction("t1", "Cafe", "cat-a")]
    await h.holder.rebuild()
    h.ynab.errors["list_transactions"] = UpstreamError("down", 503)

    with pytest.raises(UpstreamError):
        await h.holder.rebuild()
    index = await h.holder.current_for("u1")

    assert index.category_match("Cafe") == "cat-a"
