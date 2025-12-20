"""Firecracker resource cleanup utilities.

This module provides functions to clean up orphaned Firecracker resources
that may be left behind after backend restarts or failed teardowns.

SECURITY:
- Only cleans resources with known OctoLab prefixes (otp*, obr*, lab_*)
- Never removes resources that might belong to other systems
- Best-effort cleanup - failures are logged but don't block startup
"""

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Known prefixes for OctoLab resources
TAP_PREFIX = "otp"
BRIDGE_PREFIX = "obr"
LAB_DIR_PREFIX = "lab_"
MICROVM_BASE_DIR = Path("/var/lib/octolab/microvm")


async def cleanup_orphaned_firecracker_resources() -> dict:
    """Clean up orphaned Firecracker resources from previous backend runs.

    This should be called on backend startup to clean up resources that
    weren't properly removed (e.g., due to backend crash/restart).

    Returns:
        dict with cleanup statistics
    """
    stats = {
        "tap_interfaces_deleted": 0,
        "bridge_interfaces_deleted": 0,
        "vm_directories_deleted": 0,
        "errors": [],
    }

    logger.info("Starting orphaned Firecracker resource cleanup...")

    # 1. Clean TAP interfaces
    stats["tap_interfaces_deleted"] = _cleanup_tap_interfaces()

    # 2. Clean bridge interfaces
    stats["bridge_interfaces_deleted"] = _cleanup_bridge_interfaces()

    # 3. Clean VM directories
    stats["vm_directories_deleted"] = _cleanup_vm_directories()

    total_cleaned = (
        stats["tap_interfaces_deleted"] +
        stats["bridge_interfaces_deleted"] +
        stats["vm_directories_deleted"]
    )

    if total_cleaned > 0:
        logger.info(
            f"Orphaned resource cleanup complete: "
            f"{stats['tap_interfaces_deleted']} TAPs, "
            f"{stats['bridge_interfaces_deleted']} bridges, "
            f"{stats['vm_directories_deleted']} VM dirs"
        )
    else:
        logger.info("No orphaned Firecracker resources found")

    return stats


def _cleanup_tap_interfaces() -> int:
    """Delete orphaned TAP interfaces with otp* prefix.

    Returns:
        Number of interfaces deleted
    """
    deleted = 0
    try:
        result = subprocess.run(
            ["ip", "link", "show"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        for line in result.stdout.splitlines():
            # Format: "123: otpXXX: <FLAGS>..."
            if f": {TAP_PREFIX}" in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    tap_name = parts[1].strip().split("@")[0]
                    if tap_name.startswith(TAP_PREFIX):
                        try:
                            subprocess.run(
                                ["sudo", "ip", "link", "delete", tap_name],
                                check=False,
                                timeout=5,
                                capture_output=True,
                            )
                            deleted += 1
                            logger.debug(f"Deleted orphaned TAP: {tap_name}")
                        except Exception as e:
                            logger.warning(f"Failed to delete TAP {tap_name}: {e}")
    except Exception as e:
        logger.warning(f"Error listing TAP interfaces: {e}")

    return deleted


def _cleanup_bridge_interfaces() -> int:
    """Delete orphaned bridge interfaces with obr* prefix.

    Returns:
        Number of interfaces deleted
    """
    deleted = 0
    try:
        result = subprocess.run(
            ["ip", "link", "show"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        for line in result.stdout.splitlines():
            if f": {BRIDGE_PREFIX}" in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    br_name = parts[1].strip().split("@")[0]
                    if br_name.startswith(BRIDGE_PREFIX):
                        try:
                            subprocess.run(
                                ["sudo", "ip", "link", "delete", br_name],
                                check=False,
                                timeout=5,
                                capture_output=True,
                            )
                            deleted += 1
                            logger.debug(f"Deleted orphaned bridge: {br_name}")
                        except Exception as e:
                            logger.warning(f"Failed to delete bridge {br_name}: {e}")
    except Exception as e:
        logger.warning(f"Error listing bridge interfaces: {e}")

    return deleted


def _cleanup_vm_directories() -> int:
    """Delete orphaned VM directories under /var/lib/octolab/microvm/lab_*.

    Returns:
        Number of directories deleted
    """
    deleted = 0

    if not MICROVM_BASE_DIR.exists():
        return 0

    try:
        for item in MICROVM_BASE_DIR.iterdir():
            if item.is_dir() and item.name.startswith(LAB_DIR_PREFIX):
                try:
                    shutil.rmtree(item)
                    deleted += 1
                    logger.debug(f"Deleted orphaned VM dir: {item}")
                except Exception as e:
                    logger.warning(f"Failed to delete VM dir {item}: {e}")
    except Exception as e:
        logger.warning(f"Error listing VM directories: {e}")

    return deleted
