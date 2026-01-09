from typing import Dict, List, Optional

import httpx
import structlog

from models.up_models import UpTransaction
from models.ynab_models import (
    YnabBudget,
    YnabCategory,
    YnabPayee,
    YnabTransactionDetail,
    YnabTransactionRequest,
    YnabTransactionResponse,
)
from utils.config import get_settings
from utils.validation import is_validation_error, log_validation_error

logger = structlog.get_logger()


class YnabService:
    """Service for interacting with YNAB API."""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.ynab_base_url.rstrip("/")

        # Validate YNAB API token is present
        if (
            not self.settings.ynab_api_token
            or self.settings.ynab_api_token.strip() == ""
        ):
            raise ValueError("YNAB API token is required but not provided")

        self.headers = {
            "Authorization": f"Bearer {self.settings.ynab_api_token.strip()}",
            "Content-Type": "application/json",
        }

    async def create_transaction(
        self, up_transaction: UpTransaction, category_id: Optional[str] = None
    ) -> Optional[YnabTransactionResponse]:
        """Create a YNAB transaction from an Up transaction."""
        # Create YNAB transaction detail
        transaction_detail = YnabTransactionDetail(
            account_id=self.settings.ynab_account_id,
            payee_name=up_transaction.payee,
            category_id=category_id,
            memo=up_transaction.attributes.raw_text or up_transaction.payee,
            amount=up_transaction.amount_milliunits,
            date=up_transaction.date,
            import_id=self.create_import_id(up_transaction.id),
        )

        transaction_request = YnabTransactionRequest(
            transaction=transaction_detail
        )

        url = (
            f"{self.base_url}/budgets/{self.settings.ynab_budget_id}"
            f"/transactions"
        )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=transaction_request.model_dump(by_alias=True),
                    headers=self.headers,
                )
                response.raise_for_status()

                data = response.json()
                transaction_data = data["data"]["transaction"]

                logger.info(
                    "YNAB transaction created successfully",
                    up_transaction_id=up_transaction.id,
                    ynab_transaction_id=transaction_data["id"],
                    payee=up_transaction.payee,
                    amount=up_transaction.amount_milliunits,
                )

                return YnabTransactionResponse(**transaction_data)

        except httpx.HTTPStatusError as e:
            logger.error(
                "Failed to create YNAB transaction",
                up_transaction_id=up_transaction.id,
                status_code=e.response.status_code,
                error=str(e),
                response_text=e.response.text,
            )
            return None
        except Exception as e:
            logger.error(
                "Unexpected error creating YNAB transaction",
                up_transaction_id=up_transaction.id,
                error=str(e),
                exc_info=e,
            )
            return None

    async def get_budget(self) -> Optional[YnabBudget]:
        """Fetch the YNAB budget with all data."""
        url = f"{self.base_url}/budgets/{self.settings.ynab_budget_id}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self.headers)
                response.raise_for_status()

                data = response.json()
                budget_data = data["data"]["budget"]

                logger.info("Retrieved YNAB budget data")
                return YnabBudget(**budget_data)

        except Exception as e:
            if is_validation_error(e):
                log_validation_error(
                    e, "YNAB budget", budget_id=self.settings.ynab_budget_id
                )
                return None
            elif isinstance(e, httpx.HTTPStatusError):
                logger.error(
                    "Failed to fetch YNAB budget",
                    budget_id=self.settings.ynab_budget_id,
                    status_code=e.response.status_code,
                    error=str(e),
                )
                return None
            else:
                logger.error(
                    "Unexpected error fetching YNAB budget",
                    budget_id=self.settings.ynab_budget_id,
                    error=str(e),
                    exc_info=e,
                )
                return None

    async def get_categories(self) -> List[YnabCategory]:
        """Get all categories from YNAB budget."""
        budget = await self.get_budget()
        if not budget:
            return []

        logger.info("Retrieved YNAB categories", count=len(budget.categories))
        return budget.categories

    async def get_payees(self) -> List[YnabPayee]:
        """Get all payees from YNAB budget."""
        budget = await self.get_budget()
        if not budget:
            return []

        logger.info("Retrieved YNAB payees", count=len(budget.payees))
        return budget.payees

    async def find_category_for_payee(
        self,
        payee_name: str,
        payee_category_mappings: Dict[str, str],
    ) -> Optional[str]:
        """Find category for payee based on historical mappings."""
        # Check if we have a stored mapping for this payee
        category_id = payee_category_mappings.get(payee_name)

        if category_id:
            logger.info(
                "Found category mapping for payee",
                payee=payee_name,
                category_id=category_id,
            )
            return category_id

        logger.info("No category mapping found for payee", payee=payee_name)
        return None

    def create_import_id(self, up_transaction_id: str) -> str:
        """Create a unique import ID for YNAB (max 36 characters)."""
        import hashlib

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
