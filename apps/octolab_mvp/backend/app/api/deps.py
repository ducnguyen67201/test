"""FastAPI dependencies for authentication and database access."""

from typing import Generator
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db import get_db
from app.models.user import User
from app.services.auth_service import decode_token

# OAuth2 scheme for token extraction
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency to get the current authenticated user from JWT token.

    Args:
        token: JWT token extracted from Authorization header
        db: Database session

    Returns:
        User: Authenticated user instance

    Raises:
        HTTPException: 401 if token is invalid or user not found
    """
    # Decode token
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Extract user ID from token (sub field contains user ID as string)
    user_id_str: str | None = payload.get("sub")
    if user_id_str is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Convert string to UUID
    try:
        user_id = UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Load user from database
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_session() -> Generator[Session, None, None]:
    """
    Dependency function to get a sync database session for internal operations.

    Yields:
        Session: Sync SQLAlchemy session
    """
    # Convert async URL to sync URL
    sync_url = settings.database_url.replace("postgresql+psycopg://", "postgresql+psycopg2://")

    # Create sync engine
    engine = create_engine(sync_url, echo=False, future=True)

    # Create session factory
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    # Create and yield session
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

