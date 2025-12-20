"""Tests for user registration endpoint.

Tests cover:
- ALLOW_SELF_SIGNUP gate (disabled => 404)
- Happy path registration (enabled => 201 + token)
- Duplicate email (409 Conflict)
- Email normalization
- Token validity

Uses monkeypatch to control ALLOW_SELF_SIGNUP setting per test.
"""

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.config import settings
from app.main import app


@pytest.fixture
def unique_email():
    """Generate a unique email for each test."""
    return f"test_{uuid.uuid4().hex[:8]}@example.com"


@pytest.fixture
async def async_client():
    """Create an async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_register_disabled_returns_404(async_client):
    """When ALLOW_SELF_SIGNUP is false, registration returns 404."""
    with patch.object(settings, "allow_self_signup", False):
        response = await async_client.post(
            "/auth/register",
            json={"email": "new@example.com", "password": "securepassword123"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Not Found"


@pytest.mark.asyncio
async def test_register_enabled_creates_user(async_client, unique_email):
    """When ALLOW_SELF_SIGNUP is true, registration creates user and returns token."""
    with patch.object(settings, "allow_self_signup", True):
        response = await async_client.post(
            "/auth/register",
            json={"email": unique_email, "password": "securepassword123"},
        )
        assert response.status_code == 201
        data = response.json()

        # Check response structure
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert "user" in data
        assert data["user"]["email"] == unique_email.lower()

        # Token should be a non-empty string (don't log it)
        assert len(data["access_token"]) > 0


@pytest.mark.asyncio
async def test_register_token_works_for_auth_me(async_client, unique_email):
    """Token from registration should work for /auth/me."""
    with patch.object(settings, "allow_self_signup", True):
        # Register
        reg_response = await async_client.post(
            "/auth/register",
            json={"email": unique_email, "password": "securepassword123"},
        )
        assert reg_response.status_code == 201
        token = reg_response.json()["access_token"]

        # Use token to call /auth/me
        me_response = await async_client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me_response.status_code == 200
        assert me_response.json()["email"] == unique_email.lower()


@pytest.mark.asyncio
async def test_register_duplicate_email_returns_409(async_client, unique_email):
    """Registering with duplicate email returns 409 Conflict."""
    with patch.object(settings, "allow_self_signup", True):
        # First registration
        response1 = await async_client.post(
            "/auth/register",
            json={"email": unique_email, "password": "securepassword123"},
        )
        assert response1.status_code == 201

        # Second registration with same email
        response2 = await async_client.post(
            "/auth/register",
            json={"email": unique_email, "password": "differentpassword"},
        )
        assert response2.status_code == 409
        assert "already registered" in response2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_register_normalizes_email(async_client):
    """Email should be normalized (lowercase, stripped)."""
    raw_email = f"  TEST_{uuid.uuid4().hex[:8]}@EXAMPLE.COM  "
    expected_email = raw_email.strip().lower()

    with patch.object(settings, "allow_self_signup", True):
        response = await async_client.post(
            "/auth/register",
            json={"email": raw_email, "password": "securepassword123"},
        )
        assert response.status_code == 201
        assert response.json()["user"]["email"] == expected_email


@pytest.mark.asyncio
async def test_register_short_password_rejected(async_client):
    """Password shorter than 8 characters should be rejected."""
    with patch.object(settings, "allow_self_signup", True):
        response = await async_client.post(
            "/auth/register",
            json={"email": "short@example.com", "password": "short"},
        )
        assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_register_invalid_email_rejected(async_client):
    """Invalid email format should be rejected."""
    with patch.object(settings, "allow_self_signup", True):
        response = await async_client.post(
            "/auth/register",
            json={"email": "not-an-email", "password": "securepassword123"},
        )
        assert response.status_code == 422  # Validation error


# =============================================================================
# OpenAPI Tests
# =============================================================================


@pytest.mark.asyncio
async def test_openapi_exposes_register_post(async_client):
    """OpenAPI schema should expose POST /auth/register."""
    response = await async_client.get("/openapi.json")
    assert response.status_code == 200

    openapi = response.json()
    paths = openapi.get("paths", {})

    # /auth/register should be in paths
    assert "/auth/register" in paths, f"Available paths: {list(paths.keys())}"

    # POST method should be available
    register_methods = paths["/auth/register"]
    assert "post" in register_methods, f"Available methods: {list(register_methods.keys())}"


@pytest.mark.asyncio
async def test_openapi_exposes_login_post(async_client):
    """OpenAPI schema should expose POST /auth/login."""
    response = await async_client.get("/openapi.json")
    assert response.status_code == 200

    openapi = response.json()
    paths = openapi.get("paths", {})

    # /auth/login should be in paths
    assert "/auth/login" in paths, f"Available paths: {list(paths.keys())}"

    # POST method should be available
    login_methods = paths["/auth/login"]
    assert "post" in login_methods, f"Available methods: {list(login_methods.keys())}"


@pytest.mark.asyncio
async def test_openapi_exposes_auth_me_get(async_client):
    """OpenAPI schema should expose GET /auth/me."""
    response = await async_client.get("/openapi.json")
    assert response.status_code == 200

    openapi = response.json()
    paths = openapi.get("paths", {})

    # /auth/me should be in paths
    assert "/auth/me" in paths, f"Available paths: {list(paths.keys())}"

    # GET method should be available
    me_methods = paths["/auth/me"]
    assert "get" in me_methods, f"Available methods: {list(me_methods.keys())}"


# =============================================================================
# CORS Preflight Tests (optional but recommended)
# =============================================================================


@pytest.mark.asyncio
async def test_cors_preflight_register_localhost(async_client):
    """CORS preflight for /auth/register from localhost:5173."""
    response = await async_client.options(
        "/auth/register",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    # Should get 200 or 204 (preflight success) or actual endpoint response
    # FastAPI with CORS middleware typically returns 200
    assert response.status_code in (200, 204, 404), f"Got {response.status_code}"


@pytest.mark.asyncio
async def test_register_then_login_flow(async_client, unique_email):
    """Full flow: register, then login with same credentials."""
    password = "testpassword123"

    with patch.object(settings, "allow_self_signup", True):
        # Register
        reg_response = await async_client.post(
            "/auth/register",
            json={"email": unique_email, "password": password},
        )
        assert reg_response.status_code == 201

        # Login with same credentials
        login_response = await async_client.post(
            "/auth/login",
            json={"email": unique_email, "password": password},
        )
        assert login_response.status_code == 200
        login_data = login_response.json()
        assert "access_token" in login_data
        assert login_data["token_type"] == "bearer"
