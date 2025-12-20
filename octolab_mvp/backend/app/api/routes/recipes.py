"""Recipe endpoints for listing available lab templates."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.recipe import RecipeResponse
from app.services.recipe_service import list_recipes

router = APIRouter(prefix="/recipes", tags=["recipes"])


@router.get(
    "/",
    response_model=list[RecipeResponse],
    summary="List active recipes",
)
async def get_recipes(
    db: AsyncSession = Depends(get_db),
) -> list[RecipeResponse]:
    """
    Return all active recipes (public, no auth required for now).
    """

    recipes = await list_recipes(db)
    return [RecipeResponse.model_validate(recipe) for recipe in recipes]

