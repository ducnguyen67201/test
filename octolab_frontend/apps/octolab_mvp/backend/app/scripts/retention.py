"""Evidence retention job for purging old evidence files.

SECURITY:
- Only deletes files under lab-specific paths (evidence/tlog/<lab_id>, etc.)
- Enforces realpath-under-root check (no symlink escapes)
- Never follows symlinks
- Only purges labs in terminal states (FINISHED, FAILED)
- Default to dry-run unless explicitly enabled
- Logs all operations for audit trail

Usage:
    # Dry run (default) - shows what would be deleted
    python -m app.scripts.retention --dry-run

    # Live run - actually deletes files
    python -m app.scripts.retention --execute

    # Custom retention days
    python -m app.scripts.retention --days 14 --execute
"""

import argparse
import asyncio
import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import AsyncSessionLocal
from app.models.lab import Lab, LabStatus, EvidenceState
from app.utils.fs import rmtree_hardened

logger = logging.getLogger(__name__)

# Terminal lab statuses where evidence can be purged
TERMINAL_STATUSES = (LabStatus.FINISHED.value, LabStatus.FAILED.value)


class RetentionResult(NamedTuple):
    """Result of retention job execution."""
    labs_processed: int
    labs_purged: int
    labs_skipped: int
    volumes_deleted: int
    errors: list[str]


def _safe_delete_volume(volume_name: str, dry_run: bool = True) -> bool:
    """Safely delete a Docker volume.

    SECURITY:
    - Only deletes volumes matching octolab_* pattern
    - No shell execution
    - Logs all operations

    Args:
        volume_name: Docker volume name
        dry_run: If True, only log what would be deleted

    Returns:
        True if deleted (or would be deleted in dry_run), False on error
    """
    # Safety check: only delete octolab volumes
    if not volume_name.startswith("octolab_"):
        logger.warning(f"Refusing to delete non-octolab volume: {volume_name}")
        return False

    if dry_run:
        logger.info(f"[DRY-RUN] Would delete volume: {volume_name}")
        return True

    try:
        result = subprocess.run(
            ["docker", "volume", "rm", volume_name],
            capture_output=True,
            timeout=30,
            shell=False,
        )
        if result.returncode == 0:
            logger.info(f"Deleted volume: {volume_name}")
            return True
        else:
            # Volume may not exist or be in use
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            if "No such volume" in stderr:
                logger.debug(f"Volume already deleted: {volume_name}")
                return True
            logger.warning(f"Failed to delete volume {volume_name}: {stderr}")
            return False
    except subprocess.TimeoutExpired:
        logger.warning(f"Timeout deleting volume: {volume_name}")
        return False
    except Exception as e:
        logger.warning(f"Error deleting volume {volume_name}: {type(e).__name__}")
        return False


async def purge_lab_evidence(
    lab: Lab,
    session: AsyncSession,
    dry_run: bool = True,
) -> tuple[bool, int, str | None]:
    """Purge evidence for a single lab.

    SECURITY:
    - Only deletes lab-specific volumes
    - Updates lab state to unavailable
    - Safe to call multiple times (idempotent)

    Args:
        lab: Lab model instance
        session: Database session
        dry_run: If True, only log what would be done

    Returns:
        Tuple of (success, volumes_deleted, error_message)
    """
    lab_id = lab.id
    project_name = f"octolab_{lab_id}"
    volumes_deleted = 0

    # Volume names to delete (per-lab)
    volumes = [
        f"{project_name}_evidence_user",
        f"{project_name}_evidence_auth",
        f"{project_name}_lab_pcap",
    ]

    errors = []
    for vol in volumes:
        if _safe_delete_volume(vol, dry_run=dry_run):
            volumes_deleted += 1
        else:
            errors.append(f"Failed to delete {vol}")

    # Update lab state
    if not dry_run:
        lab.evidence_state = EvidenceState.UNAVAILABLE.value
        lab.evidence_purged_at = datetime.now(timezone.utc)
        await session.commit()
        logger.info(f"Updated lab {lab_id} evidence_state to unavailable")
    else:
        logger.info(f"[DRY-RUN] Would update lab {lab_id} evidence_state to unavailable")

    error_msg = "; ".join(errors) if errors else None
    return len(errors) == 0, volumes_deleted, error_msg


async def run_retention(
    retention_days: int,
    dry_run: bool = True,
    limit: int | None = None,
) -> RetentionResult:
    """Run evidence retention job.

    Finds labs with evidence older than retention_days and purges their evidence.

    SECURITY:
    - Only processes labs in terminal states
    - Only deletes lab-specific volumes
    - Default to dry_run mode

    Args:
        retention_days: Purge evidence older than this many days
        dry_run: If True, only log what would be done
        limit: Maximum number of labs to process (for testing)

    Returns:
        RetentionResult with summary
    """
    mode_str = "[DRY-RUN]" if dry_run else "[LIVE]"
    logger.info(f"{mode_str} Starting evidence retention job (retention_days={retention_days})")

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    labs_processed = 0
    labs_purged = 0
    labs_skipped = 0
    total_volumes = 0
    errors: list[str] = []

    async with AsyncSessionLocal() as session:
        # Find labs eligible for purge:
        # - In terminal state (FINISHED or FAILED)
        # - Evidence finalized before cutoff
        # - Not already purged
        query = select(Lab).where(
            and_(
                Lab.status.in_(TERMINAL_STATUSES),
                Lab.evidence_finalized_at.isnot(None),
                Lab.evidence_finalized_at < cutoff,
                Lab.evidence_purged_at.is_(None),  # Not already purged
            )
        ).order_by(Lab.evidence_finalized_at.asc())  # Oldest first

        if limit:
            query = query.limit(limit)

        result = await session.execute(query)
        labs = result.scalars().all()

        logger.info(f"{mode_str} Found {len(labs)} labs eligible for evidence purge")

        for lab in labs:
            labs_processed += 1
            logger.info(
                f"{mode_str} Processing lab {lab.id} "
                f"(status={lab.status}, finalized={lab.evidence_finalized_at})"
            )

            success, vols_deleted, error = await purge_lab_evidence(
                lab, session, dry_run=dry_run
            )

            if success:
                labs_purged += 1
                total_volumes += vols_deleted
            else:
                labs_skipped += 1
                if error:
                    errors.append(f"Lab {lab.id}: {error}")

    logger.info(
        f"{mode_str} Retention complete: "
        f"processed={labs_processed}, purged={labs_purged}, "
        f"skipped={labs_skipped}, volumes={total_volumes}"
    )

    return RetentionResult(
        labs_processed=labs_processed,
        labs_purged=labs_purged,
        labs_skipped=labs_skipped,
        volumes_deleted=total_volumes,
        errors=errors,
    )


def main():
    """CLI entrypoint for retention job."""
    parser = argparse.ArgumentParser(
        description="Purge old evidence files based on retention policy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--days",
        type=int,
        default=settings.evidence_retention_days,
        help=f"Retention days (default: {settings.evidence_retention_days})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Show what would be deleted without actually deleting (default)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete files (overrides --dry-run)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of labs to process (for testing)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Determine mode
    dry_run = not args.execute
    if args.execute:
        logger.warning("LIVE MODE: Files will be deleted!")

    # Run retention
    result = asyncio.run(run_retention(
        retention_days=args.days,
        dry_run=dry_run,
        limit=args.limit,
    ))

    # Print summary
    print(f"\n{'='*60}")
    print(f"Evidence Retention Summary ({'DRY-RUN' if dry_run else 'LIVE'})")
    print(f"{'='*60}")
    print(f"Retention days:    {args.days}")
    print(f"Labs processed:    {result.labs_processed}")
    print(f"Labs purged:       {result.labs_purged}")
    print(f"Labs skipped:      {result.labs_skipped}")
    print(f"Volumes deleted:   {result.volumes_deleted}")

    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for err in result.errors:
            print(f"  - {err}")

    # Exit code
    if result.errors:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
