import pytest

from forwarding.ledger import Failed, Forwarded, LedgerState, Skipped, SqlLedger
from tests.fakes.ledger import InMemoryLedger


@pytest.fixture(params=["sql", "memory"])
def ledger(request, database):
    if request.param == "sql":
        return SqlLedger(database.get_session)
    return InMemoryLedger()


async def test_unknown_id_is_not_handled(ledger):
    assert await ledger.is_handled("nope") is False


async def test_failed_is_not_handled(ledger):
    await ledger.record(Failed("tx1", "boom"))

    assert await ledger.is_handled("tx1") is False


async def test_failed_then_forwarded_is_handled(ledger):
    await ledger.record(Failed("tx1", "boom"))
    await ledger.record(Forwarded("tx1", "ynab-1"))

    assert await ledger.is_handled("tx1") is True
    assert await ledger.attempts("tx1") == 2


async def test_forwarded_already_in_ynab_is_handled(ledger):
    await ledger.record(Forwarded("tx1", None))

    assert await ledger.is_handled("tx1") is True


async def test_skipped_is_handled(ledger):
    await ledger.record(Skipped("tx1", "Mirror side of a Transfer"))

    assert await ledger.is_handled("tx1") is True


async def test_handled_is_not_overwritten_by_failure(ledger):
    await ledger.record(Forwarded("tx1", "ynab-1"))
    await ledger.record(Failed("tx1", "late failure"))

    assert await ledger.is_handled("tx1") is True
    assert await ledger.attempts("tx1") == 1


async def test_repeated_failure_increments_attempts(ledger):
    await ledger.record(Failed("tx1", "boom"))
    await ledger.record(Failed("tx1", "boom again"))

    assert await ledger.attempts("tx1") == 2
    assert await ledger.is_handled("tx1") is False


async def test_lookup_unknown_is_none(ledger):
    assert await ledger.lookup("nope") is None


async def test_lookup_forwarded_with_id(ledger):
    await ledger.record(Forwarded("tx1", "ynab-1"))

    assert await ledger.lookup("tx1") == LedgerState("forwarded", "ynab-1")


async def test_lookup_forwarded_without_id(ledger):
    await ledger.record(Forwarded("tx1", None))

    assert await ledger.lookup("tx1") == LedgerState("forwarded", None)


async def test_lookup_skipped(ledger):
    await ledger.record(Skipped("tx1", "Mirror side of a Transfer"))

    assert await ledger.lookup("tx1") == LedgerState("skipped", None)


async def test_lookup_failed(ledger):
    await ledger.record(Failed("tx1", "boom"))

    assert await ledger.lookup("tx1") == LedgerState("failed", None)
