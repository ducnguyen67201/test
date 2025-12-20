"""Tests for the lab cleanup module."""

import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

# Set required env vars before importing modules that need settings
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "test_secret_key_for_testing")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("OCTOLAB_RUNTIME", "noop")

# Mark all tests as no_db since we mock everything
pytestmark = pytest.mark.no_db


class TestCleanupResult:
    """Tests for CleanupResult dataclass."""

    def test_cleanup_result_to_dict(self):
        """Test CleanupResult serializes correctly."""
        from app.services.lab_cleanup import CleanupResult

        result = CleanupResult(
            success=True,
            tier_used=1,
            issues_found=["graceful_shutdown_failed"],
            issues_resolved=["firecracker_process"],
            errors=["test_error"],
        )

        d = result.to_dict()
        assert d["success"] is True
        assert d["tier_used"] == 1
        assert "graceful_shutdown_failed" in d["issues_found"]
        assert "firecracker_process" in d["issues_resolved"]
        assert "test_error" in d["errors"]


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_process_exists_returns_false_for_none(self):
        """Test _process_exists returns False for None PID."""
        from app.services.lab_cleanup import _process_exists

        assert _process_exists(None) is False

    def test_process_exists_returns_false_for_nonexistent(self):
        """Test _process_exists returns False for nonexistent PID."""
        from app.services.lab_cleanup import _process_exists

        # Use a very high PID that's unlikely to exist
        assert _process_exists(999999999) is False


class TestGracefulShutdown:
    """Tests for graceful_shutdown function."""

    @pytest.mark.asyncio
    async def test_graceful_shutdown_no_pid(self):
        """Test graceful_shutdown returns True when no PID exists."""
        from app.services.lab_cleanup import graceful_shutdown

        # Use a fake lab_id with proper UUID format
        lab_id = "12345678-1234-1234-1234-123456789abc"

        with patch(
            "app.services.lab_cleanup._get_firecracker_pid", return_value=None
        ):
            result = await graceful_shutdown(lab_id, timeout=1)
            assert result is True

    @pytest.mark.asyncio
    async def test_graceful_shutdown_process_already_gone(self):
        """Test graceful_shutdown returns True when process doesn't exist."""
        from app.services.lab_cleanup import graceful_shutdown

        lab_id = "12345678-1234-1234-1234-123456789abc"

        with patch(
            "app.services.lab_cleanup._get_firecracker_pid", return_value=12345
        ), patch("app.services.lab_cleanup._process_exists", return_value=False):
            result = await graceful_shutdown(lab_id, timeout=1)
            assert result is True


class TestVerifyCriticalResources:
    """Tests for verify_critical_resources function."""

    @pytest.mark.asyncio
    async def test_verify_clean_when_nothing_exists(self):
        """Test verify returns clean=True when no resources exist."""
        from app.services.lab_cleanup import verify_critical_resources

        lab_id = "12345678-1234-1234-1234-123456789abc"

        with patch(
            "app.services.lab_cleanup._get_firecracker_pid", return_value=None
        ), patch(
            "app.services.lab_cleanup._state_dir_exists", return_value=False
        ):
            result = await verify_critical_resources(lab_id)
            assert result.clean is True
            assert len(result.issues) == 0

    @pytest.mark.asyncio
    async def test_verify_reports_process_still_running(self):
        """Test verify reports when process is still running."""
        from app.services.lab_cleanup import verify_critical_resources

        lab_id = "12345678-1234-1234-1234-123456789abc"

        with patch(
            "app.services.lab_cleanup._get_firecracker_pid", return_value=12345
        ), patch(
            "app.services.lab_cleanup._process_exists", return_value=True
        ), patch(
            "app.services.lab_cleanup._state_dir_exists", return_value=False
        ):
            result = await verify_critical_resources(lab_id)
            assert result.clean is False
            assert "firecracker_process" in result.issues

    @pytest.mark.asyncio
    async def test_verify_reports_state_dir_exists(self):
        """Test verify reports when state directory exists."""
        from app.services.lab_cleanup import verify_critical_resources

        lab_id = "12345678-1234-1234-1234-123456789abc"

        with patch(
            "app.services.lab_cleanup._get_firecracker_pid", return_value=None
        ), patch(
            "app.services.lab_cleanup._state_dir_exists", return_value=True
        ):
            result = await verify_critical_resources(lab_id)
            assert result.clean is False
            assert "state_directory" in result.issues


class TestSmartCleanup:
    """Tests for smart_cleanup orchestrator."""

    @pytest.mark.asyncio
    async def test_smart_cleanup_tier_1_success(self):
        """Test smart_cleanup succeeds at tier 1 (graceful shutdown)."""
        from app.services.lab_cleanup import smart_cleanup, ResourceCheck

        lab_id = "12345678-1234-1234-1234-123456789abc"

        with patch(
            "app.services.lab_cleanup.graceful_shutdown",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.services.lab_cleanup.verify_critical_resources",
            new_callable=AsyncMock,
            return_value=ResourceCheck(clean=True, issues=[]),
        ), patch(
            "app.services.lab_cleanup.targeted_network_cleanup",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await smart_cleanup(lab_id, graceful_timeout=1)
            assert result.success is True
            assert result.tier_used in (1, 2)

    @pytest.mark.asyncio
    async def test_smart_cleanup_escalates_to_tier_3(self):
        """Test smart_cleanup escalates to tier 3 when resources stuck."""
        from app.services.lab_cleanup import smart_cleanup, ResourceCheck

        lab_id = "12345678-1234-1234-1234-123456789abc"

        # First verify returns dirty, second verify (after targeted) returns clean
        verify_calls = [
            ResourceCheck(clean=False, issues=["firecracker_process"]),
            ResourceCheck(clean=True, issues=[]),
        ]

        with patch(
            "app.services.lab_cleanup.graceful_shutdown",
            new_callable=AsyncMock,
            return_value=False,
        ), patch(
            "app.services.lab_cleanup.verify_critical_resources",
            new_callable=AsyncMock,
            side_effect=verify_calls,
        ), patch(
            "app.services.lab_cleanup.targeted_cleanup",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.services.lab_cleanup.targeted_network_cleanup",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await smart_cleanup(lab_id, graceful_timeout=1)
            assert result.success is True
            assert result.tier_used == 3
            assert "firecracker_process" in result.issues_resolved
