"""Tests for /health/firecracker endpoint.

Verifies that:
1. Endpoint returns correct response structure
2. Doctor checks are exposed with redaction
3. Runtime info is included
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

pytestmark = pytest.mark.no_db


@pytest.fixture
def client():
    """Create test client with mocked settings."""
    # We need to mock the config before importing the app
    with patch.dict(
        "os.environ",
        {
            "DATABASE_URL": "postgresql+psycopg://test:test@localhost/test",
            "SECRET_KEY": "test-secret-key-minimum-32-chars-long",
            "APP_ENV": "test",
            "OCTOLAB_RUNTIME": "noop",  # Use noop to avoid firecracker checks
        },
    ):
        # Import app after setting env vars
        from app.api.routes.health import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        yield TestClient(app)


class TestHealthFirecrackerEndpoint:
    """Test /health/firecracker endpoint."""

    def test_endpoint_returns_200(self, client):
        """Verify endpoint returns 200 status."""
        with patch("app.api.routes.health.run_checks") as mock_run:
            mock_run.return_value = {
                "is_ok": True,
                "summary": {"ok": 5, "warn": 0, "fatal": 0},
                "checks": [],
            }

            response = client.get("/health/firecracker")
            assert response.status_code == 200

    def test_endpoint_returns_correct_structure(self, client):
        """Verify response has required fields."""
        with patch("app.api.routes.health.run_checks") as mock_run:
            mock_run.return_value = {
                "is_ok": True,
                "summary": {"ok": 3, "warn": 1, "fatal": 0},
                "checks": [
                    {
                        "name": "kvm_device",
                        "status": "OK",
                        "message": "KVM device available",
                        "severity": "fatal",
                        "hint": None,
                    },
                    {
                        "name": "firecracker_bin",
                        "status": "WARN",
                        "message": "Firecracker not in PATH",
                        "severity": "warning",
                        "hint": "Install firecracker binary",
                    },
                ],
            }

            response = client.get("/health/firecracker")
            data = response.json()

            # Required top-level fields
            assert "is_ok" in data
            assert "summary" in data
            assert "checks" in data
            assert "runtime" in data

            # Summary structure
            assert "ok" in data["summary"]
            assert "warn" in data["summary"]
            assert "fatal" in data["summary"]

            # Check structure
            assert len(data["checks"]) == 2
            check = data["checks"][0]
            assert "name" in check
            assert "status" in check
            assert "message" in check
            assert "severity" in check

    def test_endpoint_includes_runtime_setting(self, client):
        """Verify runtime setting is included in response."""
        with patch("app.api.routes.health.run_checks") as mock_run:
            mock_run.return_value = {
                "is_ok": True,
                "summary": {"ok": 1, "warn": 0, "fatal": 0},
                "checks": [],
            }
            with patch("app.api.routes.health.settings") as mock_settings:
                mock_settings.octolab_runtime = "firecracker"

                response = client.get("/health/firecracker")
                data = response.json()

                assert data["runtime"] == "firecracker"

    def test_endpoint_truncates_long_messages(self, client):
        """Verify long messages are truncated for security."""
        long_message = "x" * 500  # Longer than 200 char limit

        with patch("app.api.routes.health.run_checks") as mock_run:
            mock_run.return_value = {
                "is_ok": False,
                "summary": {"ok": 0, "warn": 0, "fatal": 1},
                "checks": [
                    {
                        "name": "test_check",
                        "status": "FAIL",
                        "message": long_message,
                        "severity": "fatal",
                        "hint": long_message,
                    },
                ],
            }

            response = client.get("/health/firecracker")
            data = response.json()

            # Messages should be truncated to 200 chars
            assert len(data["checks"][0]["message"]) == 200
            assert len(data["checks"][0]["hint"]) == 200

    def test_endpoint_handles_missing_optional_fields(self, client):
        """Verify endpoint handles missing optional fields gracefully."""
        with patch("app.api.routes.health.run_checks") as mock_run:
            mock_run.return_value = {
                "is_ok": True,
                "summary": {"ok": 1, "warn": 0, "fatal": 0},
                "checks": [
                    {
                        "name": "minimal_check",
                        "status": "OK",
                        # Missing: message, severity, hint
                    },
                ],
            }

            response = client.get("/health/firecracker")
            data = response.json()

            assert response.status_code == 200
            check = data["checks"][0]
            assert check["name"] == "minimal_check"
            assert check["status"] == "OK"
            assert check["message"] == ""  # Default to empty string
            assert check["severity"] == "info"  # Default severity

    def test_endpoint_shows_failure_state(self, client):
        """Verify is_ok=False when checks fail."""
        with patch("app.api.routes.health.run_checks") as mock_run:
            mock_run.return_value = {
                "is_ok": False,
                "summary": {"ok": 2, "warn": 1, "fatal": 1},
                "checks": [
                    {
                        "name": "kvm_device",
                        "status": "FAIL",
                        "message": "KVM device not available",
                        "severity": "fatal",
                        "hint": "Enable KVM in BIOS",
                    },
                ],
            }

            response = client.get("/health/firecracker")
            data = response.json()

            assert data["is_ok"] is False
            assert data["summary"]["fatal"] == 1


class TestHealthFirecrackerNoAuth:
    """Test that /health/firecracker requires no authentication."""

    def test_endpoint_accessible_without_auth(self, client):
        """Verify endpoint works without authentication header."""
        with patch("app.api.routes.health.run_checks") as mock_run:
            mock_run.return_value = {
                "is_ok": True,
                "summary": {"ok": 1, "warn": 0, "fatal": 0},
                "checks": [],
            }

            # No Authorization header
            response = client.get("/health/firecracker")
            assert response.status_code == 200
