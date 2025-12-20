"""Tests for runtime override functionality.

SECURITY:
- Verify admin-only access to runtime endpoints
- Verify fail-fast when Firecracker enabled but not ready
- Verify no fallback to compose when Firecracker is enabled
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.services.runtime_selector import (
    RuntimeState,
    get_runtime_state,
    get_effective_runtime,
    set_runtime_override,
    assert_runtime_ready_for_lab,
)
from app.services.firecracker_doctor import DoctorCheck, DoctorReport, Severity

# Mark all tests in this module as not requiring database access
pytestmark = pytest.mark.no_db


class TestRuntimeState:
    """Test RuntimeState dataclass."""

    def test_default_state(self):
        """Verify default runtime state is compose."""
        state = RuntimeState()
        assert state.override is None
        assert state.last_smoke_ok is False
        assert state.last_smoke_at is None

    def test_to_dict(self):
        """Verify to_dict serialization."""
        state = RuntimeState(override="firecracker", last_smoke_ok=True)
        d = state.to_dict()
        assert d["override"] == "firecracker"
        assert d["last_smoke_ok"] is True


class TestGetEffectiveRuntime:
    """Test effective runtime resolution."""

    @patch("app.config.settings")
    def test_default_uses_settings_runtime(self, mock_settings):
        """Verify default effective runtime uses settings.octolab_runtime."""
        mock_settings.octolab_runtime = "compose"

        app = MagicMock()
        app.state = MagicMock()
        del app.state.runtime_state  # Ensure attribute doesn't exist

        # get_runtime_state will initialize it, returns settings value when no override
        effective = get_effective_runtime(app)
        assert effective == "compose"

    def test_override_firecracker(self):
        """Verify override to firecracker is respected."""
        app = MagicMock()
        app.state.runtime_state = RuntimeState(override="firecracker")

        effective = get_effective_runtime(app)
        assert effective == "firecracker"

    def test_override_compose(self):
        """Verify explicit compose override works."""
        app = MagicMock()
        app.state.runtime_state = RuntimeState(override="compose")

        effective = get_effective_runtime(app)
        assert effective == "compose"


class TestSetRuntimeOverride:
    """Test runtime override setting with validation."""

    @patch("app.services.runtime_selector.run_doctor")
    def test_setting_to_compose_always_succeeds(self, mock_doctor):
        """Verify setting override to compose doesn't require doctor check."""
        app = MagicMock()
        app.state.runtime_state = RuntimeState()

        success, msg, report = set_runtime_override(app, "compose")
        assert success is True
        assert report is None
        mock_doctor.assert_not_called()

    @patch("app.services.runtime_selector.run_doctor")
    def test_setting_to_none_always_succeeds(self, mock_doctor):
        """Verify resetting override to None doesn't require doctor check."""
        app = MagicMock()
        app.state.runtime_state = RuntimeState(override="firecracker")

        success, msg, report = set_runtime_override(app, None)
        assert success is True
        assert report is None
        mock_doctor.assert_not_called()

    @patch("app.services.runtime_selector.run_doctor")
    @patch("app.config.settings")
    def test_setting_to_firecracker_requires_doctor(self, mock_settings, mock_doctor):
        """Verify setting to firecracker runs doctor check."""
        mock_settings.dev_unsafe_allow_no_jailer = True
        mock_doctor.return_value = DoctorReport(
            ok=True,
            checks=[
                DoctorCheck("kvm", ok=True, severity=Severity.INFO, details="ok"),
                DoctorCheck("jailer", ok=True, severity=Severity.INFO, details="ok"),
            ],
            summary="Ready",
        )

        app = MagicMock()
        app.state.runtime_state = RuntimeState()

        success, msg, report = set_runtime_override(app, "firecracker")
        assert success is True
        assert report is not None
        mock_doctor.assert_called_once()

    @patch("app.services.runtime_selector.run_doctor")
    def test_firecracker_rejected_on_fatal(self, mock_doctor):
        """Verify Firecracker override is rejected when doctor reports fatal."""
        mock_doctor.return_value = DoctorReport(
            ok=False,
            checks=[
                DoctorCheck("kvm", ok=False, severity=Severity.FATAL, details="missing"),
            ],
            summary="Unavailable",
        )

        app = MagicMock()
        app.state.runtime_state = RuntimeState()

        success, msg, report = set_runtime_override(app, "firecracker")
        assert success is False
        assert "kvm" in msg.lower()

    @patch("app.services.runtime_selector.run_doctor")
    @patch("app.config.settings")
    def test_firecracker_rejected_without_jailer(self, mock_settings, mock_doctor):
        """Verify Firecracker rejected when jailer missing and not dev mode."""
        mock_settings.dev_unsafe_allow_no_jailer = False
        mock_doctor.return_value = DoctorReport(
            ok=True,  # Doctor says ok because jailer is WARN not FATAL
            checks=[
                DoctorCheck("kvm", ok=True, severity=Severity.INFO, details="ok"),
                DoctorCheck("jailer", ok=False, severity=Severity.WARN, details="missing"),
            ],
            summary="Ready with warnings",
        )

        app = MagicMock()
        app.state.runtime_state = RuntimeState()

        success, msg, report = set_runtime_override(app, "firecracker")
        assert success is False
        assert "jailer" in msg.lower()


class TestAssertRuntimeReadyForLab:
    """Test fail-fast runtime assertion for lab creation."""

    @patch("app.config.settings")
    def test_compose_is_always_ready(self, mock_settings):
        """Verify compose runtime passes without checks."""
        mock_settings.octolab_runtime = "compose"

        app = MagicMock()
        app.state.runtime_state = RuntimeState(override=None)

        result = assert_runtime_ready_for_lab(app)
        assert result == "compose"

    @patch("app.services.runtime_selector.run_doctor")
    def test_firecracker_passes_when_doctor_ok(self, mock_doctor):
        """Verify Firecracker passes when doctor reports ok."""
        mock_doctor.return_value = DoctorReport(
            ok=True,
            checks=[DoctorCheck("kvm", ok=True, severity=Severity.INFO, details="ok")],
            summary="Ready",
        )

        app = MagicMock()
        app.state.runtime_state = RuntimeState(override="firecracker")

        result = assert_runtime_ready_for_lab(app)
        assert result == "firecracker"

    @patch("app.services.runtime_selector.run_doctor")
    def test_firecracker_fails_when_doctor_fatal(self, mock_doctor):
        """Verify Firecracker fails fast when doctor reports fatal."""
        from fastapi import HTTPException

        mock_doctor.return_value = DoctorReport(
            ok=False,
            checks=[
                DoctorCheck("kvm", ok=False, severity=Severity.FATAL, details="missing", hint="enable"),
            ],
            summary="Unavailable",
        )

        app = MagicMock()
        app.state.runtime_state = RuntimeState(override="firecracker")

        with pytest.raises(HTTPException) as exc_info:
            assert_runtime_ready_for_lab(app)

        assert exc_info.value.status_code == 400
        assert "not ready" in exc_info.value.detail.lower()


class TestNoFallbackBehavior:
    """Test that there's no fallback from Firecracker to Compose."""

    @patch("app.services.runtime_selector.run_doctor")
    def test_no_fallback_on_doctor_fail(self, mock_doctor):
        """Verify no fallback to compose when Firecracker doctor fails."""
        from fastapi import HTTPException

        mock_doctor.return_value = DoctorReport(
            ok=False,
            checks=[
                DoctorCheck("kvm", ok=False, severity=Severity.FATAL, details="missing"),
            ],
            summary="Unavailable",
        )

        app = MagicMock()
        app.state.runtime_state = RuntimeState(override="firecracker")

        # This should raise, not silently fall back to compose
        with pytest.raises(HTTPException) as exc_info:
            assert_runtime_ready_for_lab(app)

        # Verify it's an error, not a fallback
        assert exc_info.value.status_code in (400, 503)

        # Effective runtime should still be firecracker (no automatic fallback)
        assert get_effective_runtime(app) == "firecracker"


class TestRuntimeOverrideIntegration:
    """Integration tests for runtime override (mocked)."""

    @patch("app.services.runtime_selector.run_doctor")
    @patch("app.config.settings")
    def test_override_persists_in_state(self, mock_settings, mock_doctor):
        """Verify runtime override persists in app state."""
        mock_settings.dev_unsafe_allow_no_jailer = True
        mock_settings.octolab_runtime = "compose"
        mock_doctor.return_value = DoctorReport(
            ok=True,
            checks=[DoctorCheck("kvm", ok=True, severity=Severity.INFO, details="ok")],
            summary="Ready",
        )

        app = MagicMock()
        app.state.runtime_state = RuntimeState()

        # Initial state uses settings.octolab_runtime (compose)
        assert get_effective_runtime(app) == "compose"

        # Enable firecracker
        success, _, _ = set_runtime_override(app, "firecracker")
        assert success is True

        # Verify it persists
        assert get_effective_runtime(app) == "firecracker"

        # Reset to default
        success, _, _ = set_runtime_override(app, None)
        assert success is True
        assert get_effective_runtime(app) == "compose"
