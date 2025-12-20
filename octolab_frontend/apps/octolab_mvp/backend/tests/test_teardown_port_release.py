"""Tests for teardown port release without owner_id.

Verifies that port release:
1. Works with lab_id only (no owner_id required)
2. Is idempotent (calling twice is safe)
3. Does not crash when lab object lacks owner_id (teardown worker scenario)
"""

import asyncio
from uuid import uuid4

import pytest

from app.db import AsyncSessionLocal
from app.models.lab import Lab, LabStatus
from app.models.recipe import Recipe
from app.models.user import User
from app.services.port_allocator import allocate_novnc_port, release_novnc_port


@pytest.mark.asyncio
async def test_release_novnc_port_with_lab_id_only():
    """Test that release_novnc_port works with just lab_id (no owner_id)."""
    # Create test data
    async with AsyncSessionLocal() as session:
        user = User(email=f"port-release-{uuid4()}@example.com", password_hash="x")
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
        owner_id = user.id

    # Allocate a port (requires owner_id during allocation for tenant check)
    async with AsyncSessionLocal() as session:
        port = await allocate_novnc_port(session, lab_id=lab_id, owner_id=owner_id)
        assert port is not None

    # Release using only lab_id (simulates teardown worker scenario)
    async with AsyncSessionLocal() as session:
        released = await release_novnc_port(session, lab_id=lab_id)
        assert released is True

    # Verify port was actually released
    async with AsyncSessionLocal() as session:
        lab = await session.get(Lab, lab_id)
        assert lab.novnc_host_port is None


@pytest.mark.asyncio
async def test_release_novnc_port_idempotent():
    """Test that calling release_novnc_port twice is safe (idempotent)."""
    # Create test data
    async with AsyncSessionLocal() as session:
        user = User(email=f"port-idempotent-{uuid4()}@example.com", password_hash="x")
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
        owner_id = user.id

    # Allocate a port
    async with AsyncSessionLocal() as session:
        port = await allocate_novnc_port(session, lab_id=lab_id, owner_id=owner_id)
        assert port is not None

    # Release once
    async with AsyncSessionLocal() as session:
        released1 = await release_novnc_port(session, lab_id=lab_id)
        assert released1 is True

    # Release again (should be no-op, not crash)
    async with AsyncSessionLocal() as session:
        released2 = await release_novnc_port(session, lab_id=lab_id)
        # Second release returns False (nothing to release)
        assert released2 is False


@pytest.mark.asyncio
async def test_release_novnc_port_nonexistent_lab():
    """Test that release_novnc_port handles nonexistent labs gracefully."""
    fake_lab_id = uuid4()

    async with AsyncSessionLocal() as session:
        # Should not crash, just return False
        released = await release_novnc_port(session, lab_id=fake_lab_id)
        assert released is False


@pytest.mark.asyncio
async def test_teardown_worker_lightweight_lab_object(monkeypatch):
    """Test that teardown worker can release ports using lightweight lab object.

    This simulates the _LabForDestroy class used by teardown_worker which
    only has lab.id (no owner_id).
    """

    # Create test data
    async with AsyncSessionLocal() as session:
        user = User(email=f"teardown-lightweight-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        lab = Lab(
            owner_id=user.id,
            recipe_id=recipe.id,
            status=LabStatus.ENDING,
            novnc_host_port=30001,  # Simulate already allocated port
        )
        session.add(lab)
        await session.commit()
        await session.refresh(lab)
        lab_id = lab.id

    # Simulate the lightweight lab object used by teardown worker
    class _LabForDestroy:
        def __init__(self, id):
            self.id = id

    lightweight_lab = _LabForDestroy(lab_id)

    # Verify lightweight lab has no owner_id attribute
    assert not hasattr(lightweight_lab, "owner_id")

    # This should NOT crash (the old code would fail with AttributeError)
    async with AsyncSessionLocal() as session:
        released = await release_novnc_port(session, lab_id=lightweight_lab.id)
        assert released is True

    # Verify port was released
    async with AsyncSessionLocal() as session:
        lab = await session.get(Lab, lab_id)
        assert lab.novnc_host_port is None


@pytest.mark.asyncio
async def test_compose_runtime_destroy_no_owner_id(monkeypatch):
    """Test that ComposeLabRuntime.destroy_lab works without owner_id on lab object."""
    from app.runtime.compose_runtime import ComposeLabRuntime
    from pathlib import Path

    # Find the compose file
    compose_path = Path(__file__).parent.parent.parent / "octolab-hackvm" / "docker-compose.yml"
    if not compose_path.exists():
        pytest.skip(f"docker-compose.yml not found at {compose_path}")

    # Create test data
    async with AsyncSessionLocal() as session:
        user = User(email=f"compose-destroy-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        lab = Lab(
            owner_id=user.id,
            recipe_id=recipe.id,
            status=LabStatus.ENDING,
            novnc_host_port=30002,
        )
        session.add(lab)
        await session.commit()
        await session.refresh(lab)
        lab_id = lab.id

    # Create lightweight lab object (no owner_id)
    class _LabForDestroy:
        def __init__(self, id):
            self.id = id

    lightweight_lab = _LabForDestroy(lab_id)

    # Mock _run_compose to avoid actually running docker
    async def mock_run_compose(self, args, env=None, suppress_errors=False):
        pass

    monkeypatch.setattr(ComposeLabRuntime, "_run_compose", mock_run_compose)

    # Create runtime and call destroy
    runtime = ComposeLabRuntime(compose_path)

    # This should NOT crash (would previously fail with AttributeError on owner_id)
    await runtime.destroy_lab(lightweight_lab)

    # Verify port was released
    async with AsyncSessionLocal() as session:
        lab = await session.get(Lab, lab_id)
        assert lab.novnc_host_port is None
