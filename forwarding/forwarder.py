from dataclasses import dataclass
from typing import Protocol

import structlog

from clients.errors import UpstreamError
from clients.up import UpClient
from clients.ynab import Created, YnabClient
from forwarding.budget_index import BudgetIndex, IndexUnavailable
from forwarding.ledger import Failed, Forwarded, Ledger, Outcome, Skipped
from forwarding.translation import Skip, translate
from models.up_models import UpWebhookEvent

logger = structlog.get_logger()


@dataclass(frozen=True)
class Ignored:
    """The event needs no action and leaves no Ledger row."""

    up_transaction_id: str | None
    reason: str


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
    ) -> Forwarded | Skipped | Failed | Ignored:
        event_type = event.data.event_type
        up_id = event.data.transaction_id
        if event_type != "TRANSACTION_CREATED" or not up_id:
            logger.info(
                "Ignoring event", event_type=event_type, up_transaction_id=up_id
            )
            return Ignored(up_id, "not a transaction creation")

        outcome: Outcome | Ignored
        try:
            if await self._ledger.is_handled(up_id):
                logger.info("Ignoring handled transaction", up_transaction_id=up_id)
                return Ignored(up_id, "already handled")
            outcome = await self._forward(up_id)
        except IndexUnavailable:
            logger.warning("Budget Index unavailable", up_transaction_id=up_id)
            outcome = Failed(up_id, "Budget Index unavailable")
        except UpstreamError as e:
            logger.error(
                "Upstream call failed",
                up_transaction_id=up_id,
                status_code=e.status_code,
                error=str(e),
            )
            outcome = Failed(up_id, str(e))
        except Exception as e:
            logger.error(
                "Unexpected error forwarding transaction",
                up_transaction_id=up_id,
                exc_info=e,
            )
            outcome = Failed(up_id, f"Unexpected error: {e}")

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
        return Forwarded(up_id, None)
