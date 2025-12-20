"""Runtime interface for lab provisioning."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Protocol

from app.models.lab import Lab
from app.models.recipe import Recipe


class LabRuntime(Protocol):
    """Defines the interface required to provision and tear down labs."""

    @abstractmethod
    async def create_lab(self, lab: Lab, recipe: Recipe) -> None:
        """Provision resources for a lab (placeholder, no side effects yet)."""

    @abstractmethod
    async def destroy_lab(self, lab: Lab) -> Any:
        """Tear down resources for a lab.

        Returns:
            Implementation-specific result. ComposeLabRuntime returns
            TeardownResult with verified cleanup status. Other runtimes
            may return None.
        """

    @abstractmethod
    async def resources_exist_for_lab(self, lab: Lab) -> bool:
        """Check if runtime resources exist for a lab (for ENDING reconciliation)."""
