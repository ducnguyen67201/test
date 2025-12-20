"""No-op runtime that satisfies the LabRuntime contract without side effects."""

from __future__ import annotations

from app.models.lab import Lab
from app.models.recipe import Recipe
from app.runtime.base import LabRuntime


class NoopRuntime(LabRuntime):
    """Placeholder runtime used until real orchestration (Docker/K8s) is implemented."""

    async def create_lab(self, lab: Lab, recipe: Recipe) -> None:  # noqa: ARG002
        """No-op provisioner that immediately reports success."""

    async def destroy_lab(self, lab: Lab) -> None:  # noqa: ARG002
        """No-op teardown without external effects."""

    async def resources_exist_for_lab(self, lab: Lab) -> bool:  # noqa: ARG002
        """No-op always returns False (no resources ever exist)."""
        return False

