"""Force teardown of labs stuck in ENDING status.

This script finds labs that are stuck in ENDING status and forces them
to complete teardown by directly calling docker compose down and updating
the database status.

ADMIN-ONLY TOOL: This script is for administrative use only and should not
be exposed via HTTP endpoints. It implements safety features including:
- Concurrency safety via skip_locked row-level locking
- Dry-run mode to preview actions
- Max-labs limit to prevent mass operations
- Redacted logging (no owner_id in logs)
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

# Add backend directory to path so we can import app modules
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import select

from app.config import settings
from app.db import AsyncSessionLocal
from app.models.lab import Lab, LabStatus
from app.runtime import get_runtime
from app.services.port_allocator import release_novnc_port

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def ending_age_anchor(lab: Lab) -> datetime:
    """
    Get the timestamp to use for calculating how long a lab has been in ENDING status.

    Uses updated_at which is automatically updated whenever the lab status changes.
    This is the most reliable indicator of when the lab entered ENDING status.
    """
    return lab.updated_at


async def force_teardown_lab(lab: Lab, session: AsyncSessionLocal) -> bool:
    """Force teardown a single lab with timeout protection.

    Logs are redacted: owner_id is not printed directly.

    Returns:
        True if teardown succeeded (lab marked FINISHED), False otherwise (lab marked FAILED).
    """
    lab_id = lab.id
    project_name = f"octolab_{lab_id}"

    # Redact owner: only show short suffix for debugging
    owner_short = str(lab.owner_id)[-6:]
    logger.info(f"Force tearing down lab {lab_id} (owner=****{owner_short}, project={project_name})")

    teardown_succeeded = False

    # Get compose path from runtime
    compose_path = None
    try:
        runtime = get_runtime()
        if hasattr(runtime, 'compose_path'):
            compose_path = runtime.compose_path
            logger.info(f"Using compose path from runtime: {compose_path}")
    except Exception as e:
        logger.warning(f"Could not get runtime for lab {lab_id}: {e}")

    # Try runtime destroy_lab with timeout
    try:
        runtime = get_runtime()
        if hasattr(runtime, 'destroy_lab'):
            try:
                await asyncio.wait_for(runtime.destroy_lab(lab), timeout=60.0)
                logger.info(f"Runtime destroy_lab completed for lab {lab_id}")
                teardown_succeeded = True
            except asyncio.TimeoutError:
                logger.warning(f"Runtime destroy_lab timed out for lab {lab_id}, forcing direct teardown")
            except Exception as e:
                logger.warning(f"Runtime destroy_lab failed for lab {lab_id}: {type(e).__name__}, trying direct teardown")
    except Exception as e:
        logger.warning(f"Could not call runtime destroy_lab for lab {lab_id}: {type(e).__name__}")

    # Direct docker compose down as fallback/ensure
    try:
        if compose_path and compose_path.exists():
            cmd = ["docker", "compose", "-f", str(compose_path), "-p", project_name, "down", "--remove-orphans"]
        else:
            # Try without compose file path (docker compose might find it by project name)
            cmd = ["docker", "compose", "-p", project_name, "down", "--remove-orphans"]

        logger.info(f"Running direct docker compose down: {' '.join(cmd)}")
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=30.0,
            check=False,
        )
        if result.returncode == 0:
            logger.info(f"Docker compose down succeeded for {project_name}")
            teardown_succeeded = True
        else:
            # Check if project doesn't exist (that's OK)
            if "no such service" in result.stderr.lower() or "no such project" in result.stderr.lower():
                logger.info(f"Compose project {project_name} doesn't exist (already torn down)")
                teardown_succeeded = True
            else:
                logger.warning(f"Docker compose down returned {result.returncode} for {project_name}: {result.stderr}")
    except asyncio.TimeoutError:
        logger.warning(f"Docker compose down timed out for {project_name}")
    except Exception as e:
        logger.warning(f"Direct docker compose down failed for {project_name}: {type(e).__name__}")

    # Release port reservation
    try:
        async with AsyncSessionLocal() as port_session:
            await release_novnc_port(port_session, lab_id=lab_id, owner_id=lab.owner_id)
            logger.info(f"Released port reservation for lab {lab_id}")
    except Exception as e:
        logger.warning(f"Failed to release port for lab {lab_id}: {type(e).__name__}")

    # Update lab status based on teardown success
    async with AsyncSessionLocal() as update_session:
        updated_lab = await update_session.get(Lab, lab_id)
        if updated_lab:
            now = datetime.now(timezone.utc)
            if teardown_succeeded:
                updated_lab.status = LabStatus.FINISHED
                updated_lab.finished_at = now
                updated_lab.evidence_expires_at = now + timedelta(hours=24)
                await update_session.commit()
                logger.info(f"Updated lab {lab_id} status to FINISHED")
            else:
                updated_lab.status = LabStatus.FAILED
                updated_lab.finished_at = now
                await update_session.commit()
                logger.info(f"Updated lab {lab_id} status to FAILED (teardown did not confirm success)")
        else:
            logger.warning(f"Lab {lab_id} not found in database during status update")
            return False

    return teardown_succeeded


async def fail_lab_only(lab: Lab) -> None:
    """Mark a lab as FAILED without attempting teardown.

    Args:
        lab: Lab instance to mark as failed
    """
    lab_id = lab.id
    owner_short = str(lab.owner_id)[-6:]
    logger.info(f"Marking lab {lab_id} (owner=****{owner_short}) as FAILED (no teardown attempt)")

    async with AsyncSessionLocal() as update_session:
        updated_lab = await update_session.get(Lab, lab_id)
        if updated_lab:
            now = datetime.now(timezone.utc)
            updated_lab.status = LabStatus.FAILED
            updated_lab.finished_at = now
            await update_session.commit()
            logger.info(f"Updated lab {lab_id} status to FAILED")
        else:
            logger.warning(f"Lab {lab_id} not found in database during status update")


async def force_teardown_ending_labs(
    lab_id: str | None = None,
    older_than_minutes: int = 30,
    max_labs: int = 20,
    dry_run: bool = False,
    action: str = "force",
) -> None:
    """Find labs in ENDING status and force complete their teardown or mark them failed.

    Watchdog mode: detect labs stuck in ENDING older than a threshold.
    Safe under concurrency: uses skip_locked to prevent double-processing.

    Args:
        lab_id: Optional specific lab ID to process (ignores age/max filters)
        older_than_minutes: Only process labs in ENDING for longer than this (default 30)
        max_labs: Maximum number of labs to process in one run (default 20)
        dry_run: If True, only log which labs would be processed (no DB writes or runtime calls)
        action: Either "force" (force teardown) or "fail" (mark FAILED only)
    """
    async with AsyncSessionLocal() as session:
        # Build query with concurrency safety
        query = select(Lab).where(Lab.status == LabStatus.ENDING)

        if lab_id is not None:
            # Specific lab mode: ignore age and max filters
            try:
                lab_uuid = UUID(lab_id)
                query = query.where(Lab.id == lab_uuid)
            except ValueError:
                logger.error(f"Invalid lab_id format: {lab_id}")
                return
        else:
            # Watchdog mode: filter by age
            now_utc = datetime.now(timezone.utc)
            age_threshold = now_utc - timedelta(minutes=older_than_minutes)
            # Filter by updated_at which changes when status changes
            query = query.where(Lab.updated_at < age_threshold)
            query = query.order_by(Lab.updated_at.asc())
            query = query.limit(max_labs)

        # Add row-level locking with skip_locked for concurrency safety
        query = query.with_for_update(skip_locked=True)

        result = await session.execute(query)
        labs = result.scalars().all()

        if not labs:
            if lab_id:
                logger.info(f"No ENDING lab found with id {lab_id} (or locked by another process)")
            else:
                logger.info(f"No labs found in ENDING status older than {older_than_minutes} minutes")
            return

        logger.info(
            f"Found {len(labs)} lab(s) in ENDING status "
            f"(dry_run={dry_run}, action={action}, older_than={older_than_minutes}m)"
        )

        if dry_run:
            # Dry-run: only log what would be done
            for lab in labs:
                age_minutes = (datetime.now(timezone.utc) - ending_age_anchor(lab)).total_seconds() / 60
                owner_short = str(lab.owner_id)[-6:]
                logger.info(
                    f"[DRY-RUN] Would {action} lab {lab.id} "
                    f"(owner=****{owner_short}, age={age_minutes:.1f}m)"
                )
            logger.info(f"[DRY-RUN] Would process {len(labs)} labs with action={action}")
            return

        # Execute actions
        success_count = 0
        failed_count = 0

        for lab in labs:
            lab_id_str = str(lab.id)
            age_minutes = (datetime.now(timezone.utc) - ending_age_anchor(lab)).total_seconds() / 60
            owner_short = str(lab.owner_id)[-6:]

            logger.info(
                f"Processing lab {lab_id_str} (owner=****{owner_short}, "
                f"age={age_minutes:.1f}m, action={action})"
            )

            try:
                if action == "fail":
                    await fail_lab_only(lab)
                    success_count += 1
                elif action == "force":
                    succeeded = await force_teardown_lab(lab, session)
                    if succeeded:
                        success_count += 1
                    else:
                        failed_count += 1
                else:
                    logger.error(f"Unknown action: {action}")
                    failed_count += 1
            except Exception as e:
                logger.error(
                    f"Failed to process lab {lab_id_str}: {type(e).__name__}",
                    exc_info=True,
                )
                failed_count += 1

        logger.info(
            f"Completed processing {len(labs)} labs: "
            f"{success_count} succeeded, {failed_count} failed"
        )


async def main(
    lab_id: str | None = None,
    older_than_minutes: int = 30,
    max_labs: int = 20,
    dry_run: bool = False,
    action: str = "force",
) -> None:
    """Main entrypoint for the watchdog script."""
    await force_teardown_ending_labs(
        lab_id=lab_id,
        older_than_minutes=older_than_minutes,
        max_labs=max_labs,
        dry_run=dry_run,
        action=action,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "ADMIN-ONLY TOOL: Force teardown of labs stuck in ENDING status.\n"
            "This watchdog script detects labs that have been in ENDING status for too long "
            "and either forces their teardown or marks them as FAILED. "
            "Safe for concurrent execution via row-level locking (skip_locked)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--lab-id",
        type=str,
        default=None,
        help="Optional specific lab ID to process (ignores age and max-labs filters)",
    )
    parser.add_argument(
        "--older-than-minutes",
        type=int,
        default=30,
        help="Only process labs in ENDING for longer than this many minutes (default: 30)",
    )
    parser.add_argument(
        "--max-labs",
        type=int,
        default=20,
        help="Maximum number of labs to process in one run (default: 20)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview which labs would be processed without making any changes",
    )
    parser.add_argument(
        "--action",
        type=str,
        choices=["force", "fail"],
        default="force",
        help=(
            "Action to take: 'force' (force teardown and mark FINISHED/FAILED) "
            "or 'fail' (mark FAILED only without teardown attempt). Default: force"
        ),
    )

    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("ADMIN-ONLY WATCHDOG: Force teardown of labs stuck in ENDING status")
    logger.info(f"Configuration: older_than={args.older_than_minutes}m, max_labs={args.max_labs}, "
                f"dry_run={args.dry_run}, action={args.action}")
    if args.lab_id:
        logger.info(f"Single lab mode: lab_id={args.lab_id}")
    logger.info("=" * 80)

    asyncio.run(
        main(
            lab_id=args.lab_id,
            older_than_minutes=args.older_than_minutes,
            max_labs=args.max_labs,
            dry_run=args.dry_run,
            action=args.action,
        )
    )

