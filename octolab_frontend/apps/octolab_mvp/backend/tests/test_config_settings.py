"""Tests for Pydantic v2 config settings.

Ensures:
- Config imports without raising
- VALID_RUNTIMES is not treated as a Pydantic field
- Runtime validation fails on invalid values
- Env file path resolution is deterministic (based on __file__, not CWD)
- SecretStr fields don't leak in repr/str
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

pytestmark = pytest.mark.no_db


class TestConfigImport:
    """Tests that importing config module is safe."""

    def test_importing_config_module_succeeds(self):
        """Verify that app.config can be imported without raising."""
        # This test ensures there are no import-time errors like
        # the PydanticUserError for untyped class attributes
        from app.config import Settings, VALID_RUNTIMES, ENV_FILE

        # Basic sanity checks
        assert Settings is not None
        assert VALID_RUNTIMES is not None
        assert ENV_FILE is not None

    def test_valid_runtimes_is_module_level_constant(self):
        """Verify VALID_RUNTIMES is at module level, not a Settings field."""
        from app.config import VALID_RUNTIMES

        # Should be a frozenset
        assert isinstance(VALID_RUNTIMES, frozenset)
        assert "compose" in VALID_RUNTIMES
        assert "firecracker" in VALID_RUNTIMES
        assert "microvm" in VALID_RUNTIMES
        assert "k8s" in VALID_RUNTIMES
        assert "noop" in VALID_RUNTIMES


class TestValidRuntimesNotAField:
    """Verify VALID_RUNTIMES is not treated as a Pydantic field."""

    def test_valid_runtimes_not_in_model_fields(self):
        """VALID_RUNTIMES must not appear in Settings.model_fields."""
        from app.config import Settings

        # This was the bug: untyped class attributes were treated as fields
        assert "VALID_RUNTIMES" not in Settings.model_fields
        assert "valid_runtimes" not in Settings.model_fields


class TestRuntimeValidation:
    """Tests for runtime validation fail-hard behavior."""

    def test_invalid_runtime_raises_validation_error(self, monkeypatch):
        """Verify that invalid runtime values cause validation to fail."""
        from pydantic import ValidationError

        # Set up minimal env with invalid runtime
        monkeypatch.setenv("OCTOLAB_RUNTIME", "not-a-real-runtime")
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("SECRET_KEY", "test-secret-key")

        # Clear the cached settings instance
        from app import config
        if hasattr(config, 'settings'):
            # Need to reimport to test fresh instantiation
            pass

        # Import Settings class (not the instance)
        from app.config import Settings

        with pytest.raises(ValidationError) as exc_info:
            Settings(_env_file=None)  # Skip env file loading

        # Should mention invalid runtime
        errors = exc_info.value.errors()
        assert any("runtime" in str(e).lower() for e in errors)

    def test_empty_runtime_allowed_for_migrations(self, monkeypatch):
        """Verify that empty/unset runtime is allowed (for Alembic migrations).

        SECURITY:
        - Runtime enforcement happens at FastAPI startup, not at import time
        - This allows Alembic to import config without OCTOLAB_RUNTIME set
        - API startup will fail-hard if runtime is not set (see main.py)
        """
        # Ensure OCTOLAB_RUNTIME is not set
        monkeypatch.delenv("OCTOLAB_RUNTIME", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("SECRET_KEY", "test-secret-key")

        from app.config import Settings

        # Should succeed - None is allowed for migrations
        settings = Settings(_env_file=None)
        assert settings.octolab_runtime is None

    def test_valid_runtimes_accepted(self, monkeypatch):
        """Verify that all valid runtime values are accepted."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("SECRET_KEY", "test-secret-key")

        from app.config import Settings

        for runtime in ["compose", "firecracker", "microvm", "k8s", "noop"]:
            monkeypatch.setenv("OCTOLAB_RUNTIME", runtime)
            settings = Settings(_env_file=None)

            # microvm should normalize to firecracker
            if runtime == "microvm":
                assert settings.octolab_runtime == "firecracker"
            else:
                assert settings.octolab_runtime == runtime

    def test_runtime_case_insensitive(self, monkeypatch):
        """Verify that runtime values are case-insensitive."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("SECRET_KEY", "test-secret-key")

        from app.config import Settings

        for runtime in ["COMPOSE", "Compose", "FIRECRACKER", "Firecracker"]:
            monkeypatch.setenv("OCTOLAB_RUNTIME", runtime)
            settings = Settings(_env_file=None)
            assert settings.octolab_runtime == runtime.lower()


class TestEnvFileResolution:
    """Tests for deterministic env file path resolution."""

    def test_env_file_path_is_absolute(self):
        """Verify that ENV_FILE is an absolute path."""
        from app.config import ENV_FILE

        assert ENV_FILE.is_absolute()

    def test_env_file_path_points_to_backend_dir(self):
        """Verify that ENV_FILE points to backend/.env.local or backend/.env."""
        from app.config import ENV_FILE, BACKEND_DIR

        # Should be in the backend directory
        assert ENV_FILE.parent == BACKEND_DIR

        # Should be .env.local or .env
        assert ENV_FILE.name in (".env.local", ".env")

    def test_config_dir_is_app_directory(self):
        """Verify CONFIG_DIR points to the app/ directory."""
        from app.config import CONFIG_DIR

        assert CONFIG_DIR.name == "app"
        assert (CONFIG_DIR / "config.py").exists()

    def test_backend_dir_is_parent_of_app(self):
        """Verify BACKEND_DIR is the parent of CONFIG_DIR (app/)."""
        from app.config import CONFIG_DIR, BACKEND_DIR

        assert BACKEND_DIR == CONFIG_DIR.parent
        assert (BACKEND_DIR / "alembic").exists() or (BACKEND_DIR / "pyproject.toml").exists()


class TestSecretStrFields:
    """Tests for SecretStr fields to ensure they don't leak."""

    def test_secret_key_is_secret_str(self, monkeypatch):
        """Verify secret_key is a SecretStr."""
        from pydantic import SecretStr

        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("SECRET_KEY", "my-super-secret-key")
        monkeypatch.setenv("OCTOLAB_RUNTIME", "compose")

        from app.config import Settings

        settings = Settings(_env_file=None)
        assert isinstance(settings.secret_key, SecretStr)

    def test_secret_str_not_in_repr(self, monkeypatch):
        """Verify SecretStr values don't appear in repr."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("SECRET_KEY", "my-super-secret-key")
        monkeypatch.setenv("OCTOLAB_RUNTIME", "compose")
        monkeypatch.setenv("GUAC_ADMIN_PASSWORD", "guac-secret-password")

        from app.config import Settings

        settings = Settings(_env_file=None)

        # repr should not contain the actual secret values
        repr_str = repr(settings)
        assert "my-super-secret-key" not in repr_str
        assert "guac-secret-password" not in repr_str

        # Should show "**********" or similar redaction
        assert "SecretStr" in repr_str or "**" in repr_str

    def test_secret_str_get_secret_value(self, monkeypatch):
        """Verify SecretStr.get_secret_value() returns the actual value."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("SECRET_KEY", "my-super-secret-key")
        monkeypatch.setenv("OCTOLAB_RUNTIME", "compose")

        from app.config import Settings

        settings = Settings(_env_file=None)
        assert settings.secret_key.get_secret_value() == "my-super-secret-key"


class TestPortRangeValidation:
    """Tests for port range validation."""

    def test_invalid_port_min_raises(self, monkeypatch):
        """Verify invalid compose_port_min raises validation error."""
        from pydantic import ValidationError

        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("OCTOLAB_RUNTIME", "compose")
        monkeypatch.setenv("COMPOSE_PORT_MIN", "500")  # Below 1024

        from app.config import Settings

        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_port_min_greater_than_max_raises(self, monkeypatch):
        """Verify compose_port_min >= compose_port_max raises error."""
        from pydantic import ValidationError

        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("OCTOLAB_RUNTIME", "compose")
        monkeypatch.setenv("COMPOSE_PORT_MIN", "40000")
        monkeypatch.setenv("COMPOSE_PORT_MAX", "30000")

        from app.config import Settings

        with pytest.raises(ValueError):  # model_post_init raises ValueError
            Settings(_env_file=None)


class TestNoImportTimeSideEffects:
    """Verify no import-time side effects (safe for alembic)."""

    def test_importing_config_does_not_run_doctor(self):
        """Verify importing config doesn't trigger doctor checks."""
        # This test verifies that simply importing config.py doesn't
        # run any validation that requires external resources

        # If this import succeeds without network/filesystem errors,
        # then there are no import-time side effects
        import importlib
        import app.config

        # Force reimport
        importlib.reload(app.config)

        # If we get here, no side effects occurred
        assert True

    def test_settings_configdict_env_file_is_string(self):
        """Verify SettingsConfigDict.env_file is a string path."""
        from app.config import Settings

        # Access the model_config
        config = Settings.model_config
        assert "env_file" in config
        assert isinstance(config["env_file"], str)


class TestStartupRuntimeEnforcement:
    """Tests for runtime enforcement at FastAPI startup.

    SECURITY:
    - Settings allows None runtime (for Alembic migrations)
    - FastAPI startup validation MUST enforce explicit runtime
    - No fallback to compose - fails closed
    """

    def test_validate_runtime_selection_raises_when_none(self, monkeypatch):
        """Verify startup validation raises RuntimeError when runtime is None."""
        import importlib
        from unittest.mock import MagicMock

        # Import main module first to get access to the function
        import app.main

        # Now patch the settings object on the already-imported module
        original_settings = app.main.settings
        try:
            mock_settings = MagicMock()
            mock_settings.octolab_runtime = None
            app.main.settings = mock_settings

            with pytest.raises(RuntimeError) as exc_info:
                app.main._validate_runtime_selection()

            error_msg = str(exc_info.value)
            assert "OCTOLAB_RUNTIME must be explicitly set" in error_msg
            assert "No default" in error_msg
        finally:
            app.main.settings = original_settings

    def test_validate_runtime_selection_succeeds_with_compose(self):
        """Verify startup validation succeeds with compose runtime."""
        from unittest.mock import MagicMock

        import app.main

        original_settings = app.main.settings
        try:
            mock_settings = MagicMock()
            mock_settings.octolab_runtime = "compose"
            app.main.settings = mock_settings

            # Should not raise
            app.main._validate_runtime_selection()
        finally:
            app.main.settings = original_settings

    def test_validate_runtime_selection_calls_firecracker_prereqs(self):
        """Verify startup validation calls firecracker prereqs when runtime is firecracker."""
        from unittest.mock import MagicMock, patch

        import app.main

        original_settings = app.main.settings
        try:
            mock_settings = MagicMock()
            mock_settings.octolab_runtime = "firecracker"
            app.main.settings = mock_settings

            with patch.object(app.main, "_validate_firecracker_prerequisites") as mock_prereqs:
                app.main._validate_runtime_selection()
                mock_prereqs.assert_called_once()
        finally:
            app.main.settings = original_settings


class TestLabServiceRuntimeValidation:
    """Tests for runtime validation in lab_service.py.

    SECURITY:
    - create_lab_for_user requires explicit runtime parameter
    - Invalid runtime values raise ValueError
    """

    def test_create_lab_for_user_requires_runtime_param(self):
        """Verify create_lab_for_user has no default for effective_runtime."""
        import inspect
        from app.services.lab_service import create_lab_for_user

        sig = inspect.signature(create_lab_for_user)
        param = sig.parameters.get("effective_runtime")

        # Should have no default (Parameter.empty)
        assert param is not None
        assert param.default is inspect.Parameter.empty, (
            "effective_runtime should not have a default value - "
            "caller must explicitly provide runtime"
        )
