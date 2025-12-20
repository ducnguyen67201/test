"""Firecracker runtime status service for admin visibility.

Provides admin-only endpoints to verify Firecracker is being used and detect
runtime drift (labs marked running in DB but no firecracker process).

SECURITY:
- Admin-only access (enforced in routes)
- No secrets in output (paths are basenames only)
- subprocess.run with shell=False always
"""

import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.lab import Lab, LabStatus, RuntimeType

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class FirecrackerProcess:
    """Information about a running Firecracker process."""
    pid: int
    cmdline: str  # Redacted to basename
    lab_id: str | None = None  # Matched lab ID if found


@dataclass
class LabRuntimeStatus:
    """Status of a single lab's runtime."""
    lab_id: str
    vm_id: str | None
    firecracker_pid: int | None
    api_sock_exists: bool
    state_dir_exists: bool
    status: str  # "ok", "missing_pid", "missing_sock", "missing_state"


@dataclass
class FirecrackerStatusResponse:
    """Response for admin firecracker status endpoint."""
    generated_at: str
    firecracker_process_count: int
    running_microvm_labs: list[LabRuntimeStatus]
    drift: dict  # {"db_running_no_pid": [...], "orphan_pids": [...]}
    summary: str


def _list_firecracker_processes() -> list[FirecrackerProcess]:
    """List running firecracker processes using ps.

    SECURITY: shell=False, no user input in command
    """
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,comm,args"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            shell=False,
        )
        if result.returncode != 0:
            logger.warning(f"ps command failed: {result.stderr[:100]}")
            return []

        processes = []
        for line in result.stdout.strip().split("\n")[1:]:  # Skip header
            parts = line.split(None, 2)
            if len(parts) < 2:
                continue
            pid_str, comm = parts[0], parts[1]
            cmdline = parts[2] if len(parts) > 2 else ""

            if comm == "firecracker" or "firecracker" in cmdline:
                try:
                    pid = int(pid_str)
                    # Redact cmdline to basenames only for security
                    redacted_cmdline = _redact_cmdline(cmdline)
                    processes.append(FirecrackerProcess(pid=pid, cmdline=redacted_cmdline))
                except ValueError:
                    continue

        return processes

    except subprocess.TimeoutExpired:
        logger.warning("ps command timed out")
        return []
    except Exception as e:
        logger.warning(f"Failed to list processes: {type(e).__name__}")
        return []


def _redact_cmdline(cmdline: str) -> str:
    """Redact full paths in cmdline to basenames only.

    SECURITY: Prevents path disclosure in admin API
    """
    parts = cmdline.split()
    redacted = []
    for part in parts:
        if part.startswith("/") or part.startswith("./"):
            # Convert to basename
            redacted.append(Path(part).name)
        else:
            redacted.append(part)
    return " ".join(redacted)[:200]  # Truncate for safety


def _extract_lab_id_from_socket_path(socket_path: str) -> str | None:
    """Extract lab ID from socket path.

    Expected patterns:
    - /var/lib/octolab/microvm/<lab_id>/firecracker.sock
    - /var/lib/octolab/microvm/lab_<lab_id>/firecracker.sock
    """
    try:
        path = Path(socket_path)
        # Parent should be the lab-specific directory
        lab_dir = path.parent.name
        if lab_dir.startswith("lab_"):
            return lab_dir[4:]  # Strip "lab_" prefix
        # Try to parse as UUID directly
        if len(lab_dir) == 36 and lab_dir.count("-") == 4:
            return lab_dir
        return None
    except Exception:
        return None


def _check_socket_exists(lab_id: str) -> bool:
    """Check if Firecracker API socket exists for a lab.

    SECURITY: Path derived from server-owned lab_id only
    """
    state_dir = Path(settings.microvm_state_dir)
    socket_path = state_dir / f"lab_{lab_id}" / "firecracker.sock"
    return socket_path.exists()


def _check_state_dir_exists(lab_id: str) -> bool:
    """Check if state directory exists for a lab.

    SECURITY: Path derived from server-owned lab_id only
    """
    state_dir = Path(settings.microvm_state_dir)
    lab_state_dir = state_dir / f"lab_{lab_id}"
    return lab_state_dir.exists() and lab_state_dir.is_dir()


async def get_firecracker_status(
    db: AsyncSession,
) -> FirecrackerStatusResponse:
    """Get comprehensive Firecracker runtime status.

    Returns:
        FirecrackerStatusResponse with process counts, lab statuses, and drift detection

    SECURITY:
    - Admin-only (enforced in route)
    - No secrets in output
    - subprocess.run with shell=False
    """
    generated_at = datetime.now(timezone.utc).isoformat()

    # 1. List running Firecracker processes
    processes = _list_firecracker_processes()
    fc_pids = {p.pid for p in processes}

    # 2. Get labs that should be running with Firecracker runtime
    running_statuses = (
        LabStatus.PROVISIONING.value,
        LabStatus.READY.value,
        LabStatus.ENDING.value,
    )
    result = await db.execute(
        select(Lab).where(
            Lab.runtime == RuntimeType.FIRECRACKER.value,
            Lab.status.in_(running_statuses),
        )
    )
    running_labs = result.scalars().all()

    # 3. Check each lab's runtime status
    lab_statuses: list[LabRuntimeStatus] = []
    labs_missing_pid: list[str] = []
    matched_pids: set[int] = set()

    for lab in running_labs:
        lab_id_str = str(lab.id)

        # Get runtime_meta if present
        runtime_meta = lab.runtime_meta or {}
        vm_id = runtime_meta.get("vm_id")
        fc_pid = runtime_meta.get("firecracker_pid")

        # Check if PID is still running
        pid_running = fc_pid is not None and fc_pid in fc_pids
        if pid_running:
            matched_pids.add(fc_pid)

        # Check socket and state dir
        api_sock_exists = _check_socket_exists(lab_id_str)
        state_dir_exists = _check_state_dir_exists(lab_id_str)

        # Determine status
        if pid_running and api_sock_exists and state_dir_exists:
            status = "ok"
        elif not pid_running:
            status = "missing_pid"
            labs_missing_pid.append(lab_id_str)
        elif not api_sock_exists:
            status = "missing_sock"
        elif not state_dir_exists:
            status = "missing_state"
        else:
            status = "unknown"

        lab_statuses.append(LabRuntimeStatus(
            lab_id=lab_id_str,
            vm_id=vm_id,
            firecracker_pid=fc_pid,
            api_sock_exists=api_sock_exists,
            state_dir_exists=state_dir_exists,
            status=status,
        ))

    # 4. Detect orphan PIDs (Firecracker processes not mapped to any lab)
    orphan_pids = [p.pid for p in processes if p.pid not in matched_pids]

    # 5. Build drift info
    drift = {
        "db_running_no_pid": labs_missing_pid,
        "orphan_pids": orphan_pids,
    }

    # 6. Build summary
    ok_count = sum(1 for ls in lab_statuses if ls.status == "ok")
    total_labs = len(lab_statuses)
    drift_count = len(labs_missing_pid) + len(orphan_pids)

    if drift_count == 0 and total_labs == ok_count:
        summary = f"Firecracker runtime healthy: {len(processes)} processes, {total_labs} labs OK"
    else:
        summary = (
            f"Firecracker runtime has drift: {len(processes)} processes, "
            f"{ok_count}/{total_labs} labs OK, {len(labs_missing_pid)} missing PID, "
            f"{len(orphan_pids)} orphan PIDs"
        )

    return FirecrackerStatusResponse(
        generated_at=generated_at,
        firecracker_process_count=len(processes),
        running_microvm_labs=lab_statuses,
        drift=drift,
        summary=summary,
    )
