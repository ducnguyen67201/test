import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lab import Lab, LabStatus
from app.db import AsyncSessionLocal
from app.services.lab_service import terminate_lab
from app.runtime import get_runtime


class FakeRuntime:
    def __init__(self, behavior: str, delay: float = 0):
        self.behavior = behavior
        self.delay = delay
        self.called = False

    async def destroy_lab(self, lab: Lab):
        self.called = True
        if self.behavior == "success":
            return
        elif self.behavior == "timeout":
            await asyncio.sleep(self.delay)
        elif self.behavior == "error":
            raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_terminate_lab_success(monkeypatch):
    async with AsyncSessionLocal() as session:
        # create required FK rows: user and recipe
        from app.models.user import User
        from app.models.recipe import Recipe
        user = User(email=f"teardown-success-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()
        # create a lab row
        lab = Lab(owner_id=user.id, recipe_id=recipe.id, status=LabStatus.ENDING)
        session.add(lab)
        await session.commit()
        await session.refresh(lab)

        fake = FakeRuntime("success")
        monkeypatch.setattr('app.services.lab_service.get_runtime', lambda: fake)

        await terminate_lab(lab.id)

        async with AsyncSessionLocal() as check_sess:
            updated = await check_sess.get(Lab, lab.id)
            assert updated.status == LabStatus.FINISHED
            assert updated.finished_at is not None


@pytest.mark.asyncio
async def test_terminate_lab_timeout(monkeypatch):
    async with AsyncSessionLocal() as session:
        from app.models.user import User
        from app.models.recipe import Recipe
        user = User(email=f"teardown-timeout-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        lab = Lab(owner_id=user.id, recipe_id=recipe.id, status=LabStatus.ENDING)
        session.add(lab)
        await session.commit()
        await session.refresh(lab)

        # set very small timeout via monkeypatching settings
        from app import config
        original = config.settings.teardown_timeout_seconds
        config.settings.teardown_timeout_seconds = 0

        fake = FakeRuntime("timeout", delay=0.1)
        monkeypatch.setattr('app.services.lab_service.get_runtime', lambda: fake)

        await terminate_lab(lab.id)

        async with AsyncSessionLocal() as check_sess:
            updated = await check_sess.get(Lab, lab.id)
            assert updated.status == LabStatus.FAILED
            assert updated.finished_at is not None

        # restore
        config.settings.teardown_timeout_seconds = original


@pytest.mark.asyncio
async def test_terminate_lab_exception(monkeypatch):
    async with AsyncSessionLocal() as session:
        from app.models.user import User
        from app.models.recipe import Recipe
        user = User(email=f"teardown-error-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        lab = Lab(owner_id=user.id, recipe_id=recipe.id, status=LabStatus.ENDING)
        session.add(lab)
        await session.commit()
        await session.refresh(lab)

        fake = FakeRuntime("error")
        monkeypatch.setattr('app.services.lab_service.get_runtime', lambda: fake)

        await terminate_lab(lab.id)

        async with AsyncSessionLocal() as check_sess:
            updated = await check_sess.get(Lab, lab.id)
            assert updated.status == LabStatus.FAILED
            assert updated.finished_at is not None


@pytest.mark.asyncio
async def test_terminate_lab_idempotent(monkeypatch):
    async with AsyncSessionLocal() as session:
        from app.models.user import User
        from app.models.recipe import Recipe
        user = User(email=f"teardown-idemp-{uuid4()}@example.com", password_hash="x")
        recipe = Recipe(name=f"r-{uuid4()}", software="svc", is_active=True)
        session.add_all((user, recipe))
        await session.commit()

        lab = Lab(owner_id=user.id, recipe_id=recipe.id, status=LabStatus.FINISHED)
        session.add(lab)
        await session.commit()
        await session.refresh(lab)

        fake = FakeRuntime("success")
        monkeypatch.setattr('app.services.lab_service.get_runtime', lambda: fake)

        await terminate_lab(lab.id)

        # runtime.destroy_lab should not have been called
        assert fake.called is False
