from dataclasses import dataclass
from datetime import datetime

import structlog

from clients.up import UpClient
from forwarding.forwarder import Forwarder
from forwarding.ledger import Failed, Forwarded, Skipped

logger = structlog.get_logger()

# YNAB allows 200 requests an hour; this leaves room for webhooks and rebuilds.
YNAB_CREATE_LIMIT = 150


@dataclass(frozen=True)
class BackfillReport:
    """Counts from one backfill run."""

    forwarded: int
    skipped: int
    failed: int
    already_handled: int
    more_remaining: bool


async def backfill(
    up: UpClient,
    forwarder: Forwarder,
    since: datetime,
    limit: int = YNAB_CREATE_LIMIT,
) -> BackfillReport:
    """Forward Up transactions created since `since` that are not yet handled.

    Works oldest first and stops once `limit` YNAB creates have been attempted;
    more_remaining is then True (possibly a false positive, when everything
    left is already handled). Raises UpstreamError if Up cannot be listed.
    """
    logger.info("Backfill started", since=since.isoformat())
    transactions = sorted(
        await up.list_transactions(since), key=lambda t: t.attributes.created_at
    )
    forwarded = skipped = failed = already_handled = creates = 0
    more_remaining = False
    for tx in transactions:
        if creates >= limit:
            more_remaining = True
            break
        step = await forwarder.backfill_one(tx)
        creates += step.ynab_create_called
        outcome = step.outcome
        if isinstance(outcome, Forwarded):
            forwarded += 1
        elif isinstance(outcome, Skipped):
            skipped += 1
        elif isinstance(outcome, Failed):
            failed += 1
        else:
            already_handled += 1
    report = BackfillReport(forwarded, skipped, failed, already_handled, more_remaining)
    logger.info(
        "Backfill finished",
        forwarded=forwarded,
        skipped=skipped,
        failed=failed,
        already_handled=already_handled,
        more_remaining=more_remaining,
    )
    return report
