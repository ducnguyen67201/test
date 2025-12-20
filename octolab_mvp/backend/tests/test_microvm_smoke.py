"""Tests for microvm_smoke Firecracker smoke test runner.

SECURITY FOCUS:
- Temp directory containment
- Cleanup on failure
- Output redaction
- No secrets leaked
"""

import json
import os
import subprocess
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

from app.services.microvm_smoke import (
    SmokeResult,
    SmokeTimings,
    SmokeDebug,
    get_fatal_summary,
    run_firecracker_smoke,
    generate_smoke_id,
    validate_smoke_id,
    get_smoke_dir,
    cleanup_old_smoke_dirs,
    list_smoke_dirs,
    SMOKE_STARTUP_WAIT_MS,
    SMOKE_METRICS_TIMEOUT_SECS,
    MAX_FAILED_SMOKE_DIRS,
    SMOKE_ID_PATTERN,
    CLASSIFICATION_CORE_BOOT,
    CLASSIFICATION_HIGHER_LAYER,
)


# Mark all tests as no_db since we don't need database
pytestmark = pytest.mark.no_db


class TestSmokeResult:
    """Tests for SmokeResult dataclass."""

    def test_default_values(self):
        """Default values should be sensible."""
        result = SmokeResult(ok=False)
        assert result.ok is False
        assert result.timings.boot_ms == 0
        assert result.notes == []
        assert result.debug is None
        assert result.firecracker_rc is None
        assert result.generated_at  # Should be set automatically

    def test_to_dict(self):
        """to_dict should return serializable dict."""
        result = SmokeResult(
            ok=True,
            timings=SmokeTimings(boot_ms=100, ready_ms=200, teardown_ms=50, total_ms=350),
            notes=["Note 1", "Note 2"],
        )
        d = result.to_dict()
        assert d["ok"] is True
        assert d["timings"]["boot_ms"] == 100
        assert d["notes"] == ["Note 1", "Note 2"]
        assert "generated_at" in d

    def test_to_dict_with_debug(self):
        """Debug info should be included on failure."""
        result = SmokeResult(
            ok=False,
            debug=SmokeDebug(
                stderr_tail="error output",
                log_tail="log output",
                config_excerpt={"key": "value"},
                temp_dir_redacted="<STATE_DIR>/smoke_123",
            ),
        )
        d = result.to_dict()
        assert d["debug"]["stderr_tail"] == "error output"
        assert d["debug"]["config_excerpt"] == {"key": "value"}


class TestGetFatalSummary:
    """Tests for get_fatal_summary function."""

    def test_success(self):
        """Success result should have simple summary."""
        result = SmokeResult(ok=True)
        summary = get_fatal_summary(result)
        assert summary == "Smoke test passed"

    def test_failure_with_rc(self):
        """Failure with exit code should include it."""
        result = SmokeResult(
            ok=False,
            firecracker_rc=1,
            notes=["Firecracker exited immediately"],
        )
        summary = get_fatal_summary(result)
        assert "rc=1" in summary
        assert "failed" in summary.lower()

    def test_failure_with_notes(self):
        """Failure notes should be included."""
        result = SmokeResult(
            ok=False,
            notes=["Smoke test FAILED", "Metrics not found"],
        )
        summary = get_fatal_summary(result)
        assert "FAILED" in summary


class TestRunFirecrackerSmoke:
    """Tests for run_firecracker_smoke function."""

    def test_missing_kernel(self, tmp_path):
        """Missing kernel should fail gracefully."""
        result = run_firecracker_smoke(
            firecracker_bin="/usr/local/bin/firecracker",
            kernel_path="/nonexistent/vmlinux",
            rootfs_path=str(tmp_path / "rootfs.ext4"),
            state_dir=str(tmp_path),
        )
        assert result.ok is False
        assert any("not found" in note.lower() for note in result.notes)

    def test_missing_rootfs(self, tmp_path):
        """Missing rootfs should fail gracefully."""
        # Create a fake kernel
        kernel = tmp_path / "vmlinux"
        kernel.write_bytes(b"fake kernel")

        result = run_firecracker_smoke(
            firecracker_bin="/usr/local/bin/firecracker",
            kernel_path=str(kernel),
            rootfs_path="/nonexistent/rootfs.ext4",
            state_dir=str(tmp_path),
        )
        assert result.ok is False
        assert any("not found" in note.lower() for note in result.notes)

    def test_containment_enforced(self, tmp_path):
        """Path traversal in state_dir should fail."""
        # This tests that even if we somehow get a bad state_dir,
        # we don't escape containment
        result = run_firecracker_smoke(
            firecracker_bin="/usr/local/bin/firecracker",
            kernel_path=str(tmp_path / "vmlinux"),
            rootfs_path=str(tmp_path / "rootfs.ext4"),
            state_dir="/nonexistent/base/dir",
        )
        # Should fail (can't create temp dir)
        assert result.ok is False

    def test_temp_kept_on_failure(self, tmp_path):
        """Temp directory should be KEPT on failure (new behavior: artifacts preserved)."""
        # Create fake kernel and rootfs
        kernel = tmp_path / "vmlinux"
        kernel.write_bytes(b"fake kernel")
        rootfs = tmp_path / "rootfs.ext4"
        rootfs.write_bytes(b"fake rootfs")

        state_dir = tmp_path / "state"
        state_dir.mkdir()

        # Run smoke test (will fail because firecracker doesn't exist or can't run)
        result = run_firecracker_smoke(
            firecracker_bin="/nonexistent/firecracker",
            kernel_path=str(kernel),
            rootfs_path=str(rootfs),
            state_dir=str(state_dir),
        )

        assert result.ok is False
        # Temp directory should be KEPT for debugging (new behavior)
        smoke_dirs = list(state_dir.glob("smoke_*"))
        assert len(smoke_dirs) == 1, f"Temp dir should be kept on failure: {smoke_dirs}"
        assert result.smoke_id is not None
        assert smoke_dirs[0].name == result.smoke_id

    def test_keep_temp_flag(self, tmp_path):
        """keep_temp=True should preserve temp directory."""
        kernel = tmp_path / "vmlinux"
        kernel.write_bytes(b"fake kernel")
        rootfs = tmp_path / "rootfs.ext4"
        rootfs.write_bytes(b"fake rootfs")

        state_dir = tmp_path / "state"
        state_dir.mkdir()

        result = run_firecracker_smoke(
            firecracker_bin="/nonexistent/firecracker",
            kernel_path=str(kernel),
            rootfs_path=str(rootfs),
            state_dir=str(state_dir),
            keep_temp=True,
        )

        assert result.ok is False
        # Temp directory should be preserved
        smoke_dirs = list(state_dir.glob("smoke_*"))
        assert len(smoke_dirs) == 1, f"Temp dir should be preserved: {smoke_dirs}"

        # Clean up manually
        import shutil
        for d in smoke_dirs:
            shutil.rmtree(d)

    @patch("subprocess.Popen")
    def test_process_exits_immediately(self, mock_popen, tmp_path):
        """Process exiting immediately should fail with diagnostics."""
        kernel = tmp_path / "vmlinux"
        kernel.write_bytes(b"fake kernel")
        rootfs = tmp_path / "rootfs.ext4"
        rootfs.write_bytes(b"fake rootfs")

        state_dir = tmp_path / "state"
        state_dir.mkdir()

        # Mock process that exits immediately
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # Exited with code 1
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        result = run_firecracker_smoke(
            firecracker_bin="/usr/local/bin/firecracker",
            kernel_path=str(kernel),
            rootfs_path=str(rootfs),
            state_dir=str(state_dir),
        )

        assert result.ok is False
        assert result.firecracker_rc == 1
        assert any("exited" in note.lower() for note in result.notes)

    @patch("subprocess.Popen")
    @patch("time.sleep")
    def test_metrics_appear_success(self, mock_sleep, mock_popen, tmp_path):
        """Process stays alive and metrics appear should succeed."""
        kernel = tmp_path / "vmlinux"
        kernel.write_bytes(b"fake kernel")
        rootfs = tmp_path / "rootfs.ext4"
        rootfs.write_bytes(b"fake rootfs")

        state_dir = tmp_path / "state"
        state_dir.mkdir()

        # Mock process that stays alive
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Still running
        mock_proc.returncode = None
        mock_proc.send_signal = MagicMock()
        mock_proc.wait = MagicMock()
        mock_popen.return_value = mock_proc

        # Create metrics file when sleep is called (simulating FC creating it)
        def create_metrics_on_sleep(*args, **kwargs):
            # Find and create metrics file in smoke dir
            smoke_dirs = list(state_dir.glob("smoke_*"))
            if smoke_dirs:
                metrics = smoke_dirs[0] / "firecracker.metrics"
                metrics.write_text('{"api_server": {}}')

        mock_sleep.side_effect = create_metrics_on_sleep

        result = run_firecracker_smoke(
            firecracker_bin="/usr/local/bin/firecracker",
            kernel_path=str(kernel),
            rootfs_path=str(rootfs),
            state_dir=str(state_dir),
        )

        assert result.ok is True
        assert result.debug is None  # No debug on success
        assert any("PASSED" in note for note in result.notes)

    @patch("subprocess.Popen")
    def test_firecracker_binary_not_found(self, mock_popen, tmp_path):
        """FileNotFoundError should be handled gracefully."""
        kernel = tmp_path / "vmlinux"
        kernel.write_bytes(b"fake kernel")
        rootfs = tmp_path / "rootfs.ext4"
        rootfs.write_bytes(b"fake rootfs")

        state_dir = tmp_path / "state"
        state_dir.mkdir()

        mock_popen.side_effect = FileNotFoundError("firecracker not found")

        result = run_firecracker_smoke(
            firecracker_bin="/nonexistent/firecracker",
            kernel_path=str(kernel),
            rootfs_path=str(rootfs),
            state_dir=str(state_dir),
        )

        assert result.ok is False
        assert any("not found" in note.lower() for note in result.notes)

    @patch("subprocess.Popen")
    def test_permission_error(self, mock_popen, tmp_path):
        """PermissionError should be handled gracefully."""
        kernel = tmp_path / "vmlinux"
        kernel.write_bytes(b"fake kernel")
        rootfs = tmp_path / "rootfs.ext4"
        rootfs.write_bytes(b"fake rootfs")

        state_dir = tmp_path / "state"
        state_dir.mkdir()

        mock_popen.side_effect = PermissionError("permission denied")

        result = run_firecracker_smoke(
            firecracker_bin="/usr/local/bin/firecracker",
            kernel_path=str(kernel),
            rootfs_path=str(rootfs),
            state_dir=str(state_dir),
        )

        assert result.ok is False
        assert any("not executable" in note.lower() for note in result.notes)

    def test_redacted_temp_dir_in_debug(self, tmp_path):
        """Debug info should have redacted temp dir path."""
        kernel = tmp_path / "vmlinux"
        kernel.write_bytes(b"fake kernel")
        rootfs = tmp_path / "rootfs.ext4"
        rootfs.write_bytes(b"fake rootfs")

        state_dir = tmp_path / "state"
        state_dir.mkdir()

        result = run_firecracker_smoke(
            firecracker_bin="/nonexistent/firecracker",
            kernel_path=str(kernel),
            rootfs_path=str(rootfs),
            state_dir=str(state_dir),
        )

        assert result.ok is False
        assert result.debug is not None
        # Full path should not appear
        assert str(state_dir) not in result.debug.temp_dir_redacted
        # Should have placeholder
        assert "<STATE_DIR>" in result.debug.temp_dir_redacted

    @patch("subprocess.Popen")
    @patch("time.sleep")
    def test_stderr_captured_and_redacted(self, mock_sleep, mock_popen, tmp_path):
        """Stderr should be captured and secrets redacted."""
        kernel = tmp_path / "vmlinux"
        kernel.write_bytes(b"fake kernel")
        rootfs = tmp_path / "rootfs.ext4"
        rootfs.write_bytes(b"fake rootfs")

        state_dir = tmp_path / "state"
        state_dir.mkdir()

        # Mock process that exits with error
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # Exited
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        # Simulate stderr with a secret
        def write_stderr_on_sleep(*args, **kwargs):
            smoke_dirs = list(state_dir.glob("smoke_*"))
            if smoke_dirs:
                stderr = smoke_dirs[0] / "stderr.log"
                stderr.write_text(
                    "Error: DATABASE_URL=postgres://user:secret@host/db\n"
                    "Failed to start"
                )

        mock_sleep.side_effect = write_stderr_on_sleep

        result = run_firecracker_smoke(
            firecracker_bin="/usr/local/bin/firecracker",
            kernel_path=str(kernel),
            rootfs_path=str(rootfs),
            state_dir=str(state_dir),
        )

        assert result.ok is False
        assert result.debug is not None
        # Secret should be redacted
        assert "secret" not in result.debug.stderr_tail.lower()
        assert "DATABASE_URL=<REDACTED>" in result.debug.stderr_tail


class TestSmokeTimings:
    """Tests for SmokeTimings dataclass."""

    def test_default_values(self):
        """Default timing values should be zero."""
        timings = SmokeTimings()
        assert timings.boot_ms == 0
        assert timings.ready_ms == 0
        assert timings.teardown_ms == 0
        assert timings.total_ms == 0


class TestSmokeDebug:
    """Tests for SmokeDebug dataclass."""

    def test_default_values(self):
        """Default debug values should be empty/false."""
        debug = SmokeDebug()
        assert debug.stderr_tail == ""
        assert debug.log_tail == ""
        assert debug.config_excerpt == {}
        assert debug.temp_dir_redacted == ""
        assert debug.firecracker_rc is None
        assert debug.metrics_appeared is False
        assert debug.process_alive_at_check is False


# =============================================================================
# New Tests: Smoke ID Generation and Validation (Slice: smoke truth + self-heal)
# =============================================================================


class TestGenerateSmokeId:
    """Tests for generate_smoke_id function."""

    def test_format(self):
        """Generated ID should match expected format."""
        smoke_id = generate_smoke_id()
        assert SMOKE_ID_PATTERN.match(smoke_id)

    def test_starts_with_smoke(self):
        """ID should start with 'smoke_'."""
        smoke_id = generate_smoke_id()
        assert smoke_id.startswith("smoke_")

    def test_contains_unix_ms(self):
        """ID should contain unix milliseconds."""
        before_ms = int(time.time() * 1000)
        smoke_id = generate_smoke_id()
        after_ms = int(time.time() * 1000)

        parts = smoke_id.split("_")
        assert len(parts) == 3
        unix_ms = int(parts[1])
        assert before_ms <= unix_ms <= after_ms

    def test_contains_8_hex_chars(self):
        """ID should end with 8 hex characters."""
        smoke_id = generate_smoke_id()
        parts = smoke_id.split("_")
        assert len(parts) == 3
        hex_part = parts[2]
        assert len(hex_part) == 8
        assert all(c in "0123456789abcdef" for c in hex_part)

    def test_uniqueness(self):
        """Multiple IDs should be unique."""
        ids = [generate_smoke_id() for _ in range(100)]
        assert len(set(ids)) == 100


class TestValidateSmokeId:
    """Tests for validate_smoke_id function."""

    def test_valid_id(self):
        """Valid IDs should pass validation."""
        assert validate_smoke_id("smoke_1733840000000_a1b2c3d4")
        assert validate_smoke_id("smoke_9999999999999_00000000")
        assert validate_smoke_id("smoke_1000000000000_ffffffff")

    def test_generated_id_valid(self):
        """Generated IDs should always be valid."""
        for _ in range(10):
            smoke_id = generate_smoke_id()
            assert validate_smoke_id(smoke_id), f"Generated ID {smoke_id} failed validation"

    def test_invalid_prefix(self):
        """IDs with wrong prefix should fail."""
        assert not validate_smoke_id("test_1733840000000_a1b2c3d4")
        assert not validate_smoke_id("SMOKE_1733840000000_a1b2c3d4")
        assert not validate_smoke_id("1733840000000_a1b2c3d4")

    def test_invalid_timestamp_length(self):
        """IDs with wrong timestamp length should fail."""
        assert not validate_smoke_id("smoke_173384000000_a1b2c3d4")  # 12 digits
        assert not validate_smoke_id("smoke_17338400000000_a1b2c3d4")  # 14 digits

    def test_invalid_hex_length(self):
        """IDs with wrong hex length should fail."""
        assert not validate_smoke_id("smoke_1733840000000_a1b2c3d")  # 7 chars
        assert not validate_smoke_id("smoke_1733840000000_a1b2c3d4e")  # 9 chars

    def test_invalid_hex_chars(self):
        """IDs with non-hex characters should fail."""
        assert not validate_smoke_id("smoke_1733840000000_a1b2c3dg")  # 'g' invalid
        assert not validate_smoke_id("smoke_1733840000000_A1B2C3D4")  # uppercase

    def test_path_traversal_rejected(self):
        """Path traversal attempts should fail."""
        assert not validate_smoke_id("../../../etc/passwd")
        assert not validate_smoke_id("smoke_1733840000000_../../../")
        assert not validate_smoke_id("smoke_1733840000000_a1b2/../")

    def test_empty_and_none(self):
        """Empty and None values should fail."""
        assert not validate_smoke_id("")
        assert not validate_smoke_id(None)

    def test_non_string(self):
        """Non-string values should fail."""
        assert not validate_smoke_id(12345)
        assert not validate_smoke_id(["smoke_1733840000000_a1b2c3d4"])


class TestGetSmokeDir:
    """Tests for get_smoke_dir function."""

    def test_valid_id(self, tmp_path):
        """Valid smoke_id should return resolved path."""
        smoke_id = "smoke_1733840000000_a1b2c3d4"
        result = get_smoke_dir(tmp_path, smoke_id)
        assert result is not None
        assert result == tmp_path / smoke_id

    def test_invalid_id_returns_none(self, tmp_path):
        """Invalid smoke_id should return None."""
        assert get_smoke_dir(tmp_path, "../etc/passwd") is None
        assert get_smoke_dir(tmp_path, "invalid") is None
        assert get_smoke_dir(tmp_path, "") is None

    def test_containment_enforced(self, tmp_path):
        """Path traversal should be blocked."""
        # Even with valid format prefix, traversal should fail
        assert get_smoke_dir(tmp_path, "smoke_1733840000000_../../../../../etc") is None


class TestCleanupOldSmokeDirs:
    """Tests for cleanup_old_smoke_dirs function."""

    def test_removes_oldest_beyond_limit(self, tmp_path):
        """Should remove oldest directories beyond retention limit."""
        # Create 12 smoke directories with valid format (13-digit timestamp, 8 hex chars)
        dirs = []
        for i in range(12):
            smoke_id = f"smoke_1733840{i:06d}_a1b2c3d{i % 10}"
            d = tmp_path / smoke_id
            d.mkdir()
            dirs.append(d)
            # Set different mtimes
            os.utime(d, (1000000 + i, 1000000 + i))

        # Cleanup with limit of 10
        removed = cleanup_old_smoke_dirs(tmp_path, keep_count=10)

        # Should have removed 2 oldest
        assert removed == 2
        remaining = list(tmp_path.glob("smoke_*"))
        assert len(remaining) == 10

    def test_keeps_all_if_under_limit(self, tmp_path):
        """Should not remove anything if under limit."""
        # Create 5 directories with valid format
        for i in range(5):
            smoke_id = f"smoke_1733840{i:06d}_a1b2c3d{i}"
            d = tmp_path / smoke_id
            d.mkdir()

        removed = cleanup_old_smoke_dirs(tmp_path, keep_count=10)
        assert removed == 0
        assert len(list(tmp_path.glob("smoke_*"))) == 5

    def test_ignores_invalid_dirs(self, tmp_path):
        """Should ignore directories that don't match pattern."""
        # Create valid smoke dirs
        for i in range(5):
            smoke_id = f"smoke_1733840{i:06d}_a1b2c3d{i}"
            d = tmp_path / smoke_id
            d.mkdir()

        # Create invalid dirs
        (tmp_path / "other_dir").mkdir()
        (tmp_path / "smoke_invalid").mkdir()
        (tmp_path / "lab-12345").mkdir()

        removed = cleanup_old_smoke_dirs(tmp_path, keep_count=3)

        # Should only process valid smoke dirs
        assert removed == 2
        invalid_dirs = ["other_dir", "smoke_invalid", "lab-12345"]
        for name in invalid_dirs:
            assert (tmp_path / name).exists()

    def test_ignores_symlinks(self, tmp_path):
        """Should skip symlinks (security)."""
        # Create some real dirs
        for i in range(5):
            smoke_id = f"smoke_1733840{i:06d}_a1b2c3d{i}"
            d = tmp_path / smoke_id
            d.mkdir()

        # Create a symlink (should be ignored)
        symlink_target = tmp_path / "smoke_9999999999999_ffffffff"
        symlink_target.mkdir()
        symlink = tmp_path / "smoke_1000000000000_00000000"
        symlink.symlink_to(symlink_target)

        removed = cleanup_old_smoke_dirs(tmp_path, keep_count=3)

        # Symlink should be skipped
        assert symlink.is_symlink()

    def test_nonexistent_state_dir(self, tmp_path):
        """Should handle nonexistent state directory."""
        nonexistent = tmp_path / "nonexistent"
        removed = cleanup_old_smoke_dirs(nonexistent)
        assert removed == 0


class TestListSmokeDirs:
    """Tests for list_smoke_dirs function."""

    def test_lists_valid_dirs(self, tmp_path):
        """Should list valid smoke directories."""
        # Create some smoke dirs with valid format
        for i in range(3):
            smoke_id = f"smoke_1733840{i:06d}_a1b2c3d{i}"
            d = tmp_path / smoke_id
            d.mkdir()

        results = list_smoke_dirs(tmp_path)
        assert len(results) == 3
        for r in results:
            assert "smoke_id" in r
            assert "mtime" in r
            assert validate_smoke_id(r["smoke_id"])

    def test_sorted_by_mtime_newest_first(self, tmp_path):
        """Results should be sorted newest first."""
        for i in range(3):
            smoke_id = f"smoke_1733840{i:06d}_a1b2c3d{i}"
            d = tmp_path / smoke_id
            d.mkdir()
            # Set different mtimes
            os.utime(d, (1000000 + i, 1000000 + i))

        results = list_smoke_dirs(tmp_path)
        mtimes = [r["mtime"] for r in results]
        assert mtimes == sorted(mtimes, reverse=True)

    def test_ignores_invalid_dirs(self, tmp_path):
        """Should ignore directories that don't match pattern."""
        (tmp_path / "smoke_1733840000000_a1b2c3d4").mkdir()
        (tmp_path / "other_dir").mkdir()
        (tmp_path / "smoke_invalid").mkdir()

        results = list_smoke_dirs(tmp_path)
        assert len(results) == 1
        assert results[0]["smoke_id"] == "smoke_1733840000000_a1b2c3d4"


class TestArtifactRetentionOnFailure:
    """Tests for artifact retention behavior on smoke test failure."""

    def test_artifacts_kept_on_failure(self, tmp_path):
        """On failure, artifacts should be kept and smoke_id returned."""
        kernel = tmp_path / "vmlinux"
        kernel.write_bytes(b"fake kernel")
        rootfs = tmp_path / "rootfs.ext4"
        rootfs.write_bytes(b"fake rootfs")

        state_dir = tmp_path / "state"
        state_dir.mkdir()

        # Run smoke test that will fail
        result = run_firecracker_smoke(
            firecracker_bin="/nonexistent/firecracker",
            kernel_path=str(kernel),
            rootfs_path=str(rootfs),
            state_dir=str(state_dir),
        )

        assert result.ok is False
        assert result.smoke_id is not None
        assert validate_smoke_id(result.smoke_id)
        assert result.artifacts_kept is True

        # Verify directory exists
        smoke_dirs = list(state_dir.glob("smoke_*"))
        assert len(smoke_dirs) == 1
        assert smoke_dirs[0].name == result.smoke_id

    def test_artifacts_cleaned_on_success(self, tmp_path):
        """On success, artifacts should be cleaned up."""
        kernel = tmp_path / "vmlinux"
        kernel.write_bytes(b"fake kernel")
        rootfs = tmp_path / "rootfs.ext4"
        rootfs.write_bytes(b"fake rootfs")

        state_dir = tmp_path / "state"
        state_dir.mkdir()

        with patch("subprocess.Popen") as mock_popen, \
             patch("time.sleep") as mock_sleep:
            # Mock successful run
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_proc.send_signal = MagicMock()
            mock_proc.wait = MagicMock()
            mock_popen.return_value = mock_proc

            def create_metrics(*args, **kwargs):
                for d in state_dir.glob("smoke_*"):
                    (d / "firecracker.metrics").write_text('{}')

            mock_sleep.side_effect = create_metrics

            result = run_firecracker_smoke(
                firecracker_bin="/usr/local/bin/firecracker",
                kernel_path=str(kernel),
                rootfs_path=str(rootfs),
                state_dir=str(state_dir),
            )

        assert result.ok is True
        assert result.smoke_id is None  # Not set on success
        assert result.artifacts_kept is False

        # Verify directory was cleaned up
        smoke_dirs = list(state_dir.glob("smoke_*"))
        assert len(smoke_dirs) == 0


class TestMinimalBootClassification:
    """Tests for failure classification via minimal boot."""

    @patch("app.services.microvm_smoke._run_minimal_boot")
    @patch("subprocess.Popen")
    def test_classification_core_boot_failure(self, mock_popen, mock_minimal, tmp_path):
        """When minimal boot fails, classification should be core_boot_failure."""
        kernel = tmp_path / "vmlinux"
        kernel.write_bytes(b"fake kernel")
        rootfs = tmp_path / "rootfs.ext4"
        rootfs.write_bytes(b"fake rootfs")

        state_dir = tmp_path / "state"
        state_dir.mkdir()

        # Full smoke fails (process exits immediately)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        # Minimal boot also fails
        mock_minimal.return_value = (False, 1, "Minimal boot failed")

        result = run_firecracker_smoke(
            firecracker_bin="/usr/local/bin/firecracker",
            kernel_path=str(kernel),
            rootfs_path=str(rootfs),
            state_dir=str(state_dir),
        )

        assert result.ok is False
        assert result.classification == CLASSIFICATION_CORE_BOOT
        assert "core" in result.classification.lower()

    @patch("app.services.microvm_smoke._run_minimal_boot")
    @patch("subprocess.Popen")
    def test_classification_higher_layer_failure(self, mock_popen, mock_minimal, tmp_path):
        """When minimal boot succeeds but full fails, classification should be higher_layer."""
        kernel = tmp_path / "vmlinux"
        kernel.write_bytes(b"fake kernel")
        rootfs = tmp_path / "rootfs.ext4"
        rootfs.write_bytes(b"fake rootfs")

        state_dir = tmp_path / "state"
        state_dir.mkdir()

        # Full smoke fails (process exits immediately)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        # Minimal boot succeeds
        mock_minimal.return_value = (True, None, "Minimal boot stayed alive")

        result = run_firecracker_smoke(
            firecracker_bin="/usr/local/bin/firecracker",
            kernel_path=str(kernel),
            rootfs_path=str(rootfs),
            state_dir=str(state_dir),
        )

        assert result.ok is False
        assert result.classification == CLASSIFICATION_HIGHER_LAYER
        assert "higher" in result.classification.lower() or "layer" in result.classification.lower()


class TestSmokeResultNewFields:
    """Tests for new SmokeResult fields."""

    def test_smoke_id_field(self):
        """smoke_id field should be present."""
        result = SmokeResult(ok=False, smoke_id="smoke_1733840000000_a1b2c3d4")
        d = result.to_dict()
        assert d["smoke_id"] == "smoke_1733840000000_a1b2c3d4"

    def test_classification_field(self):
        """classification field should be present."""
        result = SmokeResult(ok=False, classification=CLASSIFICATION_CORE_BOOT)
        d = result.to_dict()
        assert d["classification"] == CLASSIFICATION_CORE_BOOT

    def test_artifacts_kept_field(self):
        """artifacts_kept field should be present."""
        result = SmokeResult(ok=False, artifacts_kept=True)
        d = result.to_dict()
        assert d["artifacts_kept"] is True

    def test_success_no_extra_fields(self):
        """On success, smoke_id and artifacts should be clear."""
        result = SmokeResult(ok=True)
        d = result.to_dict()
        assert d["smoke_id"] is None
        assert d["classification"] is None
        assert d["artifacts_kept"] is False
