"""Utilities for handling Pydantic validation errors."""

import structlog
from typing import Any, Dict, List

logger = structlog.get_logger()


def format_validation_errors(exc: Exception) -> str:
    """Format Pydantic validation errors into a readable string."""
    if not hasattr(exc, 'errors'):
        return str(exc)

    error_details = []
    for error in exc.errors():
        field_path = " -> ".join(str(loc) for loc in error['loc'])
        error_msg = error['msg']
        error_type = error['type']
        error_details.append(f"Field '{field_path}': {error_msg} (type: {error_type})")

    return "; ".join(error_details)


def log_validation_error(exc: Exception, context: str, **kwargs) -> None:
    """Log validation errors with detailed field information."""
    if hasattr(exc, 'errors'):
        validation_summary = format_validation_errors(exc)
        logger.error(
            f"{context} validation failed",
            validation_errors=validation_summary,
            error_count=len(exc.errors()),
            **kwargs
        )
    else:
        logger.error(
            f"{context} error",
            error=str(exc),
            **kwargs
        )


def is_validation_error(exc: Exception) -> bool:
    """Check if an exception is a Pydantic validation error."""
    return hasattr(exc, 'errors') and callable(getattr(exc, 'errors', None))