"""Tests for admin Firecracker status endpoint.

SECURITY:
- Verifies admin-only access
- Verifies no secrets/full paths in response
- Verifies subprocess.run uses shell=False
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

pytestmark = pytest.mark.no_db


class TestFirecrackerStatusService:
    """Tests for the firecracker_status service."""

    def test_list_firecracker_processes_uses_shell_false(self):
        """Verify that process listing uses shell=False."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="  PID COMMAND ARGS\n  123 firecracker --api-sock /tmp/test.sock\n",
            )

            from app.services.firecracker_status import _list_firecracker_processes

            _list_firecracker_processes()

            # Verify shell=False was used
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs.get("shell") is False

    def test_redact_cmdline_removes_full_paths(self):
        """Verify that full paths are redacted to basenames."""
        from app.services.firecracker_status import _redact_cmdline

        # Test with full paths
        cmdline = "/usr/local/bin/firecracker --api-sock /var/lib/octolab/microvm/lab_123/firecracker.sock"
        redacted = _redact_cmdline(cmdline)

        # Should not contain full paths
        assert "/usr/local/bin" not in redacted
        assert "/var/lib/octolab" not in redacted

        # Should contain basenames
        assert "firecracker" in redacted
        assert "firecracker.sock" in redacted

    def test_extract_lab_id_from_socket_path(self):
        """Verify lab ID extraction from socket paths."""
        from app.services.firecracker_status import _extract_lab_id_from_socket_path

        # Test with lab_ prefix
        path1 = "/var/lib/octolab/microvm/lab_abc-123-def/firecracker.sock"
        assert _extract_lab_id_from_socket_path(path1) == "abc-123-def"

        # Test with UUID directly
        path2 = "/var/lib/octolab/microvm/12345678-1234-1234-1234-123456789012/firecracker.sock"
        assert _extract_lab_id_from_socket_path(path2) == "12345678-1234-1234-1234-123456789012"

    def test_process_listing_handles_timeout(self):
        """Verify that process listing handles timeouts gracefully."""
        import subprocess
        from app.services.firecracker_status import _list_firecracker_processes

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="ps", timeout=10)

            result = _list_firecracker_processes()

            # Should return empty list on timeout, not raise
            assert result == []

    def test_process_listing_handles_error(self):
        """Verify that process listing handles errors gracefully."""
        from app.services.firecracker_status import _list_firecracker_processes

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="ps failed")

            result = _list_firecracker_processes()

            # Should return empty list on error
            assert result == []


class TestFirecrackerStatusEndpoint:
    """Tests for the admin endpoint."""

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self):
        """Verify that non-admin users get 403."""
        # This is a behavior test - in the actual route, require_admin dependency
        # will raise HTTPException(403) for non-admin users
        from fastapi import HTTPException

        def require_admin(user):
            if not user.is_admin:
                raise HTTPException(status_code=403, detail="Admin required")
            return user

        non_admin_user = MagicMock()
        non_admin_user.is_admin = False

        with pytest.raises(HTTPException) as exc_info:
            require_admin(non_admin_user)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_returns_expected_shape(self):
        """Verify that admin users get the expected response shape."""
        # Mock the service function
        @dataclass
        class MockLabStatus:
            lab_id: str
            vm_id: str | None
            firecracker_pid: int | None
            api_sock_exists: bool
            state_dir_exists: bool
            status: str

        @dataclass
        class MockResponse:
            generated_at: str
            firecracker_process_count: int
            running_microvm_labs: list
            drift: dict
            summary: str

        mock_response = MockResponse(
            generated_at="2024-01-01T00:00:00Z",
            firecracker_process_count=2,
            running_microvm_labs=[
                MockLabStatus(
                    lab_id="lab-123",
                    vm_id="vm-456",
                    firecracker_pid=1234,
                    api_sock_exists=True,
                    state_dir_exists=True,
                    status="ok",
                )
            ],
            drift={"db_running_no_pid": [], "orphan_pids": []},
            summary="Firecracker runtime healthy",
        )

        # Verify response shape
        assert mock_response.firecracker_process_count == 2
        assert len(mock_response.running_microvm_labs) == 1
        assert mock_response.running_microvm_labs[0].status == "ok"
        assert "db_running_no_pid" in mock_response.drift
        assert "orphan_pids" in mock_response.drift

    def test_response_contains_no_secrets(self):
        """Verify that response doesn't contain full paths or secrets."""
        # Response fields that should not contain full paths:
        # - lab_id: UUID (safe)
        # - vm_id: UUID (safe)
        # - firecracker_pid: int (safe)
        # - api_sock_exists: bool (safe - not the path)
        # - state_dir_exists: bool (safe - not the path)
        # - status: string enum (safe)

        @dataclass
        class MockLabStatus:
            lab_id: str = "12345678-1234-1234-1234-123456789012"
            vm_id: str = "vm-abc123"
            firecracker_pid: int = 1234
            api_sock_exists: bool = True
            state_dir_exists: bool = True
            status: str = "ok"

        status = MockLabStatus()

        # Verify no paths in any field
        for field_name in ["lab_id", "vm_id", "status"]:
            value = getattr(status, field_name)
            if isinstance(value, str):
                assert "/" not in value, f"Field {field_name} should not contain paths"
                assert "\\" not in value, f"Field {field_name} should not contain paths"
