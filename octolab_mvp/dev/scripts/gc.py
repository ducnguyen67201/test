#!/usr/bin/env python3
"""Garbage Collection Script for OctoLab.

Cleans up:
1. Expired labs (past expires_at) - marks them ENDING for teardown worker
2. Old evidence bundles (past evidence_retention_hours)
3. Orphaned Docker volumes (optional, --include-volumes)

Usage:
    python3 dev/scripts/gc.py [--dry-run] [--include-volumes]
    make gc  # Runs with default options

Environment:
    Loads config from backend/.env and backend/.env.local

SECURITY:
- Runs with shell=False for subprocess
- Redacts all secrets from output
- Requires database connection
"""

import argparse
import asyncio
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add backend to path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# Load environment before importing app modules
try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
    load_dotenv(BACKEND_DIR / ".env.local", override=True)
except ImportError:
    pass

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import AsyncSessionLocal
from app.models.lab import Lab, LabStatus
from app.utils.redact import redact_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


EVIDENCE_BUNDLES_DIR = BACKEND_DIR / "var" / "evidence_bundles"


def run_docker(args: list[str], timeout: float = 30.0) -> tuple[bool, str, str]:
    """Run docker command with shell=False.

    Returns:
        (ok, stdout, stderr)
    """
    cmd = ["docker"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        return (result.returncode == 0, result.stdout, result.stderr)
    except subprocess.TimeoutExpired:
        return (False, "", f"Timeout after {timeout}s")
    except FileNotFoundError:
        return (False, "", "docker command not found")
    except Exception as e:
        return (False, "", str(e))


async def gc_expired_labs(session: AsyncSession, dry_run: bool = False) -> int:
    """Mark expired labs as ENDING for teardown worker.

    Returns:
        Number of labs marked for cleanup
    """
    now = datetime.now(timezone.utc)

    # Find active labs that have expired
    active_statuses = (LabStatus.PROVISIONING, LabStatus.READY)
    result = await session.execute(
        select(Lab).where(
            and_(
                Lab.status.in_(active_statuses),
                Lab.expires_at.isnot(None),
                Lab.expires_at < now,
            )
        )
    )
    expired_labs = result.scalars().all()

    if not expired_labs:
        logger.info("No expired labs found")
        return 0

    logger.info(f"Found {len(expired_labs)} expired labs")

    for lab in expired_labs:
        logger.info(f"  Lab {lab.id}: status={lab.status.value}, expired at {lab.expires_at}")
        if not dry_run:
            lab.status = LabStatus.ENDING

    if not dry_run:
        await session.commit()
        logger.info(f"Marked {len(expired_labs)} labs as ENDING")
    else:
        logger.info(f"[DRY-RUN] Would mark {len(expired_labs)} labs as ENDING")

    return len(expired_labs)


async def gc_old_evidence_bundles(dry_run: bool = False) -> int:
    """Delete evidence bundles older than retention period.

    Returns:
        Number of bundles deleted
    """
    if not EVIDENCE_BUNDLES_DIR.exists():
        logger.info(f"Evidence bundles directory does not exist: {EVIDENCE_BUNDLES_DIR}")
        return 0

    now = datetime.now(timezone.utc)
    retention_hours = settings.evidence_retention_hours
    deleted_count = 0

    for lab_dir in EVIDENCE_BUNDLES_DIR.iterdir():
        if not lab_dir.is_dir():
            continue

        for bundle_file in lab_dir.glob("*.zip"):
            # Check file modification time
            mtime = datetime.fromtimestamp(bundle_file.stat().st_mtime, tz=timezone.utc)
            age_hours = (now - mtime).total_seconds() / 3600

            if age_hours > retention_hours:
                logger.info(f"  Bundle {bundle_file.name}: age={age_hours:.1f}h (> {retention_hours}h)")
                if not dry_run:
                    bundle_file.unlink()
                    deleted_count += 1
                else:
                    deleted_count += 1

        # Remove empty lab directories
        if not dry_run and lab_dir.exists() and not any(lab_dir.iterdir()):
            lab_dir.rmdir()

    if deleted_count > 0:
        if dry_run:
            logger.info(f"[DRY-RUN] Would delete {deleted_count} old evidence bundles")
        else:
            logger.info(f"Deleted {deleted_count} old evidence bundles")
    else:
        logger.info("No old evidence bundles to delete")

    return deleted_count


def gc_orphan_volumes(dry_run: bool = False) -> int:
    """Remove orphaned OctoLab Docker volumes.

    Only removes volumes matching octolab_* pattern that don't have
    associated running containers.

    Returns:
        Number of volumes removed
    """
    # List volumes matching octolab_ pattern
    ok, stdout, stderr = run_docker([
        "volume", "ls",
        "--filter", "name=octolab_",
        "--format", "{{.Name}}"
    ])

    if not ok:
        logger.warning(f"Failed to list volumes: {redact_text(stderr)}")
        return 0

    volumes = [v.strip() for v in stdout.strip().split("\n") if v.strip()]

    if not volumes:
        logger.info("No OctoLab volumes found")
        return 0

    # Check which volumes are in use
    removed_count = 0
    for volume in volumes:
        # Check if volume is in use by any container
        ok, stdout, stderr = run_docker([
            "ps", "-a",
            "--filter", f"volume={volume}",
            "--format", "{{.ID}}"
        ])

        in_use = ok and stdout.strip()

        if not in_use:
            logger.info(f"  Orphan volume: {volume}")
            if not dry_run:
                ok, _, stderr = run_docker(["volume", "rm", volume])
                if ok:
                    removed_count += 1
                else:
                    logger.warning(f"Failed to remove volume {volume}: {redact_text(stderr)}")
            else:
                removed_count += 1

    if removed_count > 0:
        if dry_run:
            logger.info(f"[DRY-RUN] Would remove {removed_count} orphan volumes")
        else:
            logger.info(f"Removed {removed_count} orphan volumes")
    else:
        logger.info("No orphan volumes to remove")

    return removed_count


async def main():
    parser = argparse.ArgumentParser(
        description="Garbage collection for OctoLab (expired labs, old evidence)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be cleaned up without actually doing it"
    )
    parser.add_argument(
        "--include-volumes",
        action="store_true",
        help="Also clean up orphaned Docker volumes"
    )
    args = parser.parse_args()

    if args.dry_run:
        logger.info("=== DRY RUN MODE (no changes will be made) ===")

    logger.info("=" * 60)
    logger.info("OctoLab Garbage Collection")
    logger.info("=" * 60)
    logger.info(f"Evidence retention: {settings.evidence_retention_hours}h")
    logger.info(f"Lab TTL: {settings.default_lab_ttl_minutes}min")
    logger.info("")

    # GC expired labs
    logger.info("Checking for expired labs...")
    async with AsyncSessionLocal() as session:
        expired_count = await gc_expired_labs(session, dry_run=args.dry_run)

    # GC old evidence bundles
    logger.info("")
    logger.info("Checking for old evidence bundles...")
    bundle_count = await gc_old_evidence_bundles(dry_run=args.dry_run)

    # GC orphan volumes (optional)
    volume_count = 0
    if args.include_volumes:
        logger.info("")
        logger.info("Checking for orphan Docker volumes...")
        volume_count = gc_orphan_volumes(dry_run=args.dry_run)

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("Summary")
    logger.info("=" * 60)
    prefix = "[DRY-RUN] Would clean" if args.dry_run else "Cleaned"
    logger.info(f"{prefix} {expired_count} expired labs")
    logger.info(f"{prefix} {bundle_count} old evidence bundles")
    if args.include_volumes:
        logger.info(f"{prefix} {volume_count} orphan volumes")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        logger.info("Interrupted")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Error: {type(e).__name__}: {e}")
        sys.exit(1)
