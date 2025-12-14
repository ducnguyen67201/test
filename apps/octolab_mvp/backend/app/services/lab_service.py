"""Lab service for lab lifecycle management and tenant isolation."""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import settings
from app.db import AsyncSessionLocal
from app.models.lab import Lab, LabStatus, EvidenceSealStatus, RuntimeType
from app.models.recipe import Recipe
from app.models.user import User
from app.runtime import get_runtime
from app.runtime.k8s_runtime import K8sLabRuntime
from app.runtime.compose_runtime import ComposeLabRuntime
from app.runtime.firecracker_runtime import FirecrackerLabRuntime, FirecrackerRuntimeError
from app.services.firecracker_manager import StaleRootfsError
from app.runtime.exceptions import NetworkPoolExhaustedError, NetworkCleanupBlockedError
from app.services.port_allocator import allocate_novnc_port, release_novnc_port
from app.services.novnc_probe import probe_novnc_ready, NovncNotReady
from app.services.evidence_sealing import (
    export_compose_logs_to_auth_volume,
    seal_auth_evidence,
    get_evidence_volume_names,
)
from app.services.evidence_service import finalize_evidence_state, compute_evidence_state
from app.models.lab import EvidenceState
from app.services.guacamole_provisioner import (
    provision_guacamole_for_lab,
    teardown_guacamole_for_lab,
    GuacProvisioningError,
)
from app.helpers.crypto import (
    generate_secure_password,
    encrypt_password,
    EncryptionError,
)
from app.utils.diagnostics import collect_compose_diagnostics, format_diagnostics_for_log, redact_owner_id
from app.schemas.lab import LabCreate, LabIntent

logger = logging.getLogger(__name__)


async def _select_recipe_for_intent(
    db: AsyncSession,
    intent: LabIntent,
) -> Recipe | None:
    """
    Select an active recipe based on intent fields.

    Args:
        db: Database session
        intent: LabIntent with optional software, version, exploit_family

    Returns:
        Recipe instance if found, None otherwise

    Note:
        Filters by is_active == True and matches on:
        - software (if provided in intent)
        - version_constraint (if provided in intent, exact match for MVP)
        - exploit_family (if provided in intent)
    """
    query = select(Recipe).where(Recipe.is_active == True)

    # Add filters based on intent fields (if provided)
    if intent.software:
        query = query.where(Recipe.software == intent.software)
    if intent.version:
        # For MVP: exact match on version_constraint
        # Future: could parse version_constraint and do semantic matching
        query = query.where(Recipe.version_constraint == intent.version)
    if intent.exploit_family:
        query = query.where(Recipe.exploit_family == intent.exploit_family)

    result = await db.execute(query)
    recipe = result.scalar_one_or_none()
    return recipe


async def create_lab_for_user(
    db: AsyncSession,
    user: User,
    data: LabCreate,
    effective_runtime: str,
) -> Lab:
    """
    Create a new lab for a user with recipe validation or selection.

    Enforces quota (MAX_ACTIVE_LABS_PER_USER) and sets TTL (DEFAULT_LAB_TTL_MINUTES).

    Args:
        db: Database session
        user: User model instance (for tenant isolation and owner_id)
        data: LabCreate schema (contains recipe_id and/or intent)
        effective_runtime: Server-owned runtime choice ("compose" or "firecracker").
                          Never from client input.

    Returns:
        Created Lab instance

    Raises:
        HTTPException: 400 if recipe validation fails or neither recipe_id nor intent provided
        HTTPException: 404 if recipe not found or no matching recipe found
        HTTPException: 429 if user has too many active labs

    SECURITY:
        effective_runtime is server-owned and never from client input.
        It's determined by runtime_selector.get_effective_runtime(app).
    """
    recipe: Recipe | None = None

    # If recipe_id is provided, use it
    if data.recipe_id is not None:
        recipe = await db.get(Recipe, data.recipe_id)
        if recipe is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Recipe not found",
            )
        if not recipe.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Recipe is not active",
            )
    # Else if intent is provided, select a recipe
    elif data.intent is not None:
        recipe = await _select_recipe_for_intent(db, data.intent)
        if recipe is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No matching active recipe found",
            )
    # Else: neither provided
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either recipe_id or intent must be provided",
        )

    # ==========================================================================
    # Quota enforcement: check active labs count
    # ==========================================================================
    active_statuses = (LabStatus.PROVISIONING, LabStatus.READY, LabStatus.ENDING)
    result = await db.execute(
        select(Lab).where(
            Lab.owner_id == user.id,
            Lab.status.in_(active_statuses),
        )
    )
    existing_active_labs = result.scalars().all()
    active_count = len(existing_active_labs)

    if active_count >= settings.max_active_labs_per_user:
        logger.warning(
            f"User {user.id} has {active_count} active labs, exceeding quota "
            f"({settings.max_active_labs_per_user}). Rejecting new lab request."
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Maximum active labs ({settings.max_active_labs_per_user}) exceeded. "
                   f"Please terminate existing labs first.",
        )

    # Convert LabIntent to dict for JSONB storage
    intent_dict = None
    if data.intent:
        intent_dict = data.intent.model_dump(exclude_none=True)

    # Calculate expiration time based on TTL
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.default_lab_ttl_minutes)

    # Validate effective_runtime (server-owned, never from client)
    # SECURITY: No default - caller must provide explicit runtime
    if effective_runtime == "firecracker":
        runtime_value = RuntimeType.FIRECRACKER.value
    elif effective_runtime in ("compose", "k8s", "noop"):
        runtime_value = RuntimeType.COMPOSE.value  # k8s/noop use compose type for now
    else:
        raise ValueError(
            f"Invalid effective_runtime: {effective_runtime!r}. "
            "This indicates a bug - runtime should be validated at startup."
        )

    # Create new lab with TTL and runtime
    lab = Lab(
        owner_id=user.id,  # Tenant isolation: always use user.id
        recipe_id=recipe.id,
        status=LabStatus.PROVISIONING,
        requested_intent=intent_dict,  # Store as JSONB
        finished_at=None,
        expires_at=expires_at,  # TTL enforcement
        evidence_seal_status=EvidenceSealStatus.NONE.value,
        runtime=runtime_value,  # Server-owned, never from client
    )

    db.add(lab)
    await db.commit()
    await db.refresh(lab)

    # Set evidence volume names (deterministic from lab.id)
    auth_vol, user_vol = get_evidence_volume_names(lab)
    lab.evidence_auth_volume = auth_vol
    lab.evidence_user_volume = user_vol
    await db.commit()

    # Re-fetch the lab with tenant isolation to ensure all server-side values
    # (especially updated_at with onupdate) are loaded for serialization
    result = await db.execute(
        select(Lab).where(
            Lab.id == lab.id,
            Lab.owner_id == user.id,  # Tenant isolation: always scope by owner
        )
    )
    lab = result.scalar_one()

    return lab


async def _mark_lab_failed_with_cleanup(
    session: AsyncSession,
    lab: Lab,
    runtime,
    novnc_port: int | None,
    reason: str,
) -> None:
    """
    Mark a lab as FAILED and perform best-effort cleanup.

    Args:
        session: Database session
        lab: Lab instance to mark failed
        runtime: Lab runtime instance
        novnc_port: Allocated noVNC port (if any)
        reason: Reason for failure (for logging)
    """
    now = datetime.now(timezone.utc)
    lab.status = LabStatus.FAILED
    lab.finished_at = now
    await session.commit()

    logger.error(f"Lab {lab.id} marked FAILED: {reason}")

    # Collect diagnostics (runtime-specific)
    if isinstance(runtime, ComposeLabRuntime):
        # Compose runtime: collect docker compose diagnostics
        project_name = f"octolab_{lab.id}"
        try:
            diagnostics = await collect_compose_diagnostics(
                lab_id=lab.id,
                project_name=project_name,
                compose_file=None,
            )
            logger.warning(f"Diagnostics for failed lab {lab.id}:\n{format_diagnostics_for_log(diagnostics)}")
        except Exception as diag_error:
            logger.warning(f"Failed to collect diagnostics for lab {lab.id}: {type(diag_error).__name__}")
    elif isinstance(runtime, FirecrackerLabRuntime):
        # Firecracker runtime: collect netd + firecracker-specific diagnostics
        # Do NOT run compose commands for firecracker failures
        try:
            from app.services.microvm_net_client import ping_netd_sync
            netd_ok, netd_err = ping_netd_sync(timeout=2.0)
            netd_status = "ok" if netd_ok else f"error: {netd_err}"
            logger.warning(
                f"Firecracker diagnostics for failed lab {lab.id}: netd={netd_status}"
            )
        except Exception as diag_error:
            logger.warning(f"Failed to collect firecracker diagnostics: {type(diag_error).__name__}")

    retain_failed = settings.retain_failed_labs and isinstance(runtime, ComposeLabRuntime)

    if retain_failed:
        logger.warning(
            "OCTOLAB_RETAIN_FAILED_LABS=1 for lab %s - retaining compose resources for debugging",
            lab.id,
        )
    else:
        # Best-effort teardown (time-bounded)
        try:
            await asyncio.wait_for(
                runtime.destroy_lab(lab),
                timeout=30.0,  # Short timeout for cleanup
            )
            logger.info(f"Best-effort teardown completed for failed lab {lab.id}")
        except Exception as teardown_error:
            logger.warning(
                f"Best-effort teardown failed for lab {lab.id}: {type(teardown_error).__name__}"
            )

    # Release port reservation (best-effort)
    if novnc_port is not None:
        try:
            await release_novnc_port(session, lab_id=lab.id)
        except Exception as port_error:
            logger.warning(f"Failed to release port for lab {lab.id}: {type(port_error).__name__}")


async def _provision_lab_inner(
    session: AsyncSession,
    lab: Lab,
    recipe: Recipe,
    runtime,
    novnc_port: int | None,
) -> bool:
    """
    Inner provisioning logic (compose up + readiness probe).

    Returns True if lab is READY, False if it should be marked FAILED.
    Raises exceptions on unrecoverable errors.

    SECURITY:
    - NO FALLBACK: if runtime is Firecracker, use it exclusively
    - If Firecracker fails, do NOT fall back to compose
    """
    # Generate VNC password for compose/firecracker runtime (always required since hardening)
    # In GUAC mode, this password is also used for Guacamole user authentication
    vnc_password: str | None = None
    if not isinstance(runtime, K8sLabRuntime):
        vnc_password = generate_secure_password(24)
        # Store encrypted password if GUAC mode is enabled (for Guacamole auth)
        if settings.guac_enabled:
            try:
                lab.guac_password_enc = encrypt_password(vnc_password)
                await session.commit()
                logger.debug(f"Generated and stored VNC password for lab {lab.id} (GUAC mode)")
            except EncryptionError as e:
                raise RuntimeError(f"Failed to encrypt VNC password: {e}")
        else:
            logger.debug(f"Generated VNC password for lab {lab.id} (non-GUAC mode)")

    # Create lab infrastructure
    # SECURITY: NO FALLBACK - use the runtime specified by lab.runtime
    if isinstance(runtime, FirecrackerLabRuntime):
        # Firecracker runtime - runs compose inside VM
        await runtime.create_lab(lab, recipe, db_session=session, vnc_password=vnc_password)
    elif isinstance(runtime, K8sLabRuntime):
        await runtime.create_lab(lab, recipe)
    else:
        # Compose runtime
        await runtime.create_lab(lab, recipe, db_session=session, vnc_password=vnc_password)

    # Wait for container health (compose runtime only)
    # This uses Docker's healthcheck before probing the HTTP endpoint
    if isinstance(runtime, ComposeLabRuntime):
        health_start = datetime.now(timezone.utc)
        try:
            await runtime.wait_for_healthy(
                lab,
                timeout_seconds=settings.container_health_timeout_seconds,
                poll_interval_seconds=2.0,
            )
            health_elapsed = (datetime.now(timezone.utc) - health_start).total_seconds()
            logger.info(
                f"Container healthcheck passed for lab {lab.id} (elapsed {health_elapsed:.1f}s)"
            )
        except TimeoutError as e:
            logger.warning(
                f"Container healthcheck timeout for lab {lab.id}: {e}. "
                "Proceeding with HTTP probe..."
            )
        except RuntimeError as e:
            # Container is unhealthy - fail immediately
            raise RuntimeError(f"Container unhealthy for lab {lab.id}: {e}")

    # Determine connection URL based on runtime type
    # Note: For Firecracker/Compose with Guacamole enabled, this URL is overwritten
    # by provision_guacamole_for_lab() which sets connection_url = /labs/{id}/connect
    connection_url = None
    if isinstance(runtime, K8sLabRuntime) and runtime.ingress_enabled:
        connection_url = f"http://lab-{lab.id}.{runtime.base_domain}/"
    elif isinstance(runtime, K8sLabRuntime):
        connection_url = None  # Port-forward required
    elif isinstance(runtime, FirecrackerLabRuntime):
        # Firecracker: Guacamole provisioning will set connection_url
        # If Guacamole is disabled, fall back to noVNC (though not recommended)
        if not settings.guac_enabled and lab.novnc_host_port:
            connection_url = f"/vnc/{lab.novnc_host_port}/vnc.html?lab_id={lab.id}"
        else:
            connection_url = None  # Will be set by Guacamole provisioner
    else:
        # Compose runtime: use the allocated port
        if novnc_port:
            bind_host = settings.novnc_bind_addr
            connection_url = f"http://{bind_host}:{novnc_port}/vnc.html?lab_id={lab.id}"
            lab.novnc_host_port = novnc_port
        else:
            connection_url = f"{settings.vnc_base_url}?lab_id={lab.id}"

    # Guacamole provisioning (when enabled, replaces noVNC for connection)
    if settings.guac_enabled and not isinstance(runtime, K8sLabRuntime):
        guac_start = datetime.now(timezone.utc)
        try:
            await provision_guacamole_for_lab(lab, session)
            guac_elapsed = (datetime.now(timezone.utc) - guac_start).total_seconds()
            logger.info(
                f"Guacamole provisioned for lab {lab.id} (elapsed {guac_elapsed:.1f}s)"
            )
            # connection_url is set by provision_guacamole_for_lab
            connection_url = lab.connection_url
        except GuacProvisioningError as e:
            # Guacamole provisioning failed - mark lab as failed
            raise RuntimeError(f"Guacamole provisioning failed: {e}")

    # Server-side readiness gating for noVNC (compose runtime only, when Guacamole not enabled)
    elif settings.novnc_ready_gating_enabled and not isinstance(runtime, K8sLabRuntime) and novnc_port:
        probe_start = datetime.now(timezone.utc)

        # For Firecracker labs, probe guest IP directly (avoids localhost DNAT issues)
        # Note: guest_port is VNC (5900), not noVNC (6080) for Guacamole integration
        if isinstance(runtime, FirecrackerLabRuntime) and lab.runtime_meta:
            probe_host = lab.runtime_meta.get("guest_ip", settings.novnc_bind_addr)
            probe_port = lab.runtime_meta.get("guest_port", 5900)
        else:
            probe_host = settings.novnc_bind_addr
            probe_port = novnc_port

        await probe_novnc_ready(
            host=probe_host,
            port=probe_port,
            timeout_seconds=settings.novnc_ready_timeout_seconds,
            poll_interval_seconds=settings.novnc_ready_poll_interval_seconds,
            paths=settings.novnc_ready_paths,
        )
        probe_elapsed = (datetime.now(timezone.utc) - probe_start).total_seconds()
        logger.info(
            f"noVNC readiness probe succeeded for lab {lab.id} "
            f"(host={probe_host}, port={probe_port}, elapsed {probe_elapsed:.1f}s)"
        )

    # Success: mark READY
    lab.connection_url = connection_url
    lab.status = LabStatus.READY
    await session.commit()
    return True


def _get_runtime_for_lab(lab: Lab):
    """Get the appropriate runtime based on lab.runtime field.

    SECURITY:
    - lab.runtime is server-owned, never from client
    - NO FALLBACK: if firecracker, use firecracker (not compose)
    - For non-firecracker labs, uses configured runtime from settings
    """
    if lab.runtime == RuntimeType.FIRECRACKER.value:
        return FirecrackerLabRuntime()
    # Use configured runtime (validated at startup, no silent default)
    return get_runtime()


async def provision_lab(
    lab_id: UUID,
) -> None:
    """
    Background entrypoint to provision labs and update their status.

    Implements fail-fast behavior with overall startup timeout to prevent
    labs from staying in "Starting" state forever. If provisioning doesn't
    complete within lab_startup_timeout_seconds, the lab is marked FAILED.

    SECURITY:
    - Runtime selection is server-owned based on lab.runtime
    - NO FALLBACK: if lab.runtime=firecracker, use firecracker (not compose)
    """
    provision_start = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        lab = await session.get(Lab, lab_id, with_for_update=True)
        if lab is None:
            logger.warning("Lab %s missing; skipping provisioning", lab_id)
            return

        recipe = await session.get(Recipe, lab.recipe_id)
        if recipe is None:
            logger.warning("Recipe %s missing for lab %s; marking failed", lab.recipe_id, lab.id)
            lab.status = LabStatus.FAILED
            lab.finished_at = datetime.now(timezone.utc)
            await session.commit()
            return

        # Get runtime based on lab.runtime field (server-owned)
        runtime = _get_runtime_for_lab(lab)

        logger.info(
            f"lab_provision runtime={lab.runtime} lab_id={str(lab.id)[-6:]} "
            f"user_id={str(lab.owner_id)[-6:]}"
        )

        # For compose runtime, allocate a port before provisioning
        novnc_port = None
        if not isinstance(runtime, K8sLabRuntime):
            try:
                novnc_port = await allocate_novnc_port(session, lab_id=lab.id, owner_id=lab.owner_id)
            except Exception:
                logger.exception("Failed to allocate port for lab %s; marking as failed", lab.id)
                lab.status = LabStatus.FAILED
                lab.finished_at = datetime.now(timezone.utc)
                await session.commit()
                return

        # Wrap entire provisioning in overall timeout to prevent "Starting forever"
        try:
            await asyncio.wait_for(
                _provision_lab_inner(session, lab, recipe, runtime, novnc_port),
                timeout=settings.lab_startup_timeout_seconds,
            )
            elapsed = (datetime.now(timezone.utc) - provision_start).total_seconds()
            logger.info(f"Lab {lab.id} provisioned successfully (elapsed {elapsed:.1f}s)")

        except asyncio.TimeoutError:
            # Overall startup timeout - fail-fast
            elapsed = (datetime.now(timezone.utc) - provision_start).total_seconds()
            await _mark_lab_failed_with_cleanup(
                session, lab, runtime, novnc_port,
                reason=f"Startup timeout after {elapsed:.1f}s (limit: {settings.lab_startup_timeout_seconds}s)"
            )

        except NovncNotReady as e:
            # Readiness probe failed (within timeout)
            elapsed = (datetime.now(timezone.utc) - provision_start).total_seconds()
            await _mark_lab_failed_with_cleanup(
                session, lab, runtime, novnc_port,
                reason=f"noVNC readiness probe failed after {elapsed:.1f}s: {type(e).__name__}"
            )

        except NetworkPoolExhaustedError as e:
            # Docker network pool exhausted - all subnets in use
            elapsed = (datetime.now(timezone.utc) - provision_start).total_seconds()
            blocked_info = f", blocked_networks={e.blocked_networks}" if e.blocked_networks else ""
            logger.error(
                f"Lab {lab.id} FAILED: Docker network pool exhausted (cleaned={e.cleaned_count}{blocked_info}). "
                f"User should wait for labs to finish or ops should run: docker network prune"
            )
            await _mark_lab_failed_with_cleanup(
                session, lab, runtime, novnc_port,
                reason=f"Docker network pool exhausted (cleaned {e.cleaned_count} networks)"
            )

        except NetworkCleanupBlockedError as e:
            # Network cleanup blocked by containers that aren't in the allowlist
            elapsed = (datetime.now(timezone.utc) - provision_start).total_seconds()
            logger.error(
                f"Lab {lab.id} FAILED: Network cleanup blocked by containers on {e.network_name}. "
                f"Manual intervention required to remove stale containers."
            )
            await _mark_lab_failed_with_cleanup(
                session, lab, runtime, novnc_port,
                reason=f"Network cleanup blocked ({e.network_name})"
            )

        except StaleRootfsError as e:
            # Stale rootfs/agent detected - clear error for operators
            elapsed = (datetime.now(timezone.utc) - provision_start).total_seconds()
            logger.error(
                f"Lab {lab.id} FAILED: stale_rootfs - agent missing version fields "
                f"after {elapsed:.1f}s. Rebuild rootfs: "
                f"sudo infra/firecracker/build-rootfs.sh --with-kernel --deploy"
            )
            await _mark_lab_failed_with_cleanup(
                session, lab, runtime, novnc_port,
                reason="stale_rootfs: agent missing version/build_id fields"
            )

        except FirecrackerRuntimeError as e:
            # Firecracker-specific errors - NO FALLBACK
            elapsed = (datetime.now(timezone.utc) - provision_start).total_seconds()
            logger.error(
                f"Lab {lab.id} FAILED: Firecracker runtime error after {elapsed:.1f}s: "
                f"{type(e).__name__}"
            )
            await _mark_lab_failed_with_cleanup(
                session, lab, runtime, novnc_port,
                reason=f"Firecracker error: {type(e).__name__}"
            )

        except Exception as e:
            # Other provisioning errors
            elapsed = (datetime.now(timezone.utc) - provision_start).total_seconds()
            logger.exception("Provisioning failed for lab %s after %.1fs", lab.id, elapsed)
            await _mark_lab_failed_with_cleanup(
                session, lab, runtime, novnc_port,
                reason=f"Provisioning exception: {type(e).__name__}"
            )


async def terminate_lab(
    lab_id: UUID,
) -> None:
    """
    Background entrypoint to tear down labs and mark them finished/failed.

    Implements a timeout around runtime.destroy_lab to ensure ENDING can't hang forever.
    Behavior is idempotent: if lab is already FINISHED or FAILED, no-op.

    Cancellation-safe: Respects cancellation during shutdown without blocking.
    Use teardown_worker instead of calling this directly.

    SECURITY:
    - Uses runtime based on lab.runtime field (server-owned)
    - Firecracker labs are torn down with Firecracker runtime
    """
    async with AsyncSessionLocal() as session:
        lab = await session.get(Lab, lab_id, with_for_update=True)
        if lab is None:
            logger.info("Lab %s missing during teardown; nothing to do", lab_id)
            return

        # Idempotent: if already terminal, nothing to do
        if lab.status in (LabStatus.FINISHED, LabStatus.FAILED):
            logger.info("Lab %s already terminal (status=%s); skipping teardown", lab.id, lab.status)
            return

        # Get runtime based on lab.runtime field (server-owned)
        runtime = _get_runtime_for_lab(lab)

        # ENDING reconciliation: if resources don't exist, finalize as FINISHED
        if lab.status == LabStatus.ENDING:
            try:
                resources_exist = await runtime.resources_exist_for_lab(lab)
            except Exception as e:
                # If check fails, assume resources exist and proceed with teardown
                logger.warning(
                    "Failed to check resources for lab %s: %s; proceeding with teardown",
                    lab.id,
                    type(e).__name__,
                )
                resources_exist = True

            if not resources_exist:
                # Resources already gone - reconcile DB state to FINISHED
                now = datetime.now(timezone.utc)
                if lab.finished_at is None:
                    lab.finished_at = now
                lab.status = LabStatus.FINISHED
                lab.evidence_expires_at = now + timedelta(hours=24)
                await session.commit()
                logger.info(
                    "Reconciled ENDING lab %s -> FINISHED (runtime resources missing)",
                    lab.id,
                )
                return

        # =======================================================================
        # Seal authoritative evidence BEFORE destroying containers
        # This must happen while containers are still running so logs can be captured
        # =======================================================================
        if not isinstance(runtime, K8sLabRuntime):
            try:
                # Export compose logs to auth volume (best-effort)
                logger.info(f"Exporting compose logs for lab {lab.id}")
                await asyncio.wait_for(
                    export_compose_logs_to_auth_volume(lab),
                    timeout=settings.evidence_export_timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.warning(f"Timeout exporting logs for lab {lab.id}")
            except Exception as e:
                logger.warning(f"Failed to export logs for lab {lab.id}: {type(e).__name__}")

            try:
                # Seal evidence (best-effort, non-blocking on failure)
                logger.info(f"Sealing evidence for lab {lab.id}")
                await asyncio.wait_for(
                    seal_auth_evidence(lab, session),
                    timeout=settings.evidence_seal_timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.warning(f"Timeout sealing evidence for lab {lab.id}")
                lab.evidence_seal_status = EvidenceSealStatus.FAILED.value
                await session.commit()
            except Exception as e:
                logger.warning(f"Failed to seal evidence for lab {lab.id}: {type(e).__name__}")
                lab.evidence_seal_status = EvidenceSealStatus.FAILED.value
                await session.commit()

        # =======================================================================
        # Teardown Guacamole resources (best-effort, before destroying containers)
        # =======================================================================
        if settings.guac_enabled and not isinstance(runtime, K8sLabRuntime):
            try:
                await asyncio.wait_for(
                    teardown_guacamole_for_lab(lab),
                    timeout=30.0,  # Short timeout for Guac cleanup
                )
            except asyncio.TimeoutError:
                logger.warning(f"Timeout cleaning up Guacamole for lab {lab.id}")
            except Exception as e:
                logger.warning(f"Failed to cleanup Guacamole for lab {lab.id}: {type(e).__name__}")

        # =======================================================================
        # Finalize evidence state (best-effort, before destroying volumes)
        # This must happen while volumes still exist
        # =======================================================================
        if not isinstance(runtime, K8sLabRuntime):
            try:
                await asyncio.wait_for(
                    finalize_evidence_state(lab, session),
                    timeout=60.0,  # Timeout for evidence finalization
                )
            except asyncio.TimeoutError:
                logger.warning(f"Timeout finalizing evidence for lab {lab.id}")
            except Exception as e:
                logger.warning(f"Failed to finalize evidence for lab {lab.id}: {type(e).__name__}")

        start = datetime.now(timezone.utc)
        try:
            # No shield: allow cancellation during shutdown
            await asyncio.wait_for(runtime.destroy_lab(lab), timeout=settings.teardown_timeout_seconds)
        except asyncio.CancelledError:
            # Cancellation during shutdown: re-raise without marking FAILED
            # Lab will remain ENDING and be processed again on next startup
            logger.info("Teardown cancelled for lab %s; will retry on next startup", lab.id)
            raise
        except asyncio.TimeoutError:
            # Timeout: mark FAILED and set finished_at for consistency/cleanup
            now = datetime.now(timezone.utc)
            lab.status = LabStatus.FAILED
            lab.finished_at = now
            await session.commit()
            elapsed = (now - start).total_seconds()
            owner_short = str(lab.owner_id)[-6:]
            logger.warning(
                "Teardown timed out for lab %s (owner=****%s) after %.1fs; marked FAILED",
                lab.id,
                owner_short,
                elapsed,
            )
            return
        except Exception as exc:
            now = datetime.now(timezone.utc)
            lab.status = LabStatus.FAILED
            lab.finished_at = now
            await session.commit()
            owner_short = str(lab.owner_id)[-6:]
            logger.exception(
                "Teardown exception for lab %s (owner=****%s) after %.1fs: %s",
                lab.id,
                owner_short,
                (datetime.now(timezone.utc) - start).total_seconds(),
                type(exc).__name__,
            )
            return

        # Success path
        now = datetime.now(timezone.utc)
        lab.status = LabStatus.FINISHED
        lab.finished_at = now
        lab.evidence_expires_at = now + timedelta(hours=24)
        await session.commit()


async def list_labs_for_user(
    db: AsyncSession,
    user: User,
) -> list[Lab]:
    """
    List all labs owned by a user (tenant isolation enforced).

    Args:
        db: Database session
        user: User model instance (for tenant isolation)

    Returns:
        List of Lab instances owned by the user, ordered by created_at DESC
    """
    result = await db.execute(
        select(Lab)
        .where(Lab.owner_id == user.id)  # Tenant isolation filter
        .order_by(Lab.created_at.desc())
    )
    labs = result.scalars().all()
    return list(labs)


async def get_lab_for_user(
    db: AsyncSession,
    user: User,
    lab_id: UUID,
) -> Lab | None:
    """
    Get a single lab by ID with tenant isolation check.

    Args:
        db: Database session
        user: User model instance (for tenant isolation)
        lab_id: UUID of the lab to retrieve

    Returns:
        Lab instance if found and owned by user, None otherwise

    Security:
        Always filters by user.id to enforce tenant isolation.
        Returns None (not raises exception) to allow routes to return 404.
    """
    result = await db.execute(
        select(Lab).where(
            Lab.id == lab_id,
            Lab.owner_id == user.id,  # Tenant isolation filter
        )
    )
    lab = result.scalar_one_or_none()
    return lab


def end_lab_for_user(
    session: Session,
    user: User,
    lab_id: UUID,
) -> Lab:
    """
    Mark a lab as ending for a user (with tenant isolation).

    Args:
        session: Sync database session
        user: User model instance (for tenant isolation)
        lab_id: UUID of the lab to end

    Returns:
        Updated Lab instance with status ENDING

    Raises:
        HTTPException: 404 if lab not found or not owned by user
        HTTPException: 400 if lab cannot be ended from current state

    Note:
        Transitions: REQUESTED → ENDING, READY → ENDING
        The orchestrator will later transition ENDING → FINISHED.
    """
    # Query lab with tenant isolation check
    result = session.execute(
        select(Lab).where(
            Lab.id == lab_id,
            Lab.owner_id == user.id,  # Tenant isolation filter
        )
    )
    lab = result.scalar_one_or_none()

    if lab is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lab not found",
        )

    # Validate current state and transition
    if lab.status in (LabStatus.REQUESTED, LabStatus.READY):
        # Allowed transitions: REQUESTED → ENDING, READY → ENDING
        lab.status = LabStatus.ENDING
    else:
        # Invalid state: raise 400 error
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lab cannot be ended from this state",
        )

    # Commit and refresh
    session.commit()
    session.refresh(lab)

    return lab


# Terminal statuses where evidence can be reconciled (lowercase strings for comparison)
TERMINAL_STATUSES = {"finished", "failed"}


def _enumish_to_str(v) -> str:
    """Safely convert Enum or string to lowercase string.

    Handles both SQLAlchemy model fields (which may be strings) and
    Python Enum values (which have .value attribute).
    """
    try:
        return v.value.lower() if hasattr(v, "value") else str(v).lower()
    except Exception:
        return str(v).lower()


async def reconcile_evidence_state_if_needed(
    lab: Lab,
    db_session: AsyncSession,
) -> bool:
    """Reconcile evidence_state for terminal labs stuck in 'collecting'.

    This is a self-healing mechanism that computes evidence_state from disk
    when a lab is terminal but evidence_state was never finalized (e.g., due
    to a missed teardown event or server restart).

    SECURITY:
    - Only runs for terminal labs (finished/failed) to avoid turning
      GET /labs/{id} into an expensive filesystem oracle
    - All paths derived from lab.id + configured evidence volumes
    - No file lists/paths exposed to non-admin callers
    - Runs once per lab (sets evidence_finalized_at to prevent re-runs)
    - Fail-safe: exceptions are caught and logged, never propagated to caller

    NOTE: Uses flush() instead of commit() to avoid MissingGreenlet issues
    during Pydantic serialization in GET handlers. The caller (GET endpoint)
    should refresh the lab instance after this returns True.

    Args:
        lab: Lab model instance
        db_session: Async database session

    Returns:
        True if evidence_state was updated, False otherwise (including on error)

    Note:
        On IO errors during finalization, sets evidence_state to 'unavailable'
        rather than blocking the API response. On unexpected exceptions in the
        reconcile logic itself, returns False without mutating state.
    """
    try:
        # Normalize enum-ish fields to lowercase strings for safe comparison
        status_str = _enumish_to_str(lab.status).strip()
        ev_state_str = _enumish_to_str(lab.evidence_state).strip() if lab.evidence_state else ""

        # Skip if not a terminal lab
        if status_str not in TERMINAL_STATUSES:
            return False

        # Skip if already finalized
        if lab.evidence_finalized_at is not None:
            return False

        # Skip if not in collecting state (already has a computed state)
        if ev_state_str != "collecting":
            return False

        logger.info(
            f"Reconciling evidence_state for terminal lab {lab.id} "
            f"(status={status_str}, evidence_state={ev_state_str})"
        )

        # Use finalize_evidence_state with commit=False to avoid MissingGreenlet
        # The GET handler should refresh the lab after reconcile returns True
        try:
            await finalize_evidence_state(lab, db_session, commit=False)
            logger.info(
                f"Reconciled evidence_state for lab {lab.id}: {lab.evidence_state}"
            )
            return True
        except Exception as e:
            # On finalization error, mark as unavailable to prevent infinite retries
            logger.warning(
                f"Failed to reconcile evidence for lab {lab.id}: {type(e).__name__}. "
                "Setting state to unavailable."
            )
            now = datetime.now(timezone.utc)
            lab.evidence_state = EvidenceState.UNAVAILABLE.value
            lab.evidence_finalized_at = now
            await db_session.flush()  # Use flush, not commit
            return True

    except Exception as e:
        # Fail-safe: log and return False, never crash the GET endpoint
        logger.warning(
            f"Reconcile check failed for lab {lab.id}: {type(e).__name__}. "
            "Skipping reconciliation."
        )
        return False

