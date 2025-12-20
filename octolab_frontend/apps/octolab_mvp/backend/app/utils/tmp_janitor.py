"""Startup janitor for orphaned evidence temp directories.

This module provides cleanup of `/tmp/octolab-evidence-*` directories that may
have been orphaned due to crashes, ungraceful shutdowns, or other failures.

THREAT MODEL:
- Process crashes leave temp directories behind
- Permission-restricted files from containers prevent normal deletion
- Symlinks could exist in these directories (from malicious containers)

SECURITY INVARIANTS:
- Only clean directories matching the exact prefix "octolab-evidence-"
- Use rmtree_hardened for safe deletion (handles permissions, no symlink follow)
- Log only directory count and names, never contents
- Best-effort cleanup - failures are logged but don't block startup
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from app.utils.fs import rmtree_hardened

logger = logging.getLogger(__name__)

# Prefix for evidence temp directories - must match evidence_service.py
EVIDENCE_TMPDIR_PREFIX = "octolab-evidence-"


def cleanup_orphaned_evidence_tmpdirs(
    tmp_base: Path | None = None,
    *,
    dry_run: bool = False,
) -> int:
    """
    Clean up orphaned evidence temp directories.

    Scans the system temp directory for directories matching
    `octolab-evidence-*` and removes them using hardened rmtree.

    This is intended to be called during application startup to clean up
    any temp directories left behind by previous crashes.

    SECURITY:
    - Only removes directories with exact prefix match
    - Uses rmtree_hardened for safe deletion
    - Best-effort: failures are logged but don't raise

    Args:
        tmp_base: Base temp directory to scan (default: system temp dir)
        dry_run: If True, only log what would be deleted without actually deleting

    Returns:
        Number of directories cleaned up (or would be cleaned in dry_run mode)
    """
    if tmp_base is None:
        tmp_base = Path(tempfile.gettempdir())

    if not tmp_base.exists():
        logger.debug(f"Temp directory does not exist: {tmp_base}")
        return 0

    cleaned_count = 0
    candidates = []

    try:
        # Find all matching directories
        for entry in tmp_base.iterdir():
            # Only process directories
            if not entry.is_dir():
                continue

            # Skip symlinks (security: don't follow into unexpected locations)
            if entry.is_symlink():
                continue

            # Check prefix match (exact prefix, not substring)
            if entry.name.startswith(EVIDENCE_TMPDIR_PREFIX):
                candidates.append(entry)

    except PermissionError:
        logger.warning(f"Permission denied scanning temp directory: {tmp_base.name}")
        return 0
    except Exception as e:
        logger.warning(f"Error scanning temp directory: {type(e).__name__}")
        return 0

    if not candidates:
        logger.debug("No orphaned evidence temp directories found")
        return 0

    # Log what we found (names only, never contents)
    dir_names = [d.name for d in candidates]
    logger.info(
        f"Found {len(candidates)} orphaned evidence temp director{'ies' if len(candidates) > 1 else 'y'}: "
        f"{', '.join(dir_names)}"
    )

    if dry_run:
        logger.info("Dry run mode - no directories deleted")
        return len(candidates)

    # Clean up each directory
    # Log only per-directory, not per-file within directories
    skipped_privileged = []

    for candidate in candidates:
        try:
            # Check if we can access the directory at all
            # If owned by root, we likely cannot delete it without privileges
            try:
                stat_info = candidate.stat()
                is_root_owned = stat_info.st_uid == 0
            except PermissionError:
                is_root_owned = True  # Assume root-owned if we can't stat

            if is_root_owned:
                # Skip root-owned directories - requires privileged cleanup
                skipped_privileged.append(candidate.name)
                continue

            rmtree_hardened(candidate)
            cleaned_count += 1
            logger.debug(f"Cleaned up orphaned temp directory: {candidate.name}")
        except PermissionError:
            # Root-owned subdirectory prevented cleanup
            skipped_privileged.append(candidate.name)
        except Exception as e:
            # Best-effort: log and continue (per-directory, not per-file)
            logger.warning(
                f"Failed to clean up orphaned temp directory '{candidate.name}': "
                f"{type(e).__name__}"
            )

    # Log skipped root-owned directories in one message (not spam)
    if skipped_privileged:
        logger.warning(
            f"Skipping {len(skipped_privileged)} stale evidence temp dir(s) requiring "
            f"privileged cleanup: {', '.join(skipped_privileged)}"
        )

    if cleaned_count > 0:
        logger.info(f"Cleaned up {cleaned_count} orphaned evidence temp director{'ies' if cleaned_count > 1 else 'y'}")

    return cleaned_count


async def startup_cleanup() -> None:
    """
    Async startup hook for cleaning orphaned temp directories.

    Intended to be called during FastAPI lifespan startup.
    Runs cleanup in a thread to avoid blocking the event loop.
    """
    import asyncio

    await asyncio.to_thread(cleanup_orphaned_evidence_tmpdirs)
