"""Tests for microvm_paths safe path utilities.

SECURITY FOCUS:
- Path traversal prevention (../)
- Symlink attack prevention
- Containment validation
- Secret redaction
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

from app.services.microvm_paths import (
    PathContainmentError,
    PathTraversalError,
    _contains_traversal,
    redact_path,
    redact_secret_patterns,
    resolve_under_base,
    safe_config_excerpt,
    safe_tail,
)


# Mark all tests as no_db since we don't need database
pytestmark = pytest.mark.no_db


class TestContainsTraversal:
    """Tests for _contains_traversal helper."""

    def test_empty_parts(self):
        """Empty parts should not contain traversal."""
        assert not _contains_traversal(())

    def test_safe_parts(self):
        """Normal path parts should pass."""
        assert not _contains_traversal(("foo", "bar", "baz.txt"))
        assert not _contains_traversal(("smoke_12345", "rootfs.ext4"))

    def test_dotdot_component(self):
        """Standalone .. should be detected."""
        assert _contains_traversal(("..",))
        assert _contains_traversal(("foo", "..", "bar"))

    def test_embedded_traversal(self):
        """Embedded traversal patterns should be detected."""
        assert _contains_traversal(("../etc/passwd",))
        assert _contains_traversal(("foo/../bar",))
        assert _contains_traversal(("foo/../../etc",))

    def test_absolute_path_rejected(self):
        """Absolute paths in parts should be detected."""
        assert _contains_traversal(("/etc/passwd",))
        assert _contains_traversal(("foo", "/etc/passwd"))

    def test_windows_style_traversal(self):
        """Windows-style traversal should be detected."""
        assert _contains_traversal(("..\\etc\\passwd",))
        assert _contains_traversal(("foo\\..\\bar",))


class TestResolveUnderBase:
    """Tests for resolve_under_base function."""

    def test_simple_path(self, tmp_path):
        """Simple path under base should resolve correctly."""
        result = resolve_under_base(tmp_path, "subdir", "file.txt")
        assert result == tmp_path / "subdir" / "file.txt"
        assert str(result).startswith(str(tmp_path))

    def test_existing_path(self, tmp_path):
        """Existing path should resolve correctly."""
        subdir = tmp_path / "existing"
        subdir.mkdir()
        result = resolve_under_base(tmp_path, "existing")
        assert result == subdir

    def test_traversal_rejected(self, tmp_path):
        """Path traversal should raise PathTraversalError."""
        with pytest.raises(PathTraversalError):
            resolve_under_base(tmp_path, "..", "etc", "passwd")

    def test_traversal_embedded_rejected(self, tmp_path):
        """Embedded traversal should raise PathTraversalError."""
        with pytest.raises(PathTraversalError):
            resolve_under_base(tmp_path, "foo/../bar")

    def test_double_traversal_rejected(self, tmp_path):
        """Multiple traversals should raise PathTraversalError."""
        with pytest.raises(PathTraversalError):
            resolve_under_base(tmp_path, "foo", "..", "..", "etc", "passwd")

    def test_absolute_path_in_parts_rejected(self, tmp_path):
        """Absolute path as part should raise PathTraversalError."""
        with pytest.raises(PathTraversalError):
            resolve_under_base(tmp_path, "/etc/passwd")

    def test_empty_parts_returns_base(self, tmp_path):
        """Empty parts should return base."""
        result = resolve_under_base(tmp_path)
        assert result == tmp_path.resolve()

    def test_empty_string_parts_ignored(self, tmp_path):
        """Empty string parts should be ignored."""
        result = resolve_under_base(tmp_path, "", "subdir", "", "file.txt")
        assert result == tmp_path / "subdir" / "file.txt"

    def test_symlink_attack_caught(self, tmp_path):
        """Symlink pointing outside base should be caught."""
        # Create a symlink pointing outside
        outside = tmp_path.parent / "outside_dir"
        outside.mkdir(exist_ok=True)

        symlink = tmp_path / "evil_symlink"
        symlink.symlink_to(outside)

        # Trying to resolve under the symlink should fail containment
        with pytest.raises(PathContainmentError):
            resolve_under_base(tmp_path, "evil_symlink")

    def test_deep_nesting(self, tmp_path):
        """Deep nesting should work if all parts are safe."""
        result = resolve_under_base(tmp_path, "a", "b", "c", "d", "e.txt")
        assert str(result).startswith(str(tmp_path))
        assert result.name == "e.txt"


class TestRedactPath:
    """Tests for redact_path function."""

    def test_basename_only(self):
        """Without base_dir, should show only basename."""
        result = redact_path("/var/lib/octolab/microvm/smoke_123/rootfs.ext4")
        assert result == ".../rootfs.ext4"

    def test_with_base_dir(self, tmp_path):
        """With base_dir, should show relative path."""
        full_path = tmp_path / "smoke_123" / "rootfs.ext4"
        result = redact_path(full_path, "<STATE_DIR>", tmp_path)
        assert result == "<STATE_DIR>/smoke_123/rootfs.ext4"

    def test_path_not_under_base(self, tmp_path):
        """Path not under base_dir should show basename."""
        result = redact_path("/etc/passwd", "<STATE_DIR>", tmp_path)
        assert result == ".../passwd"

    def test_empty_path(self):
        """Empty path should return placeholder."""
        result = redact_path("")
        assert result == "(path)"  # Empty path gets fallback placeholder

    def test_path_object(self, tmp_path):
        """Should accept Path objects."""
        result = redact_path(tmp_path / "file.txt")
        assert result == ".../file.txt"


class TestRedactSecretPatterns:
    """Tests for redact_secret_patterns function."""

    def test_postgresql_url_redacted(self):
        """PostgreSQL URLs should be redacted."""
        text = "connecting to postgresql://user:password@localhost:5432/db"
        result = redact_secret_patterns(text)
        assert "password" not in result
        assert "postgresql://<REDACTED>" in result

    def test_asyncpg_url_redacted(self):
        """asyncpg URLs should be redacted."""
        text = "Error: postgresql+asyncpg://admin:secret123@db.example.com/prod"
        result = redact_secret_patterns(text)
        assert "secret123" not in result
        assert "postgresql://<REDACTED>" in result

    def test_secret_key_redacted(self):
        """SECRET_KEY values should be redacted."""
        text = "SECRET_KEY=mysupersecretkey123"
        result = redact_secret_patterns(text)
        assert "mysupersecretkey123" not in result
        assert "SECRET_KEY=<REDACTED>" in result

    def test_guac_password_redacted(self):
        """GUAC_ADMIN_PASSWORD should be redacted."""
        text = "GUAC_ADMIN_PASSWORD=guacadminpass"
        result = redact_secret_patterns(text)
        assert "guacadminpass" not in result
        assert "GUAC_ADMIN_PASSWORD=<REDACTED>" in result

    def test_database_url_redacted(self):
        """DATABASE_URL should be redacted."""
        text = "DATABASE_URL=postgres://user:pw@host/db"
        result = redact_secret_patterns(text)
        assert "DATABASE_URL=<REDACTED>" in result

    def test_hex_token_redacted(self):
        """Long hex tokens should be redacted."""
        text = "token=abcdef0123456789abcdef0123456789abcd"
        result = redact_secret_patterns(text)
        assert "abcdef0123456789abcdef0123456789" not in result
        assert "<REDACTED_TOKEN>" in result

    def test_safe_text_unchanged(self):
        """Text without secrets should be unchanged."""
        text = "Firecracker started with PID 12345"
        result = redact_secret_patterns(text)
        assert result == text

    def test_multiple_secrets(self):
        """Multiple secrets should all be redacted."""
        text = "SECRET_KEY=secret1 DATABASE_URL=postgres://u:p@h/d"
        result = redact_secret_patterns(text)
        assert "secret1" not in result
        assert "SECRET_KEY=<REDACTED>" in result
        assert "DATABASE_URL=<REDACTED>" in result


class TestSafeTail:
    """Tests for safe_tail function."""

    def test_short_content(self):
        """Short content should be returned as-is (after redaction)."""
        content = "Line 1\nLine 2\nLine 3"
        result = safe_tail(content, max_lines=10, max_chars=1000)
        assert "Line 1" in result
        assert "Line 3" in result

    def test_line_limit(self):
        """Should respect line limit."""
        content = "\n".join(f"Line {i}" for i in range(100))
        result = safe_tail(content, max_lines=5, max_chars=10000)
        lines = result.splitlines()
        assert len(lines) <= 5
        assert "Line 99" in result  # Last line should be present

    def test_char_limit(self):
        """Should respect character limit."""
        content = "x" * 10000
        result = safe_tail(content, max_lines=100, max_chars=100)
        assert len(result) <= 100

    def test_redaction_applied(self):
        """Secrets should be redacted in output."""
        content = "Log line\nSECRET_KEY=mysecret\nMore output"
        result = safe_tail(content, max_lines=10, max_chars=1000)
        assert "mysecret" not in result
        assert "SECRET_KEY=<REDACTED>" in result


class TestSafeConfigExcerpt:
    """Tests for safe_config_excerpt function."""

    def test_paths_redacted(self):
        """Paths in config should be redacted."""
        config = {
            "boot-source": {
                "kernel_image_path": "/var/lib/firecracker/vmlinux",
                "boot_args": "console=ttyS0",
            },
            "drives": [
                {
                    "drive_id": "rootfs",
                    "path_on_host": "/var/lib/octolab/smoke_123/rootfs.ext4",
                    "is_root_device": True,
                }
            ],
        }
        result = safe_config_excerpt(config)

        # Full paths should not appear
        assert "/var/lib/firecracker/vmlinux" not in str(result)
        assert "/var/lib/octolab" not in str(result)

        # Basenames should appear
        assert "vmlinux" in str(result)
        assert "rootfs.ext4" in str(result)

        # Non-path values should be preserved
        assert result["boot-source"]["boot_args"] == "console=ttyS0"
        assert result["drives"][0]["is_root_device"] is True

    def test_depth_limit(self):
        """Deep nesting should be truncated."""
        config = {"a": {"b": {"c": {"d": {"e": "deep"}}}}}
        result = safe_config_excerpt(config, max_depth=2)

        # Should have truncation marker at depth limit
        assert result["a"]["b"] == {"...": "(truncated)"}

    def test_list_capped(self):
        """Long lists should be capped."""
        config = {
            "drives": [
                {"drive_id": f"drive_{i}", "path_on_host": f"/path/{i}"}
                for i in range(10)
            ]
        }
        result = safe_config_excerpt(config)
        assert len(result["drives"]) <= 5

    def test_secrets_redacted(self):
        """Token-like values should be redacted."""
        config = {
            "auth": {
                "token": "secret_token_value",
                "password": "my_password",
            }
        }
        result = safe_config_excerpt(config)
        assert result["auth"]["token"] == "<REDACTED>"
        assert result["auth"]["password"] == "<REDACTED>"
