"""Lab orchestration service for managing HackVM stacks."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.lab import Lab, LabStatus

logger = logging.getLogger(__name__)


class LabOrchestrator:
    """Service responsible for starting and stopping lab environments."""

    def __init__(self, hackvm_dir: str | Path | None = None) -> None:
        configured_dir = hackvm_dir or settings.hackvm_dir
        if configured_dir is None:
            raise ValueError(
                "HackVM directory is not configured. Set `HACKVM_DIR=` in backend/.env."
            )

        path = Path(configured_dir).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"HACKVM_DIR path does not exist: {path}")

        self.hackvm_dir = path

    async def start_lab(self, lab: Lab, session: AsyncSession) -> Lab:
        """Start the HackVM stack for a lab."""
        logger.info("Starting lab %s via docker compose", lab.id)
        try:
            await self._run_compose(("docker", "compose", "up", "-d"))
        except subprocess.CalledProcessError as exc:
            logger.error(
                "Failed to start lab %s: %s",
                lab.id,
                exc.stderr or exc.stdout,
            )
            lab.status = LabStatus.FAILED
            await self._persist(session, lab)
            raise

        lab.status = LabStatus.READY
        lab.connection_url = f"http://localhost:6080/vnc.html?lab_id={lab.id}"

        await self._persist(session, lab)
        return lab

    async def stop_lab(self, lab: Lab, session: AsyncSession) -> Lab:
        """Stop a lab by marking it for teardown.

        Sets status to ENDING, which triggers the teardown worker to
        properly clean up all resources (VM, network, Guacamole, etc.).

        This replaces the old sync compose-down flow with the async
        teardown worker flow for proper resource cleanup.
        """
        if lab.status in (LabStatus.ENDING, LabStatus.FINISHED):
            logger.info(f"Lab {lab.id} already stopping/stopped")
            return lab

        logger.info(f"Marking lab {lab.id} for teardown (status=ENDING)")
        lab.status = LabStatus.ENDING
        await self._persist(session, lab)
        return lab

    async def _run_compose(self, cmd: Sequence[str]) -> None:
        """Execute a docker compose command asynchronously."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._run_blocking, cmd)

    def _run_blocking(self, cmd: Sequence[str]) -> None:
        """Run subprocess command and raise on failure."""
        result = subprocess.run(
            cmd,
            cwd=self.hackvm_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                cmd,
                output=result.stdout,
                stderr=result.stderr,
            )

    async def _persist(self, session: AsyncSession, lab: Lab) -> None:
        """Commit and refresh lab state."""
        await session.commit()
        await session.refresh(lab)

