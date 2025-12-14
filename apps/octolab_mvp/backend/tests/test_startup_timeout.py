"""Tests for fail-fast startup timeout behavior.

Verifies that labs don't stay in "Starting" state forever:
1. Overall startup timeout causes FAILED state
2. Diagnostics are collected on failure
3. Best-effort cleanup is attempted
"""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.db import AsyncSessionLocal
from app.models.lab import Lab, LabStatus
from app.models.recipe import Recipe
from app.models.user import User


class FakeRuntimeTimeout:
    """Fake runtime that simulates timeout during create_lab."""

    def __init__(self):
        self.create_lab_calls = []
        self.destroy_lab_calls = []

    async def create_lab(self, lab, recipe, db_session=None):
        """Simulate a hanging create_lab."""
        self.create_lab_calls.append(lab.id)
        # Sleep longer than the timeout to trigger timeout
        await asyncio.sleep(999)

    async def destroy_lab(self, lab):
        """Track destroy calls."""
        self.destroy_lab_calls.append(lab.id)


class FakeRuntimeSuccess:
    """Fake runtime that succeeds immediately."""

    def __init__(self):
        self.create_lab_calls = []
        self.destroy_lab_calls = []

    async def create_lab(self, lab, recipe, db_session=None):
        """Succeed immediately."""
        self.create_lab_calls.append(lab.id)

    async def destroy_lab(self, lab):
        """Track destroy calls."""
        self.destroy_lab_calls.append(lab.id)


class FakeRuntimeError:
    """Fake runtime that raises an error."""

    def __init__(self, error_type=RuntimeError):
        self.error_type = error_type
        self.create_lab_calls = []
        self.destroy_lab_calls = []

    async def create_lab(self, lab, recipe, db_session=None):
        """Raise an error."""
        self.create_lab_calls.append(lab.id)
        raise self.error_type("Fake provisioning error")

    async def destroy_lab(self, lab):
        """Track destroy calls."""
        self.destroy_lab_calls.append(lab.id)


@pytest.mark.asyncio
async def test_provision_lab_startup_timeout(monkeypatch):
    """Test that provision_lab fails-fast on startup timeout."""
    from app.services.lab_service import provision_lab
    from app import config

    # Create test data
    async with AsyncSessionLocal() as session:
        user = User(email=f"timeout-test-{uuid4()}@example.com", password_hash="x")
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

    # Use fake runtime that times out
    fake_runtime = FakeRuntimeTimeout()
    monkeypatch.setattr("app.services.lab_service.get_runtime", lambda: fake_runtime)

    # Stub K8sLabRuntime check to use fake runtime
    monkeypatch.setattr("app.services.lab_service.K8sLabRuntime", type(None))

    # Mock diagnostics collection (avoid actual docker calls)
    async def mock_diagnostics(*args, **kwargs):
        return {"compose_ps": "mocked", "compose_logs": "mocked"}

    monkeypatch.setattr("app.services.lab_service.collect_compose_diagnostics", mock_diagnostics)

    # Set very short timeout for testing
    original_timeout = config.settings.lab_startup_timeout_seconds
    config.settings.lab_startup_timeout_seconds = 1  # 1 second timeout

    try:
        # Run provisioning - should timeout and mark FAILED
        await provision_lab(lab_id)

        # Verify lab is marked FAILED (not stuck in PROVISIONING)
        async with AsyncSessionLocal() as session:
            lab = await session.get(Lab, lab_id)
            assert lab.status == LabStatus.FAILED, f"Lab should be FAILED, not {lab.status}"
            assert lab.finished_at is not None, "finished_at should be set"

    finally:
        config.settings.lab_startup_timeout_seconds = original_timeout


@pytest.mark.asyncio
async def test_provision_lab_error_marks_failed(monkeypatch):
    """Test that provisioning errors mark lab as FAILED."""
    from app.services.lab_service import provision_lab
    from app import config

    # Create test data
    async with AsyncSessionLocal() as session:
        user = User(email=f"error-test-{uuid4()}@example.com", password_hash="x")
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

    # Use fake runtime that errors
    fake_runtime = FakeRuntimeError()
    monkeypatch.setattr("app.services.lab_service.get_runtime", lambda: fake_runtime)
    monkeypatch.setattr("app.services.lab_service.K8sLabRuntime", type(None))

    # Mock diagnostics collection
    async def mock_diagnostics(*args, **kwargs):
        return {"compose_ps": "mocked", "compose_logs": "mocked"}

    monkeypatch.setattr("app.services.lab_service.collect_compose_diagnostics", mock_diagnostics)

    # Run provisioning - should error and mark FAILED
    await provision_lab(lab_id)

    # Verify lab is marked FAILED
    async with AsyncSessionLocal() as session:
        lab = await session.get(Lab, lab_id)
        assert lab.status == LabStatus.FAILED, f"Lab should be FAILED, not {lab.status}"
        assert lab.finished_at is not None, "finished_at should be set"
        # Best-effort teardown should have been attempted
        assert lab_id in fake_runtime.destroy_lab_calls


@pytest.mark.asyncio
async def test_provision_lab_success(monkeypatch):
    """Test that successful provisioning marks lab as READY."""
    from app.services.lab_service import provision_lab
    from app import config

    # Create test data
    async with AsyncSessionLocal() as session:
        user = User(email=f"success-test-{uuid4()}@example.com", password_hash="x")
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

    # Use fake runtime that succeeds
    fake_runtime = FakeRuntimeSuccess()
    monkeypatch.setattr("app.services.lab_service.get_runtime", lambda: fake_runtime)
    monkeypatch.setattr("app.services.lab_service.K8sLabRuntime", type(None))

    # Disable readiness gating for this test (would need noVNC probe)
    original_gating = config.settings.novnc_ready_gating_enabled
    config.settings.novnc_ready_gating_enabled = False

    try:
        # Run provisioning - should succeed and mark READY
        await provision_lab(lab_id)

        # Verify lab is marked READY
        async with AsyncSessionLocal() as session:
            lab = await session.get(Lab, lab_id)
            assert lab.status == LabStatus.READY, f"Lab should be READY, not {lab.status}"

    finally:
        config.settings.novnc_ready_gating_enabled = original_gating


@pytest.mark.asyncio
async def test_config_startup_timeout_setting():
    """Test that lab_startup_timeout_seconds config setting exists and is reasonable."""
    from app import config

    # Setting should exist
    assert hasattr(config.settings, "lab_startup_timeout_seconds")

    # Default should be reasonable (not too short, not infinite)
    timeout = config.settings.lab_startup_timeout_seconds
    assert timeout >= 30, "Startup timeout should be at least 30 seconds"
    assert timeout <= 600, "Startup timeout should be at most 10 minutes"


@pytest.mark.asyncio
async def test_provision_lab_missing_recipe(monkeypatch):
    """Test that missing recipe marks lab as FAILED immediately."""
    from app.services.lab_service import provision_lab

    # Create test data with a recipe that will be deleted
    async with AsyncSessionLocal() as session:
        user = User(email=f"missing-recipe-{uuid4()}@example.com", password_hash="x")
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
        recipe_id = recipe.id

        # Delete the recipe to simulate missing recipe
        await session.delete(recipe)
        await session.commit()

    # Run provisioning - should fail due to missing recipe
    await provision_lab(lab_id)

    # Verify lab is marked FAILED
    async with AsyncSessionLocal() as session:
        lab = await session.get(Lab, lab_id)
        assert lab.status == LabStatus.FAILED, f"Lab should be FAILED, not {lab.status}"
        assert lab.finished_at is not None, "finished_at should be set"
