import asyncio
import contextlib
import hmac
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, AsyncIterator, Dict, Protocol

import httpx2 as httpx
import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ValidationError

from clients.errors import UpstreamError
from clients.up import HttpUpClient, UpClient
from clients.ynab import HttpYnabClient, YnabClient
from database.connection import DatabaseManager
from database.webhook_secrets import SqlWebhookSecretStore, WebhookSecretStore
from forwarding.backfill import backfill
from forwarding.budget_index import BudgetIndexHolder, rebuild_periodically
from forwarding.forwarder import Forwarder, Settled
from forwarding.ledger import (
    Deleted,
    Failed,
    Forwarded,
    LedgerReader,
    Skipped,
    SqlLedger,
)
from models.up_models import UpWebhookEvent
from utils.config import Settings
from utils.logging import setup_logging
from webhooks import SIGNATURE_HEADER, plan_webhook_changes, signature_valid

logger = structlog.get_logger()

VERSION = "3.1.0"


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
                {"status": "deleted", "result": "deleted in YNAB"},
                {"status": "flagged", "result": "flagged red: cleared in YNAB"},
                {"status": "ignored", "result": "not a transaction event"},
                {"status": "failed", "result": "POST /transactions -> 500"},
            ]
        }
    }


class BackfillResponse(BaseModel):
    """Counts from a backfill run."""

    forwarded: int
    skipped: int
    failed: int
    already_handled: int
    more_remaining: bool

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "forwarded": 12,
                    "skipped": 3,
                    "failed": 0,
                    "already_handled": 40,
                    "more_remaining": False,
                }
            ]
        }
    }


class LedgerEntryResponse(BaseModel):
    """A Ledger row."""

    up_transaction_id: str
    status: str
    reason: str | None
    reason_code: str | None
    ynab_transaction_id: str | None
    attempts: int
    updated_at: datetime

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "up_transaction_id": "tx1",
                    "status": "skipped",
                    "reason": "Up account not in YNAB",
                    "reason_code": "account_not_in_ynab",
                    "ynab_transaction_id": None,
                    "attempts": 2,
                    "updated_at": "2026-10-30T01:02:03Z",
                }
            ]
        }
    }


# Australian Eastern Standard Time; during daylight saving the cut-off is an
# hour early, which only re-checks handled transactions.
AEST = timezone(timedelta(hours=10))


class IndexRebuilder(Protocol):
    async def rebuild(self) -> None: ...


@dataclass(frozen=True)
class Services:
    """The service objects the routes and startup tasks use."""

    up: UpClient
    forwarder: Forwarder
    budget_index: IndexRebuilder
    webhook_secrets: WebhookSecretStore
    ynab: YnabClient
    ledger: LedgerReader


def build_services(
    settings: Settings, database: DatabaseManager, up: UpClient, ynab: YnabClient
) -> Services:
    """Wire services from settings and clients; the only place they are built."""
    index = BudgetIndexHolder(up, ynab)
    ledger = SqlLedger(database.get_session)
    forwarder = Forwarder(up, ynab, index, ledger)
    return Services(
        up=up,
        forwarder=forwarder,
        budget_index=index,
        webhook_secrets=SqlWebhookSecretStore(database.get_session),
        ynab=ynab,
        ledger=ledger,
    )


@asynccontextmanager
async def open_services(settings: Settings) -> AsyncIterator[Services]:
    """Open the database and HTTP clients, build real services, close on exit."""
    async with AsyncExitStack() as stack:
        database = DatabaseManager(settings.database_url, echo=settings.debug_mode)
        stack.push_async_callback(database.close)
        await database.migrate()
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


async def reconcile_webhooks(
    up: UpClient, secrets: WebhookSecretStore, webhook_url: str | None
) -> None:
    """Make exactly one usable Up webhook point at webhook_url.

    A hook is usable only if its signing secret is stored. Upstream errors are
    logged. Secrets are never logged.
    """
    await _reconcile(up, secrets, webhook_url)
    if not await secrets.all():
        logger.warning(
            "No webhook secret stored; /webhook rejects every event",
            hint="set WEBHOOK_URL",
        )


async def reconcile_webhooks_safely(
    up: UpClient, secrets: WebhookSecretStore, webhook_url: str | None
) -> None:
    """reconcile_webhooks, but any failure is logged so callers carry on."""
    try:
        await reconcile_webhooks(up, secrets, webhook_url)
    except Exception as e:
        logger.error("Webhook reconciliation failed", error=str(e))


async def _reconcile(
    up: UpClient, secrets: WebhookSecretStore, webhook_url: str | None
) -> None:
    if not webhook_url:
        logger.info("No webhook URL configured - webhook setup skipped")
        return
    try:
        registered = await up.list_webhooks()
    except UpstreamError as e:
        logger.error("Failed to list webhooks", status_code=e.status_code, error=str(e))
        return
    plan = plan_webhook_changes(
        registered, webhook_url, known_secret_ids=set(await secrets.all())
    )
    for warning in plan.warnings:
        logger.warning("Webhook left in place", detail=warning)
    for webhook_id in plan.forget:
        await secrets.delete(webhook_id)
        logger.info("Stored secret forgotten", webhook_id=webhook_id)
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
            await secrets.delete(webhook_id)
            logger.info("Webhook deleted", webhook_id=webhook_id)
    if plan.create:
        try:
            created = await up.create_webhook(webhook_url)
        except UpstreamError as e:
            logger.error(
                "Failed to create webhook",
                url=webhook_url,
                status_code=e.status_code,
                error=str(e),
            )
        else:
            await secrets.save(created.id, created.secret_key)
            logger.info("Webhook created", webhook_id=created.id, url=webhook_url)


_bearer = HTTPBearer(auto_error=False)


async def require_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Admin endpoints need the ADMIN_TOKEN as a Bearer token, if one is set."""
    token = request.app.state.settings.admin_token
    if token is None:
        return
    if credentials is None or not hmac.compare_digest(
        credentials.credentials.encode(), token.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def warn_if_plan_archived(ynab: YnabClient) -> None:
    """Warn if the configured YNAB plan looks archived. Never raises upstream errors."""
    try:
        name = await ynab.plan_name()
    except UpstreamError as e:
        logger.warning(
            "Could not read YNAB plan name", status_code=e.status_code, error=str(e)
        )
        return
    if name is not None and "(Archived" in name:
        logger.warning(
            "YNAB plan looks archived",
            plan_name=name,
            hint="set YNAB_BUDGET_ID to the active plan",
        )


async def _run_startup_tasks(settings: Settings, services: Services) -> None:
    """Reconcile the Up webhooks and build the budget index."""
    for name in settings.ignored_env_vars():
        logger.warning(
            "Setting ignored",
            name=name,
            reason="ignored since 3.0.0; accounts are matched by name",
        )
    try:
        if settings.admin_token is None:
            logger.warning("ADMIN_TOKEN not set; admin endpoints are open")
        await reconcile_webhooks_safely(
            services.up, services.webhook_secrets, settings.webhook_url
        )

        try:
            await services.budget_index.rebuild()
        except Exception as e:
            logger.error("Failed to build budget index on startup", error=str(e))

        await warn_if_plan_archived(services.ynab)

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
        version=VERSION,
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
            "version": VERSION,
        }

    # Webhook endpoint
    @app.post(
        "/webhook",
        tags=["webhook"],
        response_model=WebhookResponse,
        summary="Handle Up Bank webhook events",
        description="""
        Process transaction webhook events from Up Bank.

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

        TRANSACTION_CREATED fetches the transaction from Up, skips the Mirror
        side of a Transfer, applies the payee's Category match and creates the
        transaction in YNAB, recording the outcome.

        TRANSACTION_SETTLED marks the YNAB copy cleared and corrects its amount,
        leaving reconciled transactions alone; a transaction never forwarded is
        created (already cleared).

        TRANSACTION_DELETED deletes the YNAB copy of a forwarded transaction if
        it is still uncleared; a cleared or reconciled copy is flagged red for
        review instead. Transactions never forwarded are ignored.

        The request must carry Up's `X-Up-Authenticity-Signature` header: the
        hex SHA-256 HMAC of the raw body under the secret of a webhook this app
        created. Answers 401 when it is missing or does not match.

        Answers 503 when handling failed so Up redelivers the event;
        otherwise 200 with status forwarded, skipped, settled, deleted, flagged
        or ignored.
        """,
        responses={401: {"description": "Missing or invalid webhook signature"}},
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": UpWebhookEvent.model_json_schema()}
                },
            }
        },
    )
    async def handle_webhook(
        request: Request,
        signature: str | None = Header(None, alias=SIGNATURE_HEADER),
    ) -> JSONResponse:
        """Handle incoming webhook events from Up Bank."""
        body = await request.body()
        secrets = await app.state.services.webhook_secrets.all()
        if not signature_valid(body, signature, secrets.values()):
            logger.warning(
                "Webhook signature rejected",
                reason="missing" if not signature else "invalid",
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid webhook signature"},
            )
        try:
            webhook_event = UpWebhookEvent.model_validate_json(body)
        except ValidationError as exc:
            raise RequestValidationError(exc.errors(include_url=False))
        logger.info("Received event", event_type=webhook_event.data.event_type)
        outcome = await app.state.services.forwarder.handle(webhook_event)
        if isinstance(outcome, Forwarded):
            body = WebhookResponse(
                status="forwarded",
                result=outcome.ynab_transaction_id or "already in YNAB",
            )
        elif isinstance(outcome, Settled):
            body = WebhookResponse(status="settled", result=outcome.ynab_transaction_id)
        elif isinstance(outcome, Deleted):
            body = WebhookResponse(
                status="flagged" if outcome.flagged else "deleted",
                result=outcome.reason,
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
    @app.get("/refresh", tags=["admin"], dependencies=[Depends(require_admin)])
    async def refresh_data() -> Dict[str, str]:
        """Rebuild the Budget Index."""
        try:
            logger.info("Manual refresh requested")

            await reconcile_webhooks_safely(
                app.state.services.up,
                app.state.services.webhook_secrets,
                app.state.settings.webhook_url,
            )
            await app.state.services.budget_index.rebuild()
            await warn_if_plan_archived(app.state.services.ynab)
            return {"status": "success", "message": "Data refreshed successfully"}

        except Exception as exc:
            logger.error("Failed to refresh data", exc_info=exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to refresh data",
            )

    @app.get(
        "/ledger/{up_transaction_id}",
        tags=["admin"],
        response_model=LedgerEntryResponse,
        dependencies=[Depends(require_admin)],
        summary="Show what happened to an Up transaction",
        responses={404: {"description": "No Ledger entry for this transaction"}},
    )
    async def show_ledger_entry(up_transaction_id: str) -> Dict[str, Any]:
        """The Ledger row for an Up transaction id."""
        view = await app.state.services.ledger.entry(up_transaction_id)
        if view is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No Ledger entry for this transaction",
            )
        return asdict(view)

    @app.post(
        "/backfill",
        tags=["admin"],
        response_model=BackfillResponse,
        dependencies=[Depends(require_admin)],
        summary="Forward Up transactions missed by the webhook",
        responses={502: {"description": "Could not list Up transactions"}},
    )
    async def run_backfill(
        since: date = Query(
            ...,
            description=(
                "YYYY-MM-DD; transactions created on or after this day "
                "(Australian time)"
            ),
        ),
    ) -> Dict[str, Any]:
        """Forward Up transactions created since a date that YNAB does not have.

        Transactions already forwarded, deleted or skipped are left alone,
        except those skipped because their Up account was not in YNAB, which
        are retried (run /refresh after adding the account). Stops after
        150 YNAB creates; run it again while `more_remaining` is true.
        """
        start = datetime.combine(since, time(0), tzinfo=AEST)
        try:
            report = await backfill(
                app.state.services.up, app.state.services.forwarder, start
            )
        except UpstreamError as exc:
            logger.error(
                "Failed to list Up transactions",
                status_code=exc.status_code,
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Could not list Up transactions",
            )
        return asdict(report)

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
