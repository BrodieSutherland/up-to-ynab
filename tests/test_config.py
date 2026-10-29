import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from utils.config import Settings


class TestSettings:
    """Test cases for application settings."""

    def test_settings_creation_with_required_fields(self):
        """Test settings creation with all required fields."""
        settings = Settings(
            up_api_token="test_up_token",
            ynab_api_token="test_ynab_token",
            ynab_budget_id="test_budget_id",
            _env_file=None,
        )

        assert settings.up_api_token == "test_up_token"
        assert settings.ynab_api_token == "test_ynab_token"
        assert settings.ynab_budget_id == "test_budget_id"

        # Test defaults
        assert settings.port == 5001
        assert settings.debug_mode is False
        assert settings.up_base_url == "https://api.up.com.au/api/v1/"
        assert settings.ynab_base_url == "https://api.youneedabudget.com/v1/"
        assert settings.database_url == "sqlite+aiosqlite:///./up_to_ynab.db"

    def test_settings_custom_values(self):
        """Test settings with custom values."""
        settings = Settings(
            port=8080,
            debug_mode=True,
            up_api_token="test_up_token",
            up_base_url="https://custom.up.api/v1/",
            webhook_url="https://custom.webhook.url/webhook",
            ynab_api_token="test_ynab_token",
            ynab_budget_id="test_budget_id",
            _env_file=None,
            ynab_base_url="https://custom.ynab.api/v1/",
            database_url="postgresql://custom:db@localhost/test",
        )

        assert settings.port == 8080
        assert settings.debug_mode is True
        assert settings.up_base_url == "https://custom.up.api/v1/"
        assert settings.webhook_url == "https://custom.webhook.url/webhook"
        assert settings.ynab_base_url == "https://custom.ynab.api/v1/"
        assert settings.database_url == "postgresql://custom:db@localhost/test"

    def test_settings_missing_required_fields(self, monkeypatch):
        """Test settings validation with missing required fields."""
        # Clear environment variables to ensure validation happens
        monkeypatch.delenv("UP_API_TOKEN", raising=False)
        monkeypatch.delenv("YNAB_API_TOKEN", raising=False)
        monkeypatch.delenv("YNAB_BUDGET_ID", raising=False)

        # Prevent loading from .env file
        monkeypatch.setenv("PYDANTIC_SETTINGS_ENV_FILE", "")

        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # Missing all required fields

        with pytest.raises(ValidationError):
            Settings(
                up_api_token="test", _env_file=None
            )  # Missing other required fields

    def test_settings_rejects_empty_and_whitespace(self):
        """Empty or whitespace-only required values fail validation."""
        base = {
            "up_api_token": "a",
            "ynab_api_token": "b",
            "ynab_budget_id": "c",
        }
        for field in base:
            for bad in ("", "   "):
                with pytest.raises(ValidationError) as exc_info:
                    Settings(_env_file=None, **{**base, field: bad})
                assert field in str(exc_info.value)

    def test_settings_strips_whitespace(self):
        """Surrounding whitespace is removed from required values."""
        settings = Settings(
            _env_file=None,
            up_api_token="  tok  ",
            ynab_api_token="b",
            ynab_budget_id="c",
        )
        assert settings.up_api_token == "tok"

    def test_validation_error_does_not_echo_other_tokens(self, monkeypatch):
        """A missing field's error must not contain another field's token."""
        monkeypatch.delenv("UP_API_TOKEN", raising=False)
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                _env_file=None,
                ynab_api_token="secret-ynab-token",
                ynab_budget_id="c",
            )
        message = str(exc_info.value)
        assert "up_api_token" in message
        assert "secret-ynab-token" not in message

    @patch.dict(
        os.environ,
        {
            "UP_API_TOKEN": "env_up_token",
            "YNAB_API_TOKEN": "env_ynab_token",
            "YNAB_BUDGET_ID": "env_budget_id",
            "PORT": "9000",
            "DEBUG_MODE": "true",
        },
    )
    def test_settings_from_environment(self):
        """Test settings loaded from environment variables."""
        settings = Settings(_env_file=None)

        assert settings.up_api_token == "env_up_token"
        assert settings.ynab_api_token == "env_ynab_token"
        assert settings.ynab_budget_id == "env_budget_id"
        assert settings.port == 9000
        assert settings.debug_mode is True

    @patch.dict(
        os.environ,
        {
            "UP_API_TOKEN": "env_up_token",
            "YNAB_API_TOKEN": "env_ynab_token",
            "YNAB_BUDGET_ID": "env_budget_id",
        },
    )
    def test_settings_case_insensitive(self):
        """Test that environment variables are case insensitive."""
        # This tests the case_sensitive=False setting in model_config
        with patch.dict(os.environ, {"up_api_token": "lowercase_token"}, clear=False):
            settings = Settings(_env_file=None)
            # The lowercase version should be found (case_sensitive=False)
            assert settings.up_api_token == "lowercase_token"

    @patch.dict(
        os.environ,
        {
            "UP_API_TOKEN": "test_token",
            "YNAB_API_TOKEN": "test_token",
            "YNAB_BUDGET_ID": "test_budget",
        },
    )
    def test_settings_model_config(self):
        """Test settings model configuration."""
        settings = Settings(_env_file=None)

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
            "ynab_base_url",
            "database_url",
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

    def test_ignored_env_vars_none_by_default(self):
        settings = Settings(
            _env_file=None,
            up_api_token="a",
            ynab_api_token="b",
            ynab_budget_id="c",
        )

        assert settings.ignored_env_vars() == []

    def test_ignored_env_vars_from_environment(self, monkeypatch):
        monkeypatch.setenv("YNAB_ACCOUNT_ID", "old")
        monkeypatch.setenv("INTERNAL_TRANSFER_STRINGS", "[]")

        settings = Settings(
            _env_file=None,
            up_api_token="a",
            ynab_api_token="b",
            ynab_budget_id="c",
        )

        assert settings.ignored_env_vars() == [
            "YNAB_ACCOUNT_ID",
            "INTERNAL_TRANSFER_STRINGS",
        ]

    def test_ignored_env_vars_from_env_file(self, monkeypatch, tmp_path):
        monkeypatch.delenv("YNAB_ACCOUNT_ID", raising=False)
        monkeypatch.delenv("INTERNAL_TRANSFER_STRINGS", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("INTERNAL_TRANSFER_STRINGS=whatever\n")

        settings = Settings(
            _env_file=env_file,
            up_api_token="a",
            ynab_api_token="b",
            ynab_budget_id="c",
        )

        assert settings.ignored_env_vars() == ["INTERNAL_TRANSFER_STRINGS"]

    def test_legacy_fields_are_not_dumped(self):
        settings = Settings(
            _env_file=None,
            up_api_token="a",
            ynab_api_token="b",
            ynab_budget_id="c",
            ynab_account_id="old",
        )

        dumped = settings.model_dump()

        assert not any(key.startswith("legacy_") for key in dumped)
        assert "old" not in repr(settings)

    def test_admin_token_is_hidden_from_repr(self):
        settings = Settings(
            _env_file=None,
            up_api_token="a",
            ynab_api_token="b",
            ynab_budget_id="c",
            admin_token="tok-secret",
        )

        assert settings.admin_token == "tok-secret"
        assert "tok-secret" not in repr(settings)

    @pytest.mark.parametrize("value", ["", "   "])
    def test_blank_admin_token_is_unset(self, value):
        settings = Settings(
            _env_file=None,
            up_api_token="a",
            ynab_api_token="b",
            ynab_budget_id="c",
            admin_token=value,
        )

        assert settings.admin_token is None

    def test_admin_token_is_stripped(self):
        settings = Settings(
            _env_file=None,
            up_api_token="a",
            ynab_api_token="b",
            ynab_budget_id="c",
            admin_token="tok\n",
        )

        assert settings.admin_token == "tok"
