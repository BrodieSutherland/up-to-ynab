import pytest

from forwarding.ledger import Failed, Forwarded, Skipped, SqlLedger
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
