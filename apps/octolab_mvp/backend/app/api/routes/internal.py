"""Internal endpoints for orchestrator and administrative operations."""

import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.deps import get_async_session, get_session
from app.config import settings
from app.models.evidence import Evidence
from app.models.lab import Lab
from app.services.orchestrator_service import advance_lab_states

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])

# In-memory rate limiting and deduplication cache
# Structure: {lab_id: {"count": int, "window_start": float}}
_rate_limit_cache: dict[str, dict] = {}
# Structure: {event_hash: expiry_timestamp}
_dedup_cache: dict[str, float] = {}

# Container name pattern: lab-{uuid}-{role}
CONTAINER_NAME_PATTERN = re.compile(r"^lab-([0-9a-f-]{36})-\w+$", re.IGNORECASE)

# Rate limit cache cleanup interval (5 minutes)
RATE_LIMIT_CACHE_TTL = 300.0


class FalcoEvent(BaseModel):
    """Single Falco event payload."""

    type: str = Field(..., description="Event type: command, network, file_read")
    timestamp: str = Field(..., description="ISO 8601 timestamp from Falco")
    container: str = Field(..., description="Container name (lab-{uuid}-{role})")
    user: str | None = Field(default=None, description="Unix username")
    uid: int | None = Field(default=None, description="Unix user ID")
    cmdline: str | None = Field(default=None, description="Command line (for command events)")
    cwd: str | None = Field(default=None, description="Current working directory")
    ppid: int | None = Field(default=None, description="Parent process ID")
    pname: str | None = Field(default=None, description="Parent process name")
    proto: str | None = Field(default=None, description="Protocol (for network events)")
    src_ip: str | None = Field(default=None, description="Source IP")
    src_port: int | None = Field(default=None, description="Source port")
    dst_ip: str | None = Field(default=None, description="Destination IP")
    dst_port: int | None = Field(default=None, description="Destination port")
    file: str | None = Field(default=None, description="File path (for file_read events)")


class FalcoIngestRequest(BaseModel):
    """Request body for Falco event ingestion."""

    events: list[FalcoEvent] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of Falco events to ingest",
    )


class FalcoIngestResponse(BaseModel):
    """Response for Falco event ingestion."""

    accepted: int = Field(..., description="Number of events accepted")
    rejected: int = Field(..., description="Number of events rejected (rate limit/dedup)")
    errors: list[str] = Field(default_factory=list, description="Error messages if any")


def verify_internal_token(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Verify the internal API token from Authorization header.

    Raises:
        HTTPException: 401 if token is missing or invalid
    """
    if not settings.internal_token:
        # Token not configured - reject all requests in production
        if settings.app_env.lower() not in ("dev", "test"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Internal token not configured",
            )
        # In dev/test, allow requests without token for easier testing
        return

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
        )

    # Expect "Bearer <token>" format
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization format. Expected: Bearer <token>",
        )

    token = parts[1]
    # Constant-time comparison to prevent timing attacks
    # SECURITY: SecretStr requires .get_secret_value() to access the value
    import secrets
    if not secrets.compare_digest(token, settings.internal_token.get_secret_value()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


def extract_lab_id(container_name: str) -> UUID | None:
    """Extract lab UUID from container name.

    Args:
        container_name: Container name in format lab-{uuid}-{role}

    Returns:
        Lab UUID or None if pattern doesn't match
    """
    match = CONTAINER_NAME_PATTERN.match(container_name)
    if not match:
        return None
    try:
        return UUID(match.group(1))
    except ValueError:
        return None


def _cleanup_rate_limit_cache() -> None:
    """Clean stale rate limit entries to prevent memory leak.

    Removes entries older than RATE_LIMIT_CACHE_TTL to prevent unbounded growth.
    Called periodically from check_rate_limit().
    """
    now = time.time()
    expired = [k for k, v in _rate_limit_cache.items()
               if now - v["window_start"] > RATE_LIMIT_CACHE_TTL]
    for k in expired:
        del _rate_limit_cache[k]


def check_rate_limit(lab_id: str) -> bool:
    """Check if lab is within rate limit.

    Returns:
        True if within limit, False if rate limited
    """
    # Clean stale entries to prevent unbounded memory growth
    _cleanup_rate_limit_cache()

    now = time.time()
    window_duration = 60.0  # 1 minute window
    limit = settings.falco_rate_limit_per_lab

    if lab_id not in _rate_limit_cache:
        _rate_limit_cache[lab_id] = {"count": 1, "window_start": now}
        return True

    entry = _rate_limit_cache[lab_id]

    # Check if window expired
    if now - entry["window_start"] > window_duration:
        entry["count"] = 1
        entry["window_start"] = now
        return True

    # Check limit
    if entry["count"] >= limit:
        return False

    entry["count"] += 1
    return True


def compute_event_hash(lab_id: UUID, event: FalcoEvent) -> str:
    """Compute SHA256 hash for deduplication.

    Hash is based on: lab_id + timestamp + event type + key fields
    """
    # Build canonical string for hashing
    parts = [
        str(lab_id),
        event.timestamp,
        event.type,
        event.container,
    ]

    if event.type == "command":
        parts.extend([str(event.cmdline), str(event.cwd)])
    elif event.type == "network":
        parts.extend([str(event.dst_ip), str(event.dst_port), str(event.proto)])
    elif event.type == "file_read":
        parts.append(str(event.file))

    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode()).hexdigest()


def check_dedup(event_hash: str) -> bool:
    """Check if event is duplicate (already seen recently).

    Returns:
        True if duplicate, False if new
    """
    now = time.time()
    ttl = settings.falco_dedup_ttl_seconds

    # Clean expired entries periodically
    if len(_dedup_cache) > 10000:
        expired = [k for k, v in _dedup_cache.items() if v < now]
        for k in expired:
            del _dedup_cache[k]

    if event_hash in _dedup_cache:
        if _dedup_cache[event_hash] > now:
            return True  # Still valid, duplicate
        else:
            del _dedup_cache[event_hash]

    # Add to cache
    _dedup_cache[event_hash] = now + ttl
    return False


async def store_evidence_batch(
    session: AsyncSession,
    events: list[tuple[UUID, str, str, datetime, dict, str]],
) -> int:
    """Store batch of evidence events in database.

    Args:
        session: Async database session
        events: List of (lab_id, event_type, container_name, timestamp, payload, event_hash)

    Returns:
        Number of events successfully stored
    """
    if not events:
        return 0

    stored = 0
    for lab_id, event_type, container_name, timestamp, payload, event_hash in events:
        try:
            # Use upsert to handle race conditions
            stmt = pg_insert(Evidence).values(
                lab_id=lab_id,
                event_type=event_type,
                container_name=container_name,
                timestamp=timestamp,
                payload=payload,
                event_hash=event_hash,
            ).on_conflict_do_nothing(index_elements=["event_hash"])

            await session.execute(stmt)
            stored += 1
        except Exception as e:
            logger.warning(f"Failed to store evidence: {e}")

    await session.commit()
    return stored


@router.post(
    "/orchestrator/tick",
    summary="Trigger orchestrator to advance lab states",
    response_model=dict[str, int],
)
def orchestrator_tick(
    session: Session = Depends(get_session),
) -> dict[str, int]:
    """Advance lab states in bulk.

    This is an internal maintenance endpoint.

    Transitions:
    - REQUESTED → READY
    - ENDING → FINISHED

    Returns:
        Dictionary with counts: {"to_ready": int, "to_finished": int}
    """
    return advance_lab_states(session)


@router.post(
    "/falco/ingest",
    summary="Ingest Falco events from lab containers",
    response_model=FalcoIngestResponse,
    dependencies=[Depends(verify_internal_token)],
)
async def falco_ingest(
    request: FalcoIngestRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_session),
) -> FalcoIngestResponse:
    """Ingest Falco events from lab containers.

    This endpoint receives events from Falco's HTTP output and stores them
    as evidence in the database. It implements:
    - Token-based authentication (via verify_internal_token dependency)
    - Rate limiting per lab (configurable via FALCO_RATE_LIMIT_PER_LAB)
    - Deduplication via event hash (configurable TTL via FALCO_DEDUP_TTL_SECONDS)
    - Background storage for better performance

    Security:
    - Only accepts events from containers matching lab-{uuid}-{role} pattern
    - Validates lab existence before storing (404 = dropped silently)
    - Events are linked to labs via extracted UUID, not user input
    """
    accepted = 0
    rejected = 0
    errors: list[str] = []
    events_to_store: list[tuple[UUID, str, str, datetime, dict, str]] = []

    # Group events by lab for rate limiting
    lab_events: dict[str, list[FalcoEvent]] = {}
    for event in request.events:
        lab_id = extract_lab_id(event.container)
        if lab_id is None:
            # Not a lab container, silently drop
            rejected += 1
            continue

        lab_id_str = str(lab_id)
        if lab_id_str not in lab_events:
            lab_events[lab_id_str] = []
        lab_events[lab_id_str].append(event)

    # Process events per lab with rate limiting
    for lab_id_str, events in lab_events.items():
        lab_id = UUID(lab_id_str)

        # Check rate limit
        if not check_rate_limit(lab_id_str):
            rejected += len(events)
            logger.debug(f"Rate limited events for lab {lab_id_str}")
            continue

        # Verify lab exists
        result = await session.execute(select(Lab).where(Lab.id == lab_id))
        lab = result.scalar_one_or_none()
        if lab is None:
            # Lab doesn't exist, silently drop events
            rejected += len(events)
            continue

        # Process individual events
        for event in events:
            event_hash = compute_event_hash(lab_id, event)

            # Check deduplication
            if check_dedup(event_hash):
                rejected += 1
                continue

            # Parse timestamp
            try:
                ts = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
            except ValueError:
                ts = datetime.now(timezone.utc)

            # Prepare event for storage
            events_to_store.append((
                lab_id,
                event.type,
                event.container,
                ts,
                event.model_dump(exclude_none=True),
                event_hash,
            ))
            accepted += 1

    # Store events in background for better response time
    if events_to_store:
        # Store directly since we're already async
        stored = await store_evidence_batch(session, events_to_store)
        if stored < len(events_to_store):
            errors.append(f"Stored {stored}/{len(events_to_store)} events")

    return FalcoIngestResponse(
        accepted=accepted,
        rejected=rejected,
        errors=errors,
    )
