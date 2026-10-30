from datetime import UTC, datetime

import pytest

from forwarding.ledger import (
    Deleted,
    Failed,
    Forwarded,
    LedgerEntryView,
    LedgerState,
    Skipped,
    SqlLedger,
    backfill_retryable,
)
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
    await ledger.record(Skipped("tx1", "Mirror side of a Transfer", "mirror_side"))

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
    await ledger.record(Skipped("tx1", "Mirror side of a Transfer", "mirror_side"))

    assert await ledger.lookup("tx1") == LedgerState("skipped", None, "mirror_side")


async def test_lookup_failed(ledger):
    await ledger.record(Failed("tx1", "boom"))

    assert await ledger.lookup("tx1") == LedgerState("failed", None)


async def test_forwarded_then_deleted_is_final(ledger):
    await ledger.record(Forwarded("tx1", "ynab-1"))
    await ledger.record(Deleted("tx1", "ynab-1", False, "deleted in YNAB"))

    assert await ledger.lookup("tx1") == LedgerState("deleted", "ynab-1")
    assert await ledger.is_handled("tx1") is True
    assert await ledger.attempts("tx1") == 1


async def test_deleted_without_entry_records_nothing(ledger):
    await ledger.record(Deleted("tx1", "ynab-1", False, "deleted in YNAB"))

    assert await ledger.lookup("tx1") is None


async def test_deleted_leaves_skipped_and_failed_untouched(ledger):
    await ledger.record(Skipped("tx1", "no account", "no_account"))
    await ledger.record(Failed("tx2", "boom"))

    await ledger.record(Deleted("tx1", "ynab-1", False, "deleted in YNAB"))
    await ledger.record(Deleted("tx2", "ynab-2", False, "deleted in YNAB"))

    assert await ledger.lookup("tx1") == LedgerState("skipped", None, "no_account")
    assert await ledger.lookup("tx2") == LedgerState("failed", None)


async def test_deleted_is_not_overwritten(ledger):
    await ledger.record(Forwarded("tx1", "ynab-1"))
    await ledger.record(Deleted("tx1", "ynab-1", False, "deleted in YNAB"))

    await ledger.record(Failed("tx1", "boom"))
    await ledger.record(Forwarded("tx1", "ynab-2"))

    assert await ledger.lookup("tx1") == LedgerState("deleted", "ynab-1")
    assert await ledger.attempts("tx1") == 1


async def test_deleted_reason_is_stored(database):
    sql = SqlLedger(database.get_session)
    await sql.record(Forwarded("tx1", "ynab-1"))
    await sql.record(Deleted("tx1", "ynab-1", True, "flagged red: cleared in YNAB"))

    async with database.get_session() as session:
        entry = await sql._entry(session, "tx1")
    assert entry.reason == "flagged red: cleared in YNAB"


NOT_IN_YNAB = Skipped("tx1", "Up account not in YNAB", "account_not_in_ynab")


async def test_unmatched_account_skip_becomes_forwarded(ledger):
    await ledger.record(NOT_IN_YNAB)
    await ledger.record(Forwarded("tx1", "ynab-1"))

    assert await ledger.lookup("tx1") == LedgerState("forwarded", "ynab-1", None)
    assert await ledger.attempts("tx1") == 2


async def test_unmatched_account_skip_becomes_mirror_skip(ledger):
    await ledger.record(NOT_IN_YNAB)
    await ledger.record(Skipped("tx1", "Mirror side of a Transfer", "mirror_side"))

    assert await ledger.lookup("tx1") == LedgerState("skipped", None, "mirror_side")
    assert await ledger.attempts("tx1") == 2


async def test_unmatched_account_skip_is_kept_when_retry_fails(ledger):
    await ledger.record(NOT_IN_YNAB)
    await ledger.record(Failed("tx1", "ynab down"))

    assert await ledger.lookup("tx1") == LedgerState(
        "skipped", None, "account_not_in_ynab"
    )
    assert await ledger.attempts("tx1") == 1


async def test_unmatched_account_skip_counts_as_handled(ledger):
    await ledger.record(NOT_IN_YNAB)

    assert await ledger.is_handled("tx1") is True


async def test_mirror_and_uncoded_skips_are_never_overwritten(ledger):
    await ledger.record(Skipped("tx1", "Mirror side of a Transfer", "mirror_side"))
    await ledger.record(Skipped("tx2", "old skip", "no_account"))

    await ledger.record(Forwarded("tx1", "ynab-1"))
    await ledger.record(Forwarded("tx2", "ynab-2"))

    assert await ledger.lookup("tx1") == LedgerState("skipped", None, "mirror_side")
    assert await ledger.lookup("tx2") == LedgerState("skipped", None, "no_account")


@pytest.mark.parametrize(
    "state, expected",
    [
        (None, True),
        (LedgerState("failed", None), True),
        (LedgerState("skipped", None, "account_not_in_ynab"), True),
        (LedgerState("skipped", None, "mirror_side"), False),
        (LedgerState("skipped", None, None), False),
        (LedgerState("forwarded", "ynab-1"), False),
        (LedgerState("deleted", "ynab-1"), False),
    ],
)
def test_backfill_retryable(state, expected):
    assert backfill_retryable(state) is expected


async def test_entry_view_of_a_skipped_transaction(ledger):
    await ledger.record(Skipped("tx1", "Up account not in YNAB", "account_not_in_ynab"))
    await ledger.record(Skipped("tx1", "Mirror side of a Transfer", "mirror_side"))

    view = await ledger.entry("tx1")

    assert view is not None
    assert view.updated_at.tzinfo is not None
    assert view.updated_at.utcoffset().total_seconds() == 0
    assert (
        view.up_transaction_id,
        view.status,
        view.reason,
        view.reason_code,
        view.ynab_transaction_id,
        view.attempts,
    ) == (
        "tx1",
        "skipped",
        "Mirror side of a Transfer",
        "mirror_side",
        None,
        2,
    )


async def test_entry_missing_is_none(ledger):
    assert await ledger.entry("nope") is None


async def test_sql_entry_maps_every_column_as_utc(database):
    from database.models import LedgerEntry

    async with database.get_session() as session:
        session.add(
            LedgerEntry(
                up_transaction_id="tx1",
                status="skipped",
                reason="Up account not in YNAB",
                reason_code="account_not_in_ynab",
                attempts=2,
                updated_at=datetime(2026, 10, 30, 1, 2, 3),
            )
        )
        await session.commit()

    assert await SqlLedger(database.get_session).entry("tx1") == LedgerEntryView(
        "tx1",
        "skipped",
        "Up account not in YNAB",
        "account_not_in_ynab",
        None,
        2,
        datetime(2026, 10, 30, 1, 2, 3, tzinfo=UTC),
    )
