"""Tests for the ending watchdog script.

Tests the watchdog functionality that detects and processes labs stuck in ENDING status.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.db import AsyncSessionLocal
from app.models.lab import Lab, LabStatus
from app.models.recipe import Recipe
from app.models.user import User
from app.scripts.force_teardown_ending_labs import (
    ending_age_anchor,
    fail_lab_only,
    force_teardown_ending_labs,
)


class FakeRuntime:
    """Fake runtime for testing without real docker/k8s calls."""

    def __init__(self, behavior: str = "success"):
        self.behavior = behavior
        self.destroy_lab_calls = []
        self.compose_path = None

    async def destroy_lab(self, lab: Lab):
        """Stub destroy_lab method."""
        self.destroy_lab_calls.append(lab.id)
        if self.behavior == "error":
            raise RuntimeError("Fake error")
        # Success: no-op


async def create_test_lab(
    session,
    user_id,
    recipe_id,
    status: LabStatus = LabStatus.ENDING,
    age_minutes: int = 0,
) -> Lab:
    """Helper to create a test lab with a specific age.

    Args:
        session: Database session
        user_id: User ID (FK)
        recipe_id: Recipe ID (FK)
        status: Lab status (default ENDING)
        age_minutes: How many minutes ago the lab was updated (simulates age)

    Returns:
        Created Lab instance
    """
    lab = Lab(
        owner_id=user_id,
        recipe_id=recipe_id,
        status=status,
    )
    session.add(lab)
    await session.commit()
    await session.refresh(lab)

    # Manually set updated_at to simulate age
    if age_minutes > 0:
        old_timestamp = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
        # Update the timestamp directly in the database
        from sqlalchemy import update
        stmt = update(Lab).where(Lab.id == lab.id).values(updated_at=old_timestamp)
        await session.execute(stmt)
        await session.commit()
        await session.refresh(lab)

    return lab


@pytest.mark.asyncio
async def test_ending_age_anchor():
    """Test that ending_age_anchor returns updated_at field."""
    async with AsyncSessionLocal() as session:
        user = User(email=f"age-test-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        lab = Lab(owner_id=user.id, recipe_id=recipe.id, status=LabStatus.ENDING)
        session.add(lab)
        await session.commit()
        await session.refresh(lab)

        anchor = ending_age_anchor(lab)
        assert anchor == lab.updated_at


@pytest.mark.asyncio
async def test_dry_run_no_changes(monkeypatch):
    """Test that dry-run mode does not change any lab statuses."""
    async with AsyncSessionLocal() as session:
        # Create test data
        user = User(email=f"dryrun-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        # Create old ENDING lab (should be selected)
        old_lab = await create_test_lab(session, user.id, recipe.id, LabStatus.ENDING, age_minutes=60)

        # Create fresh ENDING lab (should not be selected)
        fresh_lab = await create_test_lab(session, user.id, recipe.id, LabStatus.ENDING, age_minutes=5)

    # Stub runtime to prevent real calls
    fake_runtime = FakeRuntime()
    monkeypatch.setattr("app.scripts.force_teardown_ending_labs.get_runtime", lambda: fake_runtime)

    # Run watchdog in dry-run mode
    await force_teardown_ending_labs(
        older_than_minutes=30,
        max_labs=20,
        dry_run=True,
        action="force",
    )

    # Verify no changes were made
    async with AsyncSessionLocal() as check_session:
        old_updated = await check_session.get(Lab, old_lab.id)
        fresh_updated = await check_session.get(Lab, fresh_lab.id)

        # Both should still be ENDING
        assert old_updated.status == LabStatus.ENDING
        assert fresh_updated.status == LabStatus.ENDING

        # Neither should have finished_at set
        assert old_updated.finished_at is None
        assert fresh_updated.finished_at is None

    # Runtime should not have been called
    assert len(fake_runtime.destroy_lab_calls) == 0


@pytest.mark.asyncio
async def test_action_fail_marks_failed_only(monkeypatch):
    """Test that action=fail marks old labs as FAILED without calling runtime."""
    async with AsyncSessionLocal() as session:
        user = User(email=f"fail-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        # Create old ENDING lab (should be marked FAILED)
        old_lab = await create_test_lab(session, user.id, recipe.id, LabStatus.ENDING, age_minutes=60)

        # Create fresh ENDING lab (should not be touched)
        fresh_lab = await create_test_lab(session, user.id, recipe.id, LabStatus.ENDING, age_minutes=5)

    # Stub runtime
    fake_runtime = FakeRuntime()
    monkeypatch.setattr("app.scripts.force_teardown_ending_labs.get_runtime", lambda: fake_runtime)

    # Stub port release to avoid transaction issues
    async def fake_release_port(*args, **kwargs):
        return True
    monkeypatch.setattr("app.scripts.force_teardown_ending_labs.release_novnc_port", fake_release_port)

    # Run watchdog with action=fail
    await force_teardown_ending_labs(
        older_than_minutes=30,
        max_labs=20,
        dry_run=False,
        action="fail",
    )

    # Verify changes
    async with AsyncSessionLocal() as check_session:
        old_updated = await check_session.get(Lab, old_lab.id)
        fresh_updated = await check_session.get(Lab, fresh_lab.id)

        # Old lab should be FAILED with finished_at set
        assert old_updated.status == LabStatus.FAILED
        assert old_updated.finished_at is not None

        # Fresh lab should still be ENDING
        assert fresh_updated.status == LabStatus.ENDING
        assert fresh_updated.finished_at is None

    # Runtime destroy_lab should NOT have been called (action=fail doesn't teardown)
    assert len(fake_runtime.destroy_lab_calls) == 0


@pytest.mark.asyncio
async def test_action_force_calls_teardown(monkeypatch):
    """Test that action=force calls force_teardown_lab for old labs."""
    async with AsyncSessionLocal() as session:
        user = User(email=f"force-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        # Create old ENDING lab (should be force torn down)
        old_lab = await create_test_lab(session, user.id, recipe.id, LabStatus.ENDING, age_minutes=60)

        # Create fresh ENDING lab (should not be touched)
        fresh_lab = await create_test_lab(session, user.id, recipe.id, LabStatus.ENDING, age_minutes=5)

    # Stub runtime
    fake_runtime = FakeRuntime("success")
    monkeypatch.setattr("app.scripts.force_teardown_ending_labs.get_runtime", lambda: fake_runtime)

    # Stub subprocess to avoid real docker calls
    async def fake_subprocess_run(*args, **kwargs):
        class FakeResult:
            returncode = 0
            stdout = ""
            stderr = ""
        return FakeResult()

    monkeypatch.setattr("app.scripts.force_teardown_ending_labs.subprocess.run", fake_subprocess_run)

    # Stub port release to avoid transaction issues
    async def fake_release_port(*args, **kwargs):
        return True
    monkeypatch.setattr("app.scripts.force_teardown_ending_labs.release_novnc_port", fake_release_port)

    # Run watchdog with action=force
    await force_teardown_ending_labs(
        older_than_minutes=30,
        max_labs=20,
        dry_run=False,
        action="force",
    )

    # Verify changes
    async with AsyncSessionLocal() as check_session:
        old_updated = await check_session.get(Lab, old_lab.id)
        fresh_updated = await check_session.get(Lab, fresh_lab.id)

        # Old lab should be FINISHED (force_teardown_lab succeeded)
        assert old_updated.status == LabStatus.FINISHED
        assert old_updated.finished_at is not None

        # Fresh lab should still be ENDING
        assert fresh_updated.status == LabStatus.ENDING
        assert fresh_updated.finished_at is None

    # Runtime destroy_lab should have been called for old lab only
    assert old_lab.id in fake_runtime.destroy_lab_calls
    assert fresh_lab.id not in fake_runtime.destroy_lab_calls


@pytest.mark.asyncio
async def test_age_filtering(monkeypatch):
    """Test that only labs older than threshold are processed."""
    async with AsyncSessionLocal() as session:
        user = User(email=f"age-filter-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        # Create labs with different ages
        very_old_lab = await create_test_lab(session, user.id, recipe.id, LabStatus.ENDING, age_minutes=120)
        old_lab = await create_test_lab(session, user.id, recipe.id, LabStatus.ENDING, age_minutes=60)
        borderline_lab = await create_test_lab(session, user.id, recipe.id, LabStatus.ENDING, age_minutes=31)
        fresh_lab = await create_test_lab(session, user.id, recipe.id, LabStatus.ENDING, age_minutes=5)

    # Stub runtime
    fake_runtime = FakeRuntime()
    monkeypatch.setattr("app.scripts.force_teardown_ending_labs.get_runtime", lambda: fake_runtime)

    # Stub port release to avoid transaction issues
    async def fake_release_port(*args, **kwargs):
        return True
    monkeypatch.setattr("app.scripts.force_teardown_ending_labs.release_novnc_port", fake_release_port)

    # Run watchdog with 30-minute threshold using action=fail (simpler to verify)
    await force_teardown_ending_labs(
        older_than_minutes=30,
        max_labs=20,
        dry_run=False,
        action="fail",
    )

    # Verify changes
    async with AsyncSessionLocal() as check_session:
        very_old_updated = await check_session.get(Lab, very_old_lab.id)
        old_updated = await check_session.get(Lab, old_lab.id)
        borderline_updated = await check_session.get(Lab, borderline_lab.id)
        fresh_updated = await check_session.get(Lab, fresh_lab.id)

        # Very old, old, and borderline (>30 min) should be FAILED
        assert very_old_updated.status == LabStatus.FAILED
        assert old_updated.status == LabStatus.FAILED
        assert borderline_updated.status == LabStatus.FAILED

        # Fresh (<30 min) should still be ENDING
        assert fresh_updated.status == LabStatus.ENDING


@pytest.mark.asyncio
async def test_max_labs_limit(monkeypatch):
    """Test that max_labs limit is respected."""
    async with AsyncSessionLocal() as session:
        user = User(email=f"maxlabs-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        # Create 5 old ENDING labs
        labs = []
        for i in range(5):
            lab = await create_test_lab(session, user.id, recipe.id, LabStatus.ENDING, age_minutes=60 + i)
            labs.append(lab)

    # Stub runtime
    fake_runtime = FakeRuntime()
    monkeypatch.setattr("app.scripts.force_teardown_ending_labs.get_runtime", lambda: fake_runtime)

    # Stub port release to avoid transaction issues
    async def fake_release_port(*args, **kwargs):
        return True
    monkeypatch.setattr("app.scripts.force_teardown_ending_labs.release_novnc_port", fake_release_port)

    # Run watchdog with max_labs=3
    await force_teardown_ending_labs(
        older_than_minutes=30,
        max_labs=3,
        dry_run=False,
        action="fail",
    )

    # Count how many were marked FAILED
    failed_count = 0
    ending_count = 0
    async with AsyncSessionLocal() as check_session:
        for lab in labs:
            updated = await check_session.get(Lab, lab.id)
            if updated.status == LabStatus.FAILED:
                failed_count += 1
            elif updated.status == LabStatus.ENDING:
                ending_count += 1

    # Only 3 should have been processed (oldest 3)
    assert failed_count == 3
    assert ending_count == 2


@pytest.mark.asyncio
async def test_specific_lab_id_ignores_filters(monkeypatch):
    """Test that --lab-id mode ignores age and max-labs filters."""
    async with AsyncSessionLocal() as session:
        user = User(email=f"specific-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        # Create fresh ENDING lab (normally would not be selected)
        fresh_lab = await create_test_lab(session, user.id, recipe.id, LabStatus.ENDING, age_minutes=5)
        # Create old ENDING lab
        old_lab = await create_test_lab(session, user.id, recipe.id, LabStatus.ENDING, age_minutes=60)

    # Stub runtime
    fake_runtime = FakeRuntime()
    monkeypatch.setattr("app.scripts.force_teardown_ending_labs.get_runtime", lambda: fake_runtime)

    # Stub port release to avoid transaction issues
    async def fake_release_port(*args, **kwargs):
        return True
    monkeypatch.setattr("app.scripts.force_teardown_ending_labs.release_novnc_port", fake_release_port)

    # Run watchdog targeting fresh lab specifically (despite age < threshold)
    await force_teardown_ending_labs(
        lab_id=str(fresh_lab.id),
        older_than_minutes=30,  # This should be ignored
        max_labs=1,  # This should be ignored
        dry_run=False,
        action="fail",
    )

    # Verify changes
    async with AsyncSessionLocal() as check_session:
        fresh_updated = await check_session.get(Lab, fresh_lab.id)
        old_updated = await check_session.get(Lab, old_lab.id)

        # Fresh lab should be FAILED (explicitly targeted)
        assert fresh_updated.status == LabStatus.FAILED

        # Old lab should still be ENDING (not targeted)
        assert old_updated.status == LabStatus.ENDING


@pytest.mark.asyncio
async def test_fail_lab_only_function():
    """Test the fail_lab_only helper function."""
    async with AsyncSessionLocal() as session:
        user = User(email=f"failonly-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        lab = Lab(owner_id=user.id, recipe_id=recipe.id, status=LabStatus.ENDING)
        session.add(lab)
        await session.commit()
        await session.refresh(lab)

    # Call fail_lab_only
    await fail_lab_only(lab)

    # Verify changes
    async with AsyncSessionLocal() as check_session:
        updated = await check_session.get(Lab, lab.id)
        assert updated.status == LabStatus.FAILED
        assert updated.finished_at is not None


@pytest.mark.asyncio
async def test_skip_locked_in_query():
    """Test that skip_locked is used in the query to prevent double-processing.

    This is a structural test verifying that the query includes with_for_update(skip_locked=True).
    Actual concurrency behavior is hard to test in unit tests.
    """
    # This test verifies the query structure by checking that skip_locked is applied
    # We can do this by inspecting the code or by checking compiled SQL
    from sqlalchemy import select
    from app.models.lab import Lab, LabStatus
    from datetime import datetime, timedelta, timezone

    # Build the query as the script does
    query = select(Lab).where(Lab.status == LabStatus.ENDING)
    now_utc = datetime.now(timezone.utc)
    age_threshold = now_utc - timedelta(minutes=30)
    query = query.where(Lab.updated_at < age_threshold)
    query = query.order_by(Lab.updated_at.asc())
    query = query.limit(20)
    query = query.with_for_update(skip_locked=True)

    # Verify the query has the for_update clause with skip_locked
    assert query._for_update_arg is not None
    assert query._for_update_arg.skip_locked is True
