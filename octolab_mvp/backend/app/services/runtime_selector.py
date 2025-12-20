"""Runtime selector for dynamic runtime override.

This module provides server-owned runtime selection with admin-controlled override.
The override is in-memory only (resets on restart) for dev safety.

SECURITY:
- Runtime override is server-owned, never from client request
- Only admin can change override via admin endpoints
- When Firecracker is enabled, fail-fast if doctor reports fatal issues
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from fastapi import HTTPException, status

from app.services.firecracker_doctor import DoctorReport, run_doctor

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


# Valid runtime override values
RuntimeOverride = Literal["compose", "firecracker"] | None


@dataclass
class RuntimeState:
    """State for runtime selection.

    Stored in app.state.runtime_state.
    All fields are server-owned and never from client.
    """

    # Current runtime override (None = use default from env)
    override: RuntimeOverride = None

    # Last smoke test results
    last_smoke_ok: bool = False
    last_smoke_at: datetime | None = None
    last_smoke_notes: list[str] | None = None

    def to_dict(self) -> dict:
        """Convert to dict for API response."""
        return {
            "override": self.override,
            "last_smoke_ok": self.last_smoke_ok,
            "last_smoke_at": self.last_smoke_at.isoformat() if self.last_smoke_at else None,
            "last_smoke_notes": self.last_smoke_notes or [],
        }


def get_runtime_state(app: "FastAPI") -> RuntimeState:
    """Get runtime state from app, initializing if needed.

    Args:
        app: FastAPI application instance

    Returns:
        RuntimeState instance
    """
    if not hasattr(app.state, "runtime_state"):
        app.state.runtime_state = RuntimeState()
    return app.state.runtime_state


def get_effective_runtime(app: "FastAPI") -> str:
    """Get effective runtime based on override or configured default.

    Args:
        app: FastAPI application instance

    Returns:
        "compose" or "firecracker" (never None - config validation ensures this)

    SECURITY:
    - Runtime is server-owned, never from client
    - If override is set, use that
    - Otherwise use the configured runtime from settings (already validated)
    - No fallback - config validation ensures OCTOLAB_RUNTIME is set
    """
    from app.config import settings

    state = get_runtime_state(app)

    if state.override is not None:
        return state.override

    # Use configured runtime (settings validation ensures it's set)
    return settings.octolab_runtime


def set_runtime_override(
    app: "FastAPI",
    override: RuntimeOverride,
) -> tuple[bool, str, DoctorReport | None]:
    """Set runtime override with validation.

    Args:
        app: FastAPI application instance
        override: New override value ("compose", "firecracker", or None)

    Returns:
        Tuple of (success, message, doctor_report_if_firecracker)

    SECURITY:
    - If setting to firecracker, runs doctor and rejects on fatal
    - If jailer missing and not dev override, rejects
    """
    state = get_runtime_state(app)
    doctor_report = None

    # Setting to None or compose is always allowed
    if override is None or override == "compose":
        old = state.override
        state.override = override
        logger.info(f"Runtime override changed: {old} -> {override}")
        return True, f"Runtime override set to {override or 'default (compose)'}", None

    # Setting to firecracker requires doctor validation
    if override == "firecracker":
        doctor_report = run_doctor()

        if not doctor_report.ok:
            # Fatal issues - reject
            fatal_names = [c.name for c in doctor_report.fatal_checks]
            msg = f"Cannot enable Firecracker: {', '.join(fatal_names)} check(s) failed"
            logger.warning(f"Runtime override rejected: {msg}")
            return False, msg, doctor_report

        # Check jailer specifically
        from app.config import settings

        jailer_check = next((c for c in doctor_report.checks if c.name == "jailer"), None)
        if jailer_check and not jailer_check.ok:
            if not settings.dev_unsafe_allow_no_jailer:
                msg = "Cannot enable Firecracker: jailer not available and OCTOLAB_DEV_UNSAFE_ALLOW_NO_JAILER not set"
                logger.warning(f"Runtime override rejected: {msg}")
                return False, msg, doctor_report

        old = state.override
        state.override = "firecracker"
        logger.info(f"Runtime override changed: {old} -> firecracker")
        return True, "Runtime override set to firecracker", doctor_report

    # Unknown override value
    return False, f"Unknown override value: {override}", None


def assert_runtime_ready_for_lab(app: "FastAPI") -> str:
    """Assert runtime is ready for lab creation.

    When Firecracker is enabled, runs doctor and fails if any fatal issues.

    Args:
        app: FastAPI application instance

    Returns:
        Effective runtime name

    Raises:
        HTTPException: 400 if Firecracker enabled but doctor reports fatal
        HTTPException: 503 if Firecracker runtime not implemented
    """
    effective = get_effective_runtime(app)

    if effective == "compose":
        # Compose is always ready (no preflight needed)
        return effective

    if effective == "firecracker":
        # Run doctor to verify Firecracker is ready
        report = run_doctor()

        if not report.ok:
            # Fatal issues - fail fast, no fallback to compose
            fatal_hints = "; ".join(
                f"{c.name}: {c.hint}" for c in report.fatal_checks
            )[:500]
            logger.error(f"Firecracker enabled but not ready: {fatal_hints}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Firecracker enabled but not ready: {report.summary[:200]}",
            )

        return effective

    # Unknown runtime - should not happen
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Unknown runtime: {effective}",
    )


def get_runtime_status(app: "FastAPI") -> dict:
    """Get current runtime status for admin API.

    Args:
        app: FastAPI application instance

    Returns:
        Dict with runtime status
    """
    state = get_runtime_state(app)
    effective = get_effective_runtime(app)

    # Run doctor to get current status
    doctor_report = run_doctor()

    return {
        "override": state.override,
        "effective_runtime": effective,
        "doctor_ok": doctor_report.ok,
        "doctor_summary": doctor_report.summary[:200],
        "last_smoke_ok": state.last_smoke_ok,
        "last_smoke_at": state.last_smoke_at.isoformat() if state.last_smoke_at else None,
    }


def record_smoke_result(
    app: "FastAPI",
    ok: bool,
    notes: list[str] | None = None,
) -> None:
    """Record smoke test result in app state.

    Args:
        app: FastAPI application instance
        ok: Whether smoke test passed
        notes: Optional notes about the smoke test
    """
    state = get_runtime_state(app)
    state.last_smoke_ok = ok
    state.last_smoke_at = datetime.now(timezone.utc)
    state.last_smoke_notes = notes or []
