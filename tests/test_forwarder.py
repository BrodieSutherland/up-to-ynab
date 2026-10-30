import json
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from clients.errors import UpstreamError
from forwarding.budget_index import (
    BudgetIndex,
    NotInYnab,
    YnabAccountRef,
)
from forwarding.forwarder import BackfillStep, Forwarder, Ignored, Settled
from forwarding.ledger import Deleted, Failed, Forwarded, Skipped
from models.up_models import UpTransaction, UpWebhookEvent
from tests.fakes.budget_index import FakeIndexHolder
from tests.fakes.ledger import InMemoryLedger
from tests.fakes.up import FakeUpClient, up_transaction
from tests.fakes.ynab import FakeYnabClient, ynab_transaction

INDEX = BudgetIndex({"test-account-id": YnabAccountRef("acct-1", "tp-1")}, {})


@pytest.fixture
def holder():
    return FakeIndexHolder(INDEX)


@pytest.fixture
def ledger():
    return InMemoryLedger()


@pytest.fixture
def forwarder(fake_up, fake_ynab, holder, ledger):
    return Forwarder(fake_up, fake_ynab, holder, ledger)


@pytest.fixture
def event(sample_up_webhook_event_data):
    return UpWebhookEvent(**sample_up_webhook_event_data)


async def test_forwarded(forwarder, event, fake_ynab, ledger):
    result = await forwarder.handle(event)

    assert result == Forwarded("test-transaction-id", "ynab-1")
    assert ledger.entries["test-transaction-id"].status == "forwarded"
    assert len(fake_ynab.created) == 1


async def test_already_imported_counts_as_forwarded(
    forwarder, event, fake_ynab, ledger
):
    fake_ynab.already_imported = True

    result = await forwarder.handle(event)

    assert result == Forwarded("test-transaction-id", None)
    assert await ledger.is_handled("test-transaction-id")


async def test_mirror_side_is_skipped(
    sample_up_transaction_data, sample_up_webhook_event_data, fake_ynab, holder, ledger
):
    data = sample_up_transaction_data["data"]
    data["attributes"]["amount"] = {
        "currencyCode": "AUD",
        "value": "12.50",
        "valueInBaseUnits": 1250,
    }
    data["relationships"]["transferAccount"] = {
        "data": {"type": "accounts", "id": "saver-id"}
    }
    holder = FakeIndexHolder(
        BudgetIndex(
            {
                "test-account-id": YnabAccountRef("acct-1", "tp-1"),
                "saver-id": YnabAccountRef("acct-2", "tp-2"),
            }
        )
    )
    up = FakeUpClient(transactions={"test-transaction-id": UpTransaction(**data)})
    forwarder = Forwarder(up, fake_ynab, holder, ledger)

    result = await forwarder.handle(UpWebhookEvent(**sample_up_webhook_event_data))

    assert result == Skipped(
        "test-transaction-id", "Mirror side of a Transfer", "mirror_side"
    )
    assert fake_ynab.created == []
    assert ledger.entries["test-transaction-id"].status == "skipped"


async def test_up_failure_is_failed_and_not_handled(forwarder, event, fake_up, ledger):
    fake_up.errors["get_transaction"] = UpstreamError("down", 503)

    result = await forwarder.handle(event)

    assert result == Failed("test-transaction-id", "down")
    assert ledger.entries["test-transaction-id"].status == "failed"
    assert not await ledger.is_handled("test-transaction-id")


async def test_ynab_failure_is_failed(forwarder, event, fake_ynab, ledger):
    fake_ynab.errors["create_transaction"] = UpstreamError("ynab down", 500)

    result = await forwarder.handle(event)

    assert result == Failed("test-transaction-id", "ynab down")
    assert ledger.entries["test-transaction-id"].status == "failed"


async def test_unexpected_error_is_failed(forwarder, event, holder):
    async def boom(account_id):
        raise RuntimeError("index exploded")

    holder.current_for = boom

    result = await forwarder.handle(event)

    assert result == Failed("test-transaction-id", "Unexpected error: index exploded")


async def test_other_event_types_are_ignored(
    forwarder, sample_up_webhook_event_data, ledger
):
    sample_up_webhook_event_data["data"]["attributes"]["eventType"] = "PING"

    result = await forwarder.handle(UpWebhookEvent(**sample_up_webhook_event_data))

    assert result == Ignored("test-transaction-id", "not a transaction event")
    assert ledger.entries == {}


async def test_created_without_transaction_id_is_ignored(
    forwarder, sample_up_webhook_event_data, ledger
):
    sample_up_webhook_event_data["data"]["relationships"] = None

    result = await forwarder.handle(UpWebhookEvent(**sample_up_webhook_event_data))

    assert result == Ignored(None, "not a transaction event")
    assert ledger.entries == {}


async def test_already_handled_is_ignored_without_calling_up(
    forwarder, event, fake_up, ledger
):
    await forwarder.handle(event)
    fake_up.errors["get_transaction"] = AssertionError("Up must not be called")

    result = await forwarder.handle(event)

    assert result == Ignored("test-transaction-id", "already handled")


async def test_ledger_write_failure_is_failed(forwarder, event, ledger):
    ledger.errors["record"] = RuntimeError("disk full")

    result = await forwarder.handle(event)

    assert result == Failed("test-transaction-id", "Could not record outcome")


async def test_failed_transaction_is_retried(forwarder, event, fake_ynab, ledger):
    fake_ynab.errors["create_transaction"] = UpstreamError("ynab down", 500)
    await forwarder.handle(event)
    del fake_ynab.errors["create_transaction"]

    result = await forwarder.handle(event)

    assert result == Forwarded("test-transaction-id", "ynab-1")
    assert await ledger.attempts("test-transaction-id") == 2


async def test_budget_index_unavailable_is_failed(fake_up, fake_ynab, event, ledger):
    forwarder = Forwarder(fake_up, fake_ynab, FakeIndexHolder(None), ledger)

    result = await forwarder.handle(event)

    assert result == Failed("test-transaction-id", "Budget Index unavailable")
    assert ledger.entries["test-transaction-id"].status == "failed"
    assert fake_ynab.created == []


async def test_account_not_in_ynab_is_skipped(fake_up, fake_ynab, event, ledger):
    holder = FakeIndexHolder(BudgetIndex({"test-account-id": NotInYnab()}))
    forwarder = Forwarder(fake_up, fake_ynab, holder, ledger)

    result = await forwarder.handle(event)

    assert result == Skipped(
        "test-transaction-id", "Up account not in YNAB", "account_not_in_ynab"
    )
    assert fake_ynab.created == []
    assert ledger.entries["test-transaction-id"].status == "skipped"


FIXTURES = Path(__file__).parent / "fixtures" / "up"


def load_event(name):
    text = (FIXTURES / "webhook_events" / f"{name}.json").read_text()
    return UpWebhookEvent(**json.loads(text)["event"])


def load_tx(name):
    text = (FIXTURES / "transactions" / f"{name}.json").read_text()
    return UpTransaction(**json.loads(text)["data"])


SETTLED_ID = "transactions-3"
ROUND_UP_INDEX = BudgetIndex({"accounts-1": YnabAccountRef("ynab-spending", "tp-s")})


@pytest.fixture
def settled_event():
    return load_event("TRANSACTION_SETTLED_1")


@pytest.fixture
def settle_up():
    return FakeUpClient(transactions={SETTLED_ID: load_tx("purchase_with_round_up_1")})


def settle_forwarder(up, ynab, ledger, index=ROUND_UP_INDEX):
    return Forwarder(up, ynab, FakeIndexHolder(index), ledger)


async def forwarded_row(ledger, ynab_id="ynab-x"):
    await ledger.record(Forwarded(SETTLED_ID, ynab_id))


async def test_settled_marks_forwarded_transaction_cleared(
    settled_event, settle_up, ledger
):
    ynab = FakeYnabClient(
        transactions=[
            ynab_transaction(
                "ynab-x", "Payee", None, amount=-497850, cleared="uncleared"
            )
        ]
    )
    await forwarded_row(ledger)

    result = await settle_forwarder(settle_up, ynab, ledger).handle(settled_event)

    assert result == Settled(SETTLED_ID, "ynab-x")
    assert ynab.updates == [("ynab-x", "cleared", None)]
    assert ynab.created == []
    assert ledger.entries[SETTLED_ID].status == "forwarded"
    assert ledger.entries[SETTLED_ID].attempts == 1


async def test_settled_fixes_a_differing_amount(settled_event, settle_up, ledger):
    ynab = FakeYnabClient(
        transactions=[
            ynab_transaction(
                "ynab-x", "Payee", None, amount=-500000, cleared="uncleared"
            )
        ]
    )
    await forwarded_row(ledger)

    result = await settle_forwarder(settle_up, ynab, ledger).handle(settled_event)

    assert result == Settled(SETTLED_ID, "ynab-x")
    assert ynab.updates == [("ynab-x", "cleared", -497850)]


async def test_settled_leaves_reconciled_transaction(settled_event, settle_up, ledger):
    ynab = FakeYnabClient(
        transactions=[
            ynab_transaction(
                "ynab-x", "Payee", None, amount=-497850, cleared="reconciled"
            )
        ]
    )
    await forwarded_row(ledger)

    result = await settle_forwarder(settle_up, ynab, ledger).handle(settled_event)

    assert result == Ignored(SETTLED_ID, "reconciled in YNAB")
    assert ynab.updates == []


async def test_settled_without_ynab_id_finds_by_import_id(
    settled_event, settle_up, ledger
):
    ynab = FakeYnabClient(
        transactions=[
            ynab_transaction("other", "A", None, import_id="transactions-9"),
            ynab_transaction("gone", "A", None, import_id=SETTLED_ID, deleted=True),
            ynab_transaction(
                "found",
                "Payee",
                None,
                amount=-497850,
                cleared="uncleared",
                import_id=SETTLED_ID,
            ),
        ]
    )
    await forwarded_row(ledger, None)

    result = await settle_forwarder(settle_up, ynab, ledger).handle(settled_event)

    assert result == Settled(SETTLED_ID, "found")
    assert ynab.since_dates == ["2026-10-17"]
    assert ynab.updates == [("found", "cleared", None)]


async def test_settled_without_ynab_id_not_found_is_ignored(
    settled_event, settle_up, ledger
):
    ynab = FakeYnabClient()
    await forwarded_row(ledger, None)

    result = await settle_forwarder(settle_up, ynab, ledger).handle(settled_event)

    assert result == Ignored(SETTLED_ID, "not found in YNAB")
    assert ynab.updates == []


async def test_settled_never_forwarded_creates_cleared(
    settled_event, settle_up, ledger
):
    ynab = FakeYnabClient()

    result = await settle_forwarder(settle_up, ynab, ledger).handle(settled_event)

    assert result == Forwarded(SETTLED_ID, "ynab-1")
    assert [t.cleared for t in ynab.created] == ["cleared"]
    assert ledger.entries[SETTLED_ID].status == "forwarded"


async def test_settled_after_failed_creates_cleared(settled_event, settle_up, ledger):
    ynab = FakeYnabClient()
    await ledger.record(Failed(SETTLED_ID, "boom"))

    result = await settle_forwarder(settle_up, ynab, ledger).handle(settled_event)

    assert result == Forwarded(SETTLED_ID, "ynab-1")
    assert [t.cleared for t in ynab.created] == ["cleared"]
    assert ledger.entries[SETTLED_ID].attempts == 2


async def test_settled_skipped_transaction_is_ignored(settled_event, settle_up, ledger):
    ynab = FakeYnabClient()
    await ledger.record(Skipped(SETTLED_ID, "Mirror side of a Transfer", "mirror_side"))

    result = await settle_forwarder(settle_up, ynab, ledger).handle(settled_event)

    assert result == Ignored(SETTLED_ID, "skipped transaction")
    assert ynab.created == []
    assert ynab.updates == []


async def test_settled_mirror_side_without_entry_is_skipped(ledger):
    up = FakeUpClient(transactions={"transactions-4": load_tx("transfer_mirror_1")})
    mirror = load_tx("transfer_mirror_1")
    index = BudgetIndex(
        {
            mirror.account_id: YnabAccountRef("ynab-a", "tp-a"),
            mirror.transfer_account_id: YnabAccountRef("ynab-b", "tp-b"),
        }
    )
    event = UpWebhookEvent(
        **{
            "data": {
                "type": "webhook-events",
                "id": "e1",
                "attributes": {
                    "eventType": "TRANSACTION_SETTLED",
                    "createdAt": "2026-10-20T07:52:27+11:00",
                },
                "relationships": {
                    "transaction": {
                        "data": {"type": "transactions", "id": "transactions-4"}
                    }
                },
            }
        }
    )
    ynab = FakeYnabClient()

    result = await settle_forwarder(up, ynab, ledger, index).handle(event)

    assert result == Skipped(
        "transactions-4", "Mirror side of a Transfer", "mirror_side"
    )
    assert ynab.created == []
    assert ledger.entries["transactions-4"].status == "skipped"


@pytest.mark.parametrize(
    "where, error",
    [
        ("ynab_get", UpstreamError("ynab down", 500)),
        ("ynab_update", UpstreamError("ynab down", 500)),
        ("up_get", UpstreamError("up down", 503)),
        ("ledger_lookup", RuntimeError("db gone")),
    ],
)
async def test_settle_failure_is_failed_and_keeps_forwarded_row(
    settled_event, settle_up, ledger, where, error
):
    ynab = FakeYnabClient(
        transactions=[
            ynab_transaction(
                "ynab-x", "Payee", None, amount=-497850, cleared="uncleared"
            )
        ]
    )
    await forwarded_row(ledger)
    if where == "ynab_get":
        ynab.errors["get_transaction"] = error
    elif where == "ynab_update":
        ynab.errors["update_transaction"] = error
    elif where == "up_get":
        settle_up.errors["get_transaction"] = error
    else:
        ledger.errors["lookup"] = error

    result = await settle_forwarder(settle_up, ynab, ledger).handle(settled_event)

    assert isinstance(result, Failed)
    assert result.reason in ("ynab down", "up down", "Unexpected error: db gone")
    assert ledger.entries[SETTLED_ID].status == "forwarded"
    assert ledger.entries[SETTLED_ID].attempts == 1


async def test_settled_ynab_copy_missing_is_ignored(settled_event, settle_up, ledger):
    ynab = FakeYnabClient()
    await forwarded_row(ledger, "ynab-gone")

    result = await settle_forwarder(settle_up, ynab, ledger).handle(settled_event)

    assert result == Ignored(SETTLED_ID, "not in YNAB")
    assert ynab.updates == []


async def test_settled_ynab_copy_deleted_is_ignored(settled_event, settle_up, ledger):
    ynab = FakeYnabClient(
        transactions=[ynab_transaction("ynab-x", "Payee", None, deleted=True)]
    )
    await forwarded_row(ledger)

    result = await settle_forwarder(settle_up, ynab, ledger).handle(settled_event)

    assert result == Ignored(SETTLED_ID, "not in YNAB")
    assert ynab.updates == []


async def test_settled_409_clears_the_existing_copy(settled_event, settle_up, ledger):
    ynab = FakeYnabClient(
        transactions=[
            ynab_transaction(
                "existing",
                "Payee",
                None,
                amount=-497850,
                cleared="uncleared",
                import_id=SETTLED_ID,
            )
        ],
        already_imported=True,
    )

    result = await settle_forwarder(settle_up, ynab, ledger).handle(settled_event)

    assert result == Forwarded(SETTLED_ID, None)
    assert ynab.updates == [("existing", "cleared", None)]


async def test_settled_409_follow_up_failure_stays_forwarded(
    settled_event, settle_up, ledger
):
    ynab = FakeYnabClient(
        already_imported=True,
        errors={"list_transactions": UpstreamError("boom", 500)},
    )

    result = await settle_forwarder(settle_up, ynab, ledger).handle(settled_event)

    assert result == Forwarded(SETTLED_ID, None)
    assert ledger.entries[SETTLED_ID].status == "forwarded"


async def test_held_409_does_not_patch(settled_event, ledger):
    settled = load_tx("purchase_with_round_up_1")
    held = settled.model_copy(
        update={"attributes": settled.attributes.model_copy(update={"status": "HELD"})}
    )
    up = FakeUpClient(transactions={SETTLED_ID: held})
    ynab = FakeYnabClient(
        transactions=[
            ynab_transaction("existing", "Payee", None, import_id=SETTLED_ID)
        ],
        already_imported=True,
    )

    result = await settle_forwarder(up, ynab, ledger).handle(settled_event)

    assert result == Forwarded(SETTLED_ID, None)
    assert ynab.updates == []


DELETED_ID = "transactions-2001"


@pytest.fixture
def deleted_event():
    return load_event("TRANSACTION_DELETED_1")


def deleted_forwarder(ynab, ledger):
    return Forwarder(FakeUpClient(), ynab, FakeIndexHolder(ROUND_UP_INDEX), ledger)


def ynab_with(cleared, errors=None):
    return FakeYnabClient(
        transactions=[ynab_transaction("ynab-tx-1", "Shop", None, cleared=cleared)],
        errors=errors,
    )


async def seed_forwarded(ledger, ynab_id="ynab-tx-1"):
    await ledger.record(Forwarded(DELETED_ID, ynab_id))


class TestDeleted:
    async def test_uncleared_copy_is_deleted(self, deleted_event, ledger):
        ynab = ynab_with("uncleared")
        await seed_forwarded(ledger)

        result = await deleted_forwarder(ynab, ledger).handle(deleted_event)

        assert result == Deleted(DELETED_ID, "ynab-tx-1", False, "deleted in YNAB")
        assert ynab.deleted_ids == ["ynab-tx-1"]
        assert ledger.entries[DELETED_ID].status == "deleted"

    async def test_cleared_copy_is_flagged_red(self, deleted_event, ledger):
        ynab = ynab_with("cleared")
        await seed_forwarded(ledger)

        with capture_logs() as logs:
            result = await deleted_forwarder(ynab, ledger).handle(deleted_event)

        assert result == Deleted(
            DELETED_ID, "ynab-tx-1", True, "flagged red: cleared in YNAB"
        )
        assert ynab.flagged == [("ynab-tx-1", "red")]
        assert ynab.deleted_ids == []
        assert ledger.entries[DELETED_ID].status == "deleted"
        assert [
            log["log_level"]
            for log in logs
            if log["event"].startswith("Deleted in Up but already cleared")
        ] == ["warning"]

    async def test_reconciled_copy_is_flagged_red(self, deleted_event, ledger):
        ynab = ynab_with("reconciled")
        await seed_forwarded(ledger)

        result = await deleted_forwarder(ynab, ledger).handle(deleted_event)

        assert result == Deleted(
            DELETED_ID, "ynab-tx-1", True, "flagged red: reconciled in YNAB"
        )
        assert ynab.flagged == [("ynab-tx-1", "red")]

    async def test_copy_missing_in_ynab_counts_as_gone(self, deleted_event, ledger):
        ynab = FakeYnabClient()
        await seed_forwarded(ledger)

        result = await deleted_forwarder(ynab, ledger).handle(deleted_event)

        assert result == Deleted(
            DELETED_ID, "ynab-tx-1", False, "already deleted in YNAB"
        )
        assert ledger.entries[DELETED_ID].status == "deleted"

    async def test_copy_already_deleted_in_ynab(self, deleted_event, ledger):
        ynab = FakeYnabClient(
            transactions=[ynab_transaction("ynab-tx-1", "Shop", None, deleted=True)]
        )
        await seed_forwarded(ledger)

        result = await deleted_forwarder(ynab, ledger).handle(deleted_event)

        assert result == Deleted(
            DELETED_ID, "ynab-tx-1", False, "already deleted in YNAB"
        )
        assert ynab.deleted_ids == []

    async def test_delete_answering_404_counts_as_gone(self, deleted_event, ledger):
        ynab = ynab_with("uncleared", {"delete_transaction": UpstreamError("x", 404)})
        await seed_forwarded(ledger)

        result = await deleted_forwarder(ynab, ledger).handle(deleted_event)

        assert result == Deleted(
            DELETED_ID, "ynab-tx-1", False, "already deleted in YNAB"
        )

    async def test_never_seen_is_ignored_without_calling_ynab(
        self, deleted_event, ledger
    ):
        ynab = ynab_with("uncleared", {"get_transaction": UpstreamError("boom", 500)})

        result = await deleted_forwarder(ynab, ledger).handle(deleted_event)

        assert result == Ignored(DELETED_ID, "not forwarded to YNAB")
        assert ledger.entries == {}

    async def test_skipped_and_failed_rows_are_left(self, deleted_event, ledger):
        ynab = ynab_with("uncleared")
        forwarder = deleted_forwarder(ynab, ledger)
        await ledger.record(Skipped(DELETED_ID, "no account", "no_account"))

        skipped = await forwarder.handle(deleted_event)

        assert skipped == Ignored(DELETED_ID, "not forwarded to YNAB")
        assert ledger.entries[DELETED_ID].status == "skipped"

        ledger.entries.clear()
        await ledger.record(Failed(DELETED_ID, "boom"))

        failed = await forwarder.handle(deleted_event)

        assert failed == Ignored(DELETED_ID, "not forwarded to YNAB")
        assert ledger.entries[DELETED_ID].status == "failed"
        assert ynab.deleted_ids == []

    async def test_already_deleted_is_ignored(self, deleted_event, ledger):
        ynab = ynab_with("uncleared")
        await seed_forwarded(ledger)
        forwarder = deleted_forwarder(ynab, ledger)
        await forwarder.handle(deleted_event)

        result = await forwarder.handle(deleted_event)

        assert result == Ignored(DELETED_ID, "already deleted")
        assert ynab.deleted_ids == ["ynab-tx-1"]

    async def test_forwarded_without_ynab_id_is_ignored_with_warning(
        self, deleted_event, ledger
    ):
        ynab = ynab_with("uncleared")
        await seed_forwarded(ledger, None)

        with capture_logs() as logs:
            result = await deleted_forwarder(ynab, ledger).handle(deleted_event)

        assert result == Ignored(DELETED_ID, "forwarded without a YNAB id")
        assert ledger.entries[DELETED_ID].status == "forwarded"
        assert ynab.deleted_ids == []
        assert any(log["log_level"] == "warning" for log in logs)

    @pytest.mark.parametrize("method", ["get_transaction", "delete_transaction"])
    async def test_ynab_failure_is_failed_and_row_kept(
        self, deleted_event, ledger, method
    ):
        ynab = ynab_with("uncleared", {method: UpstreamError("boom", 500)})
        await seed_forwarded(ledger)

        result = await deleted_forwarder(ynab, ledger).handle(deleted_event)

        assert result == Failed(DELETED_ID, "boom")
        assert ledger.entries[DELETED_ID].status == "forwarded"
        assert ledger.entries[DELETED_ID].attempts == 1

    async def test_flag_failure_is_failed_and_row_kept(self, deleted_event, ledger):
        ynab = ynab_with("cleared", {"flag_transaction": UpstreamError("boom", 500)})
        await seed_forwarded(ledger)

        result = await deleted_forwarder(ynab, ledger).handle(deleted_event)

        assert result == Failed(DELETED_ID, "boom")
        assert ledger.entries[DELETED_ID].status == "forwarded"
        assert ledger.entries[DELETED_ID].attempts == 1

    async def test_record_error_is_failed_then_redelivery_converges(
        self, deleted_event, ledger
    ):
        ynab = ynab_with("uncleared")
        await seed_forwarded(ledger)
        forwarder = deleted_forwarder(ynab, ledger)
        ledger.errors["record"] = RuntimeError("db down")

        result = await forwarder.handle(deleted_event)

        assert result == Failed(DELETED_ID, "Could not record outcome")
        assert ynab.deleted_ids == ["ynab-tx-1"]

        del ledger.errors["record"]
        again = await forwarder.handle(deleted_event)

        assert again == Deleted(
            DELETED_ID, "ynab-tx-1", False, "already deleted in YNAB"
        )
        assert ledger.entries[DELETED_ID].status == "deleted"

    async def test_lookup_error_is_failed(self, deleted_event, ledger):
        ledger.errors["lookup"] = RuntimeError("db down")

        result = await deleted_forwarder(ynab_with("uncleared"), ledger).handle(
            deleted_event
        )

        assert result == Failed(DELETED_ID, "Unexpected error: db down")

    async def test_deleted_then_created_of_another_id_forwards(
        self, deleted_event, ledger
    ):
        ynab = ynab_with("uncleared")
        await seed_forwarded(ledger)
        up = FakeUpClient(
            transactions={"transactions-1": load_tx("purchase_with_round_up_1")}
        )
        forwarder = Forwarder(up, ynab, FakeIndexHolder(ROUND_UP_INDEX), ledger)
        await forwarder.handle(deleted_event)
        created = load_event("TRANSACTION_CREATED_1")

        result = await forwarder.handle(created)

        assert result == Forwarded("transactions-1", "ynab-1")

    @pytest.mark.parametrize(
        "name, up_id",
        [
            ("TRANSACTION_DELETED_2", "transactions-2002"),
            ("TRANSACTION_DELETED_3", "transactions-2003"),
        ],
    )
    async def test_other_delivered_events_with_empty_ledger(self, ledger, name, up_id):
        result = await deleted_forwarder(FakeYnabClient(), ledger).handle(
            load_event(name)
        )

        assert result == Ignored(up_id, "not forwarded to YNAB")


class TestBackfillOne:
    def make(self, fake_up, fake_ynab, ledger, index=INDEX):
        return Forwarder(fake_up, fake_ynab, FakeIndexHolder(index), ledger)

    async def test_new_transaction_is_forwarded_without_refetching(
        self, fake_up, fake_ynab, ledger
    ):
        fake_up.errors["get_transaction"] = UpstreamError("must not fetch", 500)
        forwarder = self.make(fake_up, fake_ynab, ledger)

        step = await forwarder.backfill_one(up_transaction("t-1"))

        assert step == BackfillStep(Forwarded("t-1", "ynab-1"), True)
        assert ledger.entries["t-1"].status == "forwarded"
        assert len(fake_ynab.created) == 1

    async def test_handled_transaction_is_ignored(self, fake_up, fake_ynab, ledger):
        await ledger.record(Forwarded("t-1", "ynab-9"))
        forwarder = self.make(fake_up, fake_ynab, ledger)

        step = await forwarder.backfill_one(up_transaction("t-1"))

        assert step == BackfillStep(Ignored("t-1", "already handled"), False)
        assert fake_ynab.created == []

    async def test_unmatched_account_skip_is_retried_once_matched(
        self, fake_up, fake_ynab, ledger
    ):
        await ledger.record(
            Skipped("t-1", "Up account not in YNAB", "account_not_in_ynab")
        )
        forwarder = self.make(fake_up, fake_ynab, ledger)

        step = await forwarder.backfill_one(up_transaction("t-1"))

        assert step == BackfillStep(Forwarded("t-1", "ynab-1"), True)
        assert ledger.entries["t-1"].status == "forwarded"
        assert ledger.entries["t-1"].reason_code is None
        assert ledger.entries["t-1"].attempts == 2

    async def test_still_unmatched_account_is_skipped_without_create(
        self, fake_up, fake_ynab, ledger
    ):
        await ledger.record(
            Skipped("t-1", "Up account not in YNAB", "account_not_in_ynab")
        )
        forwarder = self.make(fake_up, fake_ynab, ledger, BudgetIndex({}))

        step = await forwarder.backfill_one(up_transaction("t-1"))

        assert step == BackfillStep(
            Skipped("t-1", "Up account not in YNAB", "account_not_in_ynab"), False
        )

    async def test_already_in_ynab_is_forwarded(self, fake_up, fake_ynab, ledger):
        fake_ynab.already_imported = True
        forwarder = self.make(fake_up, fake_ynab, ledger)

        step = await forwarder.backfill_one(up_transaction("t-1"))

        assert step == BackfillStep(Forwarded("t-1", None), True)

    async def test_create_failure_is_failed_and_keeps_skip(
        self, fake_up, fake_ynab, ledger
    ):
        await ledger.record(
            Skipped("t-1", "Up account not in YNAB", "account_not_in_ynab")
        )
        fake_ynab.errors["create_transaction"] = UpstreamError("ynab down", 500)
        forwarder = self.make(fake_up, fake_ynab, ledger)

        step = await forwarder.backfill_one(up_transaction("t-1"))

        assert step == BackfillStep(Failed("t-1", "ynab down"), True)
        assert ledger.entries["t-1"].status == "skipped"

    async def test_index_unavailable_is_failed_without_create(
        self, fake_up, fake_ynab, ledger
    ):
        forwarder = Forwarder(fake_up, fake_ynab, FakeIndexHolder(None), ledger)

        step = await forwarder.backfill_one(up_transaction("t-1"))

        assert step == BackfillStep(Failed("t-1", "Budget Index unavailable"), False)
        assert ledger.entries["t-1"].status == "failed"

    async def test_transfer_leg_skipped_for_its_account_retries_as_ordinary(
        self, fake_up, fake_ynab, ledger
    ):
        both = BudgetIndex(
            {
                "accounts-4": YnabAccountRef("ynab-saver-3", "tp-saver-3"),
                "accounts-1": YnabAccountRef("ynab-spending", "tp-spending"),
            }
        )
        leg = load_tx("transfer_originating_1")
        await ledger.record(
            Skipped("transactions-87", "Up account not in YNAB", "account_not_in_ynab")
        )

        step = await self.make(fake_up, fake_ynab, ledger, both).backfill_one(leg)

        assert step == BackfillStep(Forwarded("transactions-87", "ynab-1"), True)
        created = fake_ynab.created[0]
        assert created.account_id == "ynab-saver-3"
        assert created.payee_id is None
        assert created.payee_name == leg.payee
        assert created.amount == -171000

    async def test_new_transfer_leg_in_backfill_uses_the_transfer_rule(
        self, fake_up, fake_ynab, ledger
    ):
        both = BudgetIndex(
            {
                "accounts-4": YnabAccountRef("ynab-saver-3", "tp-saver-3"),
                "accounts-1": YnabAccountRef("ynab-spending", "tp-spending"),
            }
        )

        step = await self.make(fake_up, fake_ynab, ledger, both).backfill_one(
            load_tx("transfer_originating_1")
        )

        assert step == BackfillStep(Forwarded("transactions-87", "ynab-1"), True)
        assert fake_ynab.created[0].payee_id == "tp-spending"
        assert fake_ynab.created[0].payee_name is None
