import logging
import sys
from typing import Any

import structlog


def setup_logging(debug: bool = False) -> None:
    """Configure structured logging for the application."""
    log_level = logging.DEBUG if debug else logging.INFO

    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            (
                structlog.dev.ConsoleRenderer(colors=True)
                if debug
                else structlog.processors.JSONRenderer()
            ),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(**initial_values: Any) -> structlog.BoundLogger:
    """Get a configured logger with optional initial context."""
    return structlog.get_logger().bind(**initial_values)
