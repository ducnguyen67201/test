"""Port allocation service for dynamic noVNC port assignment in compose runtime."""

import logging
import secrets
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.lab import Lab

logger = logging.getLogger(__name__)


async def allocate_novnc_port(session: AsyncSession, *, lab_id: UUID, owner_id: UUID) -> int:
    """
    Allocate a unique noVNC host port for a lab with concurrency handling.
    
    Args:
        session: Database session for transaction
        lab_id: ID of the lab requesting the port
        owner_id: Owner ID for tenant scoping (must match authenticated principal)
        
    Returns:
        Allocated port number
        
    Raises:
        RuntimeError: If unable to allocate a unique port after bounded retries
    """
    # First, check if lab already has a port allocated (idempotency)
    result = await session.execute(
        select(Lab.novnc_host_port).where(
            and_(
                Lab.id == lab_id,
                Lab.owner_id == owner_id  # Tenant isolation
            )
        )
    )
    existing_port = result.scalar_one_or_none()
    
    if existing_port is not None:
        logger.debug(f"Lab {lab_id} already has port {existing_port}, returning existing allocation")
        return existing_port
    
    # Try to allocate a port with bounded retries
    max_retries = 50  # Bounded retries to avoid infinite loops
    used_candidates = set()  # Track attempted candidates to avoid repeated attempts
    
    for attempt in range(max_retries):
        # Generate a candidate port in the configured range
        candidate_port = secrets.randbelow(settings.compose_port_max - settings.compose_port_min + 1) + settings.compose_port_min
        
        # Skip if we've already tried this candidate
        if candidate_port in used_candidates:
            continue
        used_candidates.add(candidate_port)
        
        try:
            # Attempt to update the specific lab with the port using SQLAlchemy Core syntax
            # This is done with tenant isolation (owner_id must match)
            from sqlalchemy import text

            result = await session.execute(
                text("UPDATE labs SET novnc_host_port = :port WHERE id = :lab_id AND owner_id = :owner_id AND novnc_host_port IS NULL"),
                {
                    "port": candidate_port,
                    "lab_id": lab_id,
                    "owner_id": owner_id
                }
            )

            if result.rowcount == 1:
                # Successfully updated one row (our lab)
                await session.commit()
                logger.info(f"Allocated port {candidate_port} for lab {lab_id}")
                return candidate_port
            else:
                # Another process may have allocated a port or lab was updated with a different owner
                await session.rollback()
                continue

        except IntegrityError:
            # Port collision occurred (another lab grabbed this port)
            await session.rollback()
            continue
    
    # If we exhausted all retries
    raise RuntimeError(
        f"Unable to allocate unique noVNC port after {max_retries} attempts for lab {lab_id}. "
        f"All attempted ports were already reserved by other labs. "
        f"Try expanding the port range (currently {settings.compose_port_min}-{settings.compose_port_max})"
    )


async def release_novnc_port(session: AsyncSession, *, lab_id: UUID) -> bool:
    """
    Release the noVNC host port reservation for a lab.

    This function is intentionally keyed by lab_id only (not owner_id) to allow
    teardown workers to release ports without needing the full lab entity.
    Port reservations are unique per lab_id, so owner_id is not required.

    Args:
        session: Database session for transaction
        lab_id: ID of the lab releasing the port

    Returns:
        True if port was released, False if no active reservation existed

    Note:
        This function is idempotent - calling it multiple times is safe.
        Failures are logged but do not raise exceptions (best-effort release).
    """
    from sqlalchemy import text

    try:
        result = await session.execute(
            text("UPDATE labs SET novnc_host_port = NULL WHERE id = :lab_id AND novnc_host_port IS NOT NULL"),
            {"lab_id": lab_id}
        )

        rows_affected = result.rowcount
        await session.commit()

        if rows_affected > 0:
            logger.info(f"Released noVNC port for lab {lab_id}")
            return True
        else:
            logger.debug(f"No active noVNC port reservation for lab {lab_id} to release")
            return False

    except Exception as e:
        # Best-effort: log and continue, don't fail teardown on port release issues
        logger.warning(f"Failed to release noVNC port for lab {lab_id}: {type(e).__name__}")
        try:
            await session.rollback()
        except Exception:
            pass
        return False