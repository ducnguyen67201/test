"""Tests for admin RBAC functionality.

These tests verify:
- Settings.admin_emails property parses correctly
- Non-admin users get 403 on admin endpoints
- /auth/me returns correct is_admin value
- require_admin dependency enforces allowlist
"""

import pytest
from unittest.mock import patch, MagicMock

# Mark all tests as not requiring database
pytestmark = pytest.mark.no_db


class TestSettingsAdminEmailsProperty:
    """Tests for Settings.admin_emails property parsing."""

    def test_parses_comma_separated_list(self):
        """Test that comma-separated emails are parsed correctly."""
        from app.config import Settings

        # Use env var since validation_alias maps OCTOLAB_ADMIN_EMAILS to admin_emails_raw
        with patch.dict("os.environ", {
            "DATABASE_URL": "sqlite:///:memory:",
            "SECRET_KEY": "test",
            "OCTOLAB_ADMIN_EMAILS": "a@b.com,c@d.com,e@f.com"
        }, clear=False):
            s = Settings(_env_file=None)
            assert s.admin_emails == {"a@b.com", "c@d.com", "e@f.com"}

    def test_handles_whitespace_and_empty_entries(self):
        """Test: " A@B.com,  c@d.com ,, " => {"a@b.com","c@d.com"}"""
        from app.config import Settings

        with patch.dict("os.environ", {
            "DATABASE_URL": "sqlite:///:memory:",
            "SECRET_KEY": "test",
            "OCTOLAB_ADMIN_EMAILS": " A@B.com,  c@d.com ,, "
        }, clear=False):
            s = Settings(_env_file=None)
            assert s.admin_emails == {"a@b.com", "c@d.com"}

    def test_lowercases_emails(self):
        """Test that emails are lowercased."""
        from app.config import Settings

        with patch.dict("os.environ", {
            "DATABASE_URL": "sqlite:///:memory:",
            "SECRET_KEY": "test",
            "OCTOLAB_ADMIN_EMAILS": "ADMIN@EXAMPLE.COM,Ops@Test.COM"
        }, clear=False):
            s = Settings(_env_file=None)
            assert "admin@example.com" in s.admin_emails
            assert "ops@test.com" in s.admin_emails
            # Uppercase should not be in set
            assert "ADMIN@EXAMPLE.COM" not in s.admin_emails

    def test_returns_empty_set_for_empty_config(self):
        """Test that empty config returns empty set."""
        from app.config import Settings

        with patch.dict("os.environ", {
            "DATABASE_URL": "sqlite:///:memory:",
            "SECRET_KEY": "test",
            "OCTOLAB_ADMIN_EMAILS": ""
        }, clear=False):
            s = Settings(_env_file=None)
            assert s.admin_emails == set()

    def test_returns_empty_set_for_whitespace_only(self):
        """Test that whitespace-only config returns empty set."""
        from app.config import Settings

        with patch.dict("os.environ", {
            "DATABASE_URL": "sqlite:///:memory:",
            "SECRET_KEY": "test",
            "OCTOLAB_ADMIN_EMAILS": "   ,  ,  "
        }, clear=False):
            s = Settings(_env_file=None)
            assert s.admin_emails == set()


class TestIsAdminHelper:
    """Tests for the _is_admin helper function in auth.py."""

    def test_returns_true_for_admin_email(self):
        """Test that admin emails are recognized."""
        from app.api.routes.auth import _is_admin

        with patch("app.api.routes.auth.settings") as mock_settings:
            mock_settings.admin_emails = {"admin@example.com", "ops@example.com"}

            assert _is_admin("admin@example.com") is True
            assert _is_admin("ADMIN@EXAMPLE.COM") is True  # Case insensitive
            assert _is_admin("ops@example.com") is True

    def test_returns_false_for_non_admin_email(self):
        """Test that non-admin emails are rejected."""
        from app.api.routes.auth import _is_admin

        with patch("app.api.routes.auth.settings") as mock_settings:
            mock_settings.admin_emails = {"admin@example.com"}

            assert _is_admin("user@example.com") is False
            assert _is_admin("notadmin@example.com") is False

    def test_returns_false_when_no_admins_configured(self):
        """Test that empty admin set means no admins."""
        from app.api.routes.auth import _is_admin

        with patch("app.api.routes.auth.settings") as mock_settings:
            mock_settings.admin_emails = set()
            assert _is_admin("admin@example.com") is False

    def test_handles_whitespace_in_email(self):
        """Test that whitespace in input email is trimmed."""
        from app.api.routes.auth import _is_admin

        with patch("app.api.routes.auth.settings") as mock_settings:
            mock_settings.admin_emails = {"admin@example.com"}

            assert _is_admin("  admin@example.com  ") is True

    def test_handles_none_email(self):
        """Test that None email doesn't crash."""
        from app.api.routes.auth import _is_admin

        with patch("app.api.routes.auth.settings") as mock_settings:
            mock_settings.admin_emails = {"admin@example.com"}
            assert _is_admin(None) is False


class TestRequireAdminDependency:
    """Tests for the require_admin dependency."""

    def test_rejects_non_admin_user(self):
        """Test that non-admin users get 403."""
        from fastapi import HTTPException
        from app.api.routes.admin import require_admin

        mock_user = MagicMock()
        mock_user.email = "user@example.com"

        with patch("app.api.routes.admin.settings") as mock_settings:
            mock_settings.admin_emails = {"admin@example.com"}

            with pytest.raises(HTTPException) as exc_info:
                require_admin(mock_user)

            assert exc_info.value.status_code == 403
            assert "Admin access required" in exc_info.value.detail

    def test_accepts_admin_user(self):
        """Test that admin users pass through."""
        from app.api.routes.admin import require_admin

        mock_user = MagicMock()
        mock_user.email = "admin@example.com"

        with patch("app.api.routes.admin.settings") as mock_settings:
            mock_settings.admin_emails = {"admin@example.com"}

            result = require_admin(mock_user)
            assert result == mock_user

    def test_accepts_admin_user_case_insensitive(self):
        """Test that admin check is case-insensitive."""
        from app.api.routes.admin import require_admin

        mock_user = MagicMock()
        mock_user.email = "ADMIN@EXAMPLE.COM"

        with patch("app.api.routes.admin.settings") as mock_settings:
            mock_settings.admin_emails = {"admin@example.com"}

            result = require_admin(mock_user)
            assert result == mock_user

    def test_rejects_when_admin_not_configured(self):
        """Test that 403 is returned when no admins configured."""
        from fastapi import HTTPException
        from app.api.routes.admin import require_admin

        mock_user = MagicMock()
        mock_user.email = "admin@example.com"

        with patch("app.api.routes.admin.settings") as mock_settings:
            mock_settings.admin_emails = set()

            with pytest.raises(HTTPException) as exc_info:
                require_admin(mock_user)

            assert exc_info.value.status_code == 403
            assert "not configured" in exc_info.value.detail

    def test_handles_user_with_none_email(self):
        """Test that user with None email gets 403."""
        from fastapi import HTTPException
        from app.api.routes.admin import require_admin

        mock_user = MagicMock()
        mock_user.email = None

        with patch("app.api.routes.admin.settings") as mock_settings:
            mock_settings.admin_emails = {"admin@example.com"}

            with pytest.raises(HTTPException) as exc_info:
                require_admin(mock_user)

            assert exc_info.value.status_code == 403


class TestUserResponseIsAdmin:
    """Tests for is_admin field in UserResponse."""

    def test_user_response_has_is_admin_field(self):
        """Test that UserResponse schema includes is_admin."""
        from app.schemas.user import UserResponse
        from datetime import datetime
        from uuid import uuid4

        response = UserResponse(
            id=uuid4(),
            email="test@example.com",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            is_admin=True,
        )

        assert hasattr(response, "is_admin")
        assert response.is_admin is True

    def test_user_response_is_admin_defaults_to_false(self):
        """Test that is_admin defaults to False."""
        from app.schemas.user import UserResponse
        from datetime import datetime
        from uuid import uuid4

        response = UserResponse(
            id=uuid4(),
            email="test@example.com",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        assert response.is_admin is False


class TestAdminRouterDependency:
    """Tests for router-wide admin dependency."""

    def test_admin_router_has_require_admin_dependency(self):
        """Test that admin router has require_admin as a dependency."""
        from app.api.routes.admin import router, require_admin

        # Check that router has dependencies
        assert len(router.dependencies) > 0

        # Verify require_admin is in the dependencies
        dep_callables = [d.dependency for d in router.dependencies]
        assert require_admin in dep_callables
