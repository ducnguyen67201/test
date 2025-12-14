"""Authentication endpoints for registration, login, and user info."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, RegisterResponse, Token
from app.schemas.user import UserResponse
from app.services.auth_service import (
    authenticate_user,
    create_access_token,
    hash_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _is_admin(email: str) -> bool:
    """Check if email is in admin allowlist.

    SECURITY: Recomputes from settings.admin_emails on each call.
    This ensures instant revoke on config change + restart.

    Args:
        email: User email to check

    Returns:
        True if user is an admin, False otherwise
    """
    return (email or "").strip().lower() in settings.admin_emails


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    responses={
        404: {"description": "Self-registration disabled"},
        409: {"description": "Email already registered"},
    },
)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """
    Register a new user with email and password.

    Requires ALLOW_SELF_SIGNUP=true in environment. Returns 404 if disabled
    to avoid exposing endpoint existence.

    Args:
        request: Registration request with email and password
        db: Database session

    Returns:
        RegisterResponse: Access token and user information

    Raises:
        HTTPException: 404 if self-signup disabled, 409 if email exists
    """
    # SECURITY: Gate registration behind config flag; return 404 to hide endpoint
    if not settings.allow_self_signup:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not Found",
        )

    # Normalize email (strip whitespace, lowercase)
    normalized_email = request.email.strip().lower()

    # Check if user with email already exists
    result = await db.execute(select(User).where(User.email == normalized_email))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Hash password and create new user
    # SECURITY: Ignore any role/tenant fields from request; force defaults
    password_hash = hash_password(request.password)
    new_user = User(email=normalized_email, password_hash=password_hash)

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    # Create access token for immediate login (include admin status)
    is_admin = _is_admin(new_user.email)
    access_token = create_access_token(data={"sub": str(new_user.id), "is_admin": is_admin})

    return RegisterResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse(
            id=new_user.id,
            email=new_user.email,
            created_at=new_user.created_at,
            updated_at=new_user.updated_at,
            is_admin=is_admin,
        ),
    )


@router.post(
    "/login",
    response_model=Token,
    summary="Login and get access token",
)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> Token:
    """
    Authenticate user and return JWT access token.

    Args:
        request: Login request with email and password
        db: Database session

    Returns:
        Token: JWT access token and token type

    Raises:
        HTTPException: 401 if credentials are invalid
    """
    # Authenticate user
    user = await authenticate_user(db, request.email, request.password)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create access token with user ID as subject and admin status
    is_admin = _is_admin(user.email)
    access_token = create_access_token(data={"sub": str(user.id), "is_admin": is_admin})

    return Token(access_token=access_token, token_type="bearer")


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user information",
)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """
    Get the current authenticated user's information.

    Args:
        current_user: Current authenticated user (from dependency)

    Returns:
        UserResponse: Current user information including admin status
    """
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        created_at=current_user.created_at,
        updated_at=current_user.updated_at,
        is_admin=_is_admin(current_user.email),
    )

