import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from utils.config import Settings, get_settings


class TestSettings:
    """Test cases for application settings."""

    def test_settings_creation_with_required_fields(self):
        """Test settings creation with all required fields."""
        settings = Settings(
            up_api_token="test_up_token",
            ynab_api_token="test_ynab_token",
            ynab_budget_id="test_budget_id",
            ynab_account_id="test_account_id",
        )

        assert settings.up_api_token == "test_up_token"
        assert settings.ynab_api_token == "test_ynab_token"
        assert settings.ynab_budget_id == "test_budget_id"
        assert settings.ynab_account_id == "test_account_id"

        # Test defaults
        assert settings.port == 5001
        assert settings.debug_mode is False
        assert settings.up_base_url == "https://api.up.com.au/api/v1/"
        assert settings.ynab_base_url == "https://api.youneedabudget.com/v1/"
        assert settings.database_url == "sqlite+aiosqlite:///./up_to_ynab.db"

    def test_settings_default_transfer_strings(self):
        """Test default internal transfer strings."""
        settings = Settings(
            up_api_token="test_up_token",
            ynab_api_token="test_ynab_token",
            ynab_budget_id="test_budget_id",
            ynab_account_id="test_account_id",
        )

        expected_strings = [
            "Transfer to ",
            "Cover to ",
            "Quick save transfer to ",
            "Forward to ",
        ]

        assert settings.internal_transfer_strings == expected_strings

    def test_settings_custom_values(self):
        """Test settings with custom values."""
        custom_transfer_strings = ["Custom transfer to "]

        settings = Settings(
            port=8080,
            debug_mode=True,
            up_api_token="test_up_token",
            up_base_url="https://custom.up.api/v1/",
            webhook_url="https://custom.webhook.url/webhook",
            ynab_api_token="test_ynab_token",
            ynab_budget_id="test_budget_id",
            ynab_account_id="test_account_id",
            ynab_base_url="https://custom.ynab.api/v1/",
            database_url="postgresql://custom:db@localhost/test",
            internal_transfer_strings=custom_transfer_strings,
        )

        assert settings.port == 8080
        assert settings.debug_mode is True
        assert settings.up_base_url == "https://custom.up.api/v1/"
        assert settings.webhook_url == "https://custom.webhook.url/webhook"
        assert settings.ynab_base_url == "https://custom.ynab.api/v1/"
        assert settings.database_url == "postgresql://custom:db@localhost/test"
        assert settings.internal_transfer_strings == custom_transfer_strings

    def test_settings_missing_required_fields(self, monkeypatch):
        """Test settings validation with missing required fields."""
        # Clear environment variables to ensure validation happens
        monkeypatch.delenv("UP_API_TOKEN", raising=False)
        monkeypatch.delenv("YNAB_API_TOKEN", raising=False)
        monkeypatch.delenv("YNAB_BUDGET_ID", raising=False)
        monkeypatch.delenv("YNAB_ACCOUNT_ID", raising=False)
        
        # Prevent loading from .env file
        monkeypatch.setenv("PYDANTIC_SETTINGS_ENV_FILE", "")

        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # Missing all required fields

        with pytest.raises(ValidationError):
            Settings(up_api_token="test", _env_file=None)  # Missing other required fields  # Missing other required fields  # Missing other required fields

    @patch.dict(
        os.environ,
        {
            "UP_API_TOKEN": "env_up_token",
            "YNAB_API_TOKEN": "env_ynab_token",
            "YNAB_BUDGET_ID": "env_budget_id",
            "YNAB_ACCOUNT_ID": "env_account_id",
            "PORT": "9000",
            "DEBUG_MODE": "true",
        },
    )
    def test_settings_from_environment(self):
        """Test settings loaded from environment variables."""
        settings = Settings()

        assert settings.up_api_token == "env_up_token"
        assert settings.ynab_api_token == "env_ynab_token"
        assert settings.ynab_budget_id == "env_budget_id"
        assert settings.ynab_account_id == "env_account_id"
        assert settings.port == 9000
        assert settings.debug_mode is True

    @patch.dict(
        os.environ,
        {
            "UP_API_TOKEN": "env_up_token",
            "YNAB_API_TOKEN": "env_ynab_token",
            "YNAB_BUDGET_ID": "env_budget_id",
            "YNAB_ACCOUNT_ID": "env_account_id",
        },
    )
    def test_settings_case_insensitive(self):
        """Test that environment variables are case insensitive."""
        # This tests the case_sensitive=False setting in model_config
        with patch.dict(os.environ, {"up_api_token": "lowercase_token"}, clear=False):
            settings = Settings()
            # The lowercase version should be found (case_sensitive=False)
            assert settings.up_api_token == "lowercase_token"

    def test_get_settings_caching(self):
        """Test that get_settings returns cached instance."""
        # Clear the cache first
        get_settings.cache_clear()

        settings1 = get_settings()
        settings2 = get_settings()

        # Should be the same instance due to lru_cache
        assert settings1 is settings2

    @patch.dict(
        os.environ,
        {
            "UP_API_TOKEN": "test_token",
            "YNAB_API_TOKEN": "test_token",
            "YNAB_BUDGET_ID": "test_budget",
            "YNAB_ACCOUNT_ID": "test_account",
        },
    )
    def test_settings_model_config(self):
        """Test settings model configuration."""
        settings = Settings()

        # Test that extra fields are ignored (extra="ignore")
        settings_dict = settings.model_dump()

        # Should contain expected fields
        expected_fields = {
            "port",
            "debug_mode",
            "up_api_token",
            "up_base_url",
            "webhook_url",
            "ynab_api_token",
            "ynab_budget_id",
            "ynab_account_id",
            "ynab_base_url",
            "database_url",
            "internal_transfer_strings",
        }

        for field in expected_fields:
            assert field in settings_dict

    def test_settings_field_descriptions(self):
        """Test that settings fields have proper descriptions."""
        # This tests the Field descriptions are properly set
        schema = Settings.model_json_schema()
        properties = schema.get("properties", {})

        # Check a few key fields have descriptions
        assert "description" in properties.get("port", {})
        assert "description" in properties.get("up_api_token", {})
        assert "description" in properties.get("ynab_api_token", {})
