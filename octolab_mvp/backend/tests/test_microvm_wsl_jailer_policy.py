"""Tests for WSL jailer policy.

Tests the resolve_use_jailer function that determines whether to use
jailer based on explicit settings and WSL detection.
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.services.microvm_paths import (
    is_wsl,
    resolve_use_jailer,
)


pytestmark = pytest.mark.no_db


class TestIsWsl:
    """Tests for is_wsl detection function."""

    def test_wsl_detected_via_interop_file(self):
        """WSL should be detected via WSLInterop file."""
        with patch.object(Path, "exists", return_value=True):
            assert is_wsl() is True

    def test_wsl_detected_via_proc_version(self):
        """WSL should be detected via 'microsoft' in /proc/version."""
        with patch.object(Path, "exists", return_value=False):
            with patch.object(Path, "read_text", return_value="Linux version 5.15.90.1-microsoft-standard-WSL2"):
                with patch.dict(os.environ, {}, clear=True):
                    assert is_wsl() is True

    def test_wsl_detected_via_env_var(self):
        """WSL should be detected via WSL_INTEROP env var."""
        with patch.object(Path, "exists", return_value=False):
            with patch.object(Path, "read_text", return_value="Linux version 5.15.0-generic"):
                with patch.dict(os.environ, {"WSL_INTEROP": "/run/WSL/1_interop"}, clear=True):
                    assert is_wsl() is True

    def test_wsl_detected_via_distro_env_var(self):
        """WSL should be detected via WSL_DISTRO_NAME env var."""
        with patch.object(Path, "exists", return_value=False):
            with patch.object(Path, "read_text", return_value="Linux version 5.15.0-generic"):
                with patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu"}, clear=True):
                    assert is_wsl() is True

    def test_native_linux_not_wsl(self):
        """Native Linux should not be detected as WSL."""
        with patch.object(Path, "exists", return_value=False):
            with patch.object(Path, "read_text", return_value="Linux version 5.15.0-generic"):
                with patch.dict(os.environ, {}, clear=True):
                    assert is_wsl() is False

    def test_proc_version_read_error(self):
        """Read error on /proc/version should not crash."""
        def mock_exists(self):
            return str(self) != "/proc/sys/fs/binfmt_misc/WSLInterop"

        with patch.object(Path, "exists", mock_exists):
            with patch.object(Path, "read_text", side_effect=OSError("Cannot read")):
                with patch.dict(os.environ, {}, clear=True):
                    # Should not raise, should return False
                    assert is_wsl() is False


class TestResolveUseJailer:
    """Tests for resolve_use_jailer function."""

    def test_explicit_true_always_uses_jailer(self):
        """Explicit True should always use jailer, even on WSL."""
        with patch("app.services.microvm_paths.is_wsl", return_value=True):
            assert resolve_use_jailer(True) is True

        with patch("app.services.microvm_paths.is_wsl", return_value=False):
            assert resolve_use_jailer(True) is True

    def test_explicit_false_never_uses_jailer(self):
        """Explicit False should never use jailer."""
        with patch("app.services.microvm_paths.is_wsl", return_value=False):
            with patch.object(Path, "exists", return_value=True):
                with patch("os.access", return_value=True):
                    assert resolve_use_jailer(False) is False

    def test_auto_wsl_no_jailer(self):
        """Auto (None) on WSL should not use jailer."""
        with patch("app.services.microvm_paths.is_wsl", return_value=True):
            # Even if jailer exists, WSL should not use it
            with patch.object(Path, "exists", return_value=True):
                with patch("os.access", return_value=True):
                    assert resolve_use_jailer(None) is False

    def test_auto_native_with_jailer_uses_jailer(self):
        """Auto (None) on native Linux with jailer should use jailer."""
        with patch("app.services.microvm_paths.is_wsl", return_value=False):
            with patch.object(Path, "exists", return_value=True):
                with patch("os.access", return_value=True):
                    assert resolve_use_jailer(None) is True

    def test_auto_native_without_jailer_no_jailer(self):
        """Auto (None) on native Linux without jailer should not use jailer."""
        with patch("app.services.microvm_paths.is_wsl", return_value=False):
            with patch.object(Path, "exists", return_value=False):
                assert resolve_use_jailer(None) is False

    def test_auto_native_jailer_not_executable(self):
        """Auto (None) on native Linux with non-executable jailer should not use it."""
        with patch("app.services.microvm_paths.is_wsl", return_value=False):
            with patch.object(Path, "exists", return_value=True):
                with patch("os.access", return_value=False):
                    assert resolve_use_jailer(None) is False

    def test_custom_jailer_path(self):
        """Custom jailer path should be checked."""
        custom_path = "/custom/path/jailer"

        with patch("app.services.microvm_paths.is_wsl", return_value=False):
            # Mock Path to check correct path is being verified
            original_exists = Path.exists
            checked_paths = []

            def mock_exists(self):
                checked_paths.append(str(self))
                return str(self) == custom_path

            with patch.object(Path, "exists", mock_exists):
                with patch("os.access", return_value=True):
                    result = resolve_use_jailer(None, jailer_bin=custom_path)

        assert custom_path in checked_paths
        assert result is True


class TestJailerPolicyIntegration:
    """Integration tests for jailer policy with smoke test."""

    def test_smoke_test_resolves_jailer_policy(self, tmp_path):
        """Smoke test should resolve jailer policy based on settings."""
        from app.services.microvm_smoke import SmokeDebug

        # Create a SmokeDebug instance to verify it has jailer fields
        debug = SmokeDebug()
        assert hasattr(debug, "use_jailer")
        assert hasattr(debug, "is_wsl")
        assert debug.use_jailer is False  # Default
        assert debug.is_wsl is False  # Default
