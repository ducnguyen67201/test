"""Tests for guest agent protocol and backend integration.

These tests verify the guest agent code without requiring a running VM.
They test the protocol parsing, command validation, and timeout configuration.

SECURITY: No actual VM or Docker execution - safe to run without elevated privileges.
"""

import pytest
import json
import sys
import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock

# Path to guest-agent module
# Test file: backend/tests/test_guest_agent_protocol.py
# Agent file: infra/firecracker/guest-agent/agent.py
# Need to go up 3 levels: tests -> backend -> octolab_mvp, then into infra/
GUEST_AGENT_PATH = Path(__file__).resolve().parent.parent.parent / "infra" / "firecracker" / "guest-agent"
AGENT_FILE = GUEST_AGENT_PATH / "agent.py"


def load_agent_module():
    """Load the guest agent module from the infra directory."""
    spec = importlib.util.spec_from_file_location("agent", AGENT_FILE)
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
    return agent


@pytest.mark.no_db
class TestGuestAgentProtocol:
    """Test guest agent protocol without requiring a running VM."""

    def test_allowed_commands_include_diag(self):
        """Verify diag command is in the allowed commands."""
        agent = load_agent_module()
        assert "diag" in agent.ALLOWED_COMMANDS
        assert "ping" in agent.ALLOWED_COMMANDS
        assert "compose_up" in agent.ALLOWED_COMMANDS
        assert "upload_project" in agent.ALLOWED_COMMANDS
        assert "status" in agent.ALLOWED_COMMANDS

    def test_validate_project_name_security(self):
        """Test project name validation prevents path traversal."""
        agent = load_agent_module()

        # Valid names
        assert agent.validate_project_name("my-project")
        assert agent.validate_project_name("project_123")
        assert agent.validate_project_name("MyProject")

        # Invalid names - path traversal
        assert not agent.validate_project_name("../etc")
        assert not agent.validate_project_name("foo/../bar")
        assert not agent.validate_project_name("/etc/passwd")

        # Invalid names - special characters
        assert not agent.validate_project_name("project;rm -rf")
        assert not agent.validate_project_name("project$(cmd)")
        assert not agent.validate_project_name("")

        # Too long
        assert not agent.validate_project_name("a" * 101)
        assert agent.validate_project_name("a" * 100)

    def test_run_cmd_returns_proper_structure(self):
        """Test run_cmd returns expected dict structure."""
        agent = load_agent_module()

        # Mock subprocess.run to avoid actual command execution
        with patch.object(agent.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="output",
                stderr="",
            )
            result = agent.run_cmd(["echo", "test"], timeout=5.0)

            # Verify structure
            assert "ok" in result
            assert "stdout" in result
            assert "stderr" in result
            assert "exit_code" in result

            # Verify types - should never be None
            assert isinstance(result["ok"], bool)
            assert isinstance(result["stdout"], str)
            assert isinstance(result["stderr"], str)
            assert isinstance(result["exit_code"], int)

    def test_run_cmd_handles_timeout(self):
        """Test run_cmd returns proper error on timeout."""
        agent = load_agent_module()
        import subprocess

        with patch.object(agent.subprocess, "run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=5)
            result = agent.run_cmd(["sleep", "100"], timeout=5.0)

            assert result["ok"] is False
            assert "timed out" in result["stderr"].lower()
            assert result["exit_code"] == -1
            # Verify stdout is empty string, not None
            assert result["stdout"] == ""

    def test_run_cmd_handles_file_not_found(self):
        """Test run_cmd returns proper error when command not found."""
        agent = load_agent_module()

        with patch.object(agent.subprocess, "run") as mock_run:
            mock_run.side_effect = FileNotFoundError(2, "No such file", "nonexistent")
            result = agent.run_cmd(["nonexistent"], timeout=5.0)

            assert result["ok"] is False
            assert "not found" in result["stderr"].lower()
            assert result["exit_code"] == -1

    def test_command_handlers_registered(self):
        """Test all allowed commands have handlers."""
        agent = load_agent_module()

        for cmd in agent.ALLOWED_COMMANDS:
            assert cmd in agent.COMMAND_HANDLERS, f"Missing handler for {cmd}"
            assert callable(agent.COMMAND_HANDLERS[cmd])

    def test_handle_ping_returns_pong(self):
        """Test ping handler returns expected response."""
        agent = load_agent_module()

        result = agent.handle_ping({})
        assert result["ok"] is True
        assert result["stdout"] == "pong"
        assert result["stderr"] == ""
        assert result["exit_code"] == 0

    def test_docker_ready_constants(self):
        """Test Docker readiness constants are reasonable."""
        agent = load_agent_module()

        # Default timeout should be reasonable (30s - 120s)
        assert 30 <= agent.DEFAULT_DOCKER_TIMEOUT <= 120
        # Poll interval should be reasonable (0.5s - 5s)
        assert 0.5 <= agent.DOCKER_POLL_INTERVAL <= 5

    def test_get_docker_timeout_default(self):
        """Test get_docker_timeout returns default when env var not set."""
        agent = load_agent_module()

        with patch.dict("os.environ", {}, clear=True):
            timeout = agent.get_docker_timeout()
            assert timeout == agent.DEFAULT_DOCKER_TIMEOUT

    def test_get_docker_timeout_from_env(self):
        """Test get_docker_timeout reads from env var."""
        agent = load_agent_module()

        with patch.dict("os.environ", {"OCTOLAB_VM_DOCKER_TIMEOUT": "90"}):
            timeout = agent.get_docker_timeout()
            assert timeout == 90

    def test_get_docker_timeout_invalid_env(self):
        """Test get_docker_timeout uses default on invalid env var."""
        agent = load_agent_module()

        with patch.dict("os.environ", {"OCTOLAB_VM_DOCKER_TIMEOUT": "not_a_number"}):
            timeout = agent.get_docker_timeout()
            assert timeout == agent.DEFAULT_DOCKER_TIMEOUT

    def test_wait_for_docker_returns_bool(self):
        """Test wait_for_docker returns boolean, not dict."""
        agent = load_agent_module()

        # Mock successful docker info
        with patch.object(agent.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = agent.wait_for_docker(timeout_seconds=5)
            assert isinstance(result, bool)
            assert result is True

    def test_wait_for_docker_timeout_returns_false(self):
        """Test wait_for_docker returns False on timeout."""
        agent = load_agent_module()

        # Mock failing docker info
        with patch.object(agent.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            # Short timeout to make test fast
            result = agent.wait_for_docker(timeout_seconds=0.1)
            assert result is False

    def test_handle_diag_returns_structured_response(self):
        """Test diag handler returns docker_ready and last_compose_status."""
        agent = load_agent_module()

        # Mock Docker commands
        with patch.object(agent, "wait_for_docker", return_value=True):
            with patch.object(agent, "load_compose_status", return_value={"success": True}):
                with patch.object(agent, "run_cmd") as mock_run_cmd:
                    # Mock docker ps and docker images
                    mock_run_cmd.return_value = {"ok": True, "stdout": "", "stderr": "", "exit_code": 0}

                    result = agent.handle_diag({})

                    assert result["ok"] is True
                    assert "docker_ready" in result
                    assert "last_compose_status" in result
                    assert result["docker_ready"] is True

    def test_save_and_load_compose_status(self):
        """Test compose status can be saved and loaded."""
        agent = load_agent_module()
        import tempfile
        import os

        # Use temp file for testing
        with tempfile.TemporaryDirectory() as tmpdir:
            test_status_file = Path(tmpdir) / "status.json"

            # Patch the status file path
            with patch.object(agent, "COMPOSE_STATUS_FILE", test_status_file):
                # Save status
                agent.save_compose_status("test_project", True)

                # Load status
                status = agent.load_compose_status()
                assert status is not None
                assert status["project"] == "test_project"
                assert status["success"] is True

    def test_save_compose_status_with_error(self):
        """Test compose status saves error information."""
        agent = load_agent_module()
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_status_file = Path(tmpdir) / "status.json"

            with patch.object(agent, "COMPOSE_STATUS_FILE", test_status_file):
                agent.save_compose_status("test_project", False, "compose_up_failed")

                status = agent.load_compose_status()
                assert status is not None
                assert status["success"] is False
                assert status["error"] == "compose_up_failed"


@pytest.mark.no_db
class TestBackendTimeoutConfiguration:
    """Test backend timeout configuration for commands."""

    def test_command_specific_timeouts_exist(self):
        """Test that command-specific timeout settings exist."""
        from app.config import settings

        # Default timeout
        assert hasattr(settings, "microvm_cmd_timeout_secs")
        assert settings.microvm_cmd_timeout_secs > 0

        # Compose-specific timeout (should be longer)
        assert hasattr(settings, "microvm_compose_timeout_secs")
        assert settings.microvm_compose_timeout_secs >= settings.microvm_cmd_timeout_secs

        # Diag timeout (should be shorter)
        assert hasattr(settings, "microvm_diag_timeout_secs")
        assert settings.microvm_diag_timeout_secs > 0

    def test_compose_timeout_is_longer(self):
        """Test compose_up gets a longer timeout than default."""
        from app.config import settings

        # Compose up may need to pull images, so should have longer timeout
        assert settings.microvm_compose_timeout_secs >= 300  # At least 5 minutes
        assert settings.microvm_compose_timeout_secs <= 900  # At most 15 minutes

    def test_get_command_timeout_function(self):
        """Test the _get_command_timeout helper function."""
        from app.services.firecracker_manager import _get_command_timeout
        from app.config import settings

        # compose_up should get compose timeout
        assert _get_command_timeout("compose_up") == settings.microvm_compose_timeout_secs

        # diag should get diag timeout
        assert _get_command_timeout("diag") == settings.microvm_diag_timeout_secs

        # Other commands should get default
        assert _get_command_timeout("ping") == settings.microvm_cmd_timeout_secs
        assert _get_command_timeout("status") == settings.microvm_cmd_timeout_secs
        assert _get_command_timeout("upload_project") == settings.microvm_cmd_timeout_secs


@pytest.mark.no_db
class TestAgentResponseDataclass:
    """Test AgentResponse dataclass behavior."""

    def test_agent_response_defaults(self):
        """Test AgentResponse has proper defaults."""
        from app.services.firecracker_manager import AgentResponse

        # Create with just ok=False
        response = AgentResponse(ok=False)

        # Check defaults are empty strings, not None
        assert response.stdout == ""
        assert response.stderr == ""
        assert response.exit_code == -1
        assert response.error is None

    def test_agent_response_with_values(self):
        """Test AgentResponse with all values set."""
        from app.services.firecracker_manager import AgentResponse

        response = AgentResponse(
            ok=True,
            stdout="output",
            stderr="",
            exit_code=0,
            error=None,
        )

        assert response.ok is True
        assert response.stdout == "output"
        assert response.stderr == ""
        assert response.exit_code == 0


@pytest.mark.no_db
class TestFirecrackerRuntimeAbstractions:
    """Test Firecracker runtime compose_up_inside_vm and run_vm_diag."""

    def test_truncate_diag_output(self):
        """Test _truncate_diag produces safe, bounded output."""
        from app.runtime.firecracker_runtime import _truncate_diag

        # Test with full diag response
        diag = {
            "docker_ready": True,
            "summary": "containers=2, images=5",
            "last_compose_status": {
                "success": True,
                "error": None,
            },
        }
        result = _truncate_diag(diag)
        assert isinstance(result, str)
        assert len(result) <= 2048
        assert "docker_ready" in result

    def test_truncate_diag_with_error(self):
        """Test _truncate_diag handles error status."""
        from app.runtime.firecracker_runtime import _truncate_diag

        diag = {
            "docker_ready": False,
            "summary": "containers=unknown",
            "last_compose_status": {
                "success": False,
                "error": "compose_up_failed: some long error message that should be truncated",
            },
        }
        result = _truncate_diag(diag)
        assert isinstance(result, str)
        assert "docker_ready" in result
        # Error should be truncated
        assert len(result) <= 2048

    def test_truncate_diag_handles_missing_fields(self):
        """Test _truncate_diag handles missing fields gracefully."""
        from app.runtime.firecracker_runtime import _truncate_diag

        # Empty dict
        result = _truncate_diag({})
        assert isinstance(result, str)

        # Partial fields
        result = _truncate_diag({"docker_ready": True})
        assert isinstance(result, str)

    def test_compose_error_exception_exists(self):
        """Test ComposeError exception is properly defined."""
        from app.runtime.firecracker_runtime import ComposeError, FirecrackerRuntimeError

        assert issubclass(ComposeError, FirecrackerRuntimeError)
        assert issubclass(ComposeError, Exception)

        # Can be raised with message
        with pytest.raises(ComposeError) as exc_info:
            raise ComposeError("test error")
        assert "test error" in str(exc_info.value)


@pytest.mark.no_db
class TestFirecrackerRuntimeComposeUpInsideVM:
    """Test compose_up_inside_vm method behavior with mocks."""

    @pytest.fixture
    def mock_lab(self):
        """Create a mock lab object."""
        from unittest.mock import MagicMock
        from uuid import uuid4

        lab = MagicMock()
        lab.id = uuid4()
        lab.owner_id = uuid4()
        return lab

    @pytest.fixture
    def runtime(self):
        """Create a FirecrackerLabRuntime instance."""
        from app.runtime.firecracker_runtime import FirecrackerLabRuntime

        return FirecrackerLabRuntime()

    @pytest.mark.asyncio
    async def test_compose_up_success(self, runtime, mock_lab):
        """Test compose_up_inside_vm on success."""
        from app.services.firecracker_manager import AgentResponse

        with patch("app.runtime.firecracker_runtime.send_agent_command") as mock_send:
            mock_send.return_value = AgentResponse(ok=True, stdout="success", exit_code=0)

            # Should not raise
            await runtime.compose_up_inside_vm(mock_lab, "test_project")

            # Verify command was sent
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert call_args[0][1] == "compose_up"  # command
            assert call_args[1]["project"] == "test_project"

    @pytest.mark.asyncio
    async def test_compose_up_failure_raises_compose_error(self, runtime, mock_lab):
        """Test compose_up_inside_vm raises ComposeError on failure."""
        from app.services.firecracker_manager import AgentResponse
        from app.runtime.firecracker_runtime import ComposeError

        with patch("app.runtime.firecracker_runtime.send_agent_command") as mock_send:
            # First call is compose_up (fails), second is diag
            mock_send.side_effect = [
                AgentResponse(ok=False, stderr="docker_not_ready", exit_code=1),
                AgentResponse(ok=True, stdout="diag info"),
            ]

            with pytest.raises(ComposeError) as exc_info:
                await runtime.compose_up_inside_vm(mock_lab, "test_project")

            assert "docker_not_ready" in str(exc_info.value) or "Compose up failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_compose_up_timeout_raises_compose_error(self, runtime, mock_lab):
        """Test compose_up_inside_vm raises ComposeError on timeout."""
        import asyncio
        from app.runtime.firecracker_runtime import ComposeError
        from app.services.firecracker_manager import AgentResponse

        with patch("app.runtime.firecracker_runtime.send_agent_command") as mock_send:
            # compose_up times out, diag succeeds
            mock_send.side_effect = [
                asyncio.TimeoutError(),
                AgentResponse(ok=True, stdout="diag info"),
            ]

            with pytest.raises(ComposeError) as exc_info:
                await runtime.compose_up_inside_vm(mock_lab, "test_project", timeout=1.0)

            assert "timed out" in str(exc_info.value).lower()


@pytest.mark.no_db
class TestFirecrackerRuntimeDiag:
    """Test run_vm_diag method behavior."""

    @pytest.fixture
    def mock_lab(self):
        """Create a mock lab object."""
        from unittest.mock import MagicMock
        from uuid import uuid4

        lab = MagicMock()
        lab.id = uuid4()
        return lab

    @pytest.fixture
    def runtime(self):
        """Create a FirecrackerLabRuntime instance."""
        from app.runtime.firecracker_runtime import FirecrackerLabRuntime

        return FirecrackerLabRuntime()

    @pytest.mark.asyncio
    async def test_run_vm_diag_success(self, runtime, mock_lab):
        """Test run_vm_diag returns structured response on success."""
        from app.services.firecracker_manager import AgentResponse

        with patch("app.runtime.firecracker_runtime.send_agent_command") as mock_send:
            mock_send.return_value = AgentResponse(
                ok=True,
                stdout="containers=2, images=5",
                exit_code=0,
            )

            result = await runtime.run_vm_diag(mock_lab)

            assert result["ok"] is True
            assert "summary" in result

    @pytest.mark.asyncio
    async def test_run_vm_diag_failure_returns_error_dict(self, runtime, mock_lab):
        """Test run_vm_diag returns error dict on failure, not exception."""
        with patch("app.runtime.firecracker_runtime.send_agent_command") as mock_send:
            mock_send.side_effect = Exception("connection failed")

            result = await runtime.run_vm_diag(mock_lab)

            assert result["ok"] is False
            assert "error" in result
            assert result["error"] == "diag_failed"

    @pytest.mark.asyncio
    async def test_run_vm_diag_timeout_returns_error_dict(self, runtime, mock_lab):
        """Test run_vm_diag returns error dict on timeout."""
        import asyncio

        with patch("app.runtime.firecracker_runtime.send_agent_command") as mock_send:
            mock_send.side_effect = asyncio.TimeoutError()

            result = await runtime.run_vm_diag(mock_lab)

            assert result["ok"] is False
            assert result["error"] == "diag_timeout"
