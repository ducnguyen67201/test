"""Tests for ENDING reconciliation (runtime missing → FINISHED).

Tests verify that labs stuck in ENDING status with no runtime resources
are automatically reconciled to FINISHED without attempting teardown.
"""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.db import AsyncSessionLocal
from app.models.lab import Lab, LabStatus
from app.models.recipe import Recipe
from app.models.user import User
from app.services.lab_service import terminate_lab


class FakeRuntimeResourcesMissing:
    """Fake runtime where resources don't exist."""

    def __init__(self):
        self.destroy_lab_calls = []
        self.resources_exist_calls = []

    async def resources_exist_for_lab(self, lab: Lab) -> bool:
        """Always returns False (resources missing)."""
        self.resources_exist_calls.append(lab.id)
        return False

    async def destroy_lab(self, lab: Lab):
        """Should NOT be called when resources missing."""
        self.destroy_lab_calls.append(lab.id)
        raise AssertionError("destroy_lab should not be called when resources missing")


class FakeRuntimeResourcesExist:
    """Fake runtime where resources exist."""

    def __init__(self):
        self.destroy_lab_calls = []
        self.resources_exist_calls = []

    async def resources_exist_for_lab(self, lab: Lab) -> bool:
        """Always returns True (resources exist)."""
        self.resources_exist_calls.append(lab.id)
        return True

    async def destroy_lab(self, lab: Lab):
        """Called when resources exist."""
        self.destroy_lab_calls.append(lab.id)
        # Simulate successful destroy
        return


@pytest.mark.asyncio
async def test_ending_reconcile_resources_missing_marks_finished(monkeypatch):
    """Test that ENDING labs with no runtime resources are reconciled to FINISHED."""
    # Create test data
    async with AsyncSessionLocal() as session:
        user = User(email=f"reconcile-test-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        # Create lab in ENDING status
        lab = Lab(
            owner_id=user.id,
            recipe_id=recipe.id,
            status=LabStatus.ENDING,
        )
        session.add(lab)
        await session.commit()
        await session.refresh(lab)
        lab_id = lab.id

    # Stub runtime to return resources_missing
    fake_runtime = FakeRuntimeResourcesMissing()
    monkeypatch.setattr("app.services.lab_service.get_runtime", lambda: fake_runtime)

    # Call terminate_lab
    await terminate_lab(lab_id)

    # Verify lab is marked FINISHED
    async with AsyncSessionLocal() as check_session:
        updated_lab = await check_session.get(Lab, lab_id)
        assert updated_lab.status == LabStatus.FINISHED
        assert updated_lab.finished_at is not None
        assert updated_lab.evidence_expires_at is not None

    # Verify resources_exist was called
    assert lab_id in fake_runtime.resources_exist_calls

    # Verify destroy_lab was NOT called
    assert len(fake_runtime.destroy_lab_calls) == 0


@pytest.mark.asyncio
async def test_ending_reconcile_resources_exist_proceeds_with_destroy(monkeypatch):
    """Test that ENDING labs with existing resources proceed with normal destroy."""
    # Create test data
    async with AsyncSessionLocal() as session:
        user = User(email=f"destroy-test-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        # Create lab in ENDING status
        lab = Lab(
            owner_id=user.id,
            recipe_id=recipe.id,
            status=LabStatus.ENDING,
        )
        session.add(lab)
        await session.commit()
        await session.refresh(lab)
        lab_id = lab.id

    # Stub runtime to return resources_exist
    fake_runtime = FakeRuntimeResourcesExist()
    monkeypatch.setattr("app.services.lab_service.get_runtime", lambda: fake_runtime)

    # Call terminate_lab
    await terminate_lab(lab_id)

    # Verify lab is marked FINISHED
    async with AsyncSessionLocal() as check_session:
        updated_lab = await check_session.get(Lab, lab_id)
        assert updated_lab.status == LabStatus.FINISHED
        assert updated_lab.finished_at is not None

    # Verify resources_exist was called
    assert lab_id in fake_runtime.resources_exist_calls

    # Verify destroy_lab WAS called (normal path)
    assert lab_id in fake_runtime.destroy_lab_calls


@pytest.mark.asyncio
async def test_ending_reconcile_preserves_finished_at_if_set(monkeypatch):
    """Test that reconciliation preserves finished_at if already set."""
    # Create test data with finished_at already set
    original_finished_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    async with AsyncSessionLocal() as session:
        user = User(email=f"preserve-test-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        # Create lab in ENDING status with finished_at already set
        lab = Lab(
            owner_id=user.id,
            recipe_id=recipe.id,
            status=LabStatus.ENDING,
            finished_at=original_finished_at,
        )
        session.add(lab)
        await session.commit()
        await session.refresh(lab)
        lab_id = lab.id

    # Stub runtime to return resources_missing
    fake_runtime = FakeRuntimeResourcesMissing()
    monkeypatch.setattr("app.services.lab_service.get_runtime", lambda: fake_runtime)

    # Call terminate_lab
    await terminate_lab(lab_id)

    # Verify lab is marked FINISHED
    async with AsyncSessionLocal() as check_session:
        updated_lab = await check_session.get(Lab, lab_id)
        assert updated_lab.status == LabStatus.FINISHED
        # finished_at should be preserved (not overwritten)
        assert updated_lab.finished_at == original_finished_at


@pytest.mark.asyncio
async def test_ending_reconcile_skips_if_already_finished(monkeypatch):
    """Test that reconciliation skips labs already in FINISHED status."""
    # Create test data
    async with AsyncSessionLocal() as session:
        user = User(email=f"skip-test-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        # Create lab already in FINISHED status
        lab = Lab(
            owner_id=user.id,
            recipe_id=recipe.id,
            status=LabStatus.FINISHED,
            finished_at=datetime.now(timezone.utc),
        )
        session.add(lab)
        await session.commit()
        await session.refresh(lab)
        lab_id = lab.id

    # Stub runtime
    fake_runtime = FakeRuntimeResourcesMissing()
    monkeypatch.setattr("app.services.lab_service.get_runtime", lambda: fake_runtime)

    # Call terminate_lab
    await terminate_lab(lab_id)

    # Verify resources_exist was NOT called (skipped due to terminal status)
    assert len(fake_runtime.resources_exist_calls) == 0


@pytest.mark.asyncio
async def test_ending_reconcile_handles_check_failure_gracefully(monkeypatch):
    """Test that reconciliation proceeds with destroy if resource check fails."""

    class FakeRuntimeCheckFails:
        """Fake runtime where resource check raises exception."""

        def __init__(self):
            self.destroy_lab_calls = []

        async def resources_exist_for_lab(self, lab: Lab) -> bool:
            """Simulate check failure."""
            raise RuntimeError("Docker daemon not responding")

        async def destroy_lab(self, lab: Lab):
            """Called when check fails (conservative approach)."""
            self.destroy_lab_calls.append(lab.id)
            return

    # Create test data
    async with AsyncSessionLocal() as session:
        user = User(email=f"check-fail-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        lab = Lab(
            owner_id=user.id,
            recipe_id=recipe.id,
            status=LabStatus.ENDING,
        )
        session.add(lab)
        await session.commit()
        await session.refresh(lab)
        lab_id = lab.id

    # Stub runtime to fail check
    fake_runtime = FakeRuntimeCheckFails()
    monkeypatch.setattr("app.services.lab_service.get_runtime", lambda: fake_runtime)

    # Call terminate_lab
    await terminate_lab(lab_id)

    # Should proceed with destroy (conservative: assume resources exist on error)
    assert lab_id in fake_runtime.destroy_lab_calls

    # Lab should still be marked FINISHED
    async with AsyncSessionLocal() as check_session:
        updated_lab = await check_session.get(Lab, lab_id)
        assert updated_lab.status == LabStatus.FINISHED
