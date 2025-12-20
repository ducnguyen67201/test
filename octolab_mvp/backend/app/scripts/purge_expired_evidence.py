"""Purge expired lab evidence volumes.

Run this script periodically (cron/systemd) to delete Docker volumes that hold
network captures after their retention window has elapsed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.lab import Lab
from app.services.evidence_service import purge_lab_evidence

logger = logging.getLogger(__name__)


async def purge_expired_labs() -> None:
    """Delete evidence volumes whose TTL has expired."""

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Lab).where(
                Lab.evidence_expires_at.is_not(None),
                Lab.evidence_deleted_at.is_(None),
                Lab.evidence_expires_at < now,
            )
        )
        labs = result.scalars().all()
        if not labs:
            logger.info("No expired lab evidence to purge.")
            return

        logger.info("Purging evidence for %d lab(s)", len(labs))
        for lab in labs:
            await purge_lab_evidence(lab)
            session.add(lab)

        await session.commit()


async def main() -> None:
    await purge_expired_labs()


if __name__ == "__main__":
    asyncio.run(main())

