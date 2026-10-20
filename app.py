from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict

import httpx2 as httpx
import structlog
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from clients.errors import UpstreamError
from clients.up import HttpUpClient, UpClient
from clients.ynab import HttpYnabClient, YnabClient
from database.connection import DatabaseManager
from models.up_models import UpWebhookEvent
from services.category_service import CategoryService
from services.transaction_service import TransactionService
from utils.config import Settings
from utils.filters import TransactionFilter
from utils.logging import setup_logging
from utils.validation import (
    format_validation_errors,
    is_validation_error,
    log_validation_error,
)

logger = structlog.get_logger()


class WebhookResponse(BaseModel):
    """Response model for webhook endpoint."""

    status: str
    result: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "processed",
                    "result": "Transaction created successfully in YNAB",
                },
                {
                    "status": "processed",
                    "result": "Event ignored - not a transaction creation",
                },
                {
                    "status": "processed",
                    "result": "Transaction already processed",
                },
            ]
        }
    }


@dataclass(frozen=True)
class Services:
    """The service objects the routes and startup tasks use."""

    up: UpClient
    transactions: TransactionService


def build_services(
    settings: Settings, database: DatabaseManager, up: UpClient, ynab: YnabClient
) -> Services:
    """Wire services from settings and clients; the only place they are built."""
    category = CategoryService(database.get_session)
    transaction_filter = TransactionFilter(settings.internal_transfer_strings)
    transactions = TransactionService(
        up, ynab, category, transaction_filter, settings.ynab_account_id
    )
    return Services(up=up, transactions=transactions)


@asynccontextmanager
async def open_services(settings: Settings) -> AsyncIterator[Services]:
    """Open the database and HTTP clients, build real services, close on exit."""
    async with AsyncExitStack() as stack:
        database = DatabaseManager(settings.database_url, echo=settings.debug_mode)
        stack.push_async_callback(database.close)
        await database.create_tables()
        up_http = await stack.enter_async_context(httpx.AsyncClient())
        ynab_http = await stack.enter_async_context(httpx.AsyncClient())
        up = HttpUpClient(up_http, settings.up_api_token, settings.up_base_url)
        ynab = HttpYnabClient(
            ynab_http,
            settings.ynab_api_token,
            settings.ynab_base_url,
            settings.ynab_budget_id,
        )
        yield build_services(settings, database, up, ynab)


async def ping_webhook(up: UpClient, url: str) -> bool:
    """Make sure a webhook for url exists in Up, creating it if missing."""
    try:
        webhooks = await up.list_webhooks()
        logger.info("Retrieved webhooks", count=len(webhooks))
    except UpstreamError as e:
        logger.error("Failed to list webhooks", status_code=e.status_code, error=str(e))
        webhooks = []

    if any(webhook.url == url for webhook in webhooks):
        logger.info("Webhook already exists", url=url)
        return True

    logger.info("Webhook not found, creating new one", url=url)
    try:
        webhook_id = await up.create_webhook(url)
    except UpstreamError as e:
        logger.error(
            "Failed to create webhook", url=url, status_code=e.status_code, error=str(e)
        )
        return False
    logger.info("Webhook created successfully", webhook_id=webhook_id, url=url)
    return True


async def _run_startup_tasks(settings: Settings, services: Services) -> None:
    """Set up the Up webhook and warm the category data."""
    try:
        if settings.webhook_url:
            webhook_exists = await ping_webhook(services.up, settings.webhook_url)
            if webhook_exists:
                logger.info("Webhook is ready", url=settings.webhook_url)
            else:
                logger.error("Failed to setup webhook", url=settings.webhook_url)
        else:
            logger.info("No webhook URL configured - webhook setup skipped")

        try:
            await services.transactions.refresh_data()
        except Exception as e:
            logger.error("Failed to refresh category data on startup", error=str(e))

    except Exception as e:
        logger.error(
            "Unexpected error during service initialization",
            error=str(e),
            exc_info=e,
        )


def _lifespan(settings: Settings, services: Services | None):
    """Build the lifespan; real services are owned here, injected ones are not."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Starting UP to YNAB application")
        async with AsyncExitStack() as stack:
            if services is None:
                app.state.services = await stack.enter_async_context(
                    open_services(settings)
                )
            else:
                app.state.services = services
            await _run_startup_tasks(settings, app.state.services)
            logger.info("UP to YNAB application started successfully")
            yield
            logger.info("Shutting down UP to YNAB application")

    return lifespan


def create_app(
    settings: Settings | None = None, services: Services | None = None
) -> FastAPI:
    """Create the FastAPI application.

    Settings default to the environment (a missing token raises a
    ValidationError). Services default to real ones built in the lifespan.
    """
    settings = settings if settings is not None else Settings()
    setup_logging(settings.debug_mode)

    app = FastAPI(
        title="UP to YNAB Transaction Sync",
        description="Sync transactions from Up Bank to YNAB",
        version="2.0.0",
        debug=settings.debug_mode,
        lifespan=_lifespan(settings, services),
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug_mode else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error(
            "Unhandled exception occurred",
            exc_info=exc,
            path=request.url.path,
            method=request.method,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error occurred"},
        )

    # Health check endpoint
    @app.get("/health", tags=["health"])
    async def health_check() -> Dict[str, Any]:
        """Health check endpoint for monitoring."""
        return {
            "status": "healthy",
            "service": "up-to-ynab",
            "version": "2.0.0",
        }

    # Webhook endpoint
    @app.post(
        "/webhook",
        tags=["webhook"],
        summary="Handle Up Bank webhook events",
        description="""
        Process webhook events from Up Bank for transaction creation.

        **Example payload for TRANSACTION_CREATED event:**
        ```json
        {
          "data": {
            "type": "webhook-events",
            "id": "webhook-event-id",
            "attributes": {
              "eventType": "TRANSACTION_CREATED",
              "createdAt": "2024-01-15T10:30:00+00:00"
            },
            "relationships": {
              "transaction": {
                "data": {
                  "type": "transactions",
                  "id": "transaction-id-from-up"
                }
              }
            }
          }
        }
        ```

        The webhook will:
        1. Validate the payload structure
        2. Check if it's a TRANSACTION_CREATED event
        3. Fetch the transaction details from Up Bank API
        4. Filter out internal transfers
        5. Map payee to YNAB category using historical data
        6. Create the transaction in YNAB
        """,
    )
    async def handle_webhook(webhook_event: UpWebhookEvent) -> WebhookResponse:
        """Handle incoming webhook events from Up Bank."""
        try:

            logger.info("Received event", event_type=webhook_event.data.event_type)

            result = await app.state.services.transactions.process_webhook_event(
                webhook_event
            )
            logger.info("Event processed", result=result)
            return WebhookResponse(status="processed", result=result)

        except Exception as exc:
            if is_validation_error(exc):
                log_validation_error(exc, "Webhook payload")
                validation_summary = format_validation_errors(exc)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(f"Invalid webhook payload - " f"{validation_summary}"),
                )
            else:
                logger.error("Failed to process webhook", exc_info=exc)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid webhook payload",
                )

    # Manual refresh endpoint
    @app.get("/refresh", tags=["admin"])
    async def refresh_data() -> Dict[str, str]:
        """Manually refresh category database."""
        try:
            logger.info("Manual refresh requested")

            result = await app.state.services.transactions.refresh_data()
            return {"status": "success", "message": result}

        except Exception as exc:
            logger.error("Failed to refresh data", exc_info=exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to refresh data",
            )

    return app


if __name__ == "__main__":
    import uvicorn

    settings = Settings()
    uvicorn.run(
        "app:create_app",
        factory=True,
        host="0.0.0.0",
        port=settings.port,
        reload=settings.debug_mode,
        log_level="debug" if settings.debug_mode else "info",
    )
