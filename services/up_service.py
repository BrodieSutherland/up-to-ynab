from typing import Optional

import httpx
import structlog

from models.up_models import UpTransaction, UpTransactionResponse, UpWebhookEvent
from utils.config import get_settings


logger = structlog.get_logger()


class UpService:
    """Service for interacting with Up Bank API."""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.up_base_url.rstrip("/")

        # Validate Up API token is present
        if not self.settings.up_api_token or self.settings.up_api_token.strip() == "":
            raise ValueError("Up API token is required but not provided")

        self.headers = {
            "Authorization": f"Bearer {self.settings.up_api_token.strip()}",
            "Content-Type": "application/json",
        }

        logger.info(self.headers)

    async def get_transaction(self, transaction_id: str) -> Optional[UpTransaction]:
        """Fetch a transaction from Up API."""
        url = f"{self.base_url}/transactions/{transaction_id}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self.headers)
                response.raise_for_status()

                data = response.json()
                transaction_response = UpTransactionResponse(**data)
                return transaction_response.data

        except httpx.HTTPStatusError as e:
            logger.error(
                "Failed to fetch Up transaction",
                transaction_id=transaction_id,
                status_code=e.response.status_code,
                error=str(e)
            )
            return None
        except Exception as e:
            logger.error(
                "Unexpected error fetching Up transaction",
                transaction_id=transaction_id,
                error=str(e),
                exc_info=e
            )
            return None

    async def create_webhook(self, webhook_url: str) -> bool:
        """Create a webhook subscription with Up Bank."""
        url = f"{self.base_url}/webhooks"
        payload = {
            "data": {
                "attributes": {
                    "url": webhook_url,
                    "description": "UP to YNAB transaction sync webhook"
                }
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=self.headers)
                response.raise_for_status()

                webhook_data = response.json()
                webhook_id = webhook_data["data"]["id"]

                logger.info("Webhook created successfully", webhook_id=webhook_id, url=webhook_url)
                return True

        except httpx.HTTPStatusError as e:
            logger.error(
                "Failed to create webhook",
                url=webhook_url,
                status_code=e.response.status_code,
                error=str(e)
            )
            return False
        except Exception as e:
            logger.error(
                "Unexpected error creating webhook",
                url=webhook_url,
                error=str(e),
                exc_info=e
            )
            return False

    async def list_webhooks(self) -> list:
        """List all existing webhooks."""
        url = f"{self.base_url}/webhooks"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self.headers)
                response.raise_for_status()

                data = response.json()
                webhooks = data.get("data", [])

                logger.info("Retrieved webhooks", count=len(webhooks))
                return webhooks

        except httpx.HTTPStatusError as e:
            logger.error(
                "Failed to list webhooks",
                status_code=e.response.status_code,
                error=str(e)
            )
            return []
        except Exception as e:
            logger.error(
                "Unexpected error listing webhooks",
                error=str(e),
                exc_info=e
            )
            return []

    async def webhook_exists(self, webhook_url: str) -> bool:
        """Check if a webhook already exists for the given URL."""
        webhooks = await self.list_webhooks()

        for webhook in webhooks:
            webhook_attributes = webhook.get("attributes", {})
            if webhook_attributes.get("url") == webhook_url:
                logger.info("Webhook already exists", url=webhook_url)
                return True

        return False

    async def ping_webhook(self, webhook_url: str) -> bool:
        """Check if webhook exists, create if it doesn't."""
        if await self.webhook_exists(webhook_url):
            return True

        logger.info("Webhook not found, creating new one", url=webhook_url)
        return await self.create_webhook(webhook_url)

    def is_internal_transfer(self, transaction: UpTransaction) -> bool:
        """Check if transaction is an internal transfer that should be filtered."""
        return transaction.is_internal_transfer

    def should_process_transaction(self, webhook_event: UpWebhookEvent) -> bool:
        """Determine if a webhook event should be processed."""
        # Only process transaction creation events
        if webhook_event.data.event_type != "TRANSACTION_CREATED":
            logger.debug("Ignoring non-transaction event", event_type=webhook_event.data.event_type)
            return False

        # Must have transaction ID
        if not webhook_event.data.transaction_id:
            logger.warning("Transaction event missing transaction ID")
            return False

        return True