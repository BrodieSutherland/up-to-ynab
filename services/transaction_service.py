import structlog

from models.up_models import UpTransaction, UpWebhookEvent
from services.category_service import CategoryService
from services.up_service import UpService
from services.ynab_service import YnabService
from utils.filters import TransactionFilter

logger = structlog.get_logger()


class TransactionService:
    """Main service for processing transactions from Up to YNAB."""

    def __init__(self):
        self.up_service = UpService()
        self.ynab_service = YnabService()
        self.category_service = CategoryService()
        self.transaction_filter = TransactionFilter()

    async def process_webhook_event(self, webhook_event: UpWebhookEvent) -> str:
        """Process a webhook event from Up Bank."""
        logger.info(
            "Processing webhook event",
            event_type=webhook_event.data.event_type,
            transaction_id=webhook_event.data.transaction_id,
        )

        # Check if we should process this event
        if not self.up_service.should_process_transaction(webhook_event):
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
        up_transaction = await self.up_service.get_transaction(transaction_id)
        if not up_transaction:
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
            category_id = await self.ynab_service.find_category_for_payee(
                up_transaction.payee, payee_mappings
            )

            # Create YNAB transaction
            ynab_transaction = await self.ynab_service.create_transaction(
                up_transaction, category_id
            )

            if ynab_transaction:
                # Record successful processing
                await self.category_service.record_processed_transaction(
                    up_transaction_id=up_transaction.id,
                    ynab_transaction_id=ynab_transaction.id,
                    payee_name=up_transaction.payee,
                    amount=up_transaction.amount_milliunits,
                    transaction_date=up_transaction.date,
                    status="processed",
                )

                logger.info(
                    "Transaction processed successfully",
                    up_transaction_id=up_transaction.id,
                    ynab_transaction_id=ynab_transaction.id,
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
