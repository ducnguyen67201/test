"""FastAPI dependencies for authentication and database access."""

from typing import Generator, Optional
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db import get_db
from app.models.user import User
from app.services.auth_service import decode_token

# Alias for async session (used by internal endpoints)
get_async_session = get_db

# OAuth2 scheme for token extraction
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
# Optional OAuth2 scheme (for endpoints that also accept service token)
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

# Module-level singleton for sync database engine (prevents connection leak)
_sync_engine: Engine | None = None
_sync_sessionmaker: sessionmaker | None = None


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


async def get_current_user_or_service(
    token: Optional[str] = Depends(oauth2_scheme_optional),
    x_service_token: Optional[str] = Header(None, alias="X-Service-Token"),
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency to get user from either:
    1. JWT token (regular user auth)
    2. Service token + user email (frontend-to-backend calls)

    SECURITY:
    - Service token must match OCTOLAB_SERVICE_TOKEN
    - X-User-Email is only trusted when service token is valid
    - Falls back to regular JWT auth if no service token

    Args:
        token: Optional JWT token from Authorization header
        x_service_token: Optional service token from X-Service-Token header
        x_user_email: User email from X-User-Email header (trusted only with valid service token)
        db: Database session

    Returns:
        User: Authenticated user instance

    Raises:
        HTTPException: 401 if authentication fails
    """
    # Check service token first
    if x_service_token and x_user_email:
        configured_token = settings.service_token
        if configured_token and x_service_token == configured_token.get_secret_value():
            # Service token is valid, look up user by email
            result = await db.execute(
                select(User).where(User.email == x_user_email.lower())
            )
            user = result.scalar_one_or_none()
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"User not found: {x_user_email}",
                )
            return user
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid service token",
            )

    # Fall back to regular JWT auth
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Decode JWT token
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str: str | None = payload.get("sub")
    if user_id_str is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

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

    Uses module-level singleton engine to prevent connection pool exhaustion.
    The engine is created once and reused across all requests.

    Yields:
        Session: Sync SQLAlchemy session
    """
    global _sync_engine, _sync_sessionmaker

    if _sync_engine is None:
        # Convert async URL to sync URL
        sync_url = settings.database_url.replace(
            "postgresql+psycopg://", "postgresql+psycopg2://"
        )
        _sync_engine = create_engine(sync_url, echo=False, future=True)
        _sync_sessionmaker = sessionmaker(bind=_sync_engine, expire_on_commit=False)

    session = _sync_sessionmaker()
    try:
        yield session
    finally:
        session.close()

