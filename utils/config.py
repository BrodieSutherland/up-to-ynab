from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # Server configuration
    port: int = Field(default=5001, description="Port to run the server on")
    debug_mode: bool = Field(default=False, description="Enable debug mode")

    # Up Bank API configuration
    up_api_token: str = Field(..., description="Up Bank API token")
    up_base_url: str = Field(
        default="https://api.up.com.au/api/v1/", description="Up Bank API base URL"
    )
    webhook_url: Optional[str] = Field(
        default=None, description="Webhook URL for Up Bank to send events to"
    )

    # YNAB API configuration
    ynab_api_token: str = Field(..., description="YNAB API token")
    ynab_budget_id: str = Field(..., description="YNAB budget ID")
    ynab_account_id: str = Field(..., description="YNAB account ID")
    ynab_base_url: str = Field(
        default="https://api.youneedabudget.com/v1/", description="YNAB API base URL"
    )

    # Database configuration
    database_url: str = Field(
        default="sqlite+aiosqlite:///./up_to_ynab.db", description="Database URL"
    )

    # Transfer filtering
    internal_transfer_strings: list[str] = Field(
        default=[
            "Transfer to ",
            "Cover to ",
            "Quick save transfer to ",
            "Forward to ",
        ],
        description="Strings that identify internal transfers to exclude",
    )


@lru_cache()
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
