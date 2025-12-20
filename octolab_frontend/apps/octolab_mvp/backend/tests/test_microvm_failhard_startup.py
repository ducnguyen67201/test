"""Tests for fail-hard microVM startup behavior.

SECURITY:
- Verify no fallback from firecracker to compose
- Verify FATAL doctor checks prevent startup
- Verify WARN-only checks allow startup
- Verify compose runtime is unaffected
"""

import pytest
from unittest.mock import patch, MagicMock

from app.services.firecracker_doctor import (
    DoctorCheck,
    DoctorReport,
    Severity,
)

# Mark all tests in this module as not requiring database access
pytestmark = pytest.mark.no_db


class TestRuntimeStartupValidation:
    """Test runtime validation at startup."""

    def test_compose_runtime_skips_doctor(self):
        """Verify compose runtime does not run doctor checks."""
        import app.main

        original_settings = app.main.settings
        try:
            mock_settings = MagicMock()
            mock_settings.octolab_runtime = "compose"
            app.main.settings = mock_settings

            # Should not raise - compose doesn't need doctor
            app.main._validate_runtime_selection()
        finally:
            app.main.settings = original_settings

    def test_noop_runtime_skips_doctor(self):
        """Verify noop runtime does not run doctor checks."""
        import app.main

        original_settings = app.main.settings
        try:
            mock_settings = MagicMock()
            mock_settings.octolab_runtime = "noop"
            app.main.settings = mock_settings

            # Should not raise - noop doesn't need doctor
            app.main._validate_runtime_selection()
        finally:
            app.main.settings = original_settings

    def test_firecracker_runtime_runs_doctor(self):
        """Verify firecracker runtime triggers doctor checks."""
        import app.main

        original_settings = app.main.settings
        try:
            mock_settings = MagicMock()
            mock_settings.octolab_runtime = "firecracker"
            app.main.settings = mock_settings

            with patch.object(app.main, "_validate_firecracker_prerequisites") as mock_prereqs:
                app.main._validate_runtime_selection()
                mock_prereqs.assert_called_once()
        finally:
            app.main.settings = original_settings

    def test_none_runtime_raises(self):
        """Verify None runtime raises RuntimeError."""
        import app.main

        original_settings = app.main.settings
        try:
            mock_settings = MagicMock()
            mock_settings.octolab_runtime = None
            app.main.settings = mock_settings

            with pytest.raises(RuntimeError) as exc_info:
                app.main._validate_runtime_selection()

            assert "OCTOLAB_RUNTIME must be explicitly set" in str(exc_info.value)
        finally:
            app.main.settings = original_settings


class TestFirecrackerFailHard:
    """Test fail-hard behavior when firecracker doctor has fatal issues."""

    @patch("app.services.firecracker_doctor.run_doctor")
    def test_fatal_doctor_check_raises_runtime_error(self, mock_run_doctor):
        """Verify fatal doctor check prevents startup with RuntimeError."""
        mock_run_doctor.return_value = DoctorReport(
            ok=False,
            checks=[
                DoctorCheck(
                    name="kvm",
                    ok=False,
                    severity=Severity.FATAL,
                    details="/dev/kvm not found",
                    hint="Enable nested virtualization",
                ),
            ],
            summary="Firecracker unavailable: kvm check(s) failed",
        )

        import app.main

        with pytest.raises(RuntimeError) as exc_info:
            app.main._validate_firecracker_prerequisites()

        error_msg = str(exc_info.value)
        assert "Cannot start with OCTOLAB_RUNTIME=firecracker" in error_msg
        assert "NO FALLBACK" in error_msg

    @patch("app.services.microvm_doctor.run_checks")
    def test_warn_only_doctor_allows_startup(self, mock_run_checks):
        """Verify WARN-only checks allow startup."""
        # microvm_doctor.run_checks returns a dict, not DoctorReport
        mock_run_checks.return_value = {
            "is_ok": True,  # No fatal failures
            "checks": [
                {
                    "name": "kvm",
                    "status": "OK",
                    "severity": "info",
                    "message": "/dev/kvm accessible",
                    "hint": None,
                },
                {
                    "name": "jailer",
                    "status": "WARN",
                    "severity": "warn",
                    "message": "jailer not found (WSL detected)",
                    "hint": "Jailer not required in WSL dev environment",
                },
            ],
            "summary": {"ok": 1, "warn": 1, "fail": 0, "fatal": 0},
            "generated_at": "2024-01-01T00:00:00Z",
        }

        import app.main

        # Should not raise
        app.main._validate_firecracker_prerequisites()

    @patch("app.services.microvm_doctor.run_checks")
    def test_multiple_fatal_checks_listed(self, mock_run_checks):
        """Verify multiple fatal checks are listed in error."""
        mock_run_checks.return_value = {
            "is_ok": False,
            "checks": [
                {
                    "name": "kvm",
                    "status": "FAIL",
                    "severity": "fatal",
                    "message": "/dev/kvm not found",
                    "hint": "Enable KVM",
                },
                {
                    "name": "kernel",
                    "status": "FAIL",
                    "severity": "fatal",
                    "message": "kernel not set",
                    "hint": "Set MICROVM_KERNEL_PATH",
                },
            ],
            "summary": {"ok": 0, "warn": 0, "fail": 2, "fatal": 2},
            "generated_at": "2024-01-01T00:00:00Z",
        }

        import app.main

        with pytest.raises(RuntimeError) as exc_info:
            app.main._validate_firecracker_prerequisites()

        error_msg = str(exc_info.value)
        # Both issues should be mentioned
        assert "kvm" in error_msg.lower()
        assert "kernel" in error_msg.lower()


class TestNoFallbackBehavior:
    """Test that there is never a silent fallback to compose."""

    @patch("app.services.firecracker_doctor.run_doctor")
    def test_no_compose_fallback_on_fatal(self, mock_run_doctor):
        """Verify firecracker NEVER falls back to compose."""
        mock_run_doctor.return_value = DoctorReport(
            ok=False,
            checks=[
                DoctorCheck(
                    name="firecracker",
                    ok=False,
                    severity=Severity.FATAL,
                    details="firecracker binary not found",
                    hint="Install Firecracker",
                ),
            ],
            summary="Firecracker unavailable",
        )

        import app.main

        original_settings = app.main.settings
        try:
            mock_settings = MagicMock()
            mock_settings.octolab_runtime = "firecracker"
            app.main.settings = mock_settings

            # This should raise, not silently fall back
            with pytest.raises(RuntimeError) as exc_info:
                app.main._validate_firecracker_prerequisites()

            # Error message should explicitly state no fallback
            assert "NO FALLBACK" in str(exc_info.value)

        finally:
            app.main.settings = original_settings


class TestRedactionInErrors:
    """Test that error messages are properly redacted."""

    @patch("app.services.firecracker_doctor.run_doctor")
    def test_no_absolute_paths_in_error(self, mock_run_doctor):
        """Verify absolute paths are not exposed in error messages."""
        # Use a hint with a redacted path
        mock_run_doctor.return_value = DoctorReport(
            ok=False,
            checks=[
                DoctorCheck(
                    name="kernel",
                    ok=False,
                    severity=Severity.FATAL,
                    details="kernel not found: .../vmlinux",  # Redacted
                    hint="Download kernel to .../vmlinux",  # Redacted
                ),
            ],
            summary="Firecracker unavailable",
        )

        import app.main

        with pytest.raises(RuntimeError) as exc_info:
            app.main._validate_firecracker_prerequisites()

        error_msg = str(exc_info.value)
        # Should not contain absolute path patterns
        assert "/home/" not in error_msg
        assert "/var/lib/" not in error_msg
        assert "/usr/" not in error_msg


class TestDoctorCheckIntegration:
    """Integration tests for doctor check behavior."""

    @patch("app.services.firecracker_doctor._check_kvm")
    @patch("app.services.firecracker_doctor._check_firecracker_binary")
    @patch("app.services.firecracker_doctor._check_jailer_binary")
    @patch("app.services.firecracker_doctor._check_kernel_path")
    @patch("app.services.firecracker_doctor._check_rootfs_path")
    @patch("app.services.firecracker_doctor._check_state_dir")
    @patch("app.services.firecracker_doctor._check_vsock")
    @patch("app.services.firecracker_doctor._check_netd")
    def test_all_checks_pass_returns_ok(
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
        """Verify all passing checks results in ok=True."""
        for mock in [mock_kvm, mock_fc, mock_jailer, mock_kernel, mock_rootfs, mock_state, mock_vsock, mock_netd]:
            mock.return_value = DoctorCheck("test", ok=True, severity=Severity.INFO, details="ok")

        from app.services.firecracker_doctor import run_doctor
        report = run_doctor()

        assert report.ok is True
        assert len(report.fatal_checks) == 0

    @patch("app.services.firecracker_doctor._check_kvm")
    @patch("app.services.firecracker_doctor._check_firecracker_binary")
    @patch("app.services.firecracker_doctor._check_jailer_binary")
    @patch("app.services.firecracker_doctor._check_kernel_path")
    @patch("app.services.firecracker_doctor._check_rootfs_path")
    @patch("app.services.firecracker_doctor._check_state_dir")
    @patch("app.services.firecracker_doctor._check_vsock")
    @patch("app.services.firecracker_doctor._check_netd")
    def test_single_fatal_returns_not_ok(
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
        """Verify single fatal check results in ok=False."""
        mock_kvm.return_value = DoctorCheck("kvm", ok=False, severity=Severity.FATAL, details="missing")
        for mock in [mock_fc, mock_jailer, mock_kernel, mock_rootfs, mock_state, mock_vsock, mock_netd]:
            mock.return_value = DoctorCheck("test", ok=True, severity=Severity.INFO, details="ok")

        from app.services.firecracker_doctor import run_doctor
        report = run_doctor()

        assert report.ok is False
        assert len(report.fatal_checks) == 1
        assert report.fatal_checks[0].name == "kvm"


class TestWSLAwareness:
    """Test WSL-aware behavior in doctor checks."""

    @patch("app.services.firecracker_doctor._run_cmd_safe")
    @patch("app.services.firecracker_doctor._is_wsl", return_value=True)
    @patch("app.services.firecracker_doctor.settings")
    def test_jailer_missing_on_wsl_is_warn(self, mock_settings, mock_is_wsl, mock_run):
        """Verify missing jailer on WSL is WARN, not FATAL."""
        mock_settings.jailer_bin = "jailer"
        mock_settings.dev_unsafe_allow_no_jailer = False
        mock_run.return_value = (1, "", "not found")

        from app.services.firecracker_doctor import _check_jailer_binary
        check = _check_jailer_binary()

        assert check.ok is False
        assert check.severity == Severity.WARN
        assert "WSL" in check.details

    @patch("app.services.firecracker_doctor._run_cmd_safe")
    @patch("app.services.firecracker_doctor._is_wsl", return_value=False)
    @patch("app.services.firecracker_doctor.settings")
    def test_jailer_missing_non_wsl_is_fatal(self, mock_settings, mock_is_wsl, mock_run):
        """Verify missing jailer on non-WSL is FATAL."""
        mock_settings.jailer_bin = "jailer"
        mock_settings.dev_unsafe_allow_no_jailer = False
        mock_run.return_value = (1, "", "not found")

        from app.services.firecracker_doctor import _check_jailer_binary
        check = _check_jailer_binary()

        assert check.ok is False
        assert check.severity == Severity.FATAL

    @patch("app.services.firecracker_doctor._run_cmd_safe")
    @patch("app.services.firecracker_doctor._is_wsl", return_value=False)
    @patch("app.services.firecracker_doctor.settings")
    def test_jailer_missing_with_dev_flag_is_warn(self, mock_settings, mock_is_wsl, mock_run):
        """Verify dev flag allows missing jailer with WARN."""
        mock_settings.jailer_bin = "jailer"
        mock_settings.dev_unsafe_allow_no_jailer = True
        mock_run.return_value = (1, "", "not found")

        from app.services.firecracker_doctor import _check_jailer_binary
        check = _check_jailer_binary()

        assert check.ok is False
        assert check.severity == Severity.WARN
        assert "UNSAFE" in check.details or "DEV" in check.details.upper()
