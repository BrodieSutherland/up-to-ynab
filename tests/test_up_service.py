from unittest.mock import Mock, patch

import httpx
import pytest

from models.up_models import UpWebhookEvent
from services.up_service import UpService


class TestUpService:
    """Test cases for Up Bank service."""

    @pytest.fixture
    def up_service(self, test_settings):
        """Create UpService instance with test settings."""
        with patch(
            "services.up_service.get_settings", return_value=test_settings
        ):
            return UpService()

    @pytest.mark.asyncio
    async def test_get_transaction_success(
        self, up_service, sample_up_transaction_data
    ):
        """Test successful transaction retrieval."""
        mock_response = Mock()
        mock_response.json.return_value = sample_up_transaction_data
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = mock_client.return_value.__aenter__.return_value.get
            mock_get.return_value = mock_response

            transaction = await up_service.get_transaction(
                "test-transaction-id"
            )

            assert transaction is not None
            assert transaction.id == "test-transaction-id"
            assert transaction.payee == "Test Merchant"
            assert transaction.amount_milliunits == -12500

    @pytest.mark.asyncio
    async def test_get_transaction_http_error(self, up_service):
        """Test transaction retrieval with HTTP error."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=Mock(), response=mock_response
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = mock_client.return_value.__aenter__.return_value.get
            mock_get.return_value = mock_response

            transaction = await up_service.get_transaction("non-existent-id")

            assert transaction is None

    @pytest.mark.asyncio
    async def test_create_webhook_success(self, up_service):
        """Test successful webhook creation."""
        webhook_response = {
            "data": {"id": "test-webhook-id", "type": "webhooks"}
        }

        mock_response = Mock()
        mock_response.json.return_value = webhook_response
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = mock_client.return_value.__aenter__.return_value.post
            mock_post.return_value = mock_response

            result = await up_service.create_webhook(
                "https://test.example.com/webhook"
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_create_webhook_failure(self, up_service):
        """Test webhook creation failure."""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=Mock(), response=mock_response
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = mock_client.return_value.__aenter__.return_value.post
            mock_post.return_value = mock_response

            result = await up_service.create_webhook("https://invalid-url")

            assert result is False

    @pytest.mark.asyncio
    async def test_list_webhooks(self, up_service):
        """Test listing webhooks."""
        webhooks_response = {
            "data": [
                {
                    "id": "webhook-1",
                    "attributes": {"url": "https://test1.example.com/webhook"},
                },
                {
                    "id": "webhook-2",
                    "attributes": {"url": "https://test2.example.com/webhook"},
                },
            ]
        }

        mock_response = Mock()
        mock_response.json.return_value = webhooks_response
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = mock_client.return_value.__aenter__.return_value.get
            mock_get.return_value = mock_response

            webhooks = await up_service.list_webhooks()

            assert len(webhooks) == 2
            assert webhooks[0]["id"] == "webhook-1"

    @pytest.mark.asyncio
    async def test_webhook_exists_true(self, up_service):
        """Test webhook existence check - exists."""
        webhooks_response = {
            "data": [
                {
                    "id": "webhook-1",
                    "attributes": {"url": "https://test.example.com/webhook"},
                }
            ]
        }

        mock_response = Mock()
        mock_response.json.return_value = webhooks_response
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = mock_client.return_value.__aenter__.return_value.get
            mock_get.return_value = mock_response

            exists = await up_service.webhook_exists(
                "https://test.example.com/webhook"
            )

            assert exists is True

    @pytest.mark.asyncio
    async def test_webhook_exists_false(self, up_service):
        """Test webhook existence check - doesn't exist."""
        webhooks_response = {"data": []}

        mock_response = Mock()
        mock_response.json.return_value = webhooks_response
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = mock_client.return_value.__aenter__.return_value.get
            mock_get.return_value = mock_response

            exists = await up_service.webhook_exists(
                "https://test.example.com/webhook"
            )

            assert exists is False

    def test_should_process_transaction_valid(
        self, up_service, sample_up_webhook_event_data
    ):
        """Test should process transaction - valid event."""
        webhook_event = UpWebhookEvent(**sample_up_webhook_event_data)

        should_process = up_service.should_process_transaction(webhook_event)

        assert should_process is True

    def test_should_process_transaction_wrong_event_type(self, up_service):
        """Test should process transaction - wrong event type."""
        webhook_data = {
            "data": {
                "type": "webhook-events",
                "id": "test-event-id",
                "attributes": {
                    "eventType": "TRANSACTION_UPDATED",
                    "createdAt": "2024-01-01T12:00:00+00:00",
                },
                "relationships": {
                    "transaction": {
                        "data": {
                            "type": "transactions",
                            "id": "test-transaction-id",
                        }
                    }
                },
            }
        }

        webhook_event = UpWebhookEvent(**webhook_data)

        should_process = up_service.should_process_transaction(webhook_event)

        assert should_process is False

    def test_should_process_transaction_no_transaction_id(self, up_service):
        """Test should process transaction - no transaction ID."""
        webhook_data = {
            "data": {
                "type": "webhook-events",
                "id": "test-event-id",
                "attributes": {
                    "eventType": "TRANSACTION_CREATED",
                    "createdAt": "2024-01-01T12:00:00+00:00",
                },
                "relationships": {},
            }
        }

        webhook_event = UpWebhookEvent(**webhook_data)

        should_process = up_service.should_process_transaction(webhook_event)

        assert should_process is False
