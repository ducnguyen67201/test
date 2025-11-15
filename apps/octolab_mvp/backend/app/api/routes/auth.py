"""Authentication endpoints for registration, login, and user info."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, Token
from app.schemas.user import UserResponse
from app.services.auth_service import (
    authenticate_user,
    create_access_token,
    hash_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    Register a new user with email and password.

    Args:
        request: Registration request with email and password
        db: Database session

    Returns:
        UserResponse: Created user information (without password hash)

    Raises:
        HTTPException: 400 if email already exists
    """
    # Check if user with email already exists
    result = await db.execute(select(User).where(User.email == request.email))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Hash password and create new user
    password_hash = hash_password(request.password)
    new_user = User(email=request.email, password_hash=password_hash)

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    return UserResponse.model_validate(new_user)


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

    # Create access token with user ID as subject
    access_token = create_access_token(data={"sub": str(user.id)})

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
        UserResponse: Current user information
    """
    return UserResponse.model_validate(current_user)

