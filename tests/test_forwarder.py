import pytest

from clients.errors import UpstreamError
from forwarding.budget_index import (
    BudgetIndex,
    NotInYnab,
    YnabAccountRef,
)
from forwarding.forwarder import Forwarder, Ignored
from forwarding.ledger import Failed, Forwarded, Skipped
from models.up_models import UpTransaction, UpWebhookEvent
from tests.fakes.budget_index import FakeIndexHolder
from tests.fakes.ledger import InMemoryLedger
from tests.fakes.up import FakeUpClient

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

    assert result == Skipped("test-transaction-id", "Mirror side of a Transfer")
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
    sample_up_webhook_event_data["data"]["attributes"][
        "eventType"
    ] = "TRANSACTION_SETTLED"

    result = await forwarder.handle(UpWebhookEvent(**sample_up_webhook_event_data))

    assert result == Ignored("test-transaction-id", "not a transaction creation")
    assert ledger.entries == {}


async def test_created_without_transaction_id_is_ignored(
    forwarder, sample_up_webhook_event_data, ledger
):
    sample_up_webhook_event_data["data"]["relationships"] = None

    result = await forwarder.handle(UpWebhookEvent(**sample_up_webhook_event_data))

    assert result == Ignored(None, "not a transaction creation")
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

    assert result == Skipped("test-transaction-id", "Up account not in YNAB")
    assert fake_ynab.created == []
    assert ledger.entries["test-transaction-id"].status == "skipped"
