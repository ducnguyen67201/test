"""Lab service for lab lifecycle management and tenant isolation."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.lab import Lab, LabStatus
from app.models.recipe import Recipe
from app.models.user import User
from app.schemas.lab import LabCreate, LabIntent


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
) -> Lab:
    """
    Create a new lab for a user with recipe validation or selection.

    Args:
        db: Database session
        user: User model instance (for tenant isolation and owner_id)
        data: LabCreate schema (contains recipe_id and/or intent)

    Returns:
        Created Lab instance

    Raises:
        HTTPException: 400 if recipe validation fails or neither recipe_id nor intent provided
        HTTPException: 404 if recipe not found or no matching recipe found
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

    # Convert LabIntent to dict for JSONB storage
    intent_dict = None
    if data.intent:
        intent_dict = data.intent.model_dump(exclude_none=True)

    # Create new lab
    lab = Lab(
        owner_id=user.id,  # Tenant isolation: always use user.id
        recipe_id=recipe.id,
        status=LabStatus.REQUESTED,
        requested_intent=intent_dict,  # Store as JSONB
        finished_at=None,
    )

    db.add(lab)
    await db.commit()
    await db.refresh(lab)

    return lab


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

