"""Smart lab cleanup with tiered approach.

This module implements resource-efficient cleanup for Firecracker labs:
- Tier 1: Graceful shutdown (SIGTERM, wait for clean exit)
- Tier 2: Verify critical resources are gone
- Tier 3: Targeted cleanup (kill specific stuck resources)
- Tier 4: Nuclear cleanup (destroy everything for this lab)
- Tier 5: Watchdog (background task catches orphans)

SECURITY:
- Never exposes internal paths or PIDs in API responses
- Uses validated lab IDs for all operations
- Fails closed on any uncertainty
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.firecracker_paths import (
    lab_pid_path,
    lab_state_dir,
    validate_lab_id,
)
from app.services.microvm_net_client import (
    cleanup_port_forward,
    release_vm_net,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class CleanupResult:
    """Result of a cleanup operation.

    SECURITY: Never include sensitive data like full paths or PIDs.
    """

    success: bool
    tier_used: int  # Which tier completed the cleanup (1-4)
    issues_found: list[str] = field(default_factory=list)
    issues_resolved: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for API response."""
        return {
            "success": self.success,
            "tier_used": self.tier_used,
            "issues_found": self.issues_found,
            "issues_resolved": self.issues_resolved,
            "errors": self.errors,
        }


@dataclass
class ResourceCheck:
    """Result of checking critical resources."""

    clean: bool
    issues: list[str] = field(default_factory=list)


# =============================================================================
# Helper Functions
# =============================================================================


def _get_firecracker_pid(lab_id: str) -> int | None:
    """Get Firecracker PID for a lab.

    Returns:
        PID if found, None otherwise
    """
    try:
        safe_lab_id = validate_lab_id(lab_id)
        pid_path = lab_pid_path(safe_lab_id)
        if pid_path.exists():
            pid_str = pid_path.read_text().strip()
            if pid_str.isdigit():
                return int(pid_str)
    except Exception:
        pass
    return None


def _process_exists(pid: int | None) -> bool:
    """Check if a process exists.

    Returns:
        True if process exists, False otherwise
    """
    if pid is None:
        return False
    try:
        os.kill(pid, 0)  # Signal 0 checks existence
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it
        return True


def _state_dir_exists(lab_id: str) -> bool:
    """Check if state directory exists for a lab.

    Returns:
        True if state directory exists
    """
    try:
        safe_lab_id = validate_lab_id(lab_id)
        return lab_state_dir(safe_lab_id).exists()
    except Exception:
        return False


# =============================================================================
# Tier 1: Graceful Shutdown
# =============================================================================


async def graceful_shutdown(lab_id: str, timeout: int = 10) -> bool:
    """Tier 1: Try graceful shutdown.

    Sends SIGTERM and waits for clean exit.

    Args:
        lab_id: Lab UUID string
        timeout: Maximum seconds to wait for clean exit

    Returns:
        True if process exited cleanly, False if needs escalation
    """
    safe_lab_id = validate_lab_id(lab_id)
    pid = _get_firecracker_pid(safe_lab_id)

    if pid is None:
        logger.debug(f"No PID found for lab ...{safe_lab_id[-6:]}, already gone")
        return True

    if not _process_exists(pid):
        logger.debug(f"Process {pid} for lab ...{safe_lab_id[-6:]} already gone")
        return True

    try:
        # Send SIGTERM for graceful shutdown
        logger.info(f"Sending SIGTERM to PID {pid} for lab ...{safe_lab_id[-6:]}")
        os.kill(pid, signal.SIGTERM)

        # Wait for clean exit with polling
        for i in range(timeout):
            await asyncio.sleep(1)
            if not _process_exists(pid):
                logger.info(
                    f"Lab ...{safe_lab_id[-6:]} exited gracefully after {i+1}s"
                )
                return True

        # Still running after timeout
        logger.warning(
            f"Lab ...{safe_lab_id[-6:]} didn't exit after {timeout}s SIGTERM"
        )
        return False

    except ProcessLookupError:
        # Process died between check and signal
        return True
    except PermissionError:
        logger.error(f"Permission denied signaling PID {pid}")
        return False
    except Exception as e:
        logger.error(f"Graceful shutdown error: {type(e).__name__}")
        return False


# =============================================================================
# Tier 2: Verify Critical Resources
# =============================================================================


async def verify_critical_resources(lab_id: str) -> ResourceCheck:
    """Tier 2: Quick check of critical resources.

    Checks resources that MUST be cleaned up:
    - Firecracker process
    - State directory

    Does NOT check reusable resources (kernel, base rootfs, Docker images).

    Args:
        lab_id: Lab UUID string

    Returns:
        ResourceCheck with clean=True if all resources gone
    """
    safe_lab_id = validate_lab_id(lab_id)
    issues: list[str] = []

    # Check Firecracker process
    pid = _get_firecracker_pid(safe_lab_id)
    if _process_exists(pid):
        issues.append("firecracker_process")

    # Check state directory
    if _state_dir_exists(safe_lab_id):
        issues.append("state_directory")

    return ResourceCheck(clean=len(issues) == 0, issues=issues)


# =============================================================================
# Tier 3: Targeted Cleanup
# =============================================================================


async def targeted_cleanup(lab_id: str, resource: str) -> bool:
    """Tier 3: Kill specific stuck resource.

    Args:
        lab_id: Lab UUID string
        resource: Resource identifier from verify_critical_resources

    Returns:
        True if resource was cleaned up
    """
    safe_lab_id = validate_lab_id(lab_id)

    if resource == "firecracker_process":
        pid = _get_firecracker_pid(safe_lab_id)
        if pid and _process_exists(pid):
            try:
                logger.warning(f"Force killing PID {pid} for lab ...{safe_lab_id[-6:]}")
                os.kill(pid, signal.SIGKILL)
                await asyncio.sleep(0.5)  # Brief wait for kernel cleanup
                return not _process_exists(pid)
            except ProcessLookupError:
                return True
            except PermissionError:
                logger.error(f"Permission denied killing PID {pid}")
                return False
        return True  # Already gone

    elif resource == "state_directory":
        try:
            state_dir = lab_state_dir(safe_lab_id)
            if state_dir.exists():
                logger.warning(f"Removing state dir for lab ...{safe_lab_id[-6:]}")
                shutil.rmtree(state_dir)
            return not state_dir.exists()
        except Exception as e:
            logger.error(f"State dir cleanup failed: {type(e).__name__}")
            return False

    else:
        logger.warning(f"Unknown resource type: {resource}")
        return False


async def targeted_network_cleanup(lab_id: str) -> bool:
    """Clean up network resources for a lab.

    This handles:
    - Port forwarding rules (DNAT)
    - TAP device and bridge membership

    Args:
        lab_id: Lab UUID string

    Returns:
        True if cleanup attempted
    """
    safe_lab_id = validate_lab_id(lab_id)
    success = True

    # Clean up port forwarding via netd
    try:
        await cleanup_port_forward(safe_lab_id)
        logger.info(f"Port forward cleaned for lab ...{safe_lab_id[-6:]}")
    except Exception as e:
        logger.warning(f"Port forward cleanup failed: {type(e).__name__}")
        success = False

    # Release network resources via netd
    try:
        await release_vm_net(safe_lab_id)
        logger.info(f"Network released for lab ...{safe_lab_id[-6:]}")
    except Exception as e:
        logger.warning(f"Network release failed: {type(e).__name__}")
        # Don't fail overall - network might already be released

    return success


# =============================================================================
# Tier 4: Nuclear Cleanup
# =============================================================================


async def nuclear_cleanup(lab_id: str) -> dict[str, Any]:
    """Tier 4: Last resort - destroy everything for this lab.

    Only called if targeted cleanup fails. Uses aggressive methods.

    Args:
        lab_id: Lab UUID string

    Returns:
        Dict with cleanup results

    SECURITY: This is destructive - use with caution.
    """
    safe_lab_id = validate_lab_id(lab_id)
    results = {
        "process_killed": False,
        "state_removed": False,
        "network_cleaned": False,
    }

    logger.error(f"Nuclear cleanup initiated for lab ...{safe_lab_id[-6:]}")

    # 1. Force kill process with SIGKILL
    pid = _get_firecracker_pid(safe_lab_id)
    if pid:
        try:
            os.kill(pid, signal.SIGKILL)
            await asyncio.sleep(0.5)
            results["process_killed"] = not _process_exists(pid)
        except ProcessLookupError:
            results["process_killed"] = True
        except Exception:
            pass
    else:
        results["process_killed"] = True

    # 2. Remove state directory
    try:
        state_dir = lab_state_dir(safe_lab_id)
        if state_dir.exists():
            shutil.rmtree(state_dir)
        results["state_removed"] = not state_dir.exists()
    except Exception:
        pass

    # 3. Clean up network resources
    try:
        await targeted_network_cleanup(safe_lab_id)
        results["network_cleaned"] = True
    except Exception:
        pass

    return results


# =============================================================================
# Main Cleanup Orchestrator
# =============================================================================


async def smart_cleanup(lab_id: str, graceful_timeout: int = 10) -> CleanupResult:
    """Smart cleanup: graceful → verify → targeted → nuclear.

    Implements tiered cleanup approach:
    1. Try graceful SIGTERM with timeout
    2. Verify critical resources are gone
    3. Targeted cleanup for each stuck resource
    4. Nuclear cleanup if targeted fails

    Args:
        lab_id: Lab UUID string
        graceful_timeout: Seconds to wait for graceful shutdown

    Returns:
        CleanupResult with details of what happened
    """
    safe_lab_id = validate_lab_id(lab_id)
    result = CleanupResult(success=False, tier_used=0)

    logger.info(f"Starting smart cleanup for lab ...{safe_lab_id[-6:]}")

    # Tier 1: Try graceful shutdown
    if await graceful_shutdown(safe_lab_id, timeout=graceful_timeout):
        result.tier_used = 1
        logger.info(f"Tier 1 (graceful) succeeded for lab ...{safe_lab_id[-6:]}")
    else:
        result.issues_found.append("graceful_shutdown_failed")

    # Tier 2: Verify critical resources
    verify = await verify_critical_resources(safe_lab_id)

    if verify.clean:
        # Clean up network resources even if VM is gone
        await targeted_network_cleanup(safe_lab_id)
        result.success = True
        if result.tier_used == 0:
            result.tier_used = 2
        logger.info(f"Lab ...{safe_lab_id[-6:]} cleanup complete (tier {result.tier_used})")
        return result

    result.issues_found.extend(verify.issues)

    # Tier 3: Targeted cleanup for each stuck resource
    for resource in verify.issues:
        logger.warning(f"Tier 3: Targeted cleanup of {resource} for lab ...{safe_lab_id[-6:]}")
        if await targeted_cleanup(safe_lab_id, resource):
            result.issues_resolved.append(resource)
        else:
            result.errors.append(f"targeted_cleanup_failed:{resource}")

    # Re-verify after targeted cleanup
    verify = await verify_critical_resources(safe_lab_id)

    if verify.clean:
        await targeted_network_cleanup(safe_lab_id)
        result.success = True
        result.tier_used = 3
        logger.info(f"Tier 3 (targeted) succeeded for lab ...{safe_lab_id[-6:]}")
        return result

    # Tier 4: Nuclear - something is really stuck
    logger.error(f"Tier 4 (nuclear) required for lab ...{safe_lab_id[-6:]}")
    nuclear_result = await nuclear_cleanup(safe_lab_id)
    result.tier_used = 4

    # Final verification
    verify = await verify_critical_resources(safe_lab_id)
    result.success = verify.clean

    if result.success:
        result.issues_resolved.extend(verify.issues)
        logger.info(f"Tier 4 (nuclear) succeeded for lab ...{safe_lab_id[-6:]}")
    else:
        result.errors.extend([f"nuclear_failed:{issue}" for issue in verify.issues])
        logger.error(f"Nuclear cleanup FAILED for lab ...{safe_lab_id[-6:]}: {verify.issues}")

    return result


# =============================================================================
# Tier 5: Watchdog (Background Orphan Cleanup)
# =============================================================================


async def find_orphaned_labs() -> list[str]:
    """Find labs that have resources but shouldn't.

    Checks for:
    - State directories with no matching active lab
    - Firecracker processes for terminated labs

    Returns:
        List of orphaned lab IDs
    """
    # Import here to avoid circular imports and allow module to load without settings
    from app.config import settings

    orphans: list[str] = []
    state_root = Path(settings.microvm_state_dir)

    if not state_root.exists():
        return orphans

    # Import here to avoid circular imports
    from app.db import AsyncSessionLocal
    from app.models.lab import Lab, LabStatus
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        for item in state_root.iterdir():
            if not item.is_dir() or not item.name.startswith("lab_"):
                continue

            # Extract lab ID from directory name
            lab_id = item.name.replace("lab_", "")

            # Check if lab exists and is in active state
            result = await session.execute(
                select(Lab).where(Lab.id == lab_id)
            )
            lab = result.scalar_one_or_none()

            if lab is None:
                # Lab doesn't exist in DB - orphan
                orphans.append(lab_id)
            elif lab.status in (LabStatus.FINISHED, LabStatus.FAILED):
                # Lab is terminated but resources exist - orphan
                orphans.append(lab_id)

    return orphans


async def watchdog_cleanup() -> dict[str, Any]:
    """Tier 5: Background watchdog cleanup.

    Runs periodically to catch orphans from crashes/restarts.

    Returns:
        Dict with cleanup results
    """
    logger.info("Watchdog cleanup starting")

    results = {
        "orphans_found": 0,
        "orphans_cleaned": 0,
        "errors": [],
    }

    try:
        orphans = await find_orphaned_labs()
        results["orphans_found"] = len(orphans)

        for lab_id in orphans:
            logger.warning(f"Watchdog: Cleaning orphan lab ...{lab_id[-6:]}")
            try:
                cleanup_result = await smart_cleanup(lab_id)
                if cleanup_result.success:
                    results["orphans_cleaned"] += 1
                else:
                    results["errors"].append(f"cleanup_failed:{lab_id[-6:]}")
            except Exception as e:
                results["errors"].append(f"exception:{lab_id[-6:]}:{type(e).__name__}")

        logger.info(
            f"Watchdog cleanup complete: "
            f"found={results['orphans_found']}, "
            f"cleaned={results['orphans_cleaned']}"
        )

    except Exception as e:
        logger.error(f"Watchdog cleanup failed: {type(e).__name__}")
        results["errors"].append(f"watchdog_error:{type(e).__name__}")

    return results


# =============================================================================
# Orphaned NAT Rule Cleanup
# =============================================================================


async def cleanup_orphaned_nat_rules() -> dict[str, Any]:
    """Clean up NAT rules that don't have matching active labs.

    Returns:
        Dict with cleanup results
    """
    import subprocess

    results = {
        "rules_found": 0,
        "rules_cleaned": 0,
        "errors": [],
    }

    # Import here to avoid circular imports
    from app.db import AsyncSessionLocal
    from app.models.lab import Lab, LabStatus
    from sqlalchemy import select

    try:
        # Get current NAT rules
        proc = subprocess.run(
            ["sudo", "iptables", "-t", "nat", "-L", "PREROUTING", "-n", "--line-numbers"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if proc.returncode != 0:
            results["errors"].append("iptables_list_failed")
            return results

        # Parse rules and find octolab ones
        rules_to_delete: list[tuple[int, str]] = []  # (line_num, lab_id)

        async with AsyncSessionLocal() as session:
            for line in proc.stdout.strip().split("\n"):
                if "octolab_" not in line:
                    continue

                results["rules_found"] += 1

                # Extract line number and lab ID
                parts = line.split()
                if len(parts) < 2:
                    continue

                line_num = int(parts[0])

                # Find lab ID in comment
                for part in parts:
                    if part.startswith("octolab_"):
                        lab_id_short = part.replace("octolab_", "")

                        # Check if this lab is active
                        result = await session.execute(
                            select(Lab).where(
                                Lab.id.like(f"%{lab_id_short}%"),
                                Lab.status.in_([
                                    LabStatus.PROVISIONING,
                                    LabStatus.READY,
                                    LabStatus.DEGRADED,
                                ])
                            )
                        )
                        lab = result.scalar_one_or_none()

                        if lab is None:
                            rules_to_delete.append((line_num, lab_id_short))
                        break

        # Delete orphaned rules (in reverse order to preserve line numbers)
        for line_num, lab_id_short in sorted(rules_to_delete, reverse=True):
            try:
                subprocess.run(
                    ["sudo", "iptables", "-t", "nat", "-D", "PREROUTING", str(line_num)],
                    check=True,
                    timeout=5,
                )
                results["rules_cleaned"] += 1
                logger.info(f"Cleaned orphaned NAT rule for lab ...{lab_id_short}")
            except Exception as e:
                results["errors"].append(f"delete_failed:{lab_id_short}:{type(e).__name__}")

    except Exception as e:
        results["errors"].append(f"cleanup_error:{type(e).__name__}")

    return results
