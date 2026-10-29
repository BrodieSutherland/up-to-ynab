from datetime import datetime, timedelta, timezone

import pytest

from clients.errors import UpstreamError
from forwarding.backfill import YNAB_CREATE_LIMIT, BackfillReport, backfill
from forwarding.budget_index import BudgetIndex, YnabAccountRef
from forwarding.forwarder import Forwarder
from forwarding.ledger import Forwarded, Skipped
from tests.fakes.budget_index import FakeIndexHolder
from tests.fakes.ledger import InMemoryLedger
from tests.fakes.up import FakeUpClient, up_transaction
from tests.fakes.ynab import FakeYnabClient

INDEX = BudgetIndex({"test-account-id": YnabAccountRef("acct-1", "tp-1")}, {})
SINCE = datetime(2026, 10, 1, tzinfo=timezone(timedelta(hours=10)))


def day(n: int) -> str:
    return f"2026-10-0{n}T01:00:00+00:00"


@pytest.fixture
def ledger():
    return InMemoryLedger()


@pytest.fixture
def ynab():
    return FakeYnabClient()


def setup(transactions, ynab, ledger, index=INDEX):
    up = FakeUpClient({t.id: t for t in transactions})
    return up, Forwarder(up, ynab, FakeIndexHolder(index), ledger)


def test_limit_is_150():
    assert YNAB_CREATE_LIMIT == 150


async def test_mixed_run_counts_each_outcome(ynab, ledger):
    txs = [
        up_transaction("new", day(2)),
        up_transaction("done", day(3)),
        up_transaction("other-account", day(4), account_id="unknown-account"),
        up_transaction("old", "2026-09-30T01:00:00+00:00"),
    ]
    await ledger.record(Forwarded("done", "ynab-9"))
    up, forwarder = setup(txs, ynab, ledger)

    report = await backfill(up, forwarder, SINCE)

    assert report == BackfillReport(
        forwarded=1, skipped=1, failed=0, already_handled=1, more_remaining=False
    )
    assert up.list_transactions_calls == [SINCE]
    assert [d.import_id for d in ynab.created] == ["new"]


async def test_failures_are_counted(ynab, ledger):
    ynab.errors["create_transaction"] = UpstreamError("ynab down", 500)
    up, forwarder = setup([up_transaction("t-1", day(2))], ynab, ledger)

    report = await backfill(up, forwarder, SINCE)

    assert report == BackfillReport(0, 0, 1, 0, False)


async def test_stops_at_the_limit_with_more_remaining(ynab, ledger):
    txs = [up_transaction(f"t-{n}", day(n)) for n in (1, 2, 3, 4)]
    up, forwarder = setup(txs, ynab, ledger)

    report = await backfill(up, forwarder, SINCE, limit=2)

    assert report == BackfillReport(2, 0, 0, 0, True)
    assert len(ynab.created) == 2


async def test_exactly_the_limit_is_not_more_remaining(ynab, ledger):
    txs = [up_transaction(f"t-{n}", day(n)) for n in (1, 2)]
    up, forwarder = setup(txs, ynab, ledger)

    report = await backfill(up, forwarder, SINCE, limit=2)

    assert report == BackfillReport(2, 0, 0, 0, False)


async def test_already_in_ynab_creates_count_toward_the_limit(ynab, ledger):
    ynab.already_imported = True
    txs = [up_transaction(f"t-{n}", day(n)) for n in (1, 2, 3)]
    up, forwarder = setup(txs, ynab, ledger)

    report = await backfill(up, forwarder, SINCE, limit=2)

    assert report == BackfillReport(2, 0, 0, 0, True)


async def test_transactions_are_created_oldest_first(ynab, ledger):
    txs = [up_transaction(f"t-{n}", day(n)) for n in (3, 1, 2)]
    up, forwarder = setup(txs, ynab, ledger)

    await backfill(up, forwarder, SINCE)

    assert [d.import_id for d in ynab.created] == ["t-1", "t-2", "t-3"]


async def test_second_run_finishes_the_rest(ynab, ledger):
    txs = [up_transaction(f"t-{n}", day(n)) for n in (1, 2, 3)]
    up, forwarder = setup(txs, ynab, ledger)

    first = await backfill(up, forwarder, SINCE, limit=2)
    second = await backfill(up, forwarder, SINCE, limit=2)

    assert first == BackfillReport(2, 0, 0, 0, True)
    assert second == BackfillReport(1, 0, 0, 2, False)
    assert [d.import_id for d in ynab.created] == ["t-1", "t-2", "t-3"]


async def test_unmatched_account_skip_is_retried(ynab, ledger):
    await ledger.record(Skipped("t-1", "Up account not in YNAB", "account_not_in_ynab"))
    up, forwarder = setup([up_transaction("t-1", day(2))], ynab, ledger)

    report = await backfill(up, forwarder, SINCE)

    assert report == BackfillReport(1, 0, 0, 0, False)


async def test_list_failure_propagates(ynab, ledger):
    up, forwarder = setup([], ynab, ledger)
    up.errors["list_transactions"] = UpstreamError("down", 503)

    with pytest.raises(UpstreamError):
        await backfill(up, forwarder, SINCE)
