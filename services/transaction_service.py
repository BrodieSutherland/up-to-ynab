import hashlib
from typing import Optional

import structlog

from clients.errors import UpstreamError
from clients.up import UpClient
from clients.ynab import Created, YnabClient
from models.up_models import UpTransaction, UpWebhookEvent
from models.ynab_models import YnabTransactionDetail
from services.category_service import CategoryService
from utils.filters import TransactionFilter

logger = structlog.get_logger()


def create_import_id(up_transaction_id: str) -> str:
    """Create a unique import ID for YNAB (max 36 characters)."""
    # For UUIDs (36 chars), just use the UUID without prefix to stay within
    # limit
    if len(up_transaction_id) == 36 and "-" in up_transaction_id:
        return up_transaction_id

    # For shorter IDs, add "up_" prefix if it fits
    prefixed_id = f"up_{up_transaction_id}"
    if len(prefixed_id) <= 36:
        return prefixed_id

    # For longer IDs, use a hash to ensure uniqueness while staying under
    # limit
    hash_hex = hashlib.sha256(up_transaction_id.encode()).hexdigest()
    return hash_hex[:36]  # Use first 36 characters of hash


class TransactionService:
    """Main service for processing transactions from Up to YNAB."""

    def __init__(
        self,
        up: UpClient,
        ynab: YnabClient,
        category_service: CategoryService,
        transaction_filter: TransactionFilter,
        account_id: str,
    ):
        self.up = up
        self.ynab = ynab
        self.account_id = account_id
        self.category_service = category_service
        self.transaction_filter = transaction_filter

    def _should_process(self, webhook_event: UpWebhookEvent) -> bool:
        """Determine if a webhook event should be processed."""
        # Only process transaction creation events
        if webhook_event.data.event_type != "TRANSACTION_CREATED":
            logger.debug(
                "Ignoring non-transaction event",
                event_type=webhook_event.data.event_type,
            )
            return False

        # Must have transaction ID
        if not webhook_event.data.transaction_id:
            logger.warning("Transaction event missing transaction ID")
            return False

        return True

    async def process_webhook_event(self, webhook_event: UpWebhookEvent) -> str:
        """Process a webhook event from Up Bank."""
        logger.info(
            "Processing webhook event",
            event_type=webhook_event.data.event_type,
            transaction_id=webhook_event.data.transaction_id,
        )

        # Check if we should process this event
        if not self._should_process(webhook_event):
            return "Event ignored - not a transaction creation"

        # Get the transaction ID
        transaction_id = webhook_event.data.transaction_id
        if not transaction_id:
            return "Event ignored - no transaction ID"

        # Check if already processed
        if await self.category_service.is_transaction_processed(transaction_id):
            logger.info("Transaction already processed", transaction_id=transaction_id)
            return f"Transaction {transaction_id} already processed"

        # Fetch the transaction from Up
        try:
            up_transaction = await self.up.get_transaction(transaction_id)
        except UpstreamError as e:
            logger.error(
                "Failed to fetch Up transaction",
                transaction_id=transaction_id,
                status_code=e.status_code,
                error=str(e),
            )
            await self.category_service.record_processed_transaction(
                up_transaction_id=transaction_id,
                ynab_transaction_id=None,
                payee_name="Unknown",
                amount=0,
                transaction_date="",
                status="failed",
                error_message="Failed to fetch transaction from Up API",
            )
            return f"Failed to fetch transaction {transaction_id} from Up API"

        # Process the transaction
        result = await self.process_transaction(up_transaction)
        return result

    async def process_transaction(self, up_transaction: UpTransaction) -> str:
        """Process a single Up transaction."""
        logger.info(
            "Processing Up transaction",
            transaction_id=up_transaction.id,
            payee=up_transaction.payee,
            amount=up_transaction.attributes.amount.value,
        )

        try:
            # Apply filters
            if not self.transaction_filter.should_process_transaction(up_transaction):
                reason = self.transaction_filter.get_filtered_reason(up_transaction)
                logger.info(
                    "Transaction filtered out",
                    transaction_id=up_transaction.id,
                    reason=reason,
                )

                await self.category_service.record_processed_transaction(
                    up_transaction_id=up_transaction.id,
                    ynab_transaction_id=None,
                    payee_name=up_transaction.payee,
                    amount=up_transaction.amount_milliunits,
                    transaction_date=up_transaction.date,
                    status="skipped",
                    error_message=reason,
                )

                return f"Transaction filtered: {reason}"

            # Get payee category mappings
            payee_mappings = await self.category_service.get_payee_category_mappings()

            # Find category for this payee
            category_id = payee_mappings.get(up_transaction.payee)
            if category_id:
                logger.info(
                    "Found category mapping for payee",
                    payee=up_transaction.payee,
                    category_id=category_id,
                )
            else:
                logger.info(
                    "No category mapping found for payee", payee=up_transaction.payee
                )

            transaction_detail = YnabTransactionDetail(
                account_id=self.account_id,
                payee_name=up_transaction.payee,
                category_id=category_id,
                memo=up_transaction.attributes.raw_text or up_transaction.payee,
                amount=up_transaction.amount_milliunits,
                date=up_transaction.date,
                import_id=create_import_id(up_transaction.id),
            )

            # Create YNAB transaction
            created: Optional[Created] = None
            try:
                outcome = await self.ynab.create_transaction(transaction_detail)
            except UpstreamError as e:
                logger.error(
                    "Failed to create YNAB transaction",
                    up_transaction_id=up_transaction.id,
                    status_code=e.status_code,
                    error=str(e),
                )
            else:
                if isinstance(outcome, Created):
                    created = outcome
                else:
                    # ticket 05: Forwarded
                    logger.error(
                        "YNAB transaction already imported",
                        up_transaction_id=up_transaction.id,
                    )

            if created:
                # Record successful processing
                await self.category_service.record_processed_transaction(
                    up_transaction_id=up_transaction.id,
                    ynab_transaction_id=created.ynab_id,
                    payee_name=up_transaction.payee,
                    amount=up_transaction.amount_milliunits,
                    transaction_date=up_transaction.date,
                    status="processed",
                )

                logger.info(
                    "Transaction processed successfully",
                    up_transaction_id=up_transaction.id,
                    ynab_transaction_id=created.ynab_id,
                    payee=up_transaction.payee,
                    category_id=category_id,
                )

                return (
                    f"${up_transaction.attributes.amount.value} paid to "
                    f"{up_transaction.payee} at {up_transaction.date}"
                )
            else:
                # Record failed processing
                await self.category_service.record_processed_transaction(
                    up_transaction_id=up_transaction.id,
                    ynab_transaction_id=None,
                    payee_name=up_transaction.payee,
                    amount=up_transaction.amount_milliunits,
                    transaction_date=up_transaction.date,
                    status="failed",
                    error_message="Failed to create YNAB transaction",
                )

                return (
                    f"Failed to create YNAB transaction for " f"{up_transaction.payee}"
                )

        except Exception as e:
            logger.error(
                "Unexpected error processing transaction",
                transaction_id=up_transaction.id,
                error=str(e),
                exc_info=e,
            )

            # Record error
            await self.category_service.record_processed_transaction(
                up_transaction_id=up_transaction.id,
                ynab_transaction_id=None,
                payee_name=up_transaction.payee,
                amount=up_transaction.amount_milliunits,
                transaction_date=up_transaction.date,
                status="failed",
                error_message=str(e),
            )

            return f"Error processing transaction: {str(e)}"

    async def refresh_data(self) -> str:
        """Refresh category mappings from YNAB."""
        try:
            logger.info("Starting data refresh")
            await self.category_service.sync_categories_from_ynab()
            logger.info("Data refresh completed successfully")
            return "Data refreshed successfully"
        except Exception as e:
            logger.error("Failed to refresh data", error=str(e), exc_info=e)
            return f"Failed to refresh data: {str(e)}"
