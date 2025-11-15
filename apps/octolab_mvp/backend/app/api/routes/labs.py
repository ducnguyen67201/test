"""Lab endpoints for creating, listing, retrieving, and ending labs."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_session
from app.db import get_db
from app.models.user import User
from app.schemas.lab import LabCreate, LabResponse
from app.services.lab_service import (
    create_lab_for_user,
    end_lab_for_user,
    get_lab_for_user,
    list_labs_for_user,
)

router = APIRouter(prefix="/labs", tags=["labs"])


@router.post(
    "/",
    response_model=LabResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new lab",
)
async def create_lab(
    request: LabCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LabResponse:
    """
    Create a new lab for the current user.

    Args:
        request: Lab creation request with recipe_id and/or intent
        current_user: Current authenticated user (from dependency)
        db: Database session

    Returns:
        LabResponse: Created lab information

    Raises:
        HTTPException: 400 if recipe validation fails or neither recipe_id nor intent provided
        HTTPException: 404 if recipe not found or no matching recipe found
    """
    lab = await create_lab_for_user(
        db=db,
        user=current_user,
        data=request,
    )

    return LabResponse.model_validate(lab)


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

