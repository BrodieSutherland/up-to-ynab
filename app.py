from contextlib import asynccontextmanager
from typing import Dict, Any

import structlog
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from database.connection import db_manager
from models.up_models import UpWebhookEvent
from services.transaction_service import TransactionService
from services.up_service import UpService
from utils.config import get_settings
from utils.logging import setup_logging
from utils.validation import log_validation_error, format_validation_errors, is_validation_error


logger = structlog.get_logger()


class WebhookResponse(BaseModel):
    """Response model for webhook endpoint."""
    status: str
    result: str

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "status": "processed",
                    "result": "Transaction created successfully in YNAB"
                },
                {
                    "status": "processed",
                    "result": "Event ignored - not a transaction creation"
                },
                {
                    "status": "processed",
                    "result": "Transaction already processed"
                }
            ]
        }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager for startup/shutdown tasks."""
    logger.info("Starting UP to YNAB application")

    # Initialize database
    await db_manager.create_tables()

    # Initialize services with proper error handling
    try:
        up_service = UpService()
        transaction_service = TransactionService()

        # Setup webhook if URL is provided
        settings = get_settings()
        if settings.webhook_url:
            webhook_exists = await up_service.ping_webhook(settings.webhook_url)
            if webhook_exists:
                logger.info("Webhook is ready", url=settings.webhook_url)
            else:
                logger.error("Failed to setup webhook", url=settings.webhook_url)
        else:
            logger.info("No webhook URL configured - webhook setup skipped")

        # Refresh category data
        try:
            await transaction_service.refresh_data()
        except Exception as e:
            logger.error("Failed to refresh category data on startup", error=str(e))

    except ValueError as e:
        logger.error("Service initialization failed - check your API tokens", error=str(e))
        # Don't fail startup completely, but services won't work
    except Exception as e:
        logger.error("Unexpected error during service initialization", error=str(e), exc_info=e)

    logger.info("UP to YNAB application started successfully")

    yield

    logger.info("Shutting down UP to YNAB application")
    await db_manager.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    setup_logging(settings.debug_mode)

    app = FastAPI(
        title="UP to YNAB Transaction Sync",
        description="Sync transactions from Up Bank to YNAB",
        version="2.0.0",
        debug=settings.debug_mode,
        lifespan=lifespan,
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
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
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
            "version": "2.0.0"
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
        """
    )
    async def handle_webhook(webhook_event: UpWebhookEvent) -> WebhookResponse:
        """Handle incoming webhooks from Up Bank."""
        try:

            logger.info("Received webhook", event_type=webhook_event.data.event_type)

            # Process the webhook event
            try:
                transaction_service = TransactionService()
                result = await transaction_service.process_webhook_event(webhook_event)
                logger.info("Webhook processed", result=result)
                return WebhookResponse(status="processed", result=result)
            except ValueError as e:
                logger.error("Service initialization failed during webhook processing", error=str(e))
                return WebhookResponse(status="error", result="Service configuration error - check API tokens")

        except Exception as exc:
            if is_validation_error(exc):
                log_validation_error(exc, "Webhook payload")
                validation_summary = format_validation_errors(exc)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid webhook payload - {validation_summary}"
                )
            else:
                logger.error("Failed to process webhook", exc_info=exc)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid webhook payload"
                )

    # Manual refresh endpoint
    @app.get("/refresh", tags=["admin"])
    async def refresh_data() -> Dict[str, str]:
        """Manually refresh category database."""
        try:
            logger.info("Manual refresh requested")

            try:
                transaction_service = TransactionService()
                result = await transaction_service.refresh_data()
                return {"status": "success", "message": result}
            except ValueError as e:
                logger.error("Service initialization failed during refresh", error=str(e))
                return {"status": "error", "message": "Service configuration error - check API tokens"}

        except Exception as exc:
            logger.error("Failed to refresh data", exc_info=exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to refresh data"
            )

    return app


# Create the app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.debug_mode,
        log_level="debug" if settings.debug_mode else "info",
    )