"""Tests for Firecracker runtime enforcement.

Verifies that:
1. Default runtime is firecracker
2. Compose/k8s runtimes are blocked in production
3. Production enforcement works at multiple layers (config, main, runtime)
"""

import pytest
from unittest.mock import patch

pytestmark = pytest.mark.no_db


class TestConfigRuntimeDefault:
    """Test runtime default value in config."""

    def test_default_runtime_is_firecracker(self):
        """Verify default runtime is firecracker, not compose."""
        # Import Settings fresh to test default value
        from app.config import Settings

        # Create settings with minimal required values
        with patch.dict(
            "os.environ",
            {
                "DATABASE_URL": "postgresql+psycopg://test:test@localhost/test",
                "SECRET_KEY": "test-secret-key-minimum-32-chars-long",
                "APP_ENV": "dev",
            },
            clear=True,
        ):
            settings = Settings()
            assert settings.octolab_runtime == "firecracker"

    def test_compose_allowed_in_dev(self):
        """Verify compose runtime is allowed in dev environment."""
        from app.config import Settings

        with patch.dict(
            "os.environ",
            {
                "DATABASE_URL": "postgresql+psycopg://test:test@localhost/test",
                "SECRET_KEY": "test-secret-key-minimum-32-chars-long",
                "APP_ENV": "dev",
                "OCTOLAB_RUNTIME": "compose",
            },
            clear=True,
        ):
            settings = Settings()
            assert settings.octolab_runtime == "compose"

    def test_compose_blocked_in_production(self):
        """Verify compose runtime raises error in production."""
        from app.config import Settings

        with patch.dict(
            "os.environ",
            {
                "DATABASE_URL": "postgresql+psycopg://test:test@localhost/test",
                "SECRET_KEY": "test-secret-key-minimum-32-chars-long",
                "APP_ENV": "production",
                "OCTOLAB_RUNTIME": "compose",
                "EVIDENCE_HMAC_SECRET": "test-hmac-secret-key-for-production",
            },
            clear=True,
        ):
            with pytest.raises(ValueError) as exc_info:
                Settings()
            assert "production" in str(exc_info.value).lower()
            assert "firecracker" in str(exc_info.value).lower()

    def test_k8s_blocked_in_production(self):
        """Verify k8s runtime raises error in production."""
        from app.config import Settings

        with patch.dict(
            "os.environ",
            {
                "DATABASE_URL": "postgresql+psycopg://test:test@localhost/test",
                "SECRET_KEY": "test-secret-key-minimum-32-chars-long",
                "APP_ENV": "production",
                "OCTOLAB_RUNTIME": "k8s",
                "EVIDENCE_HMAC_SECRET": "test-hmac-secret-key-for-production",
            },
            clear=True,
        ):
            with pytest.raises(ValueError) as exc_info:
                Settings()
            assert "production" in str(exc_info.value).lower()

    def test_firecracker_allowed_in_production(self):
        """Verify firecracker runtime is allowed in production."""
        from app.config import Settings

        with patch.dict(
            "os.environ",
            {
                "DATABASE_URL": "postgresql+psycopg://test:test@localhost/test",
                "SECRET_KEY": "test-secret-key-minimum-32-chars-long",
                "APP_ENV": "production",
                "OCTOLAB_RUNTIME": "firecracker",
                "EVIDENCE_HMAC_SECRET": "test-hmac-secret-key-for-production",
            },
            clear=True,
        ):
            settings = Settings()
            assert settings.octolab_runtime == "firecracker"

    def test_noop_allowed_in_production(self):
        """Verify noop runtime is allowed in production (for testing)."""
        from app.config import Settings

        with patch.dict(
            "os.environ",
            {
                "DATABASE_URL": "postgresql+psycopg://test:test@localhost/test",
                "SECRET_KEY": "test-secret-key-minimum-32-chars-long",
                "APP_ENV": "production",
                "OCTOLAB_RUNTIME": "noop",
                "EVIDENCE_HMAC_SECRET": "test-hmac-secret-key-for-production",
            },
            clear=True,
        ):
            settings = Settings()
            assert settings.octolab_runtime == "noop"

    def test_microvm_normalizes_to_firecracker(self):
        """Verify 'microvm' alias normalizes to 'firecracker'."""
        from app.config import Settings

        with patch.dict(
            "os.environ",
            {
                "DATABASE_URL": "postgresql+psycopg://test:test@localhost/test",
                "SECRET_KEY": "test-secret-key-minimum-32-chars-long",
                "APP_ENV": "dev",
                "OCTOLAB_RUNTIME": "microvm",
            },
            clear=True,
        ):
            settings = Settings()
            assert settings.octolab_runtime == "firecracker"


class TestRuntimeGetterEnforcement:
    """Test runtime getter blocks compose/k8s in production."""

    def test_get_runtime_compose_blocked_in_production(self):
        """Verify get_runtime() raises for compose in production."""
        from app.runtime import get_runtime

        with patch("app.runtime.settings") as mock_settings:
            mock_settings.octolab_runtime = "compose"
            mock_settings.app_env = "production"

            # Clear LRU cache to force re-evaluation
            get_runtime.cache_clear()

            with pytest.raises(RuntimeError) as exc_info:
                get_runtime()

            assert "production" in str(exc_info.value).lower()
            assert "firecracker" in str(exc_info.value).lower()

    def test_get_runtime_k8s_blocked_in_production(self):
        """Verify get_runtime() raises for k8s in production."""
        from app.runtime import get_runtime

        with patch("app.runtime.settings") as mock_settings:
            mock_settings.octolab_runtime = "k8s"
            mock_settings.app_env = "production"

            get_runtime.cache_clear()

            with pytest.raises(RuntimeError) as exc_info:
                get_runtime()

            assert "production" in str(exc_info.value).lower()

    def test_get_runtime_noop_allowed_in_production(self):
        """Verify noop runtime works in production."""
        from app.runtime import get_runtime
        from app.runtime.noop import NoopRuntime

        with patch("app.runtime.settings") as mock_settings:
            mock_settings.octolab_runtime = "noop"
            mock_settings.app_env = "production"

            get_runtime.cache_clear()
            runtime = get_runtime()
            assert isinstance(runtime, NoopRuntime)


class TestLabModelDefault:
    """Test Lab model default runtime."""

    def test_lab_model_default_runtime_is_firecracker(self):
        """Verify Lab model default runtime is firecracker."""
        from app.models.lab import Lab, RuntimeType

        # Check the column default
        runtime_col = Lab.__table__.columns["runtime"]
        assert runtime_col.default.arg == RuntimeType.FIRECRACKER.value
