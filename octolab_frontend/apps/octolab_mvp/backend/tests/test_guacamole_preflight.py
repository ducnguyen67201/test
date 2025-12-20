"""Tests for Guacamole preflight checker.

Uses httpx MockTransport to test classification of various HTTP responses
without requiring a real Guacamole server.

No database access is needed - all HTTP calls are mocked.
"""

import pytest
import httpx

# Mark entire module as not requiring database
pytestmark = pytest.mark.no_db

from app.services.guacamole_preflight import (
    guacamole_preflight,
    PreflightClassification,
    sanitize_url,
    normalize_base_url,
    build_url,
)


# ============================================================================
# URL Helper Tests
# ============================================================================

class TestSanitizeUrl:
    """Tests for sanitize_url function."""

    def test_url_without_credentials(self):
        """URLs without credentials should pass through unchanged."""
        url = "http://localhost:8081/guacamole"
        assert sanitize_url(url) == url

    def test_url_with_password_redacted(self):
        """Passwords in URLs should be redacted."""
        url = "http://admin:secret123@localhost:8081/guacamole"
        result = sanitize_url(url)
        assert "secret123" not in result
        assert "****" in result

    def test_url_with_port(self):
        """Port should be preserved when redacting."""
        url = "http://admin:pass@localhost:8081/guacamole"
        result = sanitize_url(url)
        assert "8081" in result

    def test_invalid_url_returns_placeholder(self):
        """Invalid URLs should return a safe placeholder."""
        # This is an edge case - most strings parse as URLs
        result = sanitize_url("")
        assert result == "" or result == "<invalid-url>"


class TestNormalizeBaseUrl:
    """Tests for normalize_base_url function."""

    def test_removes_trailing_slash(self):
        """Trailing slashes should be removed."""
        assert normalize_base_url("http://localhost:8081/guacamole/") == "http://localhost:8081/guacamole"

    def test_preserves_path(self):
        """Path should be preserved."""
        assert normalize_base_url("http://localhost:8081/guacamole") == "http://localhost:8081/guacamole"

    def test_removes_multiple_trailing_slashes(self):
        """Multiple trailing slashes should be removed."""
        assert normalize_base_url("http://localhost:8081/guacamole///") == "http://localhost:8081/guacamole"


class TestBuildUrl:
    """Tests for build_url function."""

    def test_simple_join(self):
        """Basic URL joining should work."""
        result = build_url("http://localhost:8081/guacamole", "api/tokens")
        assert result == "http://localhost:8081/guacamole/api/tokens"

    def test_no_double_slashes(self):
        """Should not create double slashes."""
        result = build_url("http://localhost:8081/guacamole/", "/api/tokens")
        assert "//" not in result.replace("http://", "")

    def test_base_without_trailing_slash(self):
        """Base without trailing slash should work."""
        result = build_url("http://localhost:8081/guacamole", "api/tokens")
        assert result == "http://localhost:8081/guacamole/api/tokens"

    def test_path_with_leading_slash(self):
        """Path with leading slash should work."""
        result = build_url("http://localhost:8081/guacamole", "/api/tokens")
        assert result == "http://localhost:8081/guacamole/api/tokens"

    def test_empty_path(self):
        """Empty path should return base with trailing slash."""
        result = build_url("http://localhost:8081/guacamole", "")
        assert result == "http://localhost:8081/guacamole/"


# ============================================================================
# Preflight Tests with Mock HTTP
# ============================================================================

def create_mock_transport(gui_response: httpx.Response, api_response: httpx.Response):
    """Create a mock transport that returns different responses for GUI and API endpoints."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path

        # GUI endpoint (base URL)
        if path.rstrip("/") == "/guacamole" or path == "/guacamole/":
            return gui_response

        # API tokens endpoint
        if path == "/guacamole/api/tokens":
            return api_response

        # Fallback
        return httpx.Response(404, text="Not Found")

    return httpx.MockTransport(handler)


class TestPreflightClassification:
    """Tests for preflight classification of various failure modes."""

    @pytest.mark.asyncio
    async def test_ok_when_both_succeed(self):
        """Should return OK when GUI and API both work."""
        gui_response = httpx.Response(200, text="<html>Guacamole</html>")
        api_response = httpx.Response(200, json={"authToken": "test-token", "username": "guacadmin"})

        transport = create_mock_transport(gui_response, api_response)

        # Patch httpx.AsyncClient to use our mock transport
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        httpx.AsyncClient.__init__ = patched_init

        try:
            result = await guacamole_preflight(
                base_url="http://localhost:8081/guacamole",
                admin_user="guacadmin",
                admin_password="guacadmin",
            )

            assert result.ok is True
            assert result.gui_ok is True
            assert result.api_ok is True
            assert result.classification == PreflightClassification.OK
        finally:
            httpx.AsyncClient.__init__ = original_init

    @pytest.mark.asyncio
    async def test_base_url_wrong_on_404(self):
        """404 on /api/tokens should classify as BASE_URL_WRONG."""
        gui_response = httpx.Response(200, text="<html>Guacamole</html>")
        api_response = httpx.Response(404, text="Not Found")

        transport = create_mock_transport(gui_response, api_response)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        httpx.AsyncClient.__init__ = patched_init

        try:
            result = await guacamole_preflight(
                base_url="http://localhost:8081/guacamole",
                admin_user="guacadmin",
                admin_password="guacadmin",
            )

            assert result.ok is False
            assert result.gui_ok is True
            assert result.api_ok is False
            assert result.classification == PreflightClassification.BASE_URL_WRONG
            assert result.api_status == 404
        finally:
            httpx.AsyncClient.__init__ = original_init

    @pytest.mark.asyncio
    async def test_creds_wrong_on_401(self):
        """401 on /api/tokens should classify as CREDS_WRONG."""
        gui_response = httpx.Response(200, text="<html>Guacamole</html>")
        api_response = httpx.Response(401, text="Unauthorized")

        transport = create_mock_transport(gui_response, api_response)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        httpx.AsyncClient.__init__ = patched_init

        try:
            result = await guacamole_preflight(
                base_url="http://localhost:8081/guacamole",
                admin_user="guacadmin",
                admin_password="wrongpassword",
            )

            assert result.ok is False
            assert result.gui_ok is True
            assert result.api_ok is False
            assert result.classification == PreflightClassification.CREDS_WRONG
            assert result.api_status == 401
        finally:
            httpx.AsyncClient.__init__ = original_init

    @pytest.mark.asyncio
    async def test_creds_wrong_on_403(self):
        """403 on /api/tokens should classify as CREDS_WRONG."""
        gui_response = httpx.Response(200, text="<html>Guacamole</html>")
        api_response = httpx.Response(403, text="Forbidden")

        transport = create_mock_transport(gui_response, api_response)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        httpx.AsyncClient.__init__ = patched_init

        try:
            result = await guacamole_preflight(
                base_url="http://localhost:8081/guacamole",
                admin_user="guacadmin",
                admin_password="wrongpassword",
            )

            assert result.ok is False
            assert result.classification == PreflightClassification.CREDS_WRONG
            assert result.api_status == 403
        finally:
            httpx.AsyncClient.__init__ = original_init

    @pytest.mark.asyncio
    async def test_server_5xx_on_500(self):
        """500 on /api/tokens should classify as SERVER_5XX."""
        gui_response = httpx.Response(200, text="<html>Guacamole</html>")
        api_response = httpx.Response(500, text="Internal Server Error")

        transport = create_mock_transport(gui_response, api_response)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        httpx.AsyncClient.__init__ = patched_init

        try:
            result = await guacamole_preflight(
                base_url="http://localhost:8081/guacamole",
                admin_user="guacadmin",
                admin_password="guacadmin",
            )

            assert result.ok is False
            assert result.classification == PreflightClassification.SERVER_5XX
            assert result.api_status == 500
        finally:
            httpx.AsyncClient.__init__ = original_init

    @pytest.mark.asyncio
    async def test_server_5xx_on_503(self):
        """503 on /api/tokens should classify as SERVER_5XX."""
        gui_response = httpx.Response(200, text="<html>Guacamole</html>")
        api_response = httpx.Response(503, text="Service Unavailable")

        transport = create_mock_transport(gui_response, api_response)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        httpx.AsyncClient.__init__ = patched_init

        try:
            result = await guacamole_preflight(
                base_url="http://localhost:8081/guacamole",
                admin_user="guacadmin",
                admin_password="guacadmin",
            )

            assert result.ok is False
            assert result.classification == PreflightClassification.SERVER_5XX
            assert result.api_status == 503
        finally:
            httpx.AsyncClient.__init__ = original_init

    @pytest.mark.asyncio
    async def test_gui_redirect_is_ok(self):
        """302 redirect on GUI should be treated as success."""
        gui_response = httpx.Response(302, headers={"Location": "/guacamole/#/"})
        api_response = httpx.Response(200, json={"authToken": "test-token", "username": "guacadmin"})

        transport = create_mock_transport(gui_response, api_response)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        httpx.AsyncClient.__init__ = patched_init

        try:
            result = await guacamole_preflight(
                base_url="http://localhost:8081/guacamole",
                admin_user="guacadmin",
                admin_password="guacadmin",
            )

            assert result.ok is True
            assert result.gui_ok is True
            assert result.gui_status == 302
        finally:
            httpx.AsyncClient.__init__ = original_init


class TestPreflightNetworkErrors:
    """Tests for preflight handling of network errors."""

    @pytest.mark.asyncio
    async def test_network_down_on_connect_error(self):
        """ConnectError should classify as NETWORK_DOWN."""

        def error_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(error_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        httpx.AsyncClient.__init__ = patched_init

        try:
            result = await guacamole_preflight(
                base_url="http://localhost:8081/guacamole",
                admin_user="guacadmin",
                admin_password="guacadmin",
            )

            assert result.ok is False
            assert result.gui_ok is False
            assert result.classification == PreflightClassification.NETWORK_DOWN
        finally:
            httpx.AsyncClient.__init__ = original_init


class TestPreflightResultFields:
    """Tests for PreflightResult field values."""

    @pytest.mark.asyncio
    async def test_sanitized_url_in_result(self):
        """Result should contain sanitized base URL."""
        gui_response = httpx.Response(200, text="<html>Guacamole</html>")
        api_response = httpx.Response(200, json={"authToken": "test-token", "username": "guacadmin"})

        transport = create_mock_transport(gui_response, api_response)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        httpx.AsyncClient.__init__ = patched_init

        try:
            result = await guacamole_preflight(
                base_url="http://localhost:8081/guacamole",
                admin_user="guacadmin",
                admin_password="guacadmin",
            )

            assert result.sanitized_base_url == "http://localhost:8081/guacamole"
        finally:
            httpx.AsyncClient.__init__ = original_init

    @pytest.mark.asyncio
    async def test_hint_provided_for_errors(self):
        """Result should contain a hint for errors."""
        gui_response = httpx.Response(200, text="<html>Guacamole</html>")
        api_response = httpx.Response(401, text="Unauthorized")

        transport = create_mock_transport(gui_response, api_response)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        httpx.AsyncClient.__init__ = patched_init

        try:
            result = await guacamole_preflight(
                base_url="http://localhost:8081/guacamole",
                admin_user="guacadmin",
                admin_password="wrongpassword",
            )

            assert result.hint  # Should have a non-empty hint
            assert "password" in result.hint.lower() or "credential" in result.hint.lower()
        finally:
            httpx.AsyncClient.__init__ = original_init
