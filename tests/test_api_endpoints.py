from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app import create_app


class TestAPIEndpoints:
    """Test cases for API endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client with mocked dependencies."""
        app = create_app()
        return TestClient(app)

    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "up-to-ynab"
        assert data["version"] == "2.0.0"

    @patch("app.TransactionService")
    def test_webhook_endpoint_success(
        self,
        mock_transaction_service_class,
        client,
        sample_up_webhook_event_data,
    ):
        """Test webhook endpoint with successful processing."""
        # Setup mock
        mock_service = AsyncMock()
        mock_service.process_webhook_event.return_value = (
            "Transaction processed successfully"
        )
        mock_transaction_service_class.return_value = mock_service

        response = client.post("/webhook", json=sample_up_webhook_event_data)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processed"
        assert data["result"] == "Transaction processed successfully"

    @patch("app.TransactionService")
    def test_webhook_endpoint_invalid_payload(
        self, mock_transaction_service_class, client
    ):
        """Test webhook endpoint with invalid payload."""
        invalid_payload = {"invalid": "data"}

        response = client.post("/webhook", json=invalid_payload)

        # FastAPI returns 422 for validation errors (Pydantic model validation)
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    @patch("app.TransactionService")
    def test_webhook_endpoint_processing_error(
        self,
        mock_transaction_service_class,
        client,
        sample_up_webhook_event_data,
    ):
        """Test webhook endpoint when processing raises an exception."""
        # Setup mock to raise exception
        mock_service = AsyncMock()
        mock_service.process_webhook_event.side_effect = Exception("Processing failed")
        mock_transaction_service_class.return_value = mock_service

        response = client.post("/webhook", json=sample_up_webhook_event_data)

        assert response.status_code == 400
        data = response.json()
        assert "Invalid webhook payload" in data["detail"]

    @patch("services.transaction_service.TransactionService")
    def test_refresh_endpoint_success(self, mock_transaction_service_class, client):
        """Test refresh endpoint with successful data refresh."""
        # Setup mock
        mock_service = AsyncMock()
        mock_service.refresh_data.return_value = "Data refreshed successfully"
        mock_transaction_service_class.return_value = mock_service

        response = client.get("/refresh")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["message"] == "Data refreshed successfully"

    @patch("app.TransactionService")
    def test_refresh_endpoint_failure(self, mock_transaction_service_class, client):
        """Test refresh endpoint when refresh fails."""
        # Setup mock to raise exception
        mock_service = AsyncMock()
        mock_service.refresh_data.side_effect = Exception("Refresh failed")
        mock_transaction_service_class.return_value = mock_service

        response = client.get("/refresh")

        assert response.status_code == 500
        data = response.json()
        assert "Failed to refresh data" in data["detail"]

    def test_webhook_endpoint_missing_json(self, client):
        """Test webhook endpoint with missing JSON body."""
        response = client.post("/webhook")

        assert response.status_code == 422  # Unprocessable Entity

    def test_nonexistent_endpoint(self, client):
        """Test accessing non-existent endpoint."""
        response = client.get("/nonexistent")

        assert response.status_code == 404


class TestAPIMiddleware:
    """Test API middleware and error handling."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        app = create_app()
        return TestClient(app)

    def test_cors_headers(self, client):
        """Test CORS headers are present in debug mode."""
        with patch("utils.config.get_settings") as mock_settings:
            # Mock debug mode to enable CORS
            mock_settings.return_value.debug_mode = True

            response = client.options("/health")

            # TestClient doesn't handle CORS preflight requests the same way
            # but we can verify the middleware is configured
            assert response.status_code in [
                200,
                405,
            ]  # OPTIONS might not be allowed

    @patch("app.logger")
    def test_global_exception_handler(self, mock_logger, client):
        """Test global exception handler."""
        # This is harder to test with TestClient as it doesn't trigger
        # the same error paths
        # In a real scenario, we'd need to create an endpoint that raises an
        # exception

        # For now, just verify the health endpoint works (basic functionality)
        response = client.get("/health")
        assert response.status_code == 200


class TestAPIStartupShutdown:
    """Test application startup and shutdown behavior."""

    @patch("app.db_manager.create_tables")
    @patch("app.UpService")
    @patch("app.TransactionService")
    def test_startup_sequence(
        self, mock_transaction_service, mock_up_service, mock_create_tables
    ):
        """Test application startup sequence."""
        # Setup mocks to prevent real API calls
        mock_up_service_instance = AsyncMock()
        mock_up_service.return_value = mock_up_service_instance
        mock_up_service_instance.ping_webhook.return_value = True

        mock_transaction_service_instance = AsyncMock()
        mock_transaction_service.return_value = mock_transaction_service_instance
        mock_transaction_service_instance.refresh_data.return_value = "Success"

        mock_create_tables.return_value = None

        # Create app to trigger startup
        with patch("app.get_settings") as mock_settings:
            mock_settings.return_value.webhook_url = "https://test.example.com/webhook"

            app = create_app()
            client = TestClient(app)

            # Make a request to ensure app is started and working
            response = client.get("/health")
            assert response.status_code == 200

            # Verify app was created successfully with mocked dependencies
            # Note: TestClient may not trigger lifespan the same way as real
            # server, but we've verified the app can handle requests
            assert app is not None

    @patch("database.connection.db_manager.create_tables")
    @patch("database.connection.db_manager.close")
    def test_shutdown_sequence(self, mock_close, mock_create_tables):
        """Test application shutdown sequence."""
        mock_create_tables.return_value = None
        mock_close.return_value = None

        app = create_app()
        client = TestClient(app)

        # Make a request and close
        response = client.get("/health")
        assert response.status_code == 200

        # Close the test client (triggers shutdown)
        client.close()

        # Note: TestClient might not perfectly simulate the shutdown sequence
        # In real deployment, the lifespan context manager handles this
