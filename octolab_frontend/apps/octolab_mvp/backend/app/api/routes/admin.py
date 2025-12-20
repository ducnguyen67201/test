"""Admin-only endpoints for maintenance and recovery operations.

SECURITY:
- All endpoints require admin authorization via email allowlist
- Never trust client-supplied identifiers
- All Docker operations use shell=False
- Refuse destructive operations if any OctoLab containers are running
- Stop operations bound to scan_id (never accept arbitrary project lists)
"""

import logging
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.config import settings
from app.models.lab import Lab, LabStatus
from app.models.user import User
from app.runtime import _resolve_compose_path
from app.services.docker_net import (
    AdminCleanupResult,
    AttachedContainerInfo,
    CleanupMode,
    ContainerInfo,
    ExtendedCleanupResult,
    NetworkLeakInfo,
    NetworkLeaksResult,
    RuntimeProjectClassification,
    RuntimeLabProject,
    RuntimeDriftResult,
    SkippedNetworkSample,
    StopLabsResult,
    ProjectStopResult,
    VerifiedStopLabsResult,
    admin_cleanup_octolab_resources,
    extended_network_cleanup,
    list_all_octolab_networks,
    get_network_counts,
    get_running_container_status,
    list_running_lab_containers,
    scan_network_leaks,
    scan_running_lab_projects,
    extract_lab_id_from_project,
    stop_lab_projects_batch,
    stop_lab_project,
    stop_project_verified,
    stop_projects_verified_batch,
    cleanup_project_networks,
    is_lab_project,
)
from app.services.scan_cache import get_scan_cache

logger = logging.getLogger(__name__)

# =============================================================================
# Helper Functions for netd diagnostics
# =============================================================================

# Maximum lines of netd log to include in smoke failure response
MAX_NETD_LOG_LINES = 30


def _redact_log_content(content: str) -> str:
    """Redact sensitive information from log content.

    SECURITY: Never expose secrets in API responses.
    """
    import re

    # Redact patterns like PASSWORD=..., SECRET=..., TOKEN=..., KEY=...
    content = re.sub(
        r"(PASSWORD|SECRET|TOKEN|KEY|PRIVATE)=[^\s]*",
        r"\1=***REDACTED***",
        content,
        flags=re.IGNORECASE,
    )
    # Redact DATABASE_URL with credentials
    content = re.sub(
        r"(postgres|postgresql|mysql)://[^@]+@",
        r"\1://***:***@",
        content,
        flags=re.IGNORECASE,
    )
    # Redact Bearer/Basic tokens
    content = re.sub(
        r"(Bearer|Basic) [A-Za-z0-9+/=_-]+",
        r"\1 ***REDACTED***",
        content,
        flags=re.IGNORECASE,
    )
    return content


def _get_netd_log_snippet(max_lines: int = MAX_NETD_LOG_LINES) -> str | None:
    """Get last N lines of netd log file (redacted).

    SECURITY:
    - Fixed log paths only (no user input)
    - Content is redacted before returning
    - Returns None if log not found

    Returns:
        Redacted log snippet or None
    """
    from pathlib import Path

    # Check both possible log locations (primary and fallback)
    log_paths = [
        Path("/var/log/octolab/microvm-netd.log"),
        Path("/run/octolab/microvm-netd.log"),
        Path("/var/lib/octolab/microvm/microvm-netd.log"),
    ]

    for log_path in log_paths:
        if log_path.exists() and log_path.is_file():
            try:
                # Read last N lines (read file, split, take tail)
                content = log_path.read_text(errors="replace")
                lines = content.strip().split("\n")
                tail_lines = lines[-max_lines:] if len(lines) > max_lines else lines
                snippet = "\n".join(tail_lines)
                return _redact_log_content(snippet)
            except (OSError, PermissionError):
                continue

    return None

# =============================================================================
# Admin Authorization
# =============================================================================


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    """Dependency to verify user is an admin.

    SECURITY:
    - Recomputes admin status from allowlist on each request (instant revoke)
    - Never trusts client claims or JWT is_admin (deny-by-default)
    - Checks user.email against settings.admin_emails allowlist

    Raises:
        HTTPException: 403 if user is not an admin
    """
    admin_emails = settings.admin_emails  # Use Settings property (parsed set)

    if not admin_emails:
        logger.warning("Admin operation attempted but OCTOLAB_ADMIN_EMAILS is not configured")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access not configured. Set OCTOLAB_ADMIN_EMAILS environment variable.",
        )

    email = (user.email or "").strip().lower()
    if email not in admin_emails:
        logger.warning(f"Admin operation denied for non-admin user: {user.email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )

    return user


# Router with admin authorization applied to ALL routes (deny-by-default)
router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


# =============================================================================
# Schemas
# =============================================================================


class CleanupNetworksRequest(BaseModel):
    """Request body for network cleanup operation."""

    confirm: bool = Field(
        False,
        description="Must be true to execute cleanup. Safety guard.",
    )
    remove_stopped_containers: bool = Field(
        True,
        description="Whether to also remove stopped octolab_ containers.",
    )


class CleanupNetworksResponse(BaseModel):
    """Response from network cleanup operation."""

    success: bool
    networks_found: int
    networks_removed: int
    networks_skipped_in_use: int
    containers_found: int
    containers_removed: int
    errors: list[str]
    message: str


class ContainerDebugInfo(BaseModel):
    """Debug info for a container (admin only)."""

    name: str
    project: str


# =============================================================================
# Network Leak Inspection Schemas
# =============================================================================


class AttachedContainerSample(BaseModel):
    """Sample container attached to a network."""

    container: str
    state: Literal["running", "exited", "unknown"]
    project: str | None


class NetworkLeakInfoResponse(BaseModel):
    """Information about a single network for leak inspection."""

    network: str
    attached_containers: int
    attached_running: int
    attached_exited: int
    lab_attached: int
    nonlab_attached: int
    blocked_by_nonlab: bool
    sample: list[AttachedContainerSample]


class NetworkLeaksResponse(BaseModel):
    """Response from network leak inspection."""

    total_candidates: int
    detached: int
    in_use: int
    blocked_by_nonlab: int
    networks: list[NetworkLeakInfoResponse]


# =============================================================================
# Extended Cleanup Schemas
# =============================================================================


class ExtendedCleanupMode(str, Enum):
    """Mode for extended network cleanup."""

    NETWORKS_ONLY = "networks_only"
    REMOVE_EXITED_LAB_CONTAINERS_THEN_NETWORKS = "remove_exited_lab_containers_then_networks"


CLEANUP_CONFIRM_PHRASE = "DELETE OCTOLAB NETWORKS"


class ExtendedCleanupRequest(BaseModel):
    """Request for extended network cleanup with mode selection."""

    mode: ExtendedCleanupMode = Field(
        default=ExtendedCleanupMode.NETWORKS_ONLY,
        description="Cleanup mode: networks_only (safe) or remove_exited_lab_containers_then_networks (more aggressive)",
    )
    confirm: bool = Field(
        False,
        description="Must be true to execute cleanup.",
    )
    confirm_phrase: str = Field(
        "",
        description=f"Must be '{CLEANUP_CONFIRM_PHRASE}' to execute cleanup.",
    )
    debug: bool = Field(
        False,
        description="If true, include sample info for skipped networks.",
    )


class SkippedNetworkSampleResponse(BaseModel):
    """Sample info for a skipped network."""

    network: str
    reason: str
    sample: list[AttachedContainerSample]


class ExtendedCleanupDebug(BaseModel):
    """Debug info for extended cleanup."""

    skipped_samples: list[SkippedNetworkSampleResponse]


class ExtendedCleanupResponse(BaseModel):
    """Response from extended network cleanup."""

    mode: str
    networks_found: int
    networks_removed: int
    networks_failed: int
    networks_skipped_in_use_running: int
    networks_skipped_in_use_exited: int
    networks_skipped_blocked_nonlab: int
    containers_removed: int
    message: str
    debug: ExtendedCleanupDebug | None = None


class NetworkStatusResponse(BaseModel):
    """Response from network status check."""

    total_networks: int
    octolab_networks: int
    # Corrected lab-only counts (using compose project labels)
    running_lab_projects: int
    running_lab_containers: int
    running_nonlab_containers: int
    running_total_containers: int
    hint: str
    # Debug sample (admin-only, max 10)
    debug_sample: list[ContainerDebugInfo] = []


# =============================================================================
# Runtime Drift Schemas
# =============================================================================


class RuntimeProjectInfo(BaseModel):
    """Information about a running lab project."""

    project: str
    lab_id: str
    classification: Literal["tracked", "drifted", "orphaned"]
    db_status: str | None = None
    container_count: int = 0
    sample_containers: list[str] = []


class RuntimeDriftDebugSample(BaseModel):
    """Debug sample for runtime drift."""

    project: str
    container: str
    db_status: str | None = None


class RuntimeDriftResponse(BaseModel):
    """Response from runtime drift scan.

    Includes scan_id which must be passed to stop-labs to ensure
    operations are bound to a specific, recent scan.
    """

    scan_id: str  # UUID for this scan, required for stop-labs
    generated_at: str  # ISO8601 timestamp of scan generation
    running_lab_projects_total: int
    running_lab_containers_total: int
    tracked_running_projects: int
    drifted_running_projects: int
    orphaned_running_projects: int
    projects: list[RuntimeProjectInfo] = []
    debug_sample: list[RuntimeDriftDebugSample] = []


class StopLabsMode(str, Enum):
    """Mode for stop-labs operation."""

    ORPHANED_ONLY = "orphaned_only"
    DRIFTED_ONLY = "drifted_only"
    TRACKED_ONLY = "tracked_only"
    ALL_RUNNING = "all_running"


class ProjectStopResultInfo(BaseModel):
    """Per-project result with verification data."""

    project: str
    pre_running: int = 0  # Containers before any action
    down_rc: int | None = None  # compose down return code
    remaining_after_down: int = 0  # Containers after compose down
    rm_rc: int | None = None  # docker rm -f return code (if used)
    remaining_final: int = 0  # Containers after all attempts
    networks_removed: int = 0
    verified_stopped: bool = False  # True only if remaining_final == 0
    error: str | None = None


class StopLabsResponse(BaseModel):
    """Response from stop-labs operation with verification.

    All counts are verified via docker queries, not assumed from exit codes.
    projects_stopped only increments when remaining_final == 0.

    before_* values come from the cached scan (scan_id).
    after_* values are from a fresh runtime query after execution.
    """

    scan_id: str  # The scan this operation was bound to
    mode: str  # The mode that was used
    targets_requested: int  # Number of projects targeted based on mode
    targets_found: int  # Same as requested for clarity
    before_projects: int  # Running lab projects from scan (before)
    before_containers: int  # Running lab containers from scan (before)
    projects_stopped: int  # Verified: remaining_final == 0
    projects_failed: int  # Verified: remaining_final > 0
    containers_force_removed: int = 0  # Containers removed via rm -f fallback
    networks_removed: int
    networks_failed: int
    after_projects: int  # Running lab projects after execution (fresh query)
    after_containers: int  # Running lab containers after execution (fresh query)
    errors: list[str] = []
    results: list[ProjectStopResultInfo] = []  # Per-project details (capped)
    message: str


class StopLabsRequest(BaseModel):
    """Request body for stop-labs operation.

    SECURITY: scan_id binds this operation to a specific recent scan.
    We never accept arbitrary project lists from the client.
    """

    scan_id: str = Field(
        ...,
        description="scan_id from a recent runtime-drift response. Required to bind stop to a specific scan.",
    )
    mode: StopLabsMode = Field(
        StopLabsMode.ORPHANED_ONLY,
        description=(
            "Which projects to stop: orphaned_only (no DB row), "
            "drifted_only (DB says stopped), tracked_only (DB says running), "
            "all_running (all lab projects)"
        ),
    )
    confirm: bool = Field(
        False,
        description="Must be true to execute. Safety guard.",
    )
    confirm_phrase: str = Field(
        "",
        description="Must be exactly 'STOP RUNNING LABS' to execute. Safety guard.",
    )
    debug: bool = Field(
        False,
        description="If true, include all per-project results; otherwise cap to 20 or show failures only.",
    )


class StopProjectRequest(BaseModel):
    """Request body for per-project stop operation."""

    project: str = Field(
        ...,
        description="Project name to stop (must match octolab_<uuid> pattern)",
    )
    confirm: bool = Field(
        False,
        description="Must be true to execute. Safety guard.",
    )


class StopProjectResponse(BaseModel):
    """Response from per-project stop operation with verification.

    stopped is True only if remaining_final == 0 (verified).
    """

    project: str
    pre_running: int = 0  # Containers before any action
    down_rc: int | None = None  # compose down return code
    remaining_after_down: int = 0  # Containers after compose down
    rm_rc: int | None = None  # docker rm -f return code (if used)
    remaining_final: int = 0  # Containers after all attempts
    stopped: bool  # True only if remaining_final == 0 (verified)
    networks_removed: int
    error: str | None = None


# =============================================================================
# Endpoints
# =============================================================================


@router.get(
    "/maintenance/network-status",
    response_model=NetworkStatusResponse,
    summary="Get OctoLab network status",
    description="Check current network counts and running containers. Admin only.",
)
async def get_network_status(
    admin: Annotated[User, Depends(get_current_user)],
) -> NetworkStatusResponse:
    """Get current OctoLab network and container status.

    Returns counts of networks and running containers for monitoring.
    Uses compose project labels to accurately distinguish lab containers
    (octolab_<uuid>) from infrastructure containers (guacamole, postgres, etc.).
    """
    logger.info(f"Admin {admin.email} checking network status")

    # Get network counts
    net_counts = get_network_counts(timeout=10.0)

    # Get running container status with lab/non-lab partitioning
    container_status = get_running_container_status(timeout=10.0)

    # Build debug sample (max 10 lab containers)
    debug_sample = [
        ContainerDebugInfo(name=entry.name, project=entry.project)
        for entry in container_status.lab_entries[:10]
    ]

    return NetworkStatusResponse(
        total_networks=net_counts.total_count,
        octolab_networks=net_counts.octolab_count,
        running_lab_projects=container_status.running_lab_projects,
        running_lab_containers=container_status.running_lab_containers,
        running_nonlab_containers=container_status.running_nonlab_containers,
        running_total_containers=container_status.running_total_containers,
        hint=net_counts.hint or "Network counts within normal range.",
        debug_sample=debug_sample,
    )


@router.post(
    "/maintenance/cleanup-networks",
    response_model=CleanupNetworksResponse,
    summary="Clean up leaked OctoLab networks",
    description=(
        "Remove leaked OctoLab networks to recover from IPAM exhaustion. "
        "REFUSES if any OctoLab containers are running. Admin only."
    ),
)
async def cleanup_networks(
    request: CleanupNetworksRequest,
    admin: Annotated[User, Depends(get_current_user)],
    x_confirm: Annotated[str | None, Header(alias="X-Confirm")] = None,
) -> CleanupNetworksResponse:
    """Admin-only cleanup of leaked OctoLab networks.

    This endpoint removes all OctoLab networks (octolab_<uuid>_lab_net and
    octolab_<uuid>_egress_net) that have no attached containers.

    SECURITY:
    - Requires admin authorization
    - Requires confirm=true in body OR X-Confirm: true header
    - Refuses if any OctoLab containers are RUNNING
    - Only removes networks matching strict lab pattern
    - Never runs docker network prune or system prune

    This is the recovery operation for "all predefined address pools have been
    fully subnetted" errors. Removing networks frees their subnets for reuse.
    """
    # Verify confirmation
    confirmed = request.confirm or (x_confirm and x_confirm.lower() == "true")
    if not confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation required. Set confirm=true in body or X-Confirm: true header.",
        )

    # Check for running LAB containers BEFORE cleanup (using label-based detection)
    # Only refuse if actual lab containers are running, not infrastructure
    container_status = get_running_container_status(timeout=10.0)
    if container_status.running_lab_containers > 0:
        logger.warning(
            f"Admin {admin.email} cleanup REFUSED: "
            f"{container_status.running_lab_containers} running lab containers "
            f"in {container_status.running_lab_projects} projects"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cleanup while {container_status.running_lab_containers} lab containers are running "
            f"(across {container_status.running_lab_projects} lab projects). "
            f"Stop or delete active labs first.",
        )

    logger.info(
        f"Admin {admin.email} starting network cleanup "
        f"(remove_stopped_containers={request.remove_stopped_containers})"
    )

    # Perform cleanup
    result: AdminCleanupResult = admin_cleanup_octolab_resources(
        remove_stopped_containers=request.remove_stopped_containers,
        timeout=30.0,
    )

    # Build response message
    if result.errors:
        message = f"Cleanup completed with {len(result.errors)} errors."
        success = result.networks_removed > 0 or result.containers_removed > 0
    else:
        message = (
            f"Cleanup successful. Removed {result.networks_removed} networks "
            f"and {result.containers_removed} containers."
        )
        success = True

    logger.info(
        f"Admin {admin.email} cleanup complete: "
        f"networks_removed={result.networks_removed}, "
        f"containers_removed={result.containers_removed}, "
        f"errors={len(result.errors)}"
    )

    return CleanupNetworksResponse(
        success=success,
        networks_found=result.networks_found,
        networks_removed=result.networks_removed,
        networks_skipped_in_use=result.networks_skipped_in_use,
        containers_found=result.containers_found,
        containers_removed=result.containers_removed,
        errors=result.errors,
        message=message,
    )


# =============================================================================
# Network Leak Inspection and Extended Cleanup Endpoints
# =============================================================================


@router.get(
    "/maintenance/network-leaks",
    response_model=NetworkLeaksResponse,
    summary="Inspect network leaks to see WHY networks are in use",
    description=(
        "Shows attached containers for each lab network, classified by state "
        "(running/exited) and type (lab/nonlab). Admin only."
    ),
)
async def inspect_network_leaks(
    admin: Annotated[User, Depends(get_current_user)],
    debug: bool = Query(False, description="If true, include more detail"),
    limit: int = Query(50, ge=1, le=100, description="Max networks to return"),
) -> NetworkLeaksResponse:
    """Admin-only network leak inspection.

    This endpoint shows WHY networks are "in use" by listing attached containers
    and classifying them by state (running/exited) and type (lab/nonlab).

    Use this to understand why cleanup is skipping networks before choosing
    a cleanup mode.

    SECURITY:
    - Admin only
    - Only inspects lab networks (octolab_<uuid>_* pattern)
    - Bounded response (capped to limit)
    - No secrets returned
    """
    logger.info(f"Admin {admin.email} inspecting network leaks (limit={limit})")

    # Scan networks and classify attached containers
    result = scan_network_leaks(limit=limit, timeout=30.0)

    # Convert to response model
    networks_response: list[NetworkLeakInfoResponse] = []
    for net_info in result.networks:
        sample: list[AttachedContainerSample] = []
        for c in net_info.sample:
            sample.append(AttachedContainerSample(
                container=c.name,
                state=c.state,  # type: ignore
                project=c.project,
            ))

        networks_response.append(NetworkLeakInfoResponse(
            network=net_info.network,
            attached_containers=net_info.attached_containers,
            attached_running=net_info.attached_running,
            attached_exited=net_info.attached_exited,
            lab_attached=net_info.lab_attached,
            nonlab_attached=net_info.nonlab_attached,
            blocked_by_nonlab=net_info.blocked_by_nonlab,
            sample=sample,
        ))

    logger.info(
        f"Admin {admin.email} network leak inspection: "
        f"total={result.total_candidates}, detached={result.detached}, "
        f"in_use={result.in_use}, blocked_by_nonlab={result.blocked_by_nonlab}"
    )

    return NetworkLeaksResponse(
        total_candidates=result.total_candidates,
        detached=result.detached,
        in_use=result.in_use,
        blocked_by_nonlab=result.blocked_by_nonlab,
        networks=networks_response,
    )


@router.post(
    "/maintenance/cleanup-networks-v2",
    response_model=ExtendedCleanupResponse,
    summary="Extended network cleanup with mode selection",
    description=(
        "Cleanup networks with explicit mode: networks_only (safe) or "
        "remove_exited_lab_containers_then_networks (removes exited lab containers "
        "blocking networks). Admin only."
    ),
)
async def cleanup_networks_v2(
    request: ExtendedCleanupRequest,
    admin: Annotated[User, Depends(get_current_user)],
) -> ExtendedCleanupResponse:
    """Admin-only extended network cleanup with mode selection.

    This endpoint extends cleanup to optionally remove EXITED lab containers
    that keep networks attached, then removes the networks.

    Modes:
    - networks_only: Only remove detached networks (safe, same as v1)
    - remove_exited_lab_containers_then_networks: Also remove exited lab
      containers that are keeping networks attached (more aggressive)

    SECURITY:
    - Requires confirm=true AND confirm_phrase="DELETE OCTOLAB NETWORKS"
    - Refuses if any lab containers are RUNNING
    - Only operates on octolab_<uuid>_* networks
    - Only removes containers if ALL of:
      - Container is NOT running
      - Container project matches octolab_<uuid> pattern
      - Container is attached to a lab network being cleaned
    - If any nonlab containers are attached, refuses to delete that network
    - Never runs docker network prune or system prune
    """
    # Verify confirmation
    if not request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation required. Set confirm=true.",
        )

    if request.confirm_phrase != CLEANUP_CONFIRM_PHRASE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Confirmation phrase must be exactly '{CLEANUP_CONFIRM_PHRASE}'.",
        )

    # Check for running LAB containers BEFORE cleanup
    container_status = get_running_container_status(timeout=10.0)
    if container_status.running_lab_containers > 0:
        logger.warning(
            f"Admin {admin.email} cleanup-v2 REFUSED: "
            f"{container_status.running_lab_containers} running lab containers "
            f"in {container_status.running_lab_projects} projects"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cleanup while {container_status.running_lab_containers} lab containers are running "
            f"(across {container_status.running_lab_projects} lab projects). "
            f"Stop or delete active labs first.",
        )

    # Map API mode to docker_net mode
    mode_map = {
        ExtendedCleanupMode.NETWORKS_ONLY: CleanupMode.NETWORKS_ONLY,
        ExtendedCleanupMode.REMOVE_EXITED_LAB_CONTAINERS_THEN_NETWORKS: CleanupMode.REMOVE_EXITED_LAB_CONTAINERS_THEN_NETWORKS,
    }
    cleanup_mode = mode_map[request.mode]

    logger.info(
        f"Admin {admin.email} starting extended cleanup "
        f"(mode={cleanup_mode.value}, debug={request.debug})"
    )

    # Perform cleanup
    result = extended_network_cleanup(
        mode=cleanup_mode,
        debug=request.debug,
        timeout=30.0,
    )

    # Build response message
    total_skipped = (
        result.networks_skipped_in_use_running +
        result.networks_skipped_in_use_exited +
        result.networks_skipped_blocked_nonlab
    )

    if total_skipped > 0:
        message = (
            f"Cleanup completed. Removed {result.networks_removed} networks "
            f"and {result.containers_removed} containers. "
            f"Skipped {total_skipped} networks: "
            f"{result.networks_skipped_in_use_running} running, "
            f"{result.networks_skipped_in_use_exited} exited, "
            f"{result.networks_skipped_blocked_nonlab} blocked by nonlab."
        )
    else:
        message = (
            f"Cleanup successful. Removed {result.networks_removed} networks "
            f"and {result.containers_removed} containers."
        )

    logger.info(
        f"Admin {admin.email} extended cleanup complete: "
        f"mode={result.mode}, "
        f"networks_removed={result.networks_removed}, "
        f"containers_removed={result.containers_removed}, "
        f"skipped_running={result.networks_skipped_in_use_running}, "
        f"skipped_exited={result.networks_skipped_in_use_exited}, "
        f"skipped_blocked={result.networks_skipped_blocked_nonlab}"
    )

    # Build debug info if requested
    debug_info = None
    if request.debug and result.skipped_samples:
        skipped_samples: list[SkippedNetworkSampleResponse] = []
        for s in result.skipped_samples:
            sample: list[AttachedContainerSample] = []
            for c in s.sample:
                sample.append(AttachedContainerSample(
                    container=c.name,
                    state=c.state,  # type: ignore
                    project=c.project,
                ))
            skipped_samples.append(SkippedNetworkSampleResponse(
                network=s.network,
                reason=s.reason,
                sample=sample,
            ))
        debug_info = ExtendedCleanupDebug(skipped_samples=skipped_samples)

    return ExtendedCleanupResponse(
        mode=result.mode,
        networks_found=result.networks_found,
        networks_removed=result.networks_removed,
        networks_failed=result.networks_failed,
        networks_skipped_in_use_running=result.networks_skipped_in_use_running,
        networks_skipped_in_use_exited=result.networks_skipped_in_use_exited,
        networks_skipped_blocked_nonlab=result.networks_skipped_blocked_nonlab,
        containers_removed=result.containers_removed,
        message=message,
        debug=debug_info,
    )


# =============================================================================
# Runtime Drift Endpoints
# =============================================================================

# Tracked statuses (runtime should be running)
TRACKED_STATUSES = {LabStatus.READY, LabStatus.PROVISIONING, LabStatus.ENDING}
# Terminal statuses (runtime should NOT be running)
TERMINAL_STATUSES = {LabStatus.FINISHED, LabStatus.FAILED}


async def _classify_runtime_projects(
    db: AsyncSession,
    runtime_projects: dict[str, list[str]],
) -> RuntimeDriftResult:
    """Classify running lab projects against database state.

    Args:
        db: Database session
        runtime_projects: Dict mapping project name to container names

    Returns:
        RuntimeDriftResult with classification counts and project details
    """
    result = RuntimeDriftResult()
    result.running_lab_projects_total = len(runtime_projects)

    # Count total containers
    for containers in runtime_projects.values():
        result.running_lab_containers_total += len(containers)

    # Classify each project
    projects_list: list[RuntimeLabProject] = []

    for project, containers in runtime_projects.items():
        lab_id = extract_lab_id_from_project(project)
        if not lab_id:
            continue  # Skip invalid projects (shouldn't happen)

        # Look up lab in database
        try:
            lab_uuid = UUID(lab_id)
            lab_result = await db.execute(
                select(Lab).where(Lab.id == lab_uuid)
            )
            lab = lab_result.scalar_one_or_none()
        except ValueError:
            lab = None  # Invalid UUID

        # Classify
        if lab is None:
            classification = RuntimeProjectClassification.ORPHANED
            db_status = None
            result.orphaned_running_projects += 1
        elif lab.status in TRACKED_STATUSES:
            classification = RuntimeProjectClassification.TRACKED
            db_status = lab.status.value if isinstance(lab.status, LabStatus) else str(lab.status)
            result.tracked_running_projects += 1
        else:
            classification = RuntimeProjectClassification.DRIFTED
            db_status = lab.status.value if isinstance(lab.status, LabStatus) else str(lab.status)
            result.drifted_running_projects += 1

        projects_list.append(RuntimeLabProject(
            project=project,
            lab_id=lab_id,
            classification=classification,
            db_status=db_status,
            container_count=len(containers),
            sample_containers=containers[:3],  # Max 3 sample containers
        ))

    # Sort: orphaned first, then drifted, then tracked
    def sort_key(p: RuntimeLabProject) -> int:
        if p.classification == RuntimeProjectClassification.ORPHANED:
            return 0
        elif p.classification == RuntimeProjectClassification.DRIFTED:
            return 1
        return 2

    projects_list.sort(key=sort_key)

    # Cap to 50 projects
    result.projects = projects_list[:50]

    return result


@router.get(
    "/maintenance/runtime-drift",
    response_model=RuntimeDriftResponse,
    summary="Scan for runtime drift",
    description=(
        "Scan running lab containers and classify against DB state. "
        "Identifies tracked (DB says running), drifted (DB says stopped), "
        "and orphaned (no DB row) projects. Returns scan_id required for stop-labs. "
        "Admin only."
    ),
)
async def get_runtime_drift(
    admin: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    debug: bool = Query(False, description="Include debug sample in response"),
) -> RuntimeDriftResponse:
    """Scan runtime for lab project drift against database state.

    Classification:
    - tracked: DB status is READY, PROVISIONING, or ENDING (expected to be running)
    - drifted: DB exists but status is FINISHED/FAILED (should be stopped)
    - orphaned: No DB row found for this lab_id (stale/leaked)

    Returns scan_id which must be passed to stop-labs endpoint to bind
    the stop operation to this specific scan. Scan expires after 60 seconds.
    """
    logger.info(f"Admin {admin.email} scanning runtime drift")

    # Scan running lab projects from runtime
    runtime_projects = scan_running_lab_projects(timeout=10.0)

    # Classify against database
    drift_result = await _classify_runtime_projects(db, runtime_projects)

    # Build response projects
    projects_response = [
        RuntimeProjectInfo(
            project=p.project,
            lab_id=p.lab_id,
            classification=p.classification.value,
            db_status=p.db_status,
            container_count=p.container_count,
            sample_containers=p.sample_containers,
        )
        for p in drift_result.projects
    ]

    # Build cache payload with classification info for stop-labs
    cache_payload = {
        "running_lab_projects_total": drift_result.running_lab_projects_total,
        "running_lab_containers_total": drift_result.running_lab_containers_total,
        "tracked_running_projects": drift_result.tracked_running_projects,
        "drifted_running_projects": drift_result.drifted_running_projects,
        "orphaned_running_projects": drift_result.orphaned_running_projects,
        "projects": [
            {
                "project": p.project,
                "lab_id": p.lab_id,
                "classification": p.classification.value,
                "db_status": p.db_status,
                "container_count": p.container_count,
            }
            for p in drift_result.projects
        ],
    }

    # Cache the scan result and get scan_id
    scan_cache = get_scan_cache()
    scan_id, generated_at = scan_cache.put(cache_payload)

    # Build debug sample if requested (max 10)
    debug_sample = []
    if debug:
        for p in drift_result.projects[:10]:
            for container in p.sample_containers[:1]:  # One container per project
                debug_sample.append(RuntimeDriftDebugSample(
                    project=p.project,
                    container=container,
                    db_status=p.db_status,
                ))

    logger.info(
        f"Admin {admin.email} runtime drift scan: "
        f"scan_id={scan_id}, "
        f"projects={drift_result.running_lab_projects_total}, "
        f"containers={drift_result.running_lab_containers_total}, "
        f"tracked={drift_result.tracked_running_projects}, "
        f"drifted={drift_result.drifted_running_projects}, "
        f"orphaned={drift_result.orphaned_running_projects}"
    )

    return RuntimeDriftResponse(
        scan_id=scan_id,
        generated_at=generated_at.isoformat(),
        running_lab_projects_total=drift_result.running_lab_projects_total,
        running_lab_containers_total=drift_result.running_lab_containers_total,
        tracked_running_projects=drift_result.tracked_running_projects,
        drifted_running_projects=drift_result.drifted_running_projects,
        orphaned_running_projects=drift_result.orphaned_running_projects,
        projects=projects_response,
        debug_sample=debug_sample,
    )


# Required confirmation phrase for stop-labs
STOP_LABS_CONFIRM_PHRASE = "STOP RUNNING LABS"


@router.post(
    "/maintenance/stop-labs",
    response_model=StopLabsResponse,
    summary="Stop orphaned/drifted lab projects",
    description=(
        "Stop lab projects based on mode: orphaned_only (no DB row), "
        "drifted_only (DB says stopped), tracked_only (DB says running), "
        "or all_running. Requires scan_id from runtime-drift endpoint. "
        "Admin only."
    ),
)
async def stop_labs(
    request: StopLabsRequest,
    admin: Annotated[User, Depends(get_current_user)],
) -> StopLabsResponse:
    """Stop lab projects that are running but shouldn't be.

    SECURITY:
    - Requires scan_id from a recent runtime-drift call (TTL: 60 seconds)
    - Requires confirm=true AND confirm_phrase="STOP RUNNING LABS"
    - Server derives target projects from CACHED scan (never from client)
    - Only operates on octolab_<uuid> projects (strict pattern match)
    - Never runs global prune commands

    Modes:
    - orphaned_only: Stop projects with no DB row (safest)
    - drifted_only: Stop projects where DB says FINISHED/FAILED
    - tracked_only: Stop projects where DB says still running
    - all_running: Stop all running lab projects (dangerous, use with caution)

    Response includes before/after runtime counts for verification.
    before_* comes from cached scan, after_* from fresh runtime query.
    """
    # Verify confirmation
    if not request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation required. Set confirm=true.",
        )

    if request.confirm_phrase != STOP_LABS_CONFIRM_PHRASE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Confirmation phrase must be exactly '{STOP_LABS_CONFIRM_PHRASE}'.",
        )

    # Validate scan_id and get cached scan data
    scan_cache = get_scan_cache()
    cached_payload = scan_cache.get(request.scan_id)

    if cached_payload is None:
        logger.warning(
            f"Admin {admin.email} stop-labs rejected: stale/invalid scan_id={request.scan_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Scan expired or invalid. Please refresh runtime drift scan and try again.",
        )

    logger.info(
        f"Admin {admin.email} initiating stop-labs "
        f"(scan_id={request.scan_id}, mode={request.mode.value})"
    )

    # Extract before counts from cached scan
    before_projects = cached_payload.get("running_lab_projects_total", 0)
    before_containers = cached_payload.get("running_lab_containers_total", 0)

    # Derive targets from cached scan based on mode
    # SECURITY: We never accept project lists from client, only use server-cached data
    cached_projects = cached_payload.get("projects", [])
    targets: list[str] = []

    for p in cached_projects:
        classification = p.get("classification", "")
        if request.mode == StopLabsMode.ORPHANED_ONLY:
            if classification == "orphaned":
                targets.append(p["project"])
        elif request.mode == StopLabsMode.DRIFTED_ONLY:
            if classification == "drifted":
                targets.append(p["project"])
        elif request.mode == StopLabsMode.TRACKED_ONLY:
            if classification == "tracked":
                targets.append(p["project"])
        elif request.mode == StopLabsMode.ALL_RUNNING:
            targets.append(p["project"])

    # Calculate expected targets based on mode for mode validation
    mode_expected_counts = {
        StopLabsMode.ORPHANED_ONLY: cached_payload.get("orphaned_running_projects", 0),
        StopLabsMode.DRIFTED_ONLY: cached_payload.get("drifted_running_projects", 0),
        StopLabsMode.TRACKED_ONLY: cached_payload.get("tracked_running_projects", 0),
        StopLabsMode.ALL_RUNNING: cached_payload.get("running_lab_projects_total", 0),
    }
    targets_requested = mode_expected_counts.get(request.mode, 0)

    if not targets:
        logger.info(
            f"Admin {admin.email} stop-labs: no targets for mode={request.mode.value} "
            f"(scan_id={request.scan_id})"
        )
        # Query fresh runtime for after counts (should match before if no action)
        runtime_projects_after = scan_running_lab_projects(timeout=10.0)
        after_projects = len(runtime_projects_after)
        after_containers = sum(len(c) for c in runtime_projects_after.values())

        return StopLabsResponse(
            scan_id=request.scan_id,
            mode=request.mode.value,
            targets_requested=targets_requested,
            targets_found=0,
            before_projects=before_projects,
            before_containers=before_containers,
            projects_stopped=0,
            projects_failed=0,
            containers_force_removed=0,
            networks_removed=0,
            networks_failed=0,
            after_projects=after_projects,
            after_containers=after_containers,
            errors=[],
            results=[],
            message=f"No projects matched mode '{request.mode.value}'.",
        )

    logger.info(
        f"Admin {admin.email} stop-labs: {len(targets)} targets for mode={request.mode.value} "
        f"(scan_id={request.scan_id})"
    )

    # Get compose path using the same resolution as ComposeLabRuntime
    compose_path = _resolve_compose_path()
    compose_dir = str(compose_path.parent)
    compose_file = str(compose_path)

    # Stop the projects with VERIFICATION (verify->act->verify pattern)
    stop_result = stop_projects_verified_batch(
        projects=targets,
        compose_dir=compose_dir,
        compose_file=compose_file,
        timeout_per_project=120.0,
    )

    # Query fresh runtime for after counts
    runtime_projects_after = scan_running_lab_projects(timeout=10.0)
    after_projects = len(runtime_projects_after)
    after_containers = sum(len(c) for c in runtime_projects_after.values())

    # Build per-project results for response
    # Include all if debug=true, otherwise cap to 20 or show failures only
    project_results: list[ProjectStopResultInfo] = []
    for pr in stop_result.results:
        # Always include failures; include successes only if debug or under cap
        include = (
            request.debug or
            not pr.verified_stopped or
            (pr.verified_stopped and len(project_results) < 20)
        )
        if include:
            project_results.append(ProjectStopResultInfo(
                project=pr.project,
                pre_running=pr.pre_running,
                down_rc=pr.down_rc,
                remaining_after_down=pr.remaining_after_down,
                rm_rc=pr.rm_rc,
                remaining_final=pr.remaining_final,
                networks_removed=pr.networks_removed,
                verified_stopped=pr.verified_stopped,
                error=pr.error,
            ))

    # Cap results unless debug mode
    if not request.debug and len(project_results) > 20:
        project_results = project_results[:20]

    # Build response message (truthful, with before/after context)
    if stop_result.projects_failed > 0:
        message = (
            f"PARTIAL: Verified stopped {stop_result.projects_stopped}/{stop_result.targets} projects. "
            f"{stop_result.projects_failed} failed with containers still running. "
            f"Before: {before_projects} projects, After: {after_projects} projects."
        )
    elif stop_result.containers_force_removed > 0:
        message = (
            f"Verified stopped {stop_result.projects_stopped} projects "
            f"({stop_result.containers_force_removed} containers required rm -f fallback). "
            f"Removed {stop_result.networks_removed} networks. "
            f"Before: {before_projects} projects, After: {after_projects} projects."
        )
    else:
        message = (
            f"Verified stopped {stop_result.projects_stopped} projects "
            f"and removed {stop_result.networks_removed} networks. "
            f"Before: {before_projects} projects, After: {after_projects} projects."
        )

    logger.info(
        f"Admin {admin.email} stop-labs complete: "
        f"scan_id={request.scan_id}, "
        f"mode={request.mode.value}, "
        f"targets={stop_result.targets}, "
        f"verified_stopped={stop_result.projects_stopped}, "
        f"failed={stop_result.projects_failed}, "
        f"force_removed={stop_result.containers_force_removed}, "
        f"networks_removed={stop_result.networks_removed}, "
        f"before={before_projects}/{before_containers}, "
        f"after={after_projects}/{after_containers}"
    )

    return StopLabsResponse(
        scan_id=request.scan_id,
        mode=request.mode.value,
        targets_requested=targets_requested,
        targets_found=len(targets),
        before_projects=before_projects,
        before_containers=before_containers,
        projects_stopped=stop_result.projects_stopped,
        projects_failed=stop_result.projects_failed,
        containers_force_removed=stop_result.containers_force_removed,
        networks_removed=stop_result.networks_removed,
        networks_failed=stop_result.networks_failed,
        after_projects=after_projects,
        after_containers=after_containers,
        errors=stop_result.errors,
        results=project_results,
        message=message,
    )


@router.post(
    "/maintenance/stop-project",
    response_model=StopProjectResponse,
    summary="Stop a single lab project",
    description=(
        "Stop a specific lab project by name. Safer for targeted actions. "
        "Project must be currently running and match octolab_<uuid> pattern. "
        "Admin only."
    ),
)
async def stop_project(
    request: StopProjectRequest,
    admin: Annotated[User, Depends(get_current_user)],
) -> StopProjectResponse:
    """Stop a single lab project.

    SECURITY:
    - Requires confirm=true
    - Project must match strict regex ^octolab_<uuid>$
    - Project must appear in CURRENT runtime scan (must be running now)
    - Never operates on arbitrary past projects

    This is safer than bulk stop-labs for targeted cleanup.
    """
    # Verify confirmation
    if not request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation required. Set confirm=true.",
        )

    project = request.project.strip().lower()

    # Validate project matches lab pattern
    if not is_lab_project(project):
        logger.warning(
            f"Admin {admin.email} stop-project rejected: invalid project name '{request.project}'"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid project name '{request.project}'. Must match octolab_<uuid> pattern.",
        )

    # Verify project is currently running (server-derived, not trusting client)
    runtime_projects = scan_running_lab_projects(timeout=10.0)
    if project not in runtime_projects:
        logger.warning(
            f"Admin {admin.email} stop-project rejected: project '{project}' not running"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project}' is not currently running.",
        )

    logger.info(f"Admin {admin.email} stopping single project: {project}")

    # Get compose path
    compose_path = _resolve_compose_path()
    compose_dir = str(compose_path.parent)
    compose_file = str(compose_path)

    # Stop the project with VERIFICATION (verify->act->verify pattern)
    result = stop_project_verified(
        project=project,
        compose_dir=compose_dir,
        compose_file=compose_file,
        timeout=120.0,
    )

    logger.info(
        f"Admin {admin.email} stop-project complete: "
        f"project={project}, "
        f"pre_running={result.pre_running}, "
        f"remaining_after_down={result.remaining_after_down}, "
        f"remaining_final={result.remaining_final}, "
        f"verified_stopped={result.verified_stopped}, "
        f"networks_removed={result.networks_removed}"
    )

    return StopProjectResponse(
        project=project,
        pre_running=result.pre_running,
        down_rc=result.down_rc,
        remaining_after_down=result.remaining_after_down,
        rm_rc=result.rm_rc,
        remaining_final=result.remaining_final,
        stopped=result.verified_stopped,
        networks_removed=result.networks_removed,
        error=result.error,
    )


# =============================================================================
# Evidence Inspection (Admin-Only)
# =============================================================================


class EvidenceInspectFoundItem(BaseModel):
    """Found evidence file (relative path only, no host details)."""
    rel: str = Field(description="Relative path within evidence bundle")
    bytes: int | None = Field(None, description="File size in bytes")


class EvidenceInspectMissingItem(BaseModel):
    """Missing evidence artifact with reason."""
    rel: str = Field(description="Expected relative path pattern")
    reason: str = Field(description="Reason artifact is missing")


class EvidenceInspectResponse(BaseModel):
    """Admin-only evidence inspection result.

    SECURITY:
    - No absolute paths (relative only)
    - Bounded entries (max 20 per list)
    - Admin-only endpoint
    """
    lab_id: str
    evidence_state: str
    finalized_at: str | None = Field(None, description="ISO8601 timestamp when finalized")
    found: list[EvidenceInspectFoundItem] = Field(
        default_factory=list,
        description="Found evidence files (max 20)"
    )
    missing: list[EvidenceInspectMissingItem] = Field(
        default_factory=list,
        description="Missing evidence artifacts with reasons (max 20)"
    )
    total_bytes: int = Field(description="Total size of found evidence")
    artifact_counts: dict = Field(description="Counts by artifact type")


@router.get(
    "/labs/{lab_id}/evidence/inspect",
    response_model=EvidenceInspectResponse,
    summary="Inspect evidence for a lab (admin-only)",
)
async def admin_inspect_evidence(
    lab_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EvidenceInspectResponse:
    """
    Inspect evidence artifacts for a lab (admin-only investigative endpoint).

    Returns bounded summary of found/missing evidence with relative paths only.
    Used for debugging evidence collection issues.

    SECURITY:
    - Admin-only (requires OCTOLAB_ADMIN_EMAILS membership)
    - No absolute paths in response
    - Bounded to 20 entries per list
    - Does not expose host filesystem structure
    """
    from app.services.evidence_service import (
        async_preview_bundle,
        compute_evidence_state,
        MAX_INSPECT_ENTRIES,
    )

    # Admin can inspect any lab
    result = await db.execute(select(Lab).where(Lab.id == lab_id))
    lab = result.scalar_one_or_none()

    if lab is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lab not found",
        )

    logger.info(f"Admin {admin.email} inspecting evidence for lab {lab_id}")

    # Use async_preview_bundle to extract and inspect
    preview = await async_preview_bundle(lab, debug=True)

    # Compute state from preview data
    has_terminal = preview["artifact_counts"]["terminal_logs"] > 0
    has_pcap = preview["artifact_counts"]["pcap"] > 0

    if has_terminal and has_pcap:
        computed_state = "ready"
    elif has_terminal or has_pcap:
        computed_state = "partial"
    else:
        computed_state = "unavailable"

    # Build found list (relative paths only)
    found_items = []
    for item in preview["found"][:MAX_INSPECT_ENTRIES]:
        found_items.append(EvidenceInspectFoundItem(
            rel=item["arcname"],
            bytes=item.get("bytes"),
        ))

    # Build missing list
    missing_items = []
    lab_id_str = str(lab_id)

    if not has_terminal:
        missing_items.append(EvidenceInspectMissingItem(
            rel=f"evidence/tlog/{lab_id_str}/*.jsonl",
            reason="No terminal log files found",
        ))

    if not has_pcap:
        missing_items.append(EvidenceInspectMissingItem(
            rel="pcap/*.pcap",
            reason="No network capture files found",
        ))

    # Add extraction notes as missing items
    for note in preview.get("extraction_notes", []):
        if len(missing_items) < MAX_INSPECT_ENTRIES:
            missing_items.append(EvidenceInspectMissingItem(
                rel="(extraction)",
                reason=note,
            ))

    # Add skipped files
    for item in preview.get("skipped", []):
        if len(missing_items) >= MAX_INSPECT_ENTRIES:
            break
        missing_items.append(EvidenceInspectMissingItem(
            rel=item.get("rel", "unknown"),
            reason=item.get("reason", "skipped"),
        ))

    # Format finalized_at
    finalized_at_str = None
    if lab.evidence_finalized_at:
        finalized_at_str = lab.evidence_finalized_at.isoformat()

    return EvidenceInspectResponse(
        lab_id=str(lab_id),
        evidence_state=lab.evidence_state or computed_state,
        finalized_at=finalized_at_str,
        found=found_items,
        missing=missing_items,
        total_bytes=preview["total_bytes"],
        artifact_counts=preview["artifact_counts"],
    )


# =============================================================================
# MicroVM Preflight Endpoint
# =============================================================================


class MicroVMPreflightResponse(BaseModel):
    """Response from microVM preflight check.

    SECURITY:
    - No tokens or secrets
    - No full paths (only existence checks)
    - Admin-only endpoint
    """

    has_kvm: bool = Field(description="Whether /dev/kvm exists")
    can_access_kvm: bool = Field(description="Whether /dev/kvm is accessible")
    firecracker_found: bool = Field(description="Whether firecracker binary found")
    firecracker_version: str | None = Field(None, description="Firecracker version")
    jailer_found: bool = Field(description="Whether jailer binary found")
    jailer_version: str | None = Field(None, description="Jailer version")
    jailer_usable: bool = Field(description="Whether jailer is usable")
    kernel_path_exists: bool = Field(description="Whether kernel image exists")
    rootfs_path_exists: bool = Field(description="Whether base rootfs exists")
    vsock_supported: bool = Field(description="Whether vsock appears supported")
    state_dir_writable: bool = Field(description="Whether state dir is writable")
    can_run: bool = Field(description="Whether Firecracker can run (basic)")
    can_run_safe: bool = Field(description="Whether Firecracker can run with jailer")
    errors: list[str] = Field(default_factory=list, description="Fatal errors")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal warnings")


@router.get(
    "/microvm/preflight",
    response_model=MicroVMPreflightResponse,
    summary="Check microVM (Firecracker) capabilities",
    description=(
        "Run preflight checks to determine if Firecracker microVM runtime "
        "can be used. Returns capability report without sensitive information. "
        "Admin only."
    ),
)
async def microvm_preflight(
    admin: User = Depends(require_admin),
) -> MicroVMPreflightResponse:
    """Check microVM runtime prerequisites.

    Returns preflight check results including:
    - KVM availability
    - Firecracker/jailer binary availability
    - Kernel and rootfs existence
    - vsock support

    SECURITY:
    - Admin-only endpoint
    - No secrets or full paths in response
    - Safe to expose in logs/UI
    """
    from app.services.firecracker_manager import preflight

    logger.info(f"Admin {admin.email} running microVM preflight check")

    result = preflight()

    logger.info(
        f"MicroVM preflight: "
        f"can_run={result.can_run}, "
        f"can_run_safe={result.can_run_safe}, "
        f"errors={len(result.errors)}, "
        f"warnings={len(result.warnings)}"
    )

    return MicroVMPreflightResponse(
        has_kvm=result.has_kvm,
        can_access_kvm=result.can_access_kvm,
        firecracker_found=result.firecracker_found,
        firecracker_version=result.firecracker_version,
        jailer_found=result.jailer_found,
        jailer_version=result.jailer_version,
        jailer_usable=result.jailer_usable,
        kernel_path_exists=result.kernel_path_exists,
        rootfs_path_exists=result.rootfs_path_exists,
        vsock_supported=result.vsock_supported,
        state_dir_writable=result.state_dir_writable,
        can_run=result.can_run,
        can_run_safe=result.can_run_safe,
        errors=result.errors[:10],  # Cap for safety
        warnings=result.warnings[:10],
    )


# =============================================================================
# MicroVM Doctor and Runtime Override Endpoints
# =============================================================================


class DoctorCheckResponse(BaseModel):
    """Single doctor check result."""

    name: str = Field(description="Check identifier (e.g., 'kvm', 'firecracker')")
    ok: bool = Field(description="Whether check passed")
    severity: str = Field(description="Severity: info, warn, or fatal")
    details: str = Field(description="Short description (redacted)")
    hint: str = Field("", description="Actionable hint for resolving issues")


class DoctorReportResponse(BaseModel):
    """Complete doctor report.

    SECURITY:
    - No absolute paths
    - Details truncated
    - Admin-only endpoint
    """

    ok: bool = Field(description="True only if no fatal checks failed")
    checks: list[DoctorCheckResponse] = Field(description="All check results")
    summary: str = Field(description="Human-readable summary")
    generated_at: str = Field(description="ISO8601 timestamp")
    fatal_count: int = Field(description="Number of failed fatal checks")
    warn_count: int = Field(description="Number of failed warning checks")


class RuntimeStatusResponse(BaseModel):
    """Current runtime status.

    SECURITY: Admin-only, no secrets.
    """

    override: str | None = Field(None, description="Current override (null = default)")
    effective_runtime: str = Field(description="Effective runtime: compose or firecracker")
    doctor_ok: bool = Field(description="Whether doctor reports no fatal issues")
    doctor_summary: str = Field(description="Doctor summary (truncated)")
    last_smoke_ok: bool = Field(description="Whether last smoke test passed")
    last_smoke_at: str | None = Field(None, description="ISO8601 timestamp of last smoke")


class RuntimeOverrideRequest(BaseModel):
    """Request to set runtime override."""

    override: str | None = Field(
        None,
        description="Runtime override: 'compose', 'firecracker', or null (reset to default)",
    )


class RuntimeOverrideResponse(BaseModel):
    """Response from setting runtime override."""

    success: bool
    message: str
    effective_runtime: str
    doctor_report: DoctorReportResponse | None = None


class SmokeTimings(BaseModel):
    """Timings from smoke test."""

    boot_ms: int = Field(description="Time to start Firecracker process")
    ready_ms: int = Field(description="Time until metrics appear (proves FC working)")
    teardown_ms: int = Field(description="Time to teardown")
    total_ms: int = Field(description="Total smoke test time")


class SmokeRequest(BaseModel):
    """Request for smoke test."""

    enable_for_new_labs: bool = Field(
        False,
        description="If true and smoke passes, enable Firecracker for new labs",
    )
    keep_temp: bool = Field(
        False,
        description="If true, preserve temp directory for debugging (admin only)",
    )


class SmokeDebugInfo(BaseModel):
    """Debug information for failed smoke test.

    SECURITY:
    - All paths are redacted
    - Secrets are redacted from stderr/log content
    - Only included on failure
    """

    stderr_tail: str = Field("", description="Tail of stderr (redacted, max 2000 chars)")
    log_tail: str = Field("", description="Tail of firecracker.log (redacted, max 4000 chars)")
    config_excerpt: dict = Field(default_factory=dict, description="Redacted config excerpt")
    temp_dir_redacted: str = Field("", description="Redacted temp dir path")
    firecracker_rc: int | None = Field(None, description="Firecracker exit code if exited")
    metrics_appeared: bool = Field(False, description="Whether metrics file appeared")
    process_alive_at_check: bool = Field(False, description="Whether process was alive after startup")
    use_jailer: bool = Field(False, description="Whether jailer was used for sandboxing")
    is_wsl: bool = Field(False, description="Whether running under WSL")


class SmokeResponse(BaseModel):
    """Response from smoke test.

    SECURITY:
    - No secrets or full paths
    - Notes are redacted
    - Debug only on failure
    - Admin-only endpoint
    """

    ok: bool = Field(description="Whether smoke test passed (Firecracker works)")
    timings: SmokeTimings | None = Field(None, description="Timing breakdown")
    notes: list[str] = Field(default_factory=list, description="Notes (max 10)")
    debug: SmokeDebugInfo | None = Field(
        None, description="Debug info (only on failure)"
    )
    doctor_report: DoctorReportResponse | None = Field(
        None, description="Doctor report if preflight failed"
    )
    runtime_enabled: bool = Field(
        False, description="Whether Firecracker was enabled for new labs"
    )
    error: str | None = Field(None, description="Error message if failed")
    smoke_id: str | None = Field(
        None,
        description="Smoke test ID (for artifact retrieval). Set on failure when artifacts preserved.",
    )
    classification: str | None = Field(
        None,
        description="Failure classification: 'core_boot_failure' (kernel/kvm issue) or 'higher_layer_failure' (network/vsock/agent issue)",
    )
    artifacts_kept: bool = Field(
        False,
        description="Whether debug artifacts were preserved for later download",
    )
    netd_log_snippet: str | None = Field(
        None,
        description="Last ~30 lines of netd log (redacted). Included when netd check fails.",
    )


@router.get(
    "/runtime",
    response_model=RuntimeStatusResponse,
    summary="Get current runtime status",
    description="Returns current runtime override, effective runtime, and doctor status. Admin only.",
)
async def get_runtime_status(
    request: Request,
    admin: User = Depends(require_admin),
) -> RuntimeStatusResponse:
    """Get current runtime status.

    SECURITY:
    - Admin-only endpoint
    - No secrets in response
    """
    from app.services.runtime_selector import get_runtime_status as get_status

    logger.info(f"Admin {admin.email} checking runtime status")

    status_dict = get_status(request.app)

    return RuntimeStatusResponse(**status_dict)


@router.post(
    "/runtime",
    response_model=RuntimeOverrideResponse,
    summary="Set runtime override",
    description=(
        "Set runtime override for new labs. "
        "When setting to 'firecracker', runs doctor and rejects if any fatal issues. "
        "Admin only."
    ),
)
async def set_runtime_override(
    request: Request,
    body: RuntimeOverrideRequest,
    admin: User = Depends(require_admin),
) -> RuntimeOverrideResponse:
    """Set runtime override.

    SECURITY:
    - Admin-only endpoint
    - Validates Firecracker readiness before enabling
    - No secrets in response
    """
    from app.services.runtime_selector import (
        get_effective_runtime,
        set_runtime_override as set_override,
    )

    logger.info(f"Admin {admin.email} setting runtime override to: {body.override}")

    # Validate override value
    if body.override not in (None, "compose", "firecracker"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid override value: {body.override}. Must be 'compose', 'firecracker', or null.",
        )

    success, message, doctor_report = set_override(request.app, body.override)

    effective = get_effective_runtime(request.app)

    doctor_response = None
    if doctor_report:
        doctor_response = DoctorReportResponse(**doctor_report.to_dict())

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )

    return RuntimeOverrideResponse(
        success=success,
        message=message,
        effective_runtime=effective,
        doctor_report=doctor_response,
    )


@router.get(
    "/microvm/doctor",
    response_model=DoctorReportResponse,
    summary="Run Firecracker doctor checks",
    description=(
        "Run comprehensive health checks for Firecracker runtime. "
        "Returns structured report with actionable hints. "
        "No absolute paths or secrets exposed. Admin only."
    ),
)
async def microvm_doctor(
    admin: User = Depends(require_admin),
) -> DoctorReportResponse:
    """Run Firecracker doctor checks.

    SECURITY:
    - Admin-only endpoint
    - All paths redacted
    - Details truncated
    """
    from app.services.firecracker_doctor import run_doctor

    logger.info(f"Admin {admin.email} running microVM doctor")

    report = run_doctor()

    logger.info(
        f"MicroVM doctor: ok={report.ok}, fatal={len(report.fatal_checks)}, "
        f"warn={len(report.warn_checks)}"
    )

    return DoctorReportResponse(**report.to_dict())


@router.post(
    "/microvm/smoke",
    response_model=SmokeResponse,
    summary="Run Firecracker smoke test",
    description=(
        "Boot ephemeral microVM, verify Firecracker works (metrics appear), "
        "teardown, and return timings. Does NOT require guest agent. "
        "Optionally enable Firecracker for new labs if smoke passes. "
        "Always cleans up temp resources unless keep_temp=true. Admin only."
    ),
)
async def microvm_smoke(
    request: Request,
    body: SmokeRequest,
    admin: User = Depends(require_admin),
) -> SmokeResponse:
    """Run Firecracker smoke test.

    This smoke test validates that Firecracker itself works:
    1. Process starts and stays alive
    2. Metrics file appears (proves FC API is working)

    It does NOT require a guest agent - this tests Firecracker, not the guest.

    SECURITY:
    - Admin-only endpoint
    - Always cleans up temp dir (unless keep_temp=true for debugging)
    - No secrets in response
    - All paths and output redacted
    - subprocess uses shell=False
    """
    from app.config import settings
    from app.services.firecracker_doctor import run_doctor
    from app.services.microvm_smoke import run_firecracker_smoke
    from app.services.runtime_selector import (
        record_smoke_result,
        set_runtime_override,
    )

    logger.info(
        f"Admin {admin.email} running microVM smoke test "
        f"(enable={body.enable_for_new_labs}, keep_temp={body.keep_temp})"
    )

    # Preflight doctor check
    report = run_doctor()
    if not report.ok:
        notes = ["Doctor reported fatal issues"]

        # Check which checks failed for better error messages
        failed_check_names = [c.name for c in report.fatal_checks]
        for name in failed_check_names:
            check = next((c for c in report.fatal_checks if c.name == name), None)
            if check:
                notes.append(f"{name}: {check.details[:80]}")

        # If netd check failed, include log snippet
        netd_log_snippet = None
        if "netd" in failed_check_names:
            netd_log_snippet = _get_netd_log_snippet()
            if netd_log_snippet:
                notes.append("netd log snippet included in response")

        record_smoke_result(request.app, ok=False, notes=notes)
        return SmokeResponse(
            ok=False,
            notes=notes,
            doctor_report=DoctorReportResponse(**report.to_dict()),
            error="Doctor preflight failed",
            netd_log_snippet=netd_log_snippet,
        )

    # Check jailer availability (warn only in WSL/dev)
    jailer_check = next((c for c in report.checks if c.name == "jailer"), None)
    if jailer_check and not jailer_check.ok:
        if not settings.dev_unsafe_allow_no_jailer:
            notes = ["Jailer not available and dev override not set"]
            record_smoke_result(request.app, ok=False, notes=notes)
            return SmokeResponse(
                ok=False,
                notes=notes,
                doctor_report=DoctorReportResponse(**report.to_dict()),
                error="Jailer required but not available",
            )
        # Running without jailer is allowed (dev mode)

    # Validate required paths exist
    kernel_path = settings.microvm_kernel_path
    rootfs_path = settings.microvm_rootfs_base_path

    if not kernel_path:
        notes = ["OCTOLAB_MICROVM_KERNEL_PATH not set"]
        record_smoke_result(request.app, ok=False, notes=notes)
        return SmokeResponse(
            ok=False,
            notes=notes,
            doctor_report=DoctorReportResponse(**report.to_dict()),
            error="Kernel path not configured",
        )

    if not rootfs_path:
        notes = ["OCTOLAB_MICROVM_ROOTFS_BASE_PATH not set"]
        record_smoke_result(request.app, ok=False, notes=notes)
        return SmokeResponse(
            ok=False,
            notes=notes,
            doctor_report=DoctorReportResponse(**report.to_dict()),
            error="Rootfs path not configured",
        )

    # Run the smoke test using the new runner
    result = run_firecracker_smoke(
        firecracker_bin=settings.firecracker_bin,
        kernel_path=kernel_path,
        rootfs_path=rootfs_path,
        state_dir=settings.microvm_state_dir,
        keep_temp=body.keep_temp,
        use_jailer=settings.microvm_use_jailer,
        jailer_bin=settings.jailer_bin,
    )

    # Record result in app state
    record_smoke_result(request.app, ok=result.ok, notes=result.notes)

    # Build timings response
    timings = SmokeTimings(
        boot_ms=result.timings.boot_ms,
        ready_ms=result.timings.ready_ms,
        teardown_ms=result.timings.teardown_ms,
        total_ms=result.timings.total_ms,
    )

    # Build debug info if present (only on failure)
    debug_info = None
    if result.debug:
        debug_info = SmokeDebugInfo(
            stderr_tail=result.debug.stderr_tail,
            log_tail=result.debug.log_tail,
            config_excerpt=result.debug.config_excerpt,
            temp_dir_redacted=result.debug.temp_dir_redacted,
            firecracker_rc=result.debug.firecracker_rc,
            metrics_appeared=result.debug.metrics_appeared,
            process_alive_at_check=result.debug.process_alive_at_check,
            use_jailer=result.debug.use_jailer,
            is_wsl=result.debug.is_wsl,
        )

    # Enable Firecracker if requested and smoke passed
    runtime_enabled = False
    notes = list(result.notes)  # Copy to allow modification
    if result.ok and body.enable_for_new_labs:
        success, msg, _ = set_runtime_override(request.app, "firecracker")
        if success:
            runtime_enabled = True
            notes.append("Firecracker enabled for new labs")
        else:
            notes.append(f"Failed to enable: {msg[:50]}")

    logger.info(
        f"MicroVM smoke: ok={result.ok}, total={result.timings.total_ms}ms, "
        f"enabled={runtime_enabled}, classification={result.classification}"
    )

    return SmokeResponse(
        ok=result.ok,
        timings=timings,
        notes=notes[:10],
        debug=debug_info,
        doctor_report=DoctorReportResponse(**report.to_dict()),
        runtime_enabled=runtime_enabled,
        error=None if result.ok else "Smoke test did not pass",
        smoke_id=result.smoke_id,
        classification=result.classification,
        artifacts_kept=result.artifacts_kept,
    )


# =============================================================================
# Smoke Debug Bundle Download Endpoint
# =============================================================================


class SmokeArtifactListItem(BaseModel):
    """Single item in smoke artifact list."""

    smoke_id: str
    mtime: str
    exists: bool


class SmokeArtifactListResponse(BaseModel):
    """Response listing available smoke artifacts."""

    artifacts: list[SmokeArtifactListItem]
    state_dir_exists: bool
    max_kept: int


@router.get(
    "/microvm/smoke/artifacts",
    response_model=SmokeArtifactListResponse,
    summary="List smoke test artifacts",
    description="List all preserved smoke test directories available for download. Admin only.",
)
async def list_smoke_artifacts(
    admin: User = Depends(require_admin),
) -> SmokeArtifactListResponse:
    """List available smoke test artifacts.

    SECURITY:
    - Admin-only
    - No full paths returned
    - Only lists directories matching smoke_id pattern
    """
    from pathlib import Path

    from app.config import settings
    from app.services.microvm_smoke import (
        MAX_FAILED_SMOKE_DIRS,
        list_smoke_dirs,
    )

    state_dir = Path(settings.microvm_state_dir)
    artifacts = list_smoke_dirs(state_dir)

    return SmokeArtifactListResponse(
        artifacts=[
            SmokeArtifactListItem(
                smoke_id=a["smoke_id"],
                mtime=a["mtime"],
                exists=a["exists"],
            )
            for a in artifacts
        ],
        state_dir_exists=state_dir.exists(),
        max_kept=MAX_FAILED_SMOKE_DIRS,
    )


@router.get(
    "/microvm/smoke/{smoke_id}/debug.zip",
    summary="Download smoke test debug bundle",
    description=(
        "Download a ZIP archive containing all artifacts from a failed smoke test. "
        "Includes stderr, logs, config, and minimal boot artifacts. Admin only. "
        "smoke_id must match exact pattern: smoke_<13-digit-unix-ms>_<8-hex-chars>"
    ),
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "ZIP archive of smoke test artifacts",
        },
        400: {"description": "Invalid smoke_id format"},
        404: {"description": "Smoke artifacts not found"},
    },
)
async def download_smoke_debug_bundle(
    smoke_id: str,
    admin: User = Depends(require_admin),
) -> StreamingResponse:
    """Download debug bundle for a smoke test.

    SECURITY:
    - Admin-only endpoint
    - smoke_id strictly validated via regex
    - Path containment enforced
    - Symlinks skipped (no traversal)
    - Files zipped in memory and streamed
    """
    import io
    import zipfile
    from pathlib import Path

    from app.config import settings
    from app.services.microvm_smoke import (
        get_smoke_dir,
        validate_smoke_id,
    )

    # Validate smoke_id format
    if not validate_smoke_id(smoke_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid smoke_id format. Expected: smoke_<13-digit-unix-ms>_<8-hex-chars>",
        )

    # Get and validate path
    state_dir = Path(settings.microvm_state_dir)
    smoke_dir = get_smoke_dir(state_dir, smoke_id)

    if smoke_dir is None:
        raise HTTPException(
            status_code=400,
            detail="smoke_id failed containment check",
        )

    if not smoke_dir.exists() or not smoke_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail="Smoke artifacts not found",
        )

    logger.info(f"Admin {admin.email} downloading smoke debug bundle: {smoke_id}")

    # Create in-memory ZIP
    zip_buffer = io.BytesIO()

    try:
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for entry in smoke_dir.iterdir():
                # Skip symlinks (security)
                if entry.is_symlink():
                    continue
                # Only include regular files
                if not entry.is_file():
                    continue
                # Verify containment (belt-and-suspenders)
                try:
                    entry.resolve().relative_to(smoke_dir.resolve())
                except ValueError:
                    continue

                # Read and add to ZIP
                try:
                    content = entry.read_bytes()
                    zf.writestr(entry.name, content)
                except (OSError, IOError):
                    # Skip unreadable files
                    continue

        zip_buffer.seek(0)

        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{smoke_id}_debug.zip"',
            },
        )

    except Exception as e:
        logger.error(f"Error creating debug bundle for {smoke_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to create debug bundle",
        )


# =============================================================================
# Firecracker Runtime Status Endpoint
# =============================================================================


class LabRuntimeStatusInfo(BaseModel):
    """Status of a single lab's Firecracker runtime."""

    lab_id: str
    vm_id: str | None = None
    firecracker_pid: int | None = None
    api_sock_exists: bool
    state_dir_exists: bool
    status: str  # "ok", "missing_pid", "missing_sock", "missing_state"


class FirecrackerStatusResponse(BaseModel):
    """Response for Firecracker runtime status endpoint.

    SECURITY:
    - Admin-only
    - No full paths (only existence checks)
    - No secrets
    """

    generated_at: str
    firecracker_process_count: int
    running_microvm_labs: list[LabRuntimeStatusInfo]
    drift: dict  # {"db_running_no_pid": [...], "orphan_pids": [...]}
    summary: str


@router.get(
    "/maintenance/firecracker/status",
    response_model=FirecrackerStatusResponse,
    summary="Get Firecracker runtime status",
    description=(
        "Returns comprehensive Firecracker runtime status including process counts, "
        "per-lab status, and drift detection (labs marked running but no process). "
        "Admin only."
    ),
)
async def get_firecracker_status_endpoint(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FirecrackerStatusResponse:
    """Get comprehensive Firecracker runtime status.

    SECURITY:
    - Admin-only endpoint
    - No secrets or full paths in response
    - subprocess.run with shell=False
    """
    from app.services.firecracker_status import get_firecracker_status

    logger.info(f"Admin {admin.email} checking Firecracker status")

    result = await get_firecracker_status(db)

    logger.info(
        f"Firecracker status: processes={result.firecracker_process_count}, "
        f"labs={len(result.running_microvm_labs)}, "
        f"drift_db_no_pid={len(result.drift.get('db_running_no_pid', []))}, "
        f"drift_orphan_pids={len(result.drift.get('orphan_pids', []))}"
    )

    # Convert to response model
    labs_response = [
        LabRuntimeStatusInfo(
            lab_id=ls.lab_id,
            vm_id=ls.vm_id,
            firecracker_pid=ls.firecracker_pid,
            api_sock_exists=ls.api_sock_exists,
            state_dir_exists=ls.state_dir_exists,
            status=ls.status,
        )
        for ls in result.running_microvm_labs
    ]

    return FirecrackerStatusResponse(
        generated_at=result.generated_at,
        firecracker_process_count=result.firecracker_process_count,
        running_microvm_labs=labs_response,
        drift=result.drift,
        summary=result.summary,
    )


