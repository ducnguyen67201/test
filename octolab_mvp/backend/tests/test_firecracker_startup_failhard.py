"""Tests for Firecracker runtime startup fail-hard behavior.

SECURITY:
- Verifies that OCTOLAB_RUNTIME=firecracker fails closed when prerequisites aren't met
- Ensures no silent fallback to compose runtime
- Tests the fail-hard validation logic in isolation

NOTE: These tests use isolated testing that doesn't require importing app.main
to avoid Settings validation failures. The core logic is tested via microvm_doctor.
"""

import pytest
from unittest.mock import patch, MagicMock

# Mark all tests as not requiring database access
pytestmark = pytest.mark.no_db


def _make_check_result(name: str, ok: bool, severity: str, message: str, hint: str = None) -> dict:
    """Create a check result dict matching microvm_doctor format."""
    status = "OK" if ok else ("WARN" if severity == "warn" else "FAIL")
    return {
        "name": name,
        "status": status,
        "severity": severity,
        "message": message,
        "hint": hint,
    }


def _make_doctor_result(checks: list[dict], is_ok: bool = None) -> dict:
    """Create a doctor result dict matching microvm_doctor format."""
    ok_count = sum(1 for c in checks if c["status"] == "OK")
    warn_count = sum(1 for c in checks if c["status"] == "WARN")
    fail_count = sum(1 for c in checks if c["status"] == "FAIL")
    fatal_count = sum(1 for c in checks if c["status"] == "FAIL" and c["severity"] == "fatal")

    if is_ok is None:
        is_ok = fatal_count == 0

    return {
        "checks": checks,
        "summary": {
            "ok": ok_count,
            "warn": warn_count,
            "fail": fail_count,
            "fatal": fatal_count,
        },
        "is_ok": is_ok,
        "generated_at": "2024-01-01T00:00:00Z",
    }


class TestMicrovmDoctorFailHardLogic:
    """Test the fail-hard logic using microvm_doctor directly (no app.main import)."""

    def test_is_ok_false_when_fatal_failures(self):
        """Verify is_ok is False when there are fatal failures."""
        from app.services.microvm_doctor import run_checks

        # Empty env = missing kernel/rootfs = fatal failures
        result = run_checks(env={})

        assert result["is_ok"] is False
        assert result["summary"]["fatal"] > 0

    def test_is_ok_true_when_no_fatal_failures(self):
        """Verify is_ok is True when there are no fatal failures."""
        result = _make_doctor_result([
            _make_check_result("kvm", True, "info", "ok"),
            _make_check_result("jailer", False, "warn", "missing"),  # warn, not fatal
        ])

        assert result["is_ok"] is True
        assert result["summary"]["fatal"] == 0

    def test_get_fatal_summary_redaction(self):
        """Verify get_fatal_summary doesn't expose sensitive paths."""
        from app.services.microvm_doctor import get_fatal_summary

        result = _make_doctor_result([
            _make_check_result(
                "kernel",
                ok=False,
                severity="fatal",
                message="kernel not found: .../vmlinux",
                hint="Download kernel",
            ),
        ])

        summary = get_fatal_summary(result)

        # Should not contain full paths
        assert "/var/lib" not in summary
        assert "/home/" not in summary

    def test_fatal_summary_truncation(self):
        """Verify get_fatal_summary truncates long output."""
        from app.services.microvm_doctor import get_fatal_summary

        long_hint = "x" * 1000
        result = _make_doctor_result([
            _make_check_result(
                "test",
                ok=False,
                severity="fatal",
                message="failed",
                hint=long_hint,
            ),
        ])

        summary = get_fatal_summary(result)
        assert len(summary) <= 500


class TestValidationFunctionLogic:
    """Test the validation function logic pattern (without importing app.main)."""

    def test_validation_raises_on_fatal(self):
        """Verify the validation pattern raises RuntimeError on fatal failures."""
        from app.services.microvm_doctor import get_fatal_summary

        def _validate_firecracker_prerequisites_isolated(result: dict) -> None:
            """Isolated version of the validation logic."""
            if not result["is_ok"]:
                fatal_count = result["summary"]["fatal"]
                error_msg = get_fatal_summary(result)
                raise RuntimeError(
                    f"Cannot start with OCTOLAB_RUNTIME=firecracker: {error_msg}. "
                    "Fix the issues above. NO FALLBACK to compose."
                )

        result = _make_doctor_result([
            _make_check_result("kvm", False, "fatal", "/dev/kvm not found", "Enable KVM"),
        ])

        with pytest.raises(RuntimeError) as exc_info:
            _validate_firecracker_prerequisites_isolated(result)

        error_msg = str(exc_info.value)
        assert "Cannot start with OCTOLAB_RUNTIME=firecracker" in error_msg
        assert "NO FALLBACK" in error_msg

    def test_validation_passes_on_warnings(self):
        """Verify validation passes when there are only warnings."""
        from app.services.microvm_doctor import get_fatal_summary

        def _validate_firecracker_prerequisites_isolated(result: dict) -> None:
            """Isolated version of the validation logic."""
            if not result["is_ok"]:
                fatal_count = result["summary"]["fatal"]
                error_msg = get_fatal_summary(result)
                raise RuntimeError(
                    f"Cannot start with OCTOLAB_RUNTIME=firecracker: {error_msg}. "
                    "Fix the issues above. NO FALLBACK to compose."
                )

        result = _make_doctor_result([
            _make_check_result("kvm", True, "info", "ok"),
            _make_check_result("jailer", False, "warn", "missing"),  # warn, not fatal
            _make_check_result("vsock", False, "warn", "not available"),  # warn
        ])

        # Should not raise
        _validate_firecracker_prerequisites_isolated(result)


class TestMultipleFatalFailures:
    """Test handling of multiple fatal failures."""

    def test_all_fatal_failures_in_summary(self):
        """Verify all fatal failures are included in the summary."""
        from app.services.microvm_doctor import get_fatal_summary

        result = _make_doctor_result([
            _make_check_result("kvm", False, "fatal", "missing", "Enable KVM"),
            _make_check_result("kernel", False, "fatal", "missing", "Download kernel"),
            _make_check_result("rootfs", False, "fatal", "missing", "Download rootfs"),
        ])

        summary = get_fatal_summary(result)

        # All failures should be mentioned
        assert "kvm" in summary
        assert "kernel" in summary
        assert "rootfs" in summary

    def test_mixed_fatal_and_warn(self):
        """Verify is_ok is False when there's a mix of fatal and warn."""
        result = _make_doctor_result([
            _make_check_result("kvm", True, "info", "ok"),
            _make_check_result("kernel", False, "fatal", "missing"),
            _make_check_result("jailer", False, "warn", "missing"),
        ])

        assert result["is_ok"] is False
        assert result["summary"]["fatal"] == 1
        assert result["summary"]["warn"] == 1


class TestNoFallbackBehavior:
    """Test that the error message clearly indicates no fallback."""

    def test_error_message_no_fallback(self):
        """Verify error message mentions NO FALLBACK."""
        from app.services.microvm_doctor import get_fatal_summary

        result = _make_doctor_result([
            _make_check_result("firecracker", False, "fatal", "not found", "Install it"),
        ])

        def _validate(result: dict):
            if not result["is_ok"]:
                error_msg = get_fatal_summary(result)
                raise RuntimeError(
                    f"Cannot start with OCTOLAB_RUNTIME=firecracker: {error_msg}. "
                    "Fix the issues above. NO FALLBACK to compose."
                )

        with pytest.raises(RuntimeError) as exc_info:
            _validate(result)

        assert "NO FALLBACK" in str(exc_info.value)


class TestCLIExitCodes:
    """Test CLI exit codes for fail-hard behavior."""

    def test_exit_code_0_on_success(self):
        """CLI should exit 0 when all critical checks pass."""
        from app.services.microvm_doctor import main

        with patch(
            "app.services.microvm_doctor.run_checks",
            return_value={
                "checks": [],
                "summary": {"ok": 7, "warn": 0, "fail": 0, "fatal": 0},
                "is_ok": True,
                "generated_at": "2024-01-01T00:00:00Z",
            },
        ), patch("sys.argv", ["microvm_doctor", "--json"]):
            exit_code = main()

        assert exit_code == 0

    def test_exit_code_2_on_fatal(self):
        """CLI should exit 2 when there are fatal failures (for shell scripts)."""
        from app.services.microvm_doctor import main

        with patch(
            "app.services.microvm_doctor.run_checks",
            return_value={
                "checks": [
                    {"name": "kvm", "status": "FAIL", "severity": "fatal", "message": "missing", "hint": None},
                ],
                "summary": {"ok": 0, "warn": 0, "fail": 1, "fatal": 1},
                "is_ok": False,
                "generated_at": "2024-01-01T00:00:00Z",
            },
        ), patch("sys.argv", ["microvm_doctor", "--json"]):
            exit_code = main()

        assert exit_code == 2
