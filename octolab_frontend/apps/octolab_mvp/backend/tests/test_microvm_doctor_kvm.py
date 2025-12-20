"""Tests for microVM doctor KVM ioctl check.

Tests the KVM_GET_API_VERSION ioctl-based verification that ensures
/dev/kvm is actually functional, not just present with RW permissions.
"""

import errno
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.microvm_doctor import (
    _check_kvm,
    KVM_GET_API_VERSION,
    KVM_API_VERSION_MIN,
)


pytestmark = pytest.mark.no_db


class TestCheckKvmIoctl:
    """Tests for _check_kvm with ioctl verification."""

    def test_kvm_missing_fatal(self):
        """Missing /dev/kvm should be fatal."""
        with patch.object(Path, "exists", return_value=False):
            with patch("app.services.microvm_doctor._is_wsl", return_value=False):
                result = _check_kvm({})

        assert result["status"] == "FAIL"
        assert result["severity"] == "fatal"
        assert "not found" in result["message"]

    def test_kvm_missing_wsl_hint(self):
        """Missing /dev/kvm on WSL should have WSL-specific hint."""
        with patch.object(Path, "exists", return_value=False):
            with patch("app.services.microvm_doctor._is_wsl", return_value=True):
                result = _check_kvm({})

        assert result["status"] == "FAIL"
        assert result["severity"] == "fatal"
        assert "wslconfig" in result["hint"].lower() or "nested" in result["hint"].lower()

    def test_kvm_permission_denied_fatal(self):
        """Permission denied on /dev/kvm should be fatal."""
        with patch.object(Path, "exists", return_value=True):
            with patch("os.open", side_effect=PermissionError("Permission denied")):
                with patch("app.services.microvm_doctor._is_wsl", return_value=False):
                    result = _check_kvm({})

        assert result["status"] == "FAIL"
        assert result["severity"] == "fatal"
        assert "not writable" in result["message"]

    def test_kvm_permission_denied_wsl_hint(self):
        """Permission denied on WSL should have WSL-specific hint."""
        with patch.object(Path, "exists", return_value=True):
            with patch("os.open", side_effect=PermissionError("Permission denied")):
                with patch("app.services.microvm_doctor._is_wsl", return_value=True):
                    result = _check_kvm({})

        assert result["status"] == "FAIL"
        assert result["severity"] == "fatal"
        assert "wsl --shutdown" in result["hint"].lower()

    def test_kvm_ioctl_success(self):
        """Successful ioctl should return OK with API version."""
        mock_fd = 123

        with patch.object(Path, "exists", return_value=True):
            with patch("os.open", return_value=mock_fd):
                with patch("os.close"):
                    # Mock ioctl to return a valid API version (e.g., 12)
                    with patch("fcntl.ioctl", return_value=12) as mock_ioctl:
                        with patch("app.services.microvm_doctor._is_wsl", return_value=False):
                            result = _check_kvm({})

        assert result["status"] == "OK"
        assert result["severity"] == "info"
        assert "API version 12" in result["message"]
        mock_ioctl.assert_called_once_with(mock_fd, KVM_GET_API_VERSION)

    def test_kvm_ioctl_failure_fatal(self):
        """ioctl failure should be fatal even if file is RW."""
        mock_fd = 123

        with patch.object(Path, "exists", return_value=True):
            with patch("os.open", return_value=mock_fd):
                with patch("os.close"):
                    # Mock ioctl to raise ENOTTY (device doesn't support ioctl)
                    ioctl_err = OSError(errno.ENOTTY, "Inappropriate ioctl for device")
                    with patch("fcntl.ioctl", side_effect=ioctl_err):
                        with patch("app.services.microvm_doctor._is_wsl", return_value=False):
                            result = _check_kvm({})

        assert result["status"] == "FAIL"
        assert result["severity"] == "fatal"
        assert "ioctl failed" in result["message"]
        assert "ENOTTY" in result["message"]

    def test_kvm_ioctl_failure_wsl_hint(self):
        """ioctl failure on WSL should have WSL-specific hint."""
        mock_fd = 123

        with patch.object(Path, "exists", return_value=True):
            with patch("os.open", return_value=mock_fd):
                with patch("os.close"):
                    ioctl_err = OSError(errno.ENOTTY, "Inappropriate ioctl for device")
                    with patch("fcntl.ioctl", side_effect=ioctl_err):
                        with patch("app.services.microvm_doctor._is_wsl", return_value=True):
                            result = _check_kvm({})

        assert result["status"] == "FAIL"
        assert result["severity"] == "fatal"
        assert "ioctl failed" in result["message"]
        assert "nested" in result["hint"].lower() or "wslconfig" in result["hint"].lower()

    def test_kvm_api_version_too_old(self):
        """API version below minimum should be fatal."""
        mock_fd = 123

        with patch.object(Path, "exists", return_value=True):
            with patch("os.open", return_value=mock_fd):
                with patch("os.close"):
                    # Mock ioctl to return an old API version (e.g., 5)
                    with patch("fcntl.ioctl", return_value=5):
                        with patch("app.services.microvm_doctor._is_wsl", return_value=False):
                            result = _check_kvm({})

        assert result["status"] == "FAIL"
        assert result["severity"] == "fatal"
        assert "too old" in result["message"]
        assert "5" in result["message"]

    def test_kvm_fd_always_closed(self):
        """File descriptor should always be closed, even on error."""
        mock_fd = 123
        close_called = []

        def track_close(fd):
            close_called.append(fd)

        with patch.object(Path, "exists", return_value=True):
            with patch("os.open", return_value=mock_fd):
                with patch("os.close", side_effect=track_close):
                    ioctl_err = OSError(errno.ENOTTY, "error")
                    with patch("fcntl.ioctl", side_effect=ioctl_err):
                        with patch("app.services.microvm_doctor._is_wsl", return_value=False):
                            _check_kvm({})

        assert mock_fd in close_called, "fd should be closed even on ioctl error"

    def test_kvm_unexpected_error(self):
        """Unexpected errors should be fatal with error type in message."""
        with patch.object(Path, "exists", return_value=True):
            with patch("os.open", side_effect=RuntimeError("unexpected")):
                with patch("app.services.microvm_doctor._is_wsl", return_value=False):
                    result = _check_kvm({})

        assert result["status"] == "FAIL"
        assert result["severity"] == "fatal"
        assert "RuntimeError" in result["message"]


class TestKvmConstants:
    """Tests for KVM ioctl constants."""

    def test_kvm_get_api_version_constant(self):
        """KVM_GET_API_VERSION should be 0xAE00."""
        assert KVM_GET_API_VERSION == 0xAE00

    def test_kvm_api_version_min(self):
        """Minimum API version should be 12."""
        assert KVM_API_VERSION_MIN == 12
