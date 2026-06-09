"""
Real-container integration tests for up-to-ynab.

These tests build the Docker image, start the container with fake credentials,
and fire real HTTP requests at it — testing the app as a black box.

Requires Docker to be available. These tests are skipped automatically if
Docker is not reachable (e.g. in environments without Docker daemon access).

In CI these run in the `integration-test-container` job which is separate
from the unit test job and only runs on `develop` branch pushes.
"""

import json
import os
import time

import httpx
import pytest

# ---------------------------------------------------------------------------
# Docker availability check — skip all tests gracefully if no daemon
# ---------------------------------------------------------------------------

try:
    import docker as docker_sdk

    _docker_client = docker_sdk.from_env()
    _docker_client.ping()
    DOCKER_AVAILABLE = True
except Exception:
    DOCKER_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not DOCKER_AVAILABLE,
    reason="Docker daemon not available",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IMAGE_TAG = "up-to-ynab:integration-test"
CONTAINER_NAME = "up-to-ynab-integration-test"
HOST_PORT = 5099  # Distinct port to avoid conflicts with any running instance
BASE_URL = f"http://localhost:{HOST_PORT}"

FAKE_ENV = {
    "PORT": "5001",
    "DEBUG_MODE": "true",
    "UP_API_TOKEN": "test-fake-token",
    "UP_BASE_URL": "https://api.up.com.au/api/v1/",
    "YNAB_API_TOKEN": "test-fake-ynab-token",
    "YNAB_BUDGET_ID": "test-budget-id",
    "YNAB_ACCOUNT_ID": "test-account-id",
    "YNAB_BASE_URL": "https://api.youneedabudget.com/v1/",
    "DATABASE_URL": "sqlite+aiosqlite:///./data/up_to_ynab.db",
}

VALID_WEBHOOK_PAYLOAD = {
    "data": {
        "type": "webhook-events",
        "id": "test-event-id",
        "attributes": {
            "eventType": "TRANSACTION_CREATED",
            "createdAt": "2024-06-01T10:00:00+10:00",
        },
        "relationships": {
            "transaction": {
                "data": {"type": "transactions", "id": "test-txn-id"}
            }
        },
    }
}

INVALID_WEBHOOK_PAYLOAD = {"not": "a valid webhook"}


# ---------------------------------------------------------------------------
# Session-scoped fixture: build image + start container once for all tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def docker_client():
    return docker_sdk.from_env()


@pytest.fixture(scope="session")
def running_container(docker_client):
    """
    Build the Docker image from the project root and start the container.
    Tears it down after all tests in the session complete.
    """
    # Determine project root (two levels up from this file)
    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    # Remove any leftover container from a previous run
    try:
        old = docker_client.containers.get(CONTAINER_NAME)
        old.stop()
        old.remove()
    except docker_sdk.errors.NotFound:
        pass

    # Build the image
    print(f"\nBuilding Docker image {IMAGE_TAG} from {project_root}...")
    image, _ = docker_client.images.build(
        path=project_root,
        tag=IMAGE_TAG,
        rm=True,
        dockerfile="Dockerfile",
    )

    # Start the container
    container = docker_client.containers.run(
        IMAGE_TAG,
        name=CONTAINER_NAME,
        detach=True,
        remove=False,
        ports={"5001/tcp": HOST_PORT},
        environment=FAKE_ENV,
        # Provide a writable /app/data via tmpfs so SQLite can create the DB
        tmpfs={"/app/data": "size=64m"},
    )

    # Wait for the container to be healthy (up to 30s)
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{BASE_URL}/health", timeout=2)
            if resp.status_code == 200:
                print(f"Container healthy after {30 - (deadline - time.time()):.1f}s")
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        logs = container.logs().decode("utf-8", errors="replace")
        container.stop()
        container.remove()
        pytest.fail(
            f"Container did not become healthy within 30s.\nLogs:\n{logs}"
        )

    yield container

    # Teardown
    container.stop()
    container.remove(force=True)
    try:
        docker_client.images.remove(IMAGE_TAG, force=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestContainerHealthEndpoint:
    def test_health_returns_200(self, running_container):
        resp = httpx.get(f"{BASE_URL}/health", timeout=5)
        assert resp.status_code == 200

    def test_health_returns_correct_body(self, running_container):
        resp = httpx.get(f"{BASE_URL}/health", timeout=5)
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "up-to-ynab"
        assert "version" in data

    def test_health_content_type_is_json(self, running_container):
        resp = httpx.get(f"{BASE_URL}/health", timeout=5)
        assert "application/json" in resp.headers.get("content-type", "")


class TestContainerWebhookEndpoint:
    def test_valid_webhook_payload_returns_200(self, running_container):
        """A structurally valid webhook event should be accepted (result may vary)."""
        resp = httpx.post(
            f"{BASE_URL}/webhook",
            json=VALID_WEBHOOK_PAYLOAD,
            timeout=10,
        )
        # The app will attempt to fetch from Up (which fails with fake token)
        # but the HTTP layer should still return 200 with a status field
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data

    def test_invalid_webhook_payload_returns_422(self, running_container):
        """Payloads that fail Pydantic validation should return 422."""
        resp = httpx.post(
            f"{BASE_URL}/webhook",
            json=INVALID_WEBHOOK_PAYLOAD,
            timeout=5,
        )
        assert resp.status_code == 422

    def test_empty_body_returns_422(self, running_container):
        resp = httpx.post(
            f"{BASE_URL}/webhook",
            content=b"",
            headers={"content-type": "application/json"},
            timeout=5,
        )
        assert resp.status_code == 422

    def test_non_transaction_event_is_accepted(self, running_container):
        """Non-TRANSACTION_CREATED events should be accepted and ignored gracefully."""
        ping_event = {
            "data": {
                "type": "webhook-events",
                "id": "ping-event",
                "attributes": {
                    "eventType": "PING",
                    "createdAt": "2024-06-01T10:00:00+10:00",
                },
                "relationships": {},
            }
        }
        resp = httpx.post(f"{BASE_URL}/webhook", json=ping_event, timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("processed", "error")


class TestContainerRefreshEndpoint:
    def test_refresh_endpoint_returns_200(self, running_container):
        """The /refresh endpoint should respond (even if YNAB call fails with fake token)."""
        resp = httpx.get(f"{BASE_URL}/refresh", timeout=10)
        assert resp.status_code == 200

    def test_refresh_returns_status_field(self, running_container):
        resp = httpx.get(f"{BASE_URL}/refresh", timeout=10)
        data = resp.json()
        assert "status" in data


class TestContainerNotFoundEndpoint:
    def test_unknown_route_returns_404(self, running_container):
        resp = httpx.get(f"{BASE_URL}/does-not-exist", timeout=5)
        assert resp.status_code == 404
