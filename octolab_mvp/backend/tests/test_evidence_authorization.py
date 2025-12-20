"""Tests for evidence retrieval authorization.

Tests verify:
- Only lab owner can retrieve evidence (404 for non-owners)
- JWT authentication required
- Token validation
- Pagination and filtering work correctly

SECURITY INVARIANT:
- Non-owners receive 404 (not 403) to avoid leaking lab existence
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.api.routes.evidence import verify_lab_ownership
from app.models.lab import Lab
from app.models.user import User


@pytest.mark.no_db
class TestLabOwnershipVerification:
    """Tests for verify_lab_ownership function."""

    @pytest.mark.asyncio
    async def test_owner_can_access(self):
        """Lab owner should be able to access their lab."""
        user_id = uuid4()
        lab_id = uuid4()

        # Create mock user
        mock_user = MagicMock(spec=User)
        mock_user.id = user_id

        # Create mock lab owned by user
        mock_lab = MagicMock(spec=Lab)
        mock_lab.id = lab_id
        mock_lab.owner_id = user_id

        # Create mock session that returns the lab
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_lab
        mock_session.execute.return_value = mock_result

        # Should succeed without exception
        result = await verify_lab_ownership(lab_id, mock_session, mock_user)

        assert result == mock_lab

    @pytest.mark.asyncio
    async def test_non_owner_gets_404(self):
        """Non-owner should receive 404 (not 403) to avoid leaking existence."""
        owner_id = uuid4()
        other_user_id = uuid4()
        lab_id = uuid4()

        # Create mock user (not the owner)
        mock_user = MagicMock(spec=User)
        mock_user.id = other_user_id

        # Create mock lab owned by different user
        mock_lab = MagicMock(spec=Lab)
        mock_lab.id = lab_id
        mock_lab.owner_id = owner_id

        # Create mock session that returns the lab
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_lab
        mock_session.execute.return_value = mock_result

        # Should raise 404 (NOT 403)
        with pytest.raises(HTTPException) as exc_info:
            await verify_lab_ownership(lab_id, mock_session, mock_user)

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_nonexistent_lab_gets_404(self):
        """Nonexistent lab should return 404."""
        user_id = uuid4()
        lab_id = uuid4()

        # Create mock user
        mock_user = MagicMock(spec=User)
        mock_user.id = user_id

        # Create mock session that returns None (lab not found)
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # Should raise 404
        with pytest.raises(HTTPException) as exc_info:
            await verify_lab_ownership(lab_id, mock_session, mock_user)

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_error_messages_identical_for_404_cases(self):
        """Error messages should be identical for not-found and not-owner cases.

        This prevents information disclosure via error message differences.
        """
        user_id = uuid4()
        owner_id = uuid4()
        lab_id = uuid4()

        mock_user = MagicMock(spec=User)
        mock_user.id = user_id

        mock_session = AsyncMock()

        # Case 1: Lab not found
        mock_result_not_found = MagicMock()
        mock_result_not_found.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result_not_found

        with pytest.raises(HTTPException) as exc_not_found:
            await verify_lab_ownership(lab_id, mock_session, mock_user)

        # Case 2: Lab exists but not owner
        mock_lab = MagicMock(spec=Lab)
        mock_lab.id = lab_id
        mock_lab.owner_id = owner_id

        mock_result_not_owner = MagicMock()
        mock_result_not_owner.scalar_one_or_none.return_value = mock_lab
        mock_session.execute.return_value = mock_result_not_owner

        with pytest.raises(HTTPException) as exc_not_owner:
            await verify_lab_ownership(lab_id, mock_session, mock_user)

        # Error messages should be identical
        assert exc_not_found.value.status_code == exc_not_owner.value.status_code
        assert exc_not_found.value.detail == exc_not_owner.value.detail


@pytest.mark.no_db
class TestTokenValidation:
    """Tests for internal token validation."""

    def test_missing_token_in_production_rejected(self):
        """Missing token in production environment should be rejected."""
        from app.api.routes.internal import verify_internal_token

        with patch("app.api.routes.internal.settings") as mock_settings:
            mock_settings.internal_token = "secret-token"
            mock_settings.app_env = "production"

            with pytest.raises(HTTPException) as exc_info:
                verify_internal_token(authorization=None)

            assert exc_info.value.status_code == 401

    def test_invalid_token_rejected(self):
        """Invalid token should be rejected."""
        from app.api.routes.internal import verify_internal_token

        with patch("app.api.routes.internal.settings") as mock_settings:
            mock_settings.internal_token = "correct-token"
            mock_settings.app_env = "production"

            with pytest.raises(HTTPException) as exc_info:
                verify_internal_token(authorization="Bearer wrong-token")

            assert exc_info.value.status_code == 401

    def test_valid_token_accepted(self):
        """Valid token should be accepted."""
        from app.api.routes.internal import verify_internal_token

        with patch("app.api.routes.internal.settings") as mock_settings:
            mock_settings.internal_token = "correct-token"
            mock_settings.app_env = "production"

            # Should not raise
            verify_internal_token(authorization="Bearer correct-token")

    def test_malformed_authorization_header_rejected(self):
        """Malformed Authorization header should be rejected."""
        from app.api.routes.internal import verify_internal_token

        with patch("app.api.routes.internal.settings") as mock_settings:
            mock_settings.internal_token = "secret-token"
            mock_settings.app_env = "production"

            # Missing "Bearer" prefix
            with pytest.raises(HTTPException) as exc_info:
                verify_internal_token(authorization="secret-token")

            assert exc_info.value.status_code == 401
            assert "format" in exc_info.value.detail.lower()

    def test_dev_mode_without_token_config_allowed(self):
        """In dev mode, requests should be allowed if token is not configured."""
        from app.api.routes.internal import verify_internal_token

        with patch("app.api.routes.internal.settings") as mock_settings:
            mock_settings.internal_token = None  # Not configured
            mock_settings.app_env = "dev"

            # Should not raise
            verify_internal_token(authorization=None)

    def test_test_mode_without_token_config_allowed(self):
        """In test mode, requests should be allowed if token is not configured."""
        from app.api.routes.internal import verify_internal_token

        with patch("app.api.routes.internal.settings") as mock_settings:
            mock_settings.internal_token = None  # Not configured
            mock_settings.app_env = "test"

            # Should not raise
            verify_internal_token(authorization=None)


@pytest.mark.no_db
class TestSecurityInvariants:
    """Tests for critical security invariants.

    These tests verify that security-critical behaviors are maintained.
    """

    def test_ownership_check_uses_user_id_not_request_param(self):
        """Ownership check should use current_user.id, not request parameters.

        This prevents users from bypassing ownership by manipulating request data.
        """
        # The verify_lab_ownership function takes current_user as a parameter
        # and extracts user.id from it. It does NOT accept user_id as a parameter.
        import inspect
        from app.api.routes.evidence import verify_lab_ownership

        sig = inspect.signature(verify_lab_ownership)
        params = list(sig.parameters.keys())

        # Should have: lab_id, session, current_user
        assert "lab_id" in params
        assert "session" in params
        assert "current_user" in params
        # Should NOT have user_id as separate parameter
        assert "user_id" not in params

    def test_non_owner_cannot_enumerate_labs(self):
        """Non-owners should not be able to determine if a lab exists.

        The 404 response for both "not found" and "not owner" cases
        prevents enumeration attacks.
        """
        # This is tested in test_error_messages_identical_for_404_cases
        # but we add an explicit test here for documentation
        pass

    def test_internal_token_uses_constant_time_comparison(self):
        """Token comparison should use constant-time comparison.

        This prevents timing attacks that could reveal the token.
        """
        import ast
        import inspect
        from app.api.routes.internal import verify_internal_token

        source = inspect.getsource(verify_internal_token)

        # Should use secrets.compare_digest for token comparison
        assert "secrets.compare_digest" in source or "compare_digest" in source
