from dataclasses import dataclass
from typing import Protocol

import structlog

from clients.errors import UpstreamError
from clients.up import UpClient
from clients.ynab import Created, YnabClient
from forwarding.budget_index import BudgetIndex, IndexUnavailable
from forwarding.ledger import (
    Deleted,
    Failed,
    Forwarded,
    Ledger,
    Outcome,
    Skipped,
)
from forwarding.translation import Skip, cleared_status, translate, ynab_date
from models.up_models import UpWebhookEvent

logger = structlog.get_logger()


@dataclass(frozen=True)
class Ignored:
    """The event needs no action and leaves no Ledger row."""

    up_transaction_id: str | None
    reason: str


@dataclass(frozen=True)
class Settled:
    """The YNAB copy of a forwarded transaction was updated on settlement."""

    up_transaction_id: str
    ynab_transaction_id: str


HANDLED_EVENTS = (
    "TRANSACTION_CREATED",
    "TRANSACTION_SETTLED",
    "TRANSACTION_DELETED",
)


class IndexHolder(Protocol):
    async def current_for(self, up_account_id: str) -> BudgetIndex: ...


class Forwarder:
    """Turns an Up webhook event into a YNAB transaction and a Ledger entry."""

    def __init__(
        self,
        up: UpClient,
        ynab: YnabClient,
        budget_index_holder: IndexHolder,
        ledger: Ledger,
    ):
        self._up = up
        self._ynab = ynab
        self._holder = budget_index_holder
        self._ledger = ledger

    async def handle(
        self, event: UpWebhookEvent
    ) -> Forwarded | Skipped | Failed | Ignored | Settled | Deleted:
        event_type = event.data.event_type
        up_id = event.data.transaction_id
        if not up_id or event_type not in HANDLED_EVENTS:
            logger.info(
                "Ignoring event", event_type=event_type, up_transaction_id=up_id
            )
            return Ignored(up_id, "not a transaction event")

        if event_type == "TRANSACTION_DELETED":
            return await self._handle_deleted(up_id)

        if event_type == "TRANSACTION_SETTLED":
            try:
                state = await self._ledger.lookup(up_id)
                if state is not None and state.status == "forwarded":
                    return await self._settle(up_id, state.ynab_transaction_id)
            except Exception as e:
                # Record nothing: a forwarded row must not become failed.
                return self._failed(up_id, e)
            if state is not None and state.status == "skipped":
                logger.info("Ignoring skipped transaction", up_transaction_id=up_id)
                return Ignored(up_id, "skipped transaction")

        outcome: Outcome | Ignored
        try:
            if await self._ledger.is_handled(up_id):
                logger.info("Ignoring handled transaction", up_transaction_id=up_id)
                return Ignored(up_id, "already handled")
            outcome = await self._forward(up_id)
        except Exception as e:
            outcome = self._failed(up_id, e)

        try:
            await self._ledger.record(outcome)
        except Exception as e:
            logger.error(
                "Failed to record outcome",
                up_transaction_id=up_id,
                exc_info=e,
            )
            return Failed(up_id, "Could not record outcome")
        return outcome

    async def _handle_deleted(self, up_id: str) -> Deleted | Ignored | Failed:
        """Delete or flag the YNAB copy of a forwarded transaction Up deleted."""
        try:
            state = await self._ledger.lookup(up_id)
            if state is None or state.status in ("skipped", "failed"):
                logger.info(
                    "Deleted transaction was not forwarded", up_transaction_id=up_id
                )
                return Ignored(up_id, "not forwarded to YNAB")
            if state.status == "deleted":
                logger.info(
                    "Deleted transaction already handled", up_transaction_id=up_id
                )
                return Ignored(up_id, "already deleted")
            if not state.ynab_transaction_id:
                logger.warning(
                    "Deleted in Up but no YNAB id recorded; remove it in YNAB by hand",
                    up_transaction_id=up_id,
                )
                return Ignored(up_id, "forwarded without a YNAB id")
            outcome = await self._remove_from_ynab(up_id, state.ynab_transaction_id)
        except Exception as e:
            # Record nothing: a forwarded row must not become failed.
            return self._failed(up_id, e)

        try:
            await self._ledger.record(outcome)
        except Exception as e:
            logger.error(
                "Failed to record outcome", up_transaction_id=up_id, exc_info=e
            )
            return Failed(up_id, "Could not record outcome")
        return outcome

    async def _remove_from_ynab(self, up_id: str, ynab_id: str) -> Deleted:
        """Delete the YNAB copy if uncleared, else flag it red for review."""
        gone = Deleted(up_id, ynab_id, False, "already deleted in YNAB")
        try:
            tx = await self._ynab.get_transaction(ynab_id)
        except UpstreamError as e:
            if e.status_code != 404:
                raise
            logger.info("YNAB copy already gone", up_transaction_id=up_id)
            return gone
        if tx.deleted:
            logger.info("YNAB copy already gone", up_transaction_id=up_id)
            return gone
        if tx.cleared == "uncleared":
            try:
                await self._ynab.delete_transaction(ynab_id)
            except UpstreamError as e:
                if e.status_code != 404:
                    raise
                return gone
            logger.info(
                "Deleted YNAB copy",
                up_transaction_id=up_id,
                ynab_transaction_id=ynab_id,
            )
            return Deleted(up_id, ynab_id, False, "deleted in YNAB")
        await self._ynab.flag_transaction(ynab_id, "red")
        logger.warning(
            "Deleted in Up but already cleared in YNAB; flagged red",
            up_transaction_id=up_id,
            ynab_transaction_id=ynab_id,
            cleared=tx.cleared,
        )
        return Deleted(up_id, ynab_id, True, f"flagged red: {tx.cleared} in YNAB")

    def _failed(self, up_id: str, exc: Exception) -> Failed:
        if isinstance(exc, IndexUnavailable):
            logger.warning("Budget Index unavailable", up_transaction_id=up_id)
            return Failed(up_id, "Budget Index unavailable")
        if isinstance(exc, UpstreamError):
            logger.error(
                "Upstream call failed",
                up_transaction_id=up_id,
                status_code=exc.status_code,
                error=str(exc),
            )
            return Failed(up_id, str(exc))
        logger.error(
            "Unexpected error forwarding transaction",
            up_transaction_id=up_id,
            exc_info=exc,
        )
        return Failed(up_id, f"Unexpected error: {exc}")

    async def _settle(self, up_id: str, ynab_id: str | None) -> Settled | Ignored:
        """Mark the YNAB copy cleared and fix its amount; leave reconciled ones."""
        tx = await self._up.get_transaction(up_id)
        if ynab_id:
            try:
                ynab_tx = await self._ynab.get_transaction(ynab_id)
            except UpstreamError as e:
                if e.status_code != 404:
                    raise
                ynab_tx = None
            if ynab_tx is None or ynab_tx.deleted:
                logger.info(
                    "Transaction no longer in YNAB",
                    up_transaction_id=up_id,
                    ynab_transaction_id=ynab_id,
                )
                return Ignored(up_id, "not in YNAB")
        else:
            found = [
                t
                for t in await self._ynab.list_transactions(ynab_date(tx))
                if t.import_id == up_id and not t.deleted
            ]
            if not found:
                logger.warning("Transaction not found in YNAB", up_transaction_id=up_id)
                return Ignored(up_id, "not found in YNAB")
            ynab_tx = found[0]
        if ynab_tx.cleared == "reconciled":
            logger.info(
                "Leaving reconciled transaction",
                up_transaction_id=up_id,
                ynab_transaction_id=ynab_tx.id,
            )
            return Ignored(up_id, "reconciled in YNAB")
        amount_changed = ynab_tx.amount != tx.amount_milliunits
        await self._ynab.update_transaction(
            ynab_tx.id,
            cleared_status(tx),
            tx.amount_milliunits if amount_changed else None,
        )
        logger.info(
            "Transaction settled",
            up_transaction_id=up_id,
            ynab_transaction_id=ynab_tx.id,
            amount_changed=amount_changed,
        )
        return Settled(up_id, ynab_tx.id)

    async def _forward(self, up_id: str) -> Forwarded | Skipped:
        tx = await self._up.get_transaction(up_id)
        index = await self._holder.current_for(tx.account_id)
        translated = translate(tx, index)
        if isinstance(translated, Skip):
            logger.info(
                "Transaction skipped", up_transaction_id=up_id, reason=translated.reason
            )
            return Skipped(up_id, translated.reason)

        created = await self._ynab.create_transaction(translated)
        if isinstance(created, Created):
            logger.info(
                "Transaction forwarded",
                up_transaction_id=up_id,
                ynab_transaction_id=created.ynab_id,
                payee=tx.payee,
                category_id=translated.category_id,
            )
            return Forwarded(up_id, created.ynab_id)
        logger.info("Already in YNAB", up_transaction_id=up_id)
        if tx.attributes.status == "SETTLED":
            try:
                await self._settle(up_id, None)
            except Exception as e:
                # The transaction is in YNAB; a failed clear must not undo that.
                logger.warning(
                    "Could not mark existing YNAB copy cleared",
                    up_transaction_id=up_id,
                    error=str(e),
                )
        return Forwarded(up_id, None)
