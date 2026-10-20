import asyncio
import contextlib
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Protocol

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
from forwarding.budget_index import BudgetIndexHolder, rebuild_periodically
from forwarding.forwarder import Forwarder
from forwarding.ledger import Failed, Forwarded, Skipped, SqlLedger
from models.up_models import UpWebhookEvent
from utils.config import Settings
from utils.logging import setup_logging
from webhooks import plan_webhook_changes

logger = structlog.get_logger()


class WebhookResponse(BaseModel):
    """Response model for webhook endpoint."""

    status: str
    result: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"status": "forwarded", "result": "ynab-transaction-id"},
                {"status": "forwarded", "result": "already in YNAB"},
                {"status": "skipped", "result": "Mirror side of a Transfer"},
                {"status": "ignored", "result": "not a transaction creation"},
                {"status": "failed", "result": "POST /transactions -> 500"},
            ]
        }
    }


class IndexRebuilder(Protocol):
    async def rebuild(self) -> None: ...


@dataclass(frozen=True)
class Services:
    """The service objects the routes and startup tasks use."""

    up: UpClient
    forwarder: Forwarder
    budget_index: IndexRebuilder


def build_services(
    settings: Settings, database: DatabaseManager, up: UpClient, ynab: YnabClient
) -> Services:
    """Wire services from settings and clients; the only place they are built."""
    index = BudgetIndexHolder(up, ynab)
    forwarder = Forwarder(up, ynab, index, SqlLedger(database.get_session))
    return Services(up=up, forwarder=forwarder, budget_index=index)


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


async def reconcile_webhooks(up: UpClient, webhook_url: str | None) -> None:
    """Make exactly one Up webhook point at webhook_url; upstream errors are logged."""
    if not webhook_url:
        logger.info("No webhook URL configured - webhook setup skipped")
        return
    try:
        registered = await up.list_webhooks()
    except UpstreamError as e:
        logger.error("Failed to list webhooks", status_code=e.status_code, error=str(e))
        return
    plan = plan_webhook_changes(registered, webhook_url)
    for warning in plan.warnings:
        logger.warning("Webhook left in place", detail=warning)
    for webhook_id in plan.delete:
        try:
            await up.delete_webhook(webhook_id)
        except UpstreamError as e:
            logger.error(
                "Failed to delete webhook",
                webhook_id=webhook_id,
                status_code=e.status_code,
                error=str(e),
            )
        else:
            logger.info("Webhook deleted", webhook_id=webhook_id)
    if plan.create:
        try:
            webhook_id = await up.create_webhook(webhook_url)
        except UpstreamError as e:
            logger.error(
                "Failed to create webhook",
                url=webhook_url,
                status_code=e.status_code,
                error=str(e),
            )
        else:
            logger.info("Webhook created", webhook_id=webhook_id, url=webhook_url)


async def _run_startup_tasks(settings: Settings, services: Services) -> None:
    """Reconcile the Up webhooks and build the budget index."""
    for name in settings.ignored_env_vars():
        logger.warning(
            "Setting ignored",
            name=name,
            reason="ignored since 3.0.0; accounts are matched by name",
        )
    try:
        await reconcile_webhooks(services.up, settings.webhook_url)

        try:
            await services.budget_index.rebuild()
        except Exception as e:
            logger.error("Failed to build budget index on startup", error=str(e))

    except Exception as e:
        logger.error(
            "Unexpected error during service initialization",
            error=str(e),
            exc_info=e,
        )


async def _stop_task(task: asyncio.Task) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


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
            task = asyncio.create_task(
                rebuild_periodically(app.state.services.budget_index.rebuild)
            )
            app.state.rebuild_task = task
            stack.push_async_callback(_stop_task, task)
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

    app.state.settings = settings

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
        response_model=WebhookResponse,
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
        4. Skip the Mirror side of a Transfer
        5. Look up the payee's Category match in the Budget Index
        6. Create the transaction in YNAB and record the outcome

        Answers 503 when forwarding failed so Up redelivers the event;
        otherwise 200 with status forwarded, skipped or ignored.
        """,
    )
    async def handle_webhook(webhook_event: UpWebhookEvent) -> JSONResponse:
        """Handle incoming webhook events from Up Bank."""
        logger.info("Received event", event_type=webhook_event.data.event_type)
        outcome = await app.state.services.forwarder.handle(webhook_event)
        if isinstance(outcome, Forwarded):
            body = WebhookResponse(
                status="forwarded",
                result=outcome.ynab_transaction_id or "already in YNAB",
            )
        elif isinstance(outcome, Skipped):
            body = WebhookResponse(status="skipped", result=outcome.reason)
        elif isinstance(outcome, Failed):
            body = WebhookResponse(status="failed", result=outcome.reason)
        else:
            body = WebhookResponse(status="ignored", result=outcome.reason)
        return JSONResponse(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
                if isinstance(outcome, Failed)
                else status.HTTP_200_OK
            ),
            content=body.model_dump(),
        )

    # Manual refresh endpoint
    @app.get("/refresh", tags=["admin"])
    async def refresh_data() -> Dict[str, str]:
        """Rebuild the Budget Index."""
        try:
            logger.info("Manual refresh requested")

            await reconcile_webhooks(
                app.state.services.up, app.state.settings.webhook_url
            )
            await app.state.services.budget_index.rebuild()
            return {"status": "success", "message": "Data refreshed successfully"}

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
