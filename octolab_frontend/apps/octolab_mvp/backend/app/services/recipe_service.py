"""Business logic for recipes."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recipe import Recipe


async def list_recipes(session: AsyncSession) -> list[Recipe]:
    """
    Return all active recipes.

    Args:
        session: Async database session.

    Returns:
        list[Recipe]: Active recipes ordered by creation time.
    """

    result = await session.execute(
        select(Recipe)
        .where(Recipe.is_active.is_(True))
        .order_by(Recipe.created_at.desc())
    )
    return result.scalars().all()

