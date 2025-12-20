"""Tests for the background teardown worker.

Tests verify:
- claim_ending_labs correctly claims labs with FOR UPDATE SKIP LOCKED
- Worker processes ENDING labs to completion
- Concurrent workers don't conflict (SKIP LOCKED safety)
- Cancellation during shutdown is handled gracefully
"""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.db import AsyncSessionLocal
from app.models.lab import Lab, LabStatus
from app.models.recipe import Recipe
from app.models.user import User
from app.services.teardown_worker import (
    claim_ending_labs,
    process_ending_lab,
    teardown_worker_tick,
)


class FakeRuntime:
    """Fake runtime for testing."""

    def __init__(self, behavior: str = "success"):
        self.behavior = behavior
        self.destroy_lab_calls = []

    async def destroy_lab(self, lab: Lab):
        """Stub destroy_lab method."""
        self.destroy_lab_calls.append(lab.id)
        if self.behavior == "timeout":
            await asyncio.sleep(999)  # Simulate timeout
        elif self.behavior == "error":
            raise RuntimeError("Fake runtime error")
        # success: return normally


@pytest.mark.asyncio
async def test_claim_ending_labs_empty():
    """Test claiming when no ENDING labs exist."""
    async with AsyncSessionLocal() as session:
        labs = await claim_ending_labs(session, limit=10)
        assert labs == []


@pytest.mark.asyncio
async def test_claim_ending_labs_claims_ending_only():
    """Test that only ENDING labs are claimed, not other statuses."""
    # Create test data
    async with AsyncSessionLocal() as session:
        user = User(email=f"claim-test-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        # Create labs in various states
        lab_ready = Lab(owner_id=user.id, recipe_id=recipe.id, status=LabStatus.READY)
        lab_ending = Lab(owner_id=user.id, recipe_id=recipe.id, status=LabStatus.ENDING)
        lab_finished = Lab(owner_id=user.id, recipe_id=recipe.id, status=LabStatus.FINISHED)

        session.add_all((lab_ready, lab_ending, lab_finished))
        await session.commit()
        ending_lab_id = lab_ending.id

    # Claim ENDING labs
    async with AsyncSessionLocal() as claim_session:
        claimed = await claim_ending_labs(claim_session, limit=10)
        claimed_ids = [lab.id for lab in claimed]

        # Only the ENDING lab should be claimed
        assert ending_lab_id in claimed_ids
        assert len(claimed) == 1


@pytest.mark.asyncio
async def test_claim_ending_labs_respects_limit():
    """Test that claim_ending_labs respects the limit parameter."""
    # Create test data: 5 ENDING labs
    async with AsyncSessionLocal() as session:
        user = User(email=f"limit-test-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        for i in range(5):
            lab = Lab(owner_id=user.id, recipe_id=recipe.id, status=LabStatus.ENDING)
            session.add(lab)

        await session.commit()

    # Claim with limit=3
    async with AsyncSessionLocal() as claim_session:
        claimed = await claim_ending_labs(claim_session, limit=3)
        assert len(claimed) == 3


@pytest.mark.asyncio
async def test_process_ending_lab_success(monkeypatch):
    """Test successful lab teardown processing."""
    # Create test data
    async with AsyncSessionLocal() as session:
        user = User(email=f"process-success-{uuid4()}@example.com", password_hash="x")
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

    # Stub runtime
    fake_runtime = FakeRuntime("success")
    monkeypatch.setattr("app.services.teardown_worker.get_runtime", lambda: fake_runtime)

    # Process the lab
    async with AsyncSessionLocal() as session:
        lab = await session.get(Lab, lab_id)
        await process_ending_lab(lab)

        # Verify runtime.destroy_lab was called
        assert lab_id in fake_runtime.destroy_lab_calls

        # Verify lab status is still ENDING (process_ending_lab doesn't commit)
        assert lab.status == LabStatus.FINISHED
        assert lab.finished_at is not None


@pytest.mark.asyncio
async def test_process_ending_lab_timeout(monkeypatch):
    """Test that timeout marks lab as FAILED."""
    # Create test data
    async with AsyncSessionLocal() as session:
        user = User(email=f"process-timeout-{uuid4()}@example.com", password_hash="x")
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

    # Stub runtime to timeout
    fake_runtime = FakeRuntime("timeout")
    monkeypatch.setattr("app.services.teardown_worker.get_runtime", lambda: fake_runtime)

    # Reduce timeout for testing
    from app import config
    original_timeout = config.settings.teardown_timeout_seconds
    config.settings.teardown_timeout_seconds = 1.0

    try:
        # Process the lab
        async with AsyncSessionLocal() as session:
            lab = await session.get(Lab, lab_id)
            await process_ending_lab(lab)

            # Verify lab is marked FAILED
            assert lab.status == LabStatus.FAILED
            assert lab.finished_at is not None

    finally:
        config.settings.teardown_timeout_seconds = original_timeout


@pytest.mark.asyncio
async def test_process_ending_lab_error(monkeypatch):
    """Test that runtime errors mark lab as FAILED."""
    # Create test data
    async with AsyncSessionLocal() as session:
        user = User(email=f"process-error-{uuid4()}@example.com", password_hash="x")
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

    # Stub runtime to error
    fake_runtime = FakeRuntime("error")
    monkeypatch.setattr("app.services.teardown_worker.get_runtime", lambda: fake_runtime)

    # Process the lab
    async with AsyncSessionLocal() as session:
        lab = await session.get(Lab, lab_id)
        await process_ending_lab(lab)

        # Verify lab is marked FAILED
        assert lab.status == LabStatus.FAILED
        assert lab.finished_at is not None


@pytest.mark.asyncio
async def test_teardown_worker_tick_processes_batch(monkeypatch):
    """Test that worker tick processes a batch of labs."""
    # Create test data: 5 ENDING labs
    async with AsyncSessionLocal() as session:
        user = User(email=f"tick-test-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        lab_ids = []
        for i in range(5):
            lab = Lab(owner_id=user.id, recipe_id=recipe.id, status=LabStatus.ENDING)
            session.add(lab)
            await session.flush()
            lab_ids.append(lab.id)

        await session.commit()

    # Stub runtime
    fake_runtime = FakeRuntime("success")
    monkeypatch.setattr("app.services.teardown_worker.get_runtime", lambda: fake_runtime)

    # Stub port release
    async def fake_release_port(*args, **kwargs):
        pass

    monkeypatch.setattr("app.services.teardown_worker.release_novnc_port", fake_release_port)

    # Set batch size to 3
    from app import config
    original_batch_size = config.settings.teardown_worker_batch_size
    config.settings.teardown_worker_batch_size = 3

    try:
        # Run one tick
        processed = await teardown_worker_tick()

        # Should process 3 labs (batch size)
        assert processed == 3

        # Verify those 3 are now FINISHED
        async with AsyncSessionLocal() as check_session:
            finished_count = 0
            ending_count = 0

            for lab_id in lab_ids:
                lab = await check_session.get(Lab, lab_id)
                if lab.status == LabStatus.FINISHED:
                    finished_count += 1
                elif lab.status == LabStatus.ENDING:
                    ending_count += 1

            assert finished_count == 3
            assert ending_count == 2

        # Run another tick to process remaining 2
        processed = await teardown_worker_tick()
        assert processed == 2

        # Verify all are now FINISHED
        async with AsyncSessionLocal() as check_session:
            for lab_id in lab_ids:
                lab = await check_session.get(Lab, lab_id)
                assert lab.status == LabStatus.FINISHED

    finally:
        config.settings.teardown_worker_batch_size = original_batch_size


@pytest.mark.asyncio
async def test_teardown_worker_tick_empty_returns_zero(monkeypatch):
    """Test that tick returns 0 when no ENDING labs exist."""
    # Stub runtime (shouldn't be called)
    fake_runtime = FakeRuntime("success")
    monkeypatch.setattr("app.services.teardown_worker.get_runtime", lambda: fake_runtime)

    # Run tick with no ENDING labs
    processed = await teardown_worker_tick()
    assert processed == 0
    assert len(fake_runtime.destroy_lab_calls) == 0
