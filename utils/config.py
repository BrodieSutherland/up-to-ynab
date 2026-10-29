from typing import Annotated, Optional

from pydantic import Field, StringConstraints, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RequiredStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    # Server configuration
    port: int = Field(default=5001, description="Port to run the server on")
    debug_mode: bool = Field(default=False, description="Enable debug mode")

    # Up Bank API configuration
    up_api_token: RequiredStr = Field(..., description="Up Bank API token")
    up_base_url: str = Field(
        default="https://api.up.com.au/api/v1/",
        description="Up Bank API base URL",
    )
    webhook_url: Optional[str] = Field(
        default=None, description="Webhook URL for Up Bank to send events to"
    )

    # YNAB API configuration
    ynab_api_token: RequiredStr = Field(..., description="YNAB API token")
    ynab_budget_id: RequiredStr = Field(..., description="YNAB budget ID")
    ynab_base_url: str = Field(
        default="https://api.youneedabudget.com/v1/",
        description="YNAB API base URL",
    )

    # Admin endpoints
    admin_token: Optional[str] = Field(
        default=None,
        repr=False,
        description="Bearer token required by admin endpoints; open if unset",
    )

    # Database configuration
    database_url: str = Field(
        default="sqlite+aiosqlite:///./up_to_ynab.db",
        description="Database URL",
    )

    # Removed in 3.0.0; read only so startup can warn that they are ignored.
    legacy_ynab_account_id: Optional[str] = Field(
        None, validation_alias="ynab_account_id", exclude=True, repr=False
    )
    legacy_internal_transfer_strings: Optional[str] = Field(
        None,
        validation_alias="internal_transfer_strings",
        exclude=True,
        repr=False,
    )

    @field_validator("admin_token", mode="before")
    @classmethod
    def _blank_admin_token_is_unset(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value

    def ignored_env_vars(self) -> list[str]:
        """Names of removed settings that are still set."""
        names = []
        if self.legacy_ynab_account_id is not None:
            names.append("YNAB_ACCOUNT_ID")
        if self.legacy_internal_transfer_strings is not None:
            names.append("INTERNAL_TRANSFER_STRINGS")
        return names
