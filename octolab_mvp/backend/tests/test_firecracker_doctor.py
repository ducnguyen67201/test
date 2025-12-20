"""Tests for Firecracker doctor checks.

SECURITY:
- Verify redaction: no absolute paths in output
- Verify proper severity classification
- Verify WSL detection behavior
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.services.firecracker_doctor import (
    run_doctor,
    assert_firecracker_ready,
    DoctorCheck,
    DoctorReport,
    Severity,
    _redact_path,
    _truncate,
    _is_wsl,
)

# Mark all tests in this module as not requiring database access
pytestmark = pytest.mark.no_db


class TestRedaction:
    """Test path redaction and output sanitization."""

    def test_redact_path_shows_basename_only(self):
        """Verify absolute paths are redacted to show only basename."""
        assert _redact_path("/var/lib/octolab/vmlinux") == ".../vmlinux"
        assert _redact_path(Path("/home/user/rootfs.ext4")) == ".../rootfs.ext4"

    def test_redact_path_handles_none(self):
        """Verify None path is handled gracefully."""
        assert _redact_path(None) == "(not set)"
        # Empty string is treated as not set
        assert _redact_path("") == "(not set)"

    def test_truncate_removes_newlines(self):
        """Verify newlines are stripped from output."""
        result = _truncate("line1\nline2\rline3")
        assert "\n" not in result
        assert "\r" not in result

    def test_truncate_limits_length(self):
        """Verify output is truncated at max length."""
        long_text = "x" * 500
        result = _truncate(long_text, max_len=100)
        assert len(result) <= 100
        assert result.endswith("...")


class TestDoctorReport:
    """Test DoctorReport structure and serialization."""

    def test_report_ok_when_no_fatal_failures(self):
        """Verify ok=True when all checks pass or only warnings."""
        checks = [
            DoctorCheck("kvm", ok=True, severity=Severity.INFO, details="ok"),
            DoctorCheck("jailer", ok=False, severity=Severity.WARN, details="missing"),
        ]
        report = DoctorReport(ok=True, checks=checks, summary="Test")
        assert report.ok is True
        assert len(report.fatal_checks) == 0
        assert len(report.warn_checks) == 1

    def test_report_not_ok_when_fatal_failure(self):
        """Verify ok=False when any fatal check fails."""
        checks = [
            DoctorCheck("kvm", ok=False, severity=Severity.FATAL, details="missing"),
        ]
        report = DoctorReport(ok=False, checks=checks, summary="Test")
        assert report.ok is False
        assert len(report.fatal_checks) == 1

    def test_to_dict_no_absolute_paths(self):
        """Verify to_dict output contains no absolute path patterns."""
        checks = [
            DoctorCheck(
                "kernel",
                ok=True,
                severity=Severity.INFO,
                details="kernel readable: .../vmlinux",
            ),
        ]
        report = DoctorReport(ok=True, checks=checks, summary="Test")
        d = report.to_dict()

        # Check that no absolute paths appear
        import json
        json_str = json.dumps(d)
        assert "/var/" not in json_str
        assert "/home/" not in json_str
        assert "/usr/" not in json_str


class TestKVMCheck:
    """Test /dev/kvm check behavior."""

    @patch("app.services.firecracker_doctor.Path.exists")
    def test_kvm_missing_is_fatal(self, mock_exists):
        """Verify missing /dev/kvm is a fatal error."""
        mock_exists.return_value = False

        from app.services.firecracker_doctor import _check_kvm
        check = _check_kvm()

        assert check.ok is False
        assert check.severity == Severity.FATAL
        assert "not found" in check.details.lower()

    @patch("builtins.open", side_effect=PermissionError("denied"))
    @patch("app.services.firecracker_doctor.Path.exists", return_value=True)
    def test_kvm_not_writable_is_fatal(self, mock_exists, mock_open):
        """Verify non-writable /dev/kvm is a fatal error."""
        from app.services.firecracker_doctor import _check_kvm
        check = _check_kvm()

        assert check.ok is False
        assert check.severity == Severity.FATAL
        assert "writable" in check.details.lower() or "not writable" in check.details.lower()


class TestJailerCheck:
    """Test jailer binary check with WSL awareness."""

    @patch("app.services.firecracker_doctor._run_cmd_safe")
    @patch("app.services.firecracker_doctor._is_wsl", return_value=False)
    @patch("app.services.firecracker_doctor.settings")
    def test_jailer_missing_non_wsl_is_fatal(self, mock_settings, mock_is_wsl, mock_run):
        """Verify missing jailer on non-WSL is fatal."""
        mock_settings.jailer_bin = "jailer"
        mock_settings.dev_unsafe_allow_no_jailer = False
        mock_run.return_value = (1, "", "not found")

        from app.services.firecracker_doctor import _check_jailer_binary
        check = _check_jailer_binary()

        assert check.ok is False
        assert check.severity == Severity.FATAL

    @patch("app.services.firecracker_doctor._run_cmd_safe")
    @patch("app.services.firecracker_doctor._is_wsl", return_value=True)
    @patch("app.services.firecracker_doctor.settings")
    def test_jailer_missing_wsl_is_warn(self, mock_settings, mock_is_wsl, mock_run):
        """Verify missing jailer on WSL is only a warning."""
        mock_settings.jailer_bin = "jailer"
        mock_settings.dev_unsafe_allow_no_jailer = False
        mock_run.return_value = (1, "", "not found")

        from app.services.firecracker_doctor import _check_jailer_binary
        check = _check_jailer_binary()

        assert check.ok is False
        assert check.severity == Severity.WARN
        assert "WSL" in check.details


class TestWSLDetection:
    """Test WSL environment detection."""

    @patch("app.services.firecracker_doctor.Path")
    @patch.dict(os.environ, {"WSL_INTEROP": "/run/WSL/123"})
    def test_wsl_detected_via_env(self, mock_path):
        """Verify WSL detection via WSL_INTEROP env var."""
        mock_path.return_value.exists.return_value = False
        assert _is_wsl() is True

    @patch("app.services.firecracker_doctor.Path")
    @patch.dict(os.environ, {}, clear=True)
    def test_wsl_detected_via_interop_file(self, mock_path):
        """Verify WSL detection via /proc/sys/fs/binfmt_misc/WSLInterop."""
        def exists_side_effect():
            if str(mock_path.call_args) == "call('/proc/sys/fs/binfmt_misc/WSLInterop')":
                return True
            return False

        instance = MagicMock()
        instance.exists.return_value = True
        mock_path.return_value = instance

        # When the WSLInterop file exists
        assert _is_wsl() is True


class TestIntegration:
    """Integration tests for the full doctor check."""

    @patch("app.services.firecracker_doctor._check_kvm")
    @patch("app.services.firecracker_doctor._check_firecracker_binary")
    @patch("app.services.firecracker_doctor._check_jailer_binary")
    @patch("app.services.firecracker_doctor._check_kernel_path")
    @patch("app.services.firecracker_doctor._check_rootfs_path")
    @patch("app.services.firecracker_doctor._check_state_dir")
    @patch("app.services.firecracker_doctor._check_vsock")
    @patch("app.services.firecracker_doctor._check_netd")
    def test_run_doctor_aggregates_checks(
        self,
        mock_netd,
        mock_vsock,
        mock_state,
        mock_rootfs,
        mock_kernel,
        mock_jailer,
        mock_fc,
        mock_kvm,
    ):
        """Verify run_doctor aggregates all checks correctly."""
        # All checks pass
        for mock in [mock_kvm, mock_fc, mock_jailer, mock_kernel, mock_rootfs, mock_state, mock_vsock, mock_netd]:
            mock.return_value = DoctorCheck("test", ok=True, severity=Severity.INFO, details="ok")

        report = run_doctor()
        assert report.ok is True
        assert len(report.checks) == 8

    @patch("app.services.firecracker_doctor._check_kvm")
    @patch("app.services.firecracker_doctor._check_firecracker_binary")
    @patch("app.services.firecracker_doctor._check_jailer_binary")
    @patch("app.services.firecracker_doctor._check_kernel_path")
    @patch("app.services.firecracker_doctor._check_rootfs_path")
    @patch("app.services.firecracker_doctor._check_state_dir")
    @patch("app.services.firecracker_doctor._check_vsock")
    @patch("app.services.firecracker_doctor._check_netd")
    def test_run_doctor_fails_on_fatal(
        self,
        mock_netd,
        mock_vsock,
        mock_state,
        mock_rootfs,
        mock_kernel,
        mock_jailer,
        mock_fc,
        mock_kvm,
    ):
        """Verify run_doctor returns ok=False when any fatal check fails."""
        mock_kvm.return_value = DoctorCheck("kvm", ok=False, severity=Severity.FATAL, details="missing")
        for mock in [mock_fc, mock_jailer, mock_kernel, mock_rootfs, mock_state, mock_vsock, mock_netd]:
            mock.return_value = DoctorCheck("test", ok=True, severity=Severity.INFO, details="ok")

        report = run_doctor()
        assert report.ok is False
        assert "kvm" in report.summary.lower()

    @patch("app.services.firecracker_doctor.run_doctor")
    def test_assert_firecracker_ready_raises_on_fatal(self, mock_run):
        """Verify assert_firecracker_ready raises ValueError on fatal failure."""
        mock_run.return_value = DoctorReport(
            ok=False,
            checks=[
                DoctorCheck("kvm", ok=False, severity=Severity.FATAL, details="missing", hint="enable kvm"),
            ],
            summary="Firecracker unavailable",
        )

        with pytest.raises(ValueError) as exc_info:
            assert_firecracker_ready()

        assert "kvm" in str(exc_info.value).lower()


class TestNoAbsolutePathsInOutput:
    """Verify no absolute paths leak through doctor checks."""

    @patch("app.services.firecracker_doctor._check_kvm")
    @patch("app.services.firecracker_doctor._check_firecracker_binary")
    @patch("app.services.firecracker_doctor._check_jailer_binary")
    @patch("app.services.firecracker_doctor._check_kernel_path")
    @patch("app.services.firecracker_doctor._check_rootfs_path")
    @patch("app.services.firecracker_doctor._check_state_dir")
    @patch("app.services.firecracker_doctor._check_vsock")
    def test_no_absolute_paths_in_report(
        self,
        mock_vsock,
        mock_state,
        mock_rootfs,
        mock_kernel,
        mock_jailer,
        mock_fc,
        mock_kvm,
    ):
        """Verify doctor report doesn't contain absolute paths."""
        # Use details that might tempt leaking paths
        mock_kvm.return_value = DoctorCheck(
            "kvm", ok=True, severity=Severity.INFO, details="/dev/kvm accessible"
        )
        mock_fc.return_value = DoctorCheck(
            "firecracker", ok=True, severity=Severity.INFO,
            details="firecracker: Firecracker v1.0.0"
        )
        mock_jailer.return_value = DoctorCheck(
            "jailer", ok=True, severity=Severity.INFO, details="jailer found"
        )
        mock_kernel.return_value = DoctorCheck(
            "kernel", ok=True, severity=Severity.INFO,
            details="kernel readable: .../vmlinux"  # Already redacted
        )
        mock_rootfs.return_value = DoctorCheck(
            "rootfs", ok=True, severity=Severity.INFO,
            details="rootfs readable: .../rootfs.ext4"  # Already redacted
        )
        mock_state.return_value = DoctorCheck(
            "state_dir", ok=True, severity=Severity.INFO,
            details="state_dir writable: .../microvm"  # Already redacted
        )
        mock_vsock.return_value = DoctorCheck(
            "vsock", ok=True, severity=Severity.INFO, details="/dev/vsock available"
        )

        report = run_doctor()
        d = report.to_dict()

        import json
        json_str = json.dumps(d)

        # Check for common absolute path patterns
        # /dev/kvm is allowed as it's a well-known device path
        # But we should NOT see:
        assert "/var/lib" not in json_str
        assert "/home/" not in json_str
        assert "/usr/local" not in json_str
        assert "/opt/" not in json_str
