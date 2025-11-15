"""Authentication Pydantic schemas."""

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """Schema for user registration."""

    email: EmailStr
    password: str = Field(min_length=8, description="Password must be at least 8 characters")


class LoginRequest(BaseModel):
    """Schema for user login."""

    email: EmailStr
    password: str


class Token(BaseModel):
    """Schema for JWT token response."""

    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    """Schema for JWT token payload (internal use)."""

    user_id: UUID | None = None
    sub: str | None = None  # Subject (user ID as string)

