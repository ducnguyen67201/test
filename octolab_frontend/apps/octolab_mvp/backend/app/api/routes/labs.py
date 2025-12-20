"""Lab endpoints for creating, listing, retrieving, and ending labs."""

import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from io import BytesIO
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.api.deps import get_current_user, get_session
from app.config import settings
from app.db import get_db
from app.helpers.crypto import decrypt_password, EncryptionError
from app.models.lab import LabStatus
from app.models.user import User
from app.schemas.lab import LabCreate, LabConnectResponse, LabResponse, EvidenceStatusResponse
from app.services.lab_orchestrator import LabOrchestrator
from app.services.evidence_service import (
    EvidenceNotFoundError,
    build_lab_network_evidence_tar,
    build_evidence_bundle_zip_file,
    build_evidence_status,
    async_preview_bundle,
)
from app.services.evidence_sealing import (
    EvidenceNotSealedError,
    EvidenceVerificationError,
    build_verified_evidence_bundle_file,
)
from app.services.guacamole_client import (
    GuacClient,
    GuacClientError,
    GuacAuthError,
)
from app.services.lab_service import (
    create_lab_for_user,
    end_lab_for_user,
    get_lab_for_user,
    list_labs_for_user,
    provision_lab,
    reconcile_evidence_state_if_needed,
)
from app.services.runtime_selector import (
    get_effective_runtime,
    assert_runtime_ready_for_lab,
)
from app.api.routes.admin import require_admin
from app.utils.fs import rmtree_hardened

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/labs", tags=["labs"])


@router.post(
    "/",
    response_model=LabResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new lab",
)
async def create_lab(
    lab_request: LabCreate,
    http_request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LabResponse:
    """
    Create a new lab for the current user.

    Args:
        lab_request: Lab creation request with recipe_id and/or intent
        http_request: HTTP request (for accessing app state)
        current_user: Current authenticated user (from dependency)
        db: Database session

    Returns:
        LabResponse: Created lab information

    Raises:
        HTTPException: 400 if recipe validation fails or neither recipe_id nor intent provided
        HTTPException: 400 if Firecracker enabled but doctor reports fatal issues
        HTTPException: 404 if recipe not found or no matching recipe found
        HTTPException: 503 if Firecracker enabled but runtime not available
    """
    # =========================================================================
    # FAIL-FAST: Check runtime readiness before creating lab
    #
    # SECURITY:
    # - When Firecracker is enabled (admin toggle), validate before committing
    # - If doctor reports fatal issues, reject immediately (no DB write)
    # - No fallback to compose - fail closed
    # =========================================================================
    effective_runtime = get_effective_runtime(http_request.app)

    if effective_runtime == "firecracker":
        # Run doctor check - raises HTTPException if fatal issues
        # This is fail-fast: we don't create the lab if Firecracker isn't ready
        assert_runtime_ready_for_lab(http_request.app)

        logger.info(
            f"lab_create runtime=firecracker user_id={str(current_user.id)[-6:]}"
        )

    # Create lab with effective runtime (server-owned, never from client)
    lab = await create_lab_for_user(
        db=db,
        user=current_user,
        data=lab_request,
        effective_runtime=effective_runtime,
    )

    # TODO: replace BackgroundTasks with dedicated orchestration worker/queue.
    background_tasks.add_task(provision_lab, lab.id)

    return LabResponse.model_validate(lab)


@router.delete(
    "/{lab_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a lab (trigger teardown)",
)
async def delete_lab(
    lab_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Initiate lab teardown for the current user.

    Non-blocking: Marks lab as ENDING and returns immediately.
    The teardown worker will pick up and process the lab asynchronously.
    """
    lab = await get_lab_for_user(db=db, user=current_user, lab_id=lab_id)
    if lab is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lab not found",
        )

    if lab.status in (LabStatus.ENDING, LabStatus.FINISHED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lab teardown already in progress or finished",
        )

    lab.status = LabStatus.ENDING
    await db.commit()

    # Worker will pick up ENDING labs automatically - no background task needed


@router.get(
    "/{lab_id}/evidence",
    summary="Download structured evidence tarball",
)
async def get_lab_evidence(
    lab_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Return the lab's structured evidence logs as a tar.gz archive.

    Contains:
    - commands.log: Terminal I/O transcript recorded by script utility (PTY format)
    - commands.time: Timing data for replay (binary format)
    - network.json: Structured network logs from the gateway (JSON format)
    - metadata.json: Lab metadata including SHA256 checksums (commands_log_sha256,
      commands_timing_sha256) and evidence_version: "2.0"

    Evidence is only available for labs in FINISHED status to ensure all logs are flushed.
    """
    # Enforce ownership strictly by lab_id; reference IDs are never accepted here.
    lab = await get_lab_for_user(db=db, user=current_user, lab_id=lab_id)
    if lab is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lab not found",
        )

    if lab.status != LabStatus.FINISHED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Evidence is only available for finished labs",
        )

    now = datetime.now(timezone.utc)
    if lab.evidence_expires_at is not None and now >= lab.evidence_expires_at:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence not found",
        )

    try:
        tar_bytes = await build_lab_network_evidence_tar(lab)
    except EvidenceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence not found",
        )

    file_obj = BytesIO(tar_bytes)
    filename = f"lab_{lab.id}_evidence.tar.gz"
    return StreamingResponse(
        file_obj,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{lab_id}/evidence/bundle.zip",
    summary="Download complete evidence bundle as ZIP",
)
async def get_lab_evidence_bundle(
    lab_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """
    Return the lab's complete evidence bundle as a ZIP archive.

    Contains:
    - evidence/tlog/<lab_id>/session.jsonl: Structured tlog session recording (JSONL format)
    - evidence/commands.log: Legacy terminal I/O transcript (if present)
    - evidence/commands.time: Legacy timing data for replay (if present)
    - pcap/: Network capture files (if present)
    - manifest.json: Bundle metadata including file list, timestamps, checksums

    Evidence can be downloaded for labs in READY or FINISHED status.
    FINISHED labs have complete evidence; READY labs may have partial evidence.

    Authorization:
    - Only the lab owner can download evidence
    - Returns 404 if lab not found or not owned by current user (prevents enumeration)

    SECURITY (Pattern B):
    - Uses FileResponse with BackgroundTask for deterministic temp cleanup
    - Temp directory is cleaned up after response is sent via rmtree_hardened
    """
    # Enforce ownership strictly by lab_id; never accept tenant ID from client
    lab = await get_lab_for_user(db=db, user=current_user, lab_id=lab_id)
    if lab is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lab not found",
        )

    # Allow download for READY or FINISHED labs
    if lab.status not in (LabStatus.READY, LabStatus.FINISHED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Evidence is only available for ready or finished labs",
        )

    # Check evidence expiration
    now = datetime.now(timezone.utc)
    if lab.evidence_expires_at is not None and now >= lab.evidence_expires_at:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence not found",
        )

    # Build evidence bundle - always returns valid ZIP with manifest
    # Missing artifacts are described in manifest but don't cause 404
    zip_path, tmpdir = await build_evidence_bundle_zip_file(lab)

    filename = f"lab_{lab.id}_evidence.zip"
    # Pattern B: FileResponse with BackgroundTask for deterministic cleanup
    return FileResponse(
        path=str(zip_path),
        filename=filename,
        media_type="application/zip",
        background=BackgroundTask(rmtree_hardened, tmpdir),
    )


@router.get(
    "/{lab_id}/evidence/verified-bundle.zip",
    summary="Download verified authoritative evidence bundle",
)
async def get_verified_evidence_bundle(
    lab_id: UUID,
    include_untrusted: bool = True,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """
    Return the lab's verified authoritative evidence bundle as a ZIP archive.

    This endpoint verifies the evidence seal before serving:
    - Checks HMAC signature matches
    - Verifies all file hashes match manifest

    Contents (verified/authoritative):
    - auth/network/network.json: Gateway network capture (JSONL)
    - auth/logs/compose.log: Container logs from docker compose
    - auth/manifest.json: Evidence manifest with file hashes
    - auth/manifest.sig: HMAC signature of manifest

    Contents (untrusted, if include_untrusted=True):
    - untrusted/: User evidence from OctoBox (tlog, commands.log)

    SECURITY:
    - Authoritative evidence (auth/) is tamper-evident and signed
    - Untrusted evidence (untrusted/) may have been modified by user
    - Only the lab owner can download evidence (returns 404 if not owner)

    SECURITY (Pattern B):
    - Uses FileResponse with BackgroundTask for deterministic temp cleanup
    - Temp directory is cleaned up after response is sent via rmtree_hardened

    Returns:
    - 200: ZIP file stream
    - 404: Lab not found or not owned by user
    - 409: Evidence not sealed yet (lab still active)
    - 422: Seal verification failed (tampered or corrupted)
    """
    # Enforce ownership strictly by lab_id
    lab = await get_lab_for_user(db=db, user=current_user, lab_id=lab_id)
    if lab is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lab not found",
        )

    # Check evidence expiration
    now = datetime.now(timezone.utc)
    if lab.evidence_expires_at is not None and now >= lab.evidence_expires_at:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence not found",
        )

    try:
        zip_path, tmpdir = await build_verified_evidence_bundle_file(lab, include_untrusted=include_untrusted)
    except EvidenceNotSealedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Evidence not sealed yet - lab may still be active",
        )
    except EvidenceVerificationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Evidence verification failed: {e}",
        )

    filename = f"lab_{lab.id}_verified_evidence.zip"
    # Pattern B: FileResponse with BackgroundTask for deterministic cleanup
    return FileResponse(
        path=str(zip_path),
        filename=filename,
        media_type="application/zip",
        background=BackgroundTask(rmtree_hardened, tmpdir),
    )


@router.get(
    "/{lab_id}/evidence/status",
    response_model=EvidenceStatusResponse,
    summary="Get evidence artifact status",
)
async def get_evidence_status(
    lab_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvidenceStatusResponse:
    """
    Get the status of evidence artifacts for a lab.

    Returns structured information about which artifacts are present,
    their sizes, and reasons for any missing artifacts. This is the
    single source of truth for evidence availability.

    Artifact types checked:
    - terminal_logs: tlog session recordings and/or legacy commands.log
    - pcap: Network packet captures
    - guac_recordings: Guacamole session recordings (if enabled)

    Authorization:
    - Only the lab owner can check evidence status
    - Returns 404 if lab not found or not owned by current user (prevents enumeration)

    Can be called for labs in READY or FINISHED status.
    READY labs may have partial evidence; FINISHED labs have complete evidence.
    """
    # Enforce ownership - return 404 for not found OR unauthorized
    lab = await get_lab_for_user(db=db, user=current_user, lab_id=lab_id)
    if lab is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lab not found",
        )

    # Allow status check for READY or FINISHED labs
    if lab.status not in (LabStatus.READY, LabStatus.FINISHED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Evidence status is only available for ready or finished labs",
        )

    # Check evidence expiration
    now = datetime.now(timezone.utc)
    if lab.evidence_expires_at is not None and now >= lab.evidence_expires_at:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence not found",
        )

    # Build evidence status (extracts to tmpdir, inspects, cleans up)
    status_dict = await build_evidence_status(lab)

    return EvidenceStatusResponse(**status_dict)


@router.get(
    "/{lab_id}/evidence/preview",
    summary="Preview evidence bundle contents (admin-only debug endpoint)",
)
async def get_evidence_preview(
    lab_id: UUID,
    debug: Annotated[bool, Query(description="Include debug hints for skipped files")] = False,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Preview what files would be included in an evidence bundle (admin-only).

    This endpoint performs the discovery phase of evidence bundling without
    creating the actual ZIP. Useful for debugging why files might be missing
    from evidence bundles.

    SECURITY:
    - Admin-only endpoint (requires OCTOLAB_ADMIN_EMAILS allowlist membership)
    - Does not verify lab ownership (admin can inspect any lab)
    - Returns bounded debug info to prevent information disclosure

    Returns:
    - found: List of files that would be included in bundle
    - skipped: List of files that were skipped (if debug=true)
    - total_bytes: Total size of files that would be included
    - artifact_counts: Counts by artifact type (terminal_logs, pcap, guac_recordings)
    - extraction_notes: Notes about volume extraction
    - volumes_extracted: Files extracted from each Docker volume
    """
    from sqlalchemy import select
    from app.models.lab import Lab

    # Admin can inspect any lab - query directly without ownership check
    result = await db.execute(select(Lab).where(Lab.id == lab_id))
    lab = result.scalar_one_or_none()

    if lab is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lab not found",
        )

    # Check evidence expiration
    now = datetime.now(timezone.utc)
    if lab.evidence_expires_at is not None and now >= lab.evidence_expires_at:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence not found (expired)",
        )

    # Run preview (extracts volumes, discovers files, cleans up)
    preview = await async_preview_bundle(lab, debug=debug)

    # Add lab metadata for context
    preview["lab_id"] = str(lab.id)
    preview["lab_status"] = lab.status.value if lab.status else "unknown"

    return preview


@router.get(
    "/",
    response_model=list[LabResponse],
    summary="List labs for current user",
)
async def list_labs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LabResponse]:
    """
    List all labs owned by the current user.

    Args:
        current_user: Current authenticated user (from dependency)
        db: Database session

    Returns:
        List of LabResponse for labs owned by the user
    """
    labs = await list_labs_for_user(
        db=db,
        user=current_user,
    )

    return [LabResponse.model_validate(lab) for lab in labs]


@router.get(
    "/{lab_id}",
    response_model=LabResponse,
    summary="Get a single lab by ID",
)
async def get_lab(
    lab_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LabResponse:
    """
    Get a single lab by ID (must be owned by current user).

    Includes self-healing: if a terminal lab (finished/failed) is still
    in 'collecting' evidence_state, reconciles from disk once.

    Args:
        lab_id: UUID of the lab to retrieve
        current_user: Current authenticated user (from dependency)
        db: Database session

    Returns:
        LabResponse: Lab information

    Raises:
        HTTPException: 404 if lab not found or not owned by user
    """
    lab = await get_lab_for_user(
        db=db,
        user=current_user,
        lab_id=lab_id,
    )

    if lab is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lab not found",
        )

    # Self-healing: reconcile evidence_state for terminal labs stuck in 'collecting'
    # This runs once per lab (sets evidence_finalized_at to prevent re-runs)
    # Uses flush() internally, so we refresh after to ensure Pydantic sees current values
    reconciled = await reconcile_evidence_state_if_needed(lab, db)

    if reconciled:
        # Refresh the lab instance to ensure all attributes are current
        # This prevents MissingGreenlet errors during Pydantic serialization
        await db.refresh(lab)

    return LabResponse.model_validate(lab)


@router.post(
    "/{lab_id}/end",
    response_model=LabResponse,
    summary="End a lab",
)
def end_lab(
    lab_id: UUID,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> LabResponse:
    """
    Mark a lab as ending (must be owned by current user).

    Args:
        lab_id: UUID of the lab to end
        session: Sync database session
        current_user: Current authenticated user (from dependency)

    Returns:
        LabResponse: Updated lab information with status ENDING

    Raises:
        HTTPException: 404 if lab not found or not owned by user
        HTTPException: 400 if lab cannot be ended from current state
    """
    lab = end_lab_for_user(session, current_user, lab_id)

    return LabResponse.model_validate(lab)


@router.post(
    "/{lab_id}/start",
    response_model=LabResponse,
    summary="Start lab environment",
)
async def start_lab(
    lab_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LabResponse:
    """Start the HackVM stack for the specified lab."""
    lab = await get_lab_for_user(db=db, user=current_user, lab_id=lab_id)
    if lab is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lab not found",
        )

    orchestrator = LabOrchestrator()
    updated_lab = await orchestrator.start_lab(lab, db)
    return LabResponse.model_validate(updated_lab)


@router.post(
    "/{lab_id}/stop",
    response_model=LabResponse,
    summary="Stop lab environment",
)
async def stop_lab(
    lab_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LabResponse:
    """Stop the HackVM stack for the specified lab."""
    lab = await get_lab_for_user(db=db, user=current_user, lab_id=lab_id)
    if lab is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lab not found",
        )

    orchestrator = LabOrchestrator()
    updated_lab = await orchestrator.stop_lab(lab, db)
    return LabResponse.model_validate(updated_lab)


@router.get(
    "/{lab_id}/connect",
    summary="Connect to lab via Guacamole",
    response_class=RedirectResponse,
    responses={
        302: {"description": "Redirect to Guacamole client"},
        404: {"description": "Lab not found or Guacamole not configured"},
        409: {"description": "Lab not ready for connection"},
        503: {"description": "Guacamole service unavailable"},
    },
)
async def connect_to_lab(
    lab_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """
    Passwordless auth gateway to Guacamole for a lab.

    This endpoint:
    1. Verifies the user owns the lab
    2. Decrypts the per-lab Guacamole password
    3. Logs in to Guacamole as the lab user to get an auth token
    4. Redirects to the Guacamole client with the token

    SECURITY:
    - Requires authentication
    - Enforces tenant isolation (user can only connect to their own labs)
    - Passwords and tokens are never logged
    - Short-lived Guacamole tokens

    Returns:
        302 redirect to Guacamole client URL with auth token
    """
    # Check if Guacamole is enabled
    if not settings.guac_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Guacamole integration is not enabled",
        )

    # Get lab with tenant isolation
    lab = await get_lab_for_user(db=db, user=current_user, lab_id=lab_id)
    if lab is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lab not found",
        )

    # Verify lab is ready for connection
    if lab.status != LabStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Lab is not ready for connection (status: {lab.status.value})",
        )

    # Verify Guacamole is configured for this lab
    if not lab.guac_username or not lab.guac_password_enc or not lab.guac_connection_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lab was not provisioned with Guacamole connection",
        )

    # Decrypt password
    try:
        password = decrypt_password(lab.guac_password_enc)
    except EncryptionError:
        logger.error(f"Failed to decrypt Guacamole password for lab {lab.id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt connection credentials",
        )

    # Login to Guacamole and get token
    try:
        async with GuacClient() as guac:
            if not await guac.health_check():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Guacamole service is not available",
                )

            token = await guac.login(lab.guac_username, password)

            # Build redirect URL
            # SECURITY: Token is passed as URL parameter (Guacamole standard)
            # This is secure because HTTPS should be used in production
            redirect_url = guac.get_client_url(
                lab.guac_connection_id,
                token.token,
            )

            logger.info(f"User {current_user.id} connecting to lab {lab.id} via Guacamole")
            return RedirectResponse(url=redirect_url, status_code=302)

    except GuacAuthError:
        logger.error(f"Guacamole auth failed for lab {lab.id} user {lab.guac_username}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to authenticate with Guacamole",
        )
    except GuacClientError as e:
        logger.error(f"Guacamole client error for lab {lab.id}: {type(e).__name__}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Guacamole service error",
        )


@router.post(
    "/{lab_id}/connect",
    response_model=LabConnectResponse,
    summary="Get connection URL for lab (Guacamole or direct noVNC)",
    responses={
        200: {"description": "Connection URL for lab VNC access"},
        404: {"description": "Lab not found"},
        409: {"description": "Lab not ready for connection"},
        503: {"description": "Connection service unavailable"},
    },
)
async def get_lab_connect_url(
    lab_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LabConnectResponse:
    """
    Get connection URL for a lab (SPA-friendly).

    This endpoint supports two modes:
    1. Guacamole mode (when enabled): Returns Guacamole client URL with auth token
    2. Direct noVNC mode (Firecracker labs): Returns direct noVNC URL

    SECURITY:
    - Requires JWT authentication
    - Enforces tenant isolation (user can only connect to their own labs)
    - Passwords and tokens are never logged

    Returns:
        LabConnectResponse with redirect_url to VNC client
    """
    # Get lab with tenant isolation
    lab = await get_lab_for_user(db=db, user=current_user, lab_id=lab_id)
    if lab is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lab not found",
        )

    # Verify lab is ready for connection
    if lab.status != LabStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Lab is not ready for connection (status: {lab.status.value})",
        )

    # Mode 1: Guacamole (when enabled and configured for this lab)
    if settings.guac_enabled and lab.guac_username and lab.guac_password_enc and lab.guac_connection_id:
        # Decrypt password
        try:
            password = decrypt_password(lab.guac_password_enc)
        except EncryptionError:
            logger.error(f"Failed to decrypt Guacamole password for lab {lab.id}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to decrypt connection credentials",
            )

        # Login to Guacamole and get token
        try:
            async with GuacClient() as guac:
                if not await guac.health_check():
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Guacamole service is not available",
                    )

                token = await guac.login(lab.guac_username, password)

                # Build redirect URL
                redirect_url = guac.get_client_url(
                    lab.guac_connection_id,
                    token.token,
                )

                logger.info(f"User {current_user.id} got Guacamole connect URL for lab {lab.id}")
                return LabConnectResponse(redirect_url=redirect_url)

        except GuacAuthError:
            logger.error(f"Guacamole auth failed for lab {lab.id} user {lab.guac_username}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to authenticate with Guacamole",
            )
        except GuacClientError as e:
            logger.error(f"Guacamole client error for lab {lab.id}: {type(e).__name__}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Guacamole service error",
            )

    # Mode 2: Direct noVNC (Firecracker or non-Guacamole labs with connection_url)
    if lab.connection_url:
        logger.info(f"User {current_user.id} got direct noVNC URL for lab {lab.id}")
        return LabConnectResponse(redirect_url=lab.connection_url)

    # No connection method available
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Lab has no configured connection method",
    )

