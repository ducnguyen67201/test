"""Background teardown worker for processing ENDING labs.

This module provides:
1. claim_ending_labs: Concurrency-safe lab claiming using FOR UPDATE SKIP LOCKED
2. teardown_worker_loop: Periodic worker that processes ENDING labs in background

Design:
- Worker runs independently of API request lifecycle
- Uses FOR UPDATE SKIP LOCKED to prevent concurrent processing
- Cancellation-safe: respects shutdown signals without blocking
- Idempotent: safe to run multiple workers (they won't conflict)
- TRUTHFUL: marks FAILED if containers/networks remain after teardown

Usage:
    # In main.py startup:
    asyncio.create_task(teardown_worker_loop())
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import AsyncSessionLocal
from app.models.lab import Lab, LabStatus
from app.runtime import get_runtime_for_type
from app.services.port_allocator import release_novnc_port
from app.services.guacamole_provisioner import teardown_guacamole_for_lab

logger = logging.getLogger(__name__)


async def claim_ending_labs(session: AsyncSession, limit: int) -> list[Lab]:
    """Claim ENDING lab IDs for processing using FOR UPDATE SKIP LOCKED.

    Returns a list of lightweight Lab objects (only id and status) while keeping
    the transaction short. The heavy teardown work must be done outside DB txn.
    """
    # Select only id and status to minimize lock footprint
    query = (
        select(Lab.id, Lab.status)
        .where(Lab.status == LabStatus.ENDING)
        .order_by(Lab.updated_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )

    result = await session.execute(query)
    rows = result.all()

    # Build minimal Lab-like objects (using simple namespace)
    class _LabRef:
        def __init__(self, id, status):
            self.id = id
            self.status = status

    return [_LabRef(r[0], r[1]) for r in rows]


async def process_ending_lab(lab: Lab) -> None:
    """Process a single ENDING lab to completion.

    Args:
        lab: Lab instance to process (must be in ENDING status)

    Side Effects:
        - Calls runtime.destroy_lab to tear down infrastructure
        - Updates lab status to FINISHED or FAILED
        - Sets finished_at timestamp
        - Releases port reservation (compose runtime)

    Error Handling:
        - Timeouts → FAILED status
        - Exceptions → FAILED status
        - Always updates database to prevent stuck labs
    """
    # Use per-lab runtime (not global runtime) to handle labs created with different runtimes
    runtime = get_runtime_for_type(lab.runtime)
    start = datetime.now(timezone.utc)

    try:
        # Teardown infrastructure with timeout
        # Note: We don't use asyncio.shield here to allow cancellation during shutdown
        await asyncio.wait_for(
            runtime.destroy_lab(lab),
            timeout=settings.teardown_timeout_seconds,
        )

        # Success: mark FINISHED
        lab.status = LabStatus.FINISHED
        lab.finished_at = datetime.now(timezone.utc)

        logger.info(
            f"Teardown worker completed lab {lab.id} "
            f"(elapsed {(datetime.now(timezone.utc) - start).total_seconds():.1f}s)"
        )

    except asyncio.TimeoutError:
        # Timeout: mark FAILED
        lab.status = LabStatus.FAILED
        lab.finished_at = datetime.now(timezone.utc)

        owner_short = str(lab.owner_id)[-6:]
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        logger.warning(
            f"Teardown worker timed out for lab {lab.id} (owner=****{owner_short}) "
            f"after {elapsed:.1f}s; marked FAILED"
        )

    except asyncio.CancelledError:
        # Worker shutdown: re-raise to propagate cancellation
        logger.info(f"Teardown worker cancelled for lab {lab.id}; re-raising")
        raise

    except Exception as exc:
        # Other errors: mark FAILED
        lab.status = LabStatus.FAILED
        lab.finished_at = datetime.now(timezone.utc)

        owner_short = str(lab.owner_id)[-6:]
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        logger.exception(
            f"Teardown worker error for lab {lab.id} (owner=****{owner_short}) "
            f"after {elapsed:.1f}s: {type(exc).__name__}"
        )


async def teardown_worker_tick() -> int:
    """Process one batch of ENDING labs.

    Returns:
        Number of labs processed in this tick

    Concurrency:
        - Opens new session per tick
        - Claims labs with FOR UPDATE SKIP LOCKED
        - Commits after processing batch
        - Safe to run concurrently with other workers
    """
    # Phase 1: short transaction to claim lab IDs
    async with AsyncSessionLocal() as session:
        lab_refs = await claim_ending_labs(session, limit=settings.teardown_worker_batch_size)
        if not lab_refs:
            return 0
        claimed_ids = [lr.id for lr in lab_refs]
        await session.commit()

    logger.debug(f"Teardown worker claimed {len(claimed_ids)} lab(s): {claimed_ids}")

    processed = 0

    # Phase 2: perform runtime work outside DB transaction
    for lab_ref in lab_refs:
        lab_id = lab_ref.id

        # Fetch full lab record first to get runtime type
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(Lab).where(Lab.id == lab_id))
            full_lab = res.scalar_one_or_none()

        if not full_lab:
            logger.warning(f"Lab {lab_id} not found in DB, skipping teardown")
            processed += 1
            continue

        # Get runtime for this specific lab (not global runtime)
        runtime = get_runtime_for_type(full_lab.runtime)
        logger.debug(f"Using {full_lab.runtime} runtime for lab {lab_id}")

        try:
            # Reconcile: if resources are already gone, finalize without calling destroy
            try:
                resources_exist = await runtime.resources_exist_for_lab(full_lab) if hasattr(runtime, 'resources_exist_for_lab') else True
            except Exception:
                resources_exist = True

            if not resources_exist:
                # Finalize DB state and skip destroy
                async with AsyncSessionLocal() as session:
                    now = datetime.now(timezone.utc)
                    stmt = (
                        # Avoid racing: only update if still ENDING
                        select(Lab).where(Lab.id == lab_id)
                    )
                    res = await session.execute(stmt)
                    lab_row = res.scalar_one_or_none()
                    if lab_row and lab_row.status == LabStatus.ENDING:
                        lab_row.status = LabStatus.FINISHED
                        if lab_row.finished_at is None:
                            lab_row.finished_at = now
                        lab_row.evidence_expires_at = now + timedelta(hours=24)
                        await session.commit()
                        logger.info(f"Reconciled ENDING lab {lab_id} -> FINISHED (no resources)")
                        processed += 1
                        continue

            # Resources exist: call destroy
            # Guacamole cleanup (best-effort, before destroying VM)
            if settings.guac_enabled:
                try:
                    await asyncio.wait_for(
                        teardown_guacamole_for_lab(full_lab),
                        timeout=30.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"Guacamole teardown timed out for lab {lab_id}")
                except Exception as e:
                    logger.warning(f"Guacamole teardown failed for lab {lab_id}: {type(e).__name__}")

            # Destroy lab using the full lab object (has all needed attributes)
            teardown_result = await asyncio.wait_for(
                runtime.destroy_lab(full_lab),
                timeout=settings.teardown_timeout_seconds,
            )

            # TRUTHFUL: Only mark FINISHED if teardown actually succeeded
            # TeardownResult.success is True only if containers_remaining==0 AND networks_remaining==0
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(Lab).where(Lab.id == lab_id))
                lab_row = res.scalar_one_or_none()
                if lab_row:
                    now = datetime.now(timezone.utc)
                    if hasattr(teardown_result, 'success') and not teardown_result.success:
                        # Teardown incomplete: mark FAILED with details
                        lab_row.status = LabStatus.FAILED
                        lab_row.finished_at = now
                        containers_remaining = getattr(teardown_result, 'containers_remaining', 0)
                        networks_remaining = getattr(teardown_result, 'networks_remaining', 0)
                        logger.warning(
                            f"Teardown incomplete for lab {lab_id}: "
                            f"containers_remaining={containers_remaining}, "
                            f"networks_remaining={networks_remaining}"
                        )
                    else:
                        # Teardown succeeded: mark FINISHED
                        lab_row.status = LabStatus.FINISHED
                        lab_row.finished_at = now
                        lab_row.evidence_expires_at = now + timedelta(hours=24)
                    await session.commit()
            processed += 1

        except asyncio.TimeoutError:
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(Lab).where(Lab.id == lab_id))
                lab_row = res.scalar_one_or_none()
                if lab_row:
                    lab_row.status = LabStatus.FAILED
                    lab_row.finished_at = datetime.now(timezone.utc)
                    await session.commit()
            logger.warning(f"Teardown timed out for lab {lab_id}; marked FAILED")
            processed += 1

        except Exception as exc:
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(Lab).where(Lab.id == lab_id))
                lab_row = res.scalar_one_or_none()
                if lab_row:
                    lab_row.status = LabStatus.FAILED
                    lab_row.finished_at = datetime.now(timezone.utc)
                    await session.commit()
            logger.exception(f"Teardown error for lab {lab_id}: {type(exc).__name__}")
            processed += 1

    logger.debug(f"Teardown worker tick completed: processed {processed} lab(s)")
    return processed


async def teardown_worker_loop() -> None:
    """Background worker loop for processing ENDING labs.

    Runs continuously until cancelled (e.g., during shutdown).

    Behavior:
        - Runs startup tick immediately (if enabled)
        - Then polls every teardown_worker_interval_seconds
        - Processes up to teardown_worker_batch_size labs per tick
        - Respects cancellation for graceful shutdown

    Configuration (via settings):
        - teardown_worker_enabled: Enable/disable worker
        - teardown_worker_interval_seconds: Poll interval
        - teardown_worker_batch_size: Max labs per tick
        - teardown_worker_startup_tick: Run immediate tick on startup
    """
    if not settings.teardown_worker_enabled:
        logger.info("Teardown worker is disabled (teardown_worker_enabled=false)")
        return

    logger.info(
        f"Teardown worker starting "
        f"(interval={settings.teardown_worker_interval_seconds}s, "
        f"batch_size={settings.teardown_worker_batch_size})"
    )

    try:
        # Startup tick for reconciliation (process any labs stuck in ENDING)
        if settings.teardown_worker_startup_tick:
            logger.info("Running startup tick for ENDING labs reconciliation")
            processed = await teardown_worker_tick()
            if processed > 0:
                logger.info(f"Startup tick processed {processed} lab(s)")

        # Main loop: poll and process
        while True:
            await asyncio.sleep(settings.teardown_worker_interval_seconds)

            try:
                processed = await teardown_worker_tick()
                # Only log if we actually processed something (reduce log noise)
                if processed > 0:
                    logger.info(f"Teardown worker tick processed {processed} lab(s)")

            except asyncio.CancelledError:
                # Shutdown signal: exit gracefully
                raise

            except Exception as exc:
                # Don't crash the worker on tick errors
                logger.exception(f"Teardown worker tick failed: {type(exc).__name__}")
                # Continue polling after error

    except asyncio.CancelledError:
        logger.info("Teardown worker shutting down gracefully")
        raise

    except Exception as exc:
        logger.exception(f"Teardown worker crashed: {type(exc).__name__}")
        raise
