"""Seed script to populate initial recipes in the database."""

import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

# Add backend directory to path for imports
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from app.config import settings
from app.models.recipe import Recipe


def get_sync_session():
    """
    Create a sync database session factory.

    Converts the async database URL to use psycopg2-binary for sync operations.
    Note: Requires psycopg2-binary to be installed (pre-built, no compilation needed).
    """
    # Convert async URL (postgresql+psycopg://) to sync URL using psycopg2-binary
    # psycopg2-binary is a pre-built package that doesn't require compilation
    sync_url = settings.database_url.replace("postgresql+psycopg://", "postgresql+psycopg2://")
    
    # Create sync engine
    engine = create_engine(sync_url, echo=False, future=True)
    
    # Create session factory
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    
    return SessionLocal


def main():
    """Seed initial recipes into the database."""
    SessionLocal = get_sync_session()
    
    # Recipe data
    recipes_data = [
        {
            "name": "apache_rce_2_4_18",
            "description": "Apache Tomcat Vulnerable to RCE",
            "software": "apache_tomcat",
            "version_constraint": "2.4.18",
            "exploit_family": "rce",
            "is_active": True,
        },
        {
            "name": "jquery_2_2_1_dom_xss",
            "description": "jQuery 2.2.1 DOM XSS scenario",
            "software": "jquery",
            "version_constraint": "2.2.1",
            "exploit_family": "xss",
            "is_active": True,
        },
    ]
    
    created_count = 0
    
    with SessionLocal() as session:
        for recipe_data in recipes_data:
            # Check if recipe already exists by name
            result = session.execute(
                select(Recipe).where(Recipe.name == recipe_data["name"])
            )
            existing = result.scalar_one_or_none()
            
            if existing is None:
                # Create new recipe
                recipe = Recipe(**recipe_data)
                session.add(recipe)
                created_count += 1
                print(f"Created recipe: {recipe_data['name']}")
            else:
                print(f"Recipe already exists: {recipe_data['name']} (skipping)")
        
        # Commit all changes at once
        session.commit()
        print(f"\nSeeding complete. Created {created_count} new recipe(s).")


if __name__ == "__main__":
    main()

