"""Tests for passwordless VNC localhost guard.

Verifies that:
1. Passwordless VNC (vnc_auth_mode=none) is allowed ONLY when binding to localhost
2. Non-localhost binding with passwordless VNC is refused (SECURITY)
3. Password mode works with any bind host
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

from app.runtime.compose_runtime import ComposeLabRuntime


class MockLab:
    """Mock lab object for testing."""

    def __init__(self):
        self.id = uuid4()
        self.owner_id = uuid4()


class MockRecipe:
    """Mock recipe object for testing."""

    def __init__(self):
        self.id = uuid4()


class MockSettings:
    """Mock settings for testing."""

    def __init__(self, vnc_auth_mode: str = "password", compose_bind_host: str = "127.0.0.1"):
        self.vnc_auth_mode = vnc_auth_mode
        self.compose_bind_host = compose_bind_host


@pytest.fixture
def compose_runtime(tmp_path):
    """Create a ComposeLabRuntime with a fake compose file."""
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("services: {}")
    return ComposeLabRuntime(compose_file)


def test_is_localhost_127_0_0_1(compose_runtime):
    """Test that 127.0.0.1 is recognized as localhost."""
    assert compose_runtime._is_localhost("127.0.0.1") is True


def test_is_localhost_localhost(compose_runtime):
    """Test that 'localhost' string is recognized as localhost."""
    assert compose_runtime._is_localhost("localhost") is True


def test_is_localhost_ipv6_loopback(compose_runtime):
    """Test that IPv6 loopback ::1 is recognized as localhost."""
    assert compose_runtime._is_localhost("::1") is True


def test_is_not_localhost_0_0_0_0(compose_runtime):
    """Test that 0.0.0.0 (all interfaces) is NOT localhost."""
    assert compose_runtime._is_localhost("0.0.0.0") is False


def test_is_not_localhost_external_ip(compose_runtime):
    """Test that external IPs are NOT localhost."""
    assert compose_runtime._is_localhost("192.168.1.100") is False
    assert compose_runtime._is_localhost("10.0.0.1") is False


@pytest.mark.asyncio
async def test_passwordless_vnc_allowed_on_localhost(compose_runtime, monkeypatch):
    """Test that passwordless VNC is allowed when binding to localhost."""
    mock_settings = MockSettings(vnc_auth_mode="none", compose_bind_host="127.0.0.1")
    monkeypatch.setattr("app.runtime.compose_runtime.settings", mock_settings)

    lab = MockLab()
    recipe = MockRecipe()
    mock_session = AsyncMock()

    # Mock port allocation
    monkeypatch.setattr(
        "app.runtime.compose_runtime.allocate_novnc_port",
        AsyncMock(return_value=30001),
    )

    # Mock compose run to succeed
    async def mock_run_compose(*args, **kwargs):
        pass

    monkeypatch.setattr(compose_runtime, "_run_compose", mock_run_compose)

    # Should NOT raise - passwordless VNC is allowed on localhost
    await compose_runtime.create_lab(lab, recipe, db_session=mock_session)


@pytest.mark.asyncio
async def test_passwordless_vnc_blocked_on_0_0_0_0(compose_runtime, monkeypatch):
    """SECURITY: Test that passwordless VNC is BLOCKED when binding to 0.0.0.0."""
    mock_settings = MockSettings(vnc_auth_mode="none", compose_bind_host="0.0.0.0")
    monkeypatch.setattr("app.runtime.compose_runtime.settings", mock_settings)

    lab = MockLab()
    recipe = MockRecipe()
    mock_session = AsyncMock()

    # Should raise RuntimeError - passwordless VNC on non-localhost is forbidden
    with pytest.raises(RuntimeError) as exc_info:
        await compose_runtime.create_lab(lab, recipe, db_session=mock_session)

    assert "Passwordless VNC" in str(exc_info.value)
    assert "localhost" in str(exc_info.value)


@pytest.mark.asyncio
async def test_passwordless_vnc_blocked_on_external_ip(compose_runtime, monkeypatch):
    """SECURITY: Test that passwordless VNC is BLOCKED when binding to external IP."""
    mock_settings = MockSettings(vnc_auth_mode="none", compose_bind_host="192.168.1.100")
    monkeypatch.setattr("app.runtime.compose_runtime.settings", mock_settings)

    lab = MockLab()
    recipe = MockRecipe()
    mock_session = AsyncMock()

    # Should raise RuntimeError
    with pytest.raises(RuntimeError) as exc_info:
        await compose_runtime.create_lab(lab, recipe, db_session=mock_session)

    assert "Passwordless VNC" in str(exc_info.value)


@pytest.mark.asyncio
async def test_password_vnc_allowed_on_any_host(compose_runtime, monkeypatch):
    """Test that password-protected VNC is allowed on any bind host."""
    mock_settings = MockSettings(vnc_auth_mode="password", compose_bind_host="0.0.0.0")
    monkeypatch.setattr("app.runtime.compose_runtime.settings", mock_settings)

    lab = MockLab()
    recipe = MockRecipe()
    mock_session = AsyncMock()

    # Mock port allocation
    monkeypatch.setattr(
        "app.runtime.compose_runtime.allocate_novnc_port",
        AsyncMock(return_value=30002),
    )

    # Mock compose run to succeed
    async def mock_run_compose(*args, **kwargs):
        pass

    monkeypatch.setattr(compose_runtime, "_run_compose", mock_run_compose)

    # Should NOT raise - password VNC is allowed on any host
    await compose_runtime.create_lab(lab, recipe, db_session=mock_session)


@pytest.mark.asyncio
async def test_no_docker_compose_invoked_when_blocked(compose_runtime, monkeypatch):
    """Test that docker compose is NOT invoked when passwordless VNC is blocked."""
    mock_settings = MockSettings(vnc_auth_mode="none", compose_bind_host="0.0.0.0")
    monkeypatch.setattr("app.runtime.compose_runtime.settings", mock_settings)

    lab = MockLab()
    recipe = MockRecipe()
    mock_session = AsyncMock()

    # Track if _run_compose is called
    compose_called = False

    async def mock_run_compose(*args, **kwargs):
        nonlocal compose_called
        compose_called = True

    monkeypatch.setattr(compose_runtime, "_run_compose", mock_run_compose)

    # Attempt to create lab - should fail before calling compose
    with pytest.raises(RuntimeError):
        await compose_runtime.create_lab(lab, recipe, db_session=mock_session)

    # Verify compose was never called
    assert compose_called is False, "Docker compose should NOT be invoked when security check fails"
