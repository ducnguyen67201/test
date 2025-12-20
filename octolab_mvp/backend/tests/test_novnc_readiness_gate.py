"""Tests for noVNC readiness gating.

Tests the server-side readiness probe that gates lab status transitions to READY.
"""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.db import AsyncSessionLocal
from app.models.lab import Lab, LabStatus
from app.models.recipe import Recipe
from app.models.user import User
from app.services.lab_service import provision_lab
from app.services.novnc_probe import NovncNotReady


class FakeComposeRuntime:
    """Fake compose runtime for testing."""

    def __init__(self, behavior: str = "success"):
        self.behavior = behavior
        self.create_lab_calls = []
        self.destroy_lab_calls = []

    async def create_lab(self, lab: Lab, recipe: Recipe, db_session=None):
        """Stub create_lab method."""
        self.create_lab_calls.append(lab.id)
        # Simulate successful container creation
        # In real implementation, this would start docker compose
        if self.behavior == "error":
            raise RuntimeError("Fake compose error")

    async def destroy_lab(self, lab: Lab):
        """Stub destroy_lab method."""
        self.destroy_lab_calls.append(lab.id)


@pytest.mark.asyncio
async def test_readiness_probe_success_marks_ready(monkeypatch):
    """Test that successful readiness probe marks lab as READY."""
    # Create test data
    async with AsyncSessionLocal() as session:
        user = User(email=f"probe-success-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        # Create lab in PROVISIONING status
        lab = Lab(
            owner_id=user.id,
            recipe_id=recipe.id,
            status=LabStatus.PROVISIONING,
        )
        session.add(lab)
        await session.commit()
        await session.refresh(lab)
        lab_id = lab.id

    # Stub runtime
    fake_runtime = FakeComposeRuntime("success")
    monkeypatch.setattr("app.services.lab_service.get_runtime", lambda: fake_runtime)

    # Stub port allocation to return deterministic port
    async def fake_allocate_port(*args, **kwargs):
        return 38044

    monkeypatch.setattr("app.services.lab_service.allocate_novnc_port", fake_allocate_port)

    # Stub readiness probe to succeed immediately
    async def fake_probe_success(*args, **kwargs):
        return "vnc.html"  # Success

    monkeypatch.setattr("app.services.lab_service.probe_novnc_ready", fake_probe_success)

    # Stub diagnostics collection (should not be called on success)
    diagnostics_called = []

    async def fake_diagnostics(*args, **kwargs):
        diagnostics_called.append(True)
        return {}

    monkeypatch.setattr("app.services.lab_service.collect_compose_diagnostics", fake_diagnostics)

    # Run provision_lab
    await provision_lab(lab_id)

    # Verify lab is READY
    async with AsyncSessionLocal() as check_session:
        updated_lab = await check_session.get(Lab, lab_id)
        assert updated_lab.status == LabStatus.READY
        assert updated_lab.connection_url is not None
        assert "38044" in updated_lab.connection_url
        assert updated_lab.finished_at is None

    # Verify diagnostics not collected on success
    assert len(diagnostics_called) == 0

    # Verify runtime create was called
    assert lab_id in fake_runtime.create_lab_calls


@pytest.mark.asyncio
async def test_readiness_probe_failure_marks_failed(monkeypatch):
    """Test that failed readiness probe marks lab as FAILED and collects diagnostics."""
    # Create test data
    async with AsyncSessionLocal() as session:
        user = User(email=f"probe-fail-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        lab = Lab(
            owner_id=user.id,
            recipe_id=recipe.id,
            status=LabStatus.PROVISIONING,
        )
        session.add(lab)
        await session.commit()
        await session.refresh(lab)
        lab_id = lab.id

    # Stub runtime
    fake_runtime = FakeComposeRuntime("success")
    monkeypatch.setattr("app.services.lab_service.get_runtime", lambda: fake_runtime)

    # Stub port allocation
    async def fake_allocate_port(*args, **kwargs):
        return 38044

    monkeypatch.setattr("app.services.lab_service.allocate_novnc_port", fake_allocate_port)

    # Stub readiness probe to fail
    async def fake_probe_failure(*args, **kwargs):
        raise NovncNotReady("Fake timeout")

    monkeypatch.setattr("app.services.lab_service.probe_novnc_ready", fake_probe_failure)

    # Track diagnostics collection
    diagnostics_called = []

    async def fake_diagnostics(*args, **kwargs):
        diagnostics_called.append(kwargs.get("lab_id"))
        return {"compose_ps": "fake ps output", "compose_logs": "fake logs"}

    monkeypatch.setattr("app.services.lab_service.collect_compose_diagnostics", fake_diagnostics)

    # Stub port release
    async def fake_release_port(*args, **kwargs):
        pass

    monkeypatch.setattr("app.services.lab_service.release_novnc_port", fake_release_port)

    # Run provision_lab
    await provision_lab(lab_id)

    # Verify lab is FAILED
    async with AsyncSessionLocal() as check_session:
        updated_lab = await check_session.get(Lab, lab_id)
        assert updated_lab.status == LabStatus.FAILED
        assert updated_lab.finished_at is not None
        assert updated_lab.connection_url is None  # Should not be set on failure

    # Verify diagnostics were collected
    assert lab_id in diagnostics_called

    # Verify destroy_lab was called for cleanup
    assert lab_id in fake_runtime.destroy_lab_calls


@pytest.mark.asyncio
async def test_readiness_gating_disabled_marks_ready_immediately(monkeypatch):
    """Test that disabling gating marks lab READY immediately without probe."""
    # Create test data
    async with AsyncSessionLocal() as session:
        user = User(email=f"gating-disabled-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        lab = Lab(
            owner_id=user.id,
            recipe_id=recipe.id,
            status=LabStatus.PROVISIONING,
        )
        session.add(lab)
        await session.commit()
        await session.refresh(lab)
        lab_id = lab.id

    # Disable gating
    from app import config

    original_gating = config.settings.novnc_ready_gating_enabled
    config.settings.novnc_ready_gating_enabled = False

    # Stub runtime
    fake_runtime = FakeComposeRuntime("success")
    monkeypatch.setattr("app.services.lab_service.get_runtime", lambda: fake_runtime)

    # Stub port allocation
    async def fake_allocate_port(*args, **kwargs):
        return 38044

    monkeypatch.setattr("app.services.lab_service.allocate_novnc_port", fake_allocate_port)

    # Track if probe was called (should NOT be called when gating disabled)
    probe_called = []

    async def fake_probe(*args, **kwargs):
        probe_called.append(True)
        return "vnc.html"

    monkeypatch.setattr("app.services.lab_service.probe_novnc_ready", fake_probe)

    # Run provision_lab
    await provision_lab(lab_id)

    # Verify lab is READY
    async with AsyncSessionLocal() as check_session:
        updated_lab = await check_session.get(Lab, lab_id)
        assert updated_lab.status == LabStatus.READY
        assert updated_lab.connection_url is not None

    # Verify probe was NOT called
    assert len(probe_called) == 0

    # Restore setting
    config.settings.novnc_ready_gating_enabled = original_gating


@pytest.mark.asyncio
async def test_readiness_probe_tcp_connect_test():
    """Test the TCP probe helper (integration-style test)."""
    from app.services.novnc_probe import _tcp_probe

    # Test connecting to a known listening port (SSH on localhost, usually port 22)
    # This test may fail if SSH is not running, so we'll catch that
    try:
        await _tcp_probe("127.0.0.1", 22)
        # If SSH is running, this should succeed
    except (OSError, ConnectionRefusedError):
        # SSH not running or port blocked, that's OK for this test
        pass

    # Test connecting to a port that definitely won't be listening
    with pytest.raises((OSError, ConnectionRefusedError, asyncio.TimeoutError)):
        await asyncio.wait_for(_tcp_probe("127.0.0.1", 65535), timeout=2.0)


@pytest.mark.asyncio
async def test_novnc_not_ready_exception_message():
    """Test that NovncNotReady exception contains useful information."""
    from app.services.novnc_probe import probe_novnc_ready, NovncNotReady

    # Use a port that won't be listening
    with pytest.raises(NovncNotReady) as exc_info:
        await probe_novnc_ready(
            host="127.0.0.1",
            port=65534,  # Unlikely to be in use
            timeout_seconds=2.0,
            poll_interval_seconds=0.5,
            paths=["test.html"],
        )

    # Verify exception message contains useful info
    exc_message = str(exc_info.value)
    assert "127.0.0.1" in exc_message
    assert "65534" in exc_message
    assert "not ready" in exc_message.lower()
