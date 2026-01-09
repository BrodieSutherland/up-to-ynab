from datetime import UTC, datetime
from typing import Dict, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import db_manager
from database.models import PayeeCategoryMapping, ProcessedTransaction
from services.ynab_service import YnabService

logger = structlog.get_logger()


class CategoryService:
    """Service for managing payee-category mappings and database sync."""

    def __init__(self):
        self.ynab_service = YnabService()

    async def sync_categories_from_ynab(self) -> None:
        """Sync category mappings from YNAB transactions."""
        logger.info("Starting category sync from YNAB")

        try:
            # Get all categories and payees from YNAB
            categories = await self.ynab_service.get_categories()
            payees = await self.ynab_service.get_payees()

            logger.info(
                "Retrieved YNAB data for sync",
                categories_count=len(categories),
                payees_count=len(payees),
            )

            # TODO: Implement actual transaction history analysis
            # For now, we'll just ensure the database structure is ready
            async with db_manager.get_session() as session:
                await self._ensure_database_ready(session)

            logger.info("Category sync completed successfully")

        except Exception as e:
            logger.error(
                "Failed to sync categories from YNAB", error=str(e), exc_info=e
            )
            raise

    async def get_payee_category_mappings(self) -> Dict[str, str]:
        """Get all payee to category ID mappings."""
        try:
            async with db_manager.get_session() as session:
                stmt = select(PayeeCategoryMapping).where(
                    PayeeCategoryMapping.is_active.is_(True)
                )
                result = await session.execute(stmt)
                mappings = result.scalars().all()

                mapping_dict = {
                    mapping.payee_name: mapping.category_id
                    for mapping in mappings
                }

                logger.info(
                    "Retrieved payee category mappings",
                    count=len(mapping_dict),
                )
                return mapping_dict

        except Exception as e:
            logger.error(
                "Failed to retrieve payee category mappings",
                error=str(e),
                exc_info=e,
            )
            return {}

    async def update_payee_category_mapping(
        self, payee_name: str, category_id: str, category_name: str
    ) -> None:
        """Update or create a payee-category mapping."""
        try:
            async with db_manager.get_session() as session:
                # Check if mapping exists
                stmt = select(PayeeCategoryMapping).where(
                    PayeeCategoryMapping.payee_name == payee_name
                )
                result = await session.execute(stmt)
                existing_mapping = result.scalar_one_or_none()

                if existing_mapping:
                    # Update existing mapping
                    existing_mapping.category_id = category_id
                    existing_mapping.category_name = category_name
                    existing_mapping.last_updated = datetime.now(UTC)
                    existing_mapping.transaction_count += 1

                    logger.info(
                        "Updated payee category mapping",
                        payee=payee_name,
                        category=category_name,
                        transaction_count=existing_mapping.transaction_count,
                    )
                else:
                    # Create new mapping
                    new_mapping = PayeeCategoryMapping(
                        payee_name=payee_name,
                        category_id=category_id,
                        category_name=category_name,
                    )
                    session.add(new_mapping)

                    logger.info(
                        "Created new payee category mapping",
                        payee=payee_name,
                        category=category_name,
                    )

                await session.commit()

        except Exception as e:
            logger.error(
                "Failed to update payee category mapping",
                payee=payee_name,
                category=category_name,
                error=str(e),
                exc_info=e,
            )
            raise

    async def record_processed_transaction(
        self,
        up_transaction_id: str,
        ynab_transaction_id: Optional[str],
        payee_name: str,
        amount: int,
        transaction_date: str,
        status: str = "processed",
        error_message: Optional[str] = None,
    ) -> None:
        """Record a processed transaction to avoid duplicates."""
        try:
            async with db_manager.get_session() as session:
                processed_tx = ProcessedTransaction(
                    up_transaction_id=up_transaction_id,
                    ynab_transaction_id=ynab_transaction_id,
                    payee_name=payee_name,
                    amount=amount,
                    transaction_date=transaction_date,
                    status=status,
                    error_message=error_message,
                )
                session.add(processed_tx)
                await session.commit()

                logger.info(
                    "Recorded processed transaction",
                    up_transaction_id=up_transaction_id,
                    payee=payee_name,
                    status=status,
                )

        except Exception as e:
            logger.error(
                "Failed to record processed transaction",
                up_transaction_id=up_transaction_id,
                error=str(e),
                exc_info=e,
            )
            # Don't raise - this is not critical for main workflow

    async def is_transaction_processed(self, up_transaction_id: str) -> bool:
        """Check if a transaction has already been processed."""
        try:
            async with db_manager.get_session() as session:
                stmt = select(ProcessedTransaction).where(
                    ProcessedTransaction.up_transaction_id == up_transaction_id
                )
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()

                return existing is not None

        except Exception as e:
            logger.error(
                "Failed to check if transaction is processed",
                up_transaction_id=up_transaction_id,
                error=str(e),
                exc_info=e,
            )
            # Err on the side of caution - assume not processed
            return False

    async def _ensure_database_ready(self, session: AsyncSession) -> None:
        """Ensure database tables exist and are ready."""
        # This is handled by the database manager's create_tables method
        # Just a placeholder for any additional database setup
        pass
