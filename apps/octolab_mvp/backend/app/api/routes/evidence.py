"""Evidence API routes for retrieving Falco events."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_session, get_current_user
from app.models.evidence import Evidence
from app.models.lab import Lab
from app.models.user import User

router = APIRouter(prefix="/evidence", tags=["evidence"])


class EvidenceEvent(BaseModel):
    """Single evidence event response."""

    id: UUID
    lab_id: UUID
    event_type: str
    container_name: str
    timestamp: datetime
    payload: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class EvidenceListResponse(BaseModel):
    """Paginated evidence list response."""

    events: list[EvidenceEvent]
    total: int = Field(..., description="Total number of matching events")
    limit: int = Field(..., description="Max events per page")
    offset: int = Field(..., description="Current offset")
    has_more: bool = Field(..., description="Whether more events exist")


async def verify_lab_ownership(
    lab_id: UUID,
    session: AsyncSession,
    current_user: User,
) -> Lab:
    """Verify user owns the lab.

    Args:
        lab_id: Lab UUID to verify
        session: Database session
        current_user: Authenticated user

    Returns:
        Lab instance if owned by user

    Raises:
        HTTPException: 404 if lab not found OR not owned by user (to avoid leaking existence)
    """
    result = await session.execute(
        select(Lab).where(Lab.id == lab_id)
    )
    lab = result.scalar_one_or_none()

    if lab is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lab not found",
        )

    # Security: Return 404 (not 403) to avoid leaking lab existence
    if lab.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lab not found",
        )

    return lab


@router.get(
    "/labs/{lab_id}/events",
    summary="Retrieve evidence events for a lab",
    response_model=EvidenceListResponse,
)
async def get_lab_evidence_events(
    lab_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    event_type: Annotated[
        Literal["command", "network", "file_read"] | None,
        Query(description="Filter by event type"),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=1000, description="Max events to return"),
    ] = 100,
    offset: Annotated[
        int,
        Query(ge=0, description="Number of events to skip"),
    ] = 0,
) -> EvidenceListResponse:
    """Retrieve evidence events for a lab.

    Requires authentication and verifies lab ownership. Returns 404 if:
    - Lab does not exist
    - User does not own the lab (to avoid leaking existence)

    Supports pagination and filtering by event type.
    Events are ordered by timestamp descending (most recent first).
    """
    # Verify ownership (raises 404 if not found or not owned)
    await verify_lab_ownership(lab_id, session, current_user)

    # Build query
    query = select(Evidence).where(Evidence.lab_id == lab_id)

    if event_type:
        query = query.where(Evidence.event_type == event_type)

    # Get total count
    count_query = select(func.count()).select_from(
        query.subquery()
    )
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Get paginated results (most recent first)
    query = query.order_by(Evidence.timestamp.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    events = result.scalars().all()

    return EvidenceListResponse(
        events=[EvidenceEvent.model_validate(e) for e in events],
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(events) < total,
    )


@router.get(
    "/labs/{lab_id}/events/summary",
    summary="Get evidence summary for a lab",
)
async def get_lab_evidence_summary(
    lab_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    """Get a summary of evidence events for a lab.

    Returns counts by event type and time range.
    """
    # Verify ownership (raises 404 if not found or not owned)
    await verify_lab_ownership(lab_id, session, current_user)

    # Get counts by type
    type_counts_query = (
        select(Evidence.event_type, func.count().label("count"))
        .where(Evidence.lab_id == lab_id)
        .group_by(Evidence.event_type)
    )
    type_result = await session.execute(type_counts_query)
    type_counts = {row.event_type: row.count for row in type_result}

    # Get time range
    time_range_query = (
        select(
            func.min(Evidence.timestamp).label("first_event"),
            func.max(Evidence.timestamp).label("last_event"),
        )
        .where(Evidence.lab_id == lab_id)
    )
    time_result = await session.execute(time_range_query)
    time_row = time_result.one()

    return {
        "lab_id": str(lab_id),
        "total_events": sum(type_counts.values()),
        "by_type": type_counts,
        "first_event_at": time_row.first_event.isoformat() if time_row.first_event else None,
        "last_event_at": time_row.last_event.isoformat() if time_row.last_event else None,
    }
