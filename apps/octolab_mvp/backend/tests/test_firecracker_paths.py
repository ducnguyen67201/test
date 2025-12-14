"""Tests for Firecracker path handling and containment.

SECURITY tests:
- Path traversal attacks rejected
- Containment validation works
- Invalid lab IDs rejected
- Paths resolve correctly under state dir
"""

import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.firecracker_paths import (
    InvalidLabIdError,
    PathContainmentError,
    cleanup_lab_state_dir,
    ensure_lab_state_dir,
    lab_log_path,
    lab_pid_path,
    lab_rootfs_path,
    lab_socket_path,
    lab_state_dir,
    lab_token_path,
    redact_path,
    validate_lab_id,
)


# =============================================================================
# Lab ID Validation Tests
# =============================================================================


class TestValidateLabId:
    """Tests for lab ID validation."""

    def test_valid_uuid_string(self):
        """Valid UUID string should pass."""
        lab_id = "12345678-1234-1234-1234-123456789abc"
        result = validate_lab_id(lab_id)
        assert result == lab_id.lower()

    def test_valid_uuid_object(self):
        """Valid UUID object should pass."""
        lab_id = uuid4()
        result = validate_lab_id(lab_id)
        assert result == str(lab_id).lower()

    def test_uppercase_normalized(self):
        """Uppercase UUIDs should be normalized to lowercase."""
        lab_id = "12345678-1234-1234-1234-123456789ABC"
        result = validate_lab_id(lab_id)
        assert result == lab_id.lower()

    def test_rejects_empty_string(self):
        """Empty string should be rejected."""
        with pytest.raises(InvalidLabIdError):
            validate_lab_id("")

    def test_rejects_short_uuid(self):
        """Short UUID should be rejected."""
        with pytest.raises(InvalidLabIdError):
            validate_lab_id("12345678-1234")

    def test_rejects_traversal_attempt(self):
        """Path traversal attempts should be rejected."""
        with pytest.raises(InvalidLabIdError):
            validate_lab_id("../../../etc/passwd")

    def test_rejects_command_injection(self):
        """Command injection attempts should be rejected."""
        with pytest.raises(InvalidLabIdError):
            validate_lab_id("$(rm -rf /)")

    def test_rejects_null_bytes(self):
        """Null bytes should be rejected."""
        with pytest.raises(InvalidLabIdError):
            validate_lab_id("12345678-1234-1234-1234-123456789abc\x00evil")


# =============================================================================
# Path Containment Tests
# =============================================================================


class TestLabStateDir:
    """Tests for lab_state_dir containment."""

    def test_valid_lab_id_returns_path(self):
        """Valid lab ID should return a path under state dir."""
        lab_id = uuid4()
        result = lab_state_dir(lab_id)
        assert "lab_" in str(result)
        assert str(lab_id).lower() in str(result).lower()

    def test_path_under_state_dir(self, monkeypatch):
        """Returned path must be under state directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(
                "app.services.firecracker_paths.settings.microvm_state_dir",
                tmpdir,
            )
            lab_id = uuid4()
            result = lab_state_dir(lab_id)
            assert str(result).startswith(tmpdir)

    def test_rejects_invalid_lab_id(self):
        """Invalid lab ID should raise InvalidLabIdError."""
        with pytest.raises(InvalidLabIdError):
            lab_state_dir("not-a-uuid")


class TestPathFunctions:
    """Tests for path derivation functions."""

    def test_socket_path_under_state_dir(self, monkeypatch):
        """Socket path should be under lab state dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(
                "app.services.firecracker_paths.settings.microvm_state_dir",
                tmpdir,
            )
            lab_id = uuid4()
            result = lab_socket_path(lab_id)
            assert str(result).startswith(tmpdir)
            assert result.name == "firecracker.sock"

    def test_rootfs_path_under_state_dir(self, monkeypatch):
        """Rootfs path should be under lab state dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(
                "app.services.firecracker_paths.settings.microvm_state_dir",
                tmpdir,
            )
            lab_id = uuid4()
            result = lab_rootfs_path(lab_id)
            assert str(result).startswith(tmpdir)
            assert result.name == "rootfs.ext4"

    def test_log_path_under_state_dir(self, monkeypatch):
        """Log path should be under lab state dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(
                "app.services.firecracker_paths.settings.microvm_state_dir",
                tmpdir,
            )
            lab_id = uuid4()
            result = lab_log_path(lab_id)
            assert str(result).startswith(tmpdir)
            assert result.name == "firecracker.log"

    def test_token_path_under_state_dir(self, monkeypatch):
        """Token path should be under lab state dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(
                "app.services.firecracker_paths.settings.microvm_state_dir",
                tmpdir,
            )
            lab_id = uuid4()
            result = lab_token_path(lab_id)
            assert str(result).startswith(tmpdir)
            assert result.name == ".token"

    def test_pid_path_under_state_dir(self, monkeypatch):
        """PID path should be under lab state dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(
                "app.services.firecracker_paths.settings.microvm_state_dir",
                tmpdir,
            )
            lab_id = uuid4()
            result = lab_pid_path(lab_id)
            assert str(result).startswith(tmpdir)
            assert result.name == "firecracker.pid"


# =============================================================================
# Directory Management Tests
# =============================================================================


class TestEnsureLabStateDir:
    """Tests for ensure_lab_state_dir."""

    def test_creates_directory(self, monkeypatch):
        """Should create lab state directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(
                "app.services.firecracker_paths.settings.microvm_state_dir",
                tmpdir,
            )
            lab_id = uuid4()
            result = ensure_lab_state_dir(lab_id)
            assert result.exists()
            assert result.is_dir()

    def test_directory_has_restrictive_permissions(self, monkeypatch):
        """Created directory should have 0700 permissions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(
                "app.services.firecracker_paths.settings.microvm_state_dir",
                tmpdir,
            )
            lab_id = uuid4()
            result = ensure_lab_state_dir(lab_id)
            mode = result.stat().st_mode & 0o777
            assert mode == 0o700

    def test_idempotent(self, monkeypatch):
        """Should be safe to call multiple times."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(
                "app.services.firecracker_paths.settings.microvm_state_dir",
                tmpdir,
            )
            lab_id = uuid4()
            result1 = ensure_lab_state_dir(lab_id)
            result2 = ensure_lab_state_dir(lab_id)
            assert result1 == result2
            assert result1.exists()


class TestCleanupLabStateDir:
    """Tests for cleanup_lab_state_dir."""

    def test_removes_directory(self, monkeypatch):
        """Should remove lab state directory and contents."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(
                "app.services.firecracker_paths.settings.microvm_state_dir",
                tmpdir,
            )
            lab_id = uuid4()
            lab_dir = ensure_lab_state_dir(lab_id)

            # Create some files
            (lab_dir / "test.txt").touch()
            (lab_dir / "subdir").mkdir()
            (lab_dir / "subdir" / "file.txt").touch()

            assert lab_dir.exists()
            result = cleanup_lab_state_dir(lab_id)
            assert result is True
            assert not lab_dir.exists()

    def test_returns_false_for_nonexistent(self, monkeypatch):
        """Should return False if directory doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(
                "app.services.firecracker_paths.settings.microvm_state_dir",
                tmpdir,
            )
            lab_id = uuid4()
            result = cleanup_lab_state_dir(lab_id)
            assert result is False


# =============================================================================
# Path Redaction Tests
# =============================================================================


class TestRedactPath:
    """Tests for path redaction."""

    def test_shows_only_basename(self, tmp_path):
        """Should only show basename, not full path."""
        test_file = tmp_path / "secret.txt"
        test_file.touch()
        result = redact_path(test_file)
        assert "secret.txt" in result
        assert str(tmp_path) not in result

    def test_shows_exists_status(self, tmp_path):
        """Should show whether path exists."""
        existing = tmp_path / "exists.txt"
        existing.touch()
        missing = tmp_path / "missing.txt"

        assert "(exists)" in redact_path(existing)
        assert "(missing)" in redact_path(missing)

    def test_handles_string_path(self, tmp_path):
        """Should handle string paths."""
        result = redact_path(str(tmp_path / "test.txt"))
        assert "test.txt" in result
        assert "(missing)" in result

    def test_never_contains_parent_dirs(self, tmp_path):
        """Should never contain parent directory names."""
        deep_path = tmp_path / "a" / "b" / "c" / "secret.txt"
        deep_path.parent.mkdir(parents=True, exist_ok=True)
        deep_path.touch()

        result = redact_path(deep_path)
        assert "/a/" not in result
        assert "/b/" not in result
        assert "/c/" not in result


# =============================================================================
# Security Regression Tests
# =============================================================================


class TestSecurityRegressions:
    """Regression tests for security issues."""

    def test_no_path_traversal_via_uuid_chars(self, monkeypatch):
        """Ensure special characters in UUID-like input don't cause traversal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(
                "app.services.firecracker_paths.settings.microvm_state_dir",
                tmpdir,
            )
            # These should all be rejected
            malicious_inputs = [
                "../../../etc/passwd",
                "..%2f..%2f..%2fetc%2fpasswd",
                "....//....//etc/passwd",
                "/etc/passwd",
                "12345678-1234-1234-1234-123456789abc/../../../etc",
            ]
            for mal_input in malicious_inputs:
                with pytest.raises((InvalidLabIdError, PathContainmentError)):
                    lab_state_dir(mal_input)

    def test_deterministic_paths(self, monkeypatch):
        """Same lab ID should always produce same path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(
                "app.services.firecracker_paths.settings.microvm_state_dir",
                tmpdir,
            )
            lab_id = uuid4()
            path1 = lab_state_dir(lab_id)
            path2 = lab_state_dir(lab_id)
            path3 = lab_state_dir(str(lab_id))
            assert path1 == path2 == path3
