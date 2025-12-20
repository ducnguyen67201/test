"""Tests for compose_runtime deterministic execution and output sanitization.

These tests verify:
- --project-directory is passed to docker compose
- cwd is set to compose_dir
- Secret redaction occurs in stdout/stderr
- Truncation applies for large outputs
- Diagnostics include stderr when commands fail
"""

import io
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

# Mark all tests as not requiring database
pytestmark = pytest.mark.no_db


class MockLab:
    """Mock Lab object for testing."""

    def __init__(self, lab_id=None, owner_id=None):
        self.id = lab_id or uuid4()
        self.owner_id = owner_id or uuid4()


class TestProjectNameNormalization:
    """Tests for project name normalization."""

    def test_normalize_project_name_lowercase(self):
        """Test that project names are lowercased."""
        from app.runtime.compose_runtime import _normalize_project_name

        assert _normalize_project_name("OCTOLAB_ABC") == "octolab_abc"
        assert _normalize_project_name("OcToLaB_XyZ") == "octolab_xyz"

    def test_normalize_project_name_uuid(self):
        """Test that UUIDs are normalized correctly."""
        from app.runtime.compose_runtime import _normalize_project_name

        # UUID with hyphens is valid for compose
        result = _normalize_project_name("octolab_12345678-1234-1234-1234-123456789abc")
        assert result == "octolab_12345678-1234-1234-1234-123456789abc"

    def test_normalize_project_name_invalid_chars(self):
        """Test that invalid characters are replaced with underscore."""
        from app.runtime.compose_runtime import _normalize_project_name

        assert _normalize_project_name("octolab_test!@#$%") == "octolab_test_____"
        assert _normalize_project_name("octolab test.name") == "octolab_test_name"


class TestComposeRuntimeInit:
    """Tests for ComposeLabRuntime initialization."""

    def test_compose_dir_set_from_compose_path(self, tmp_path):
        """Test that compose_dir is derived from compose_path."""
        from app.runtime.compose_runtime import ComposeLabRuntime

        compose_file = tmp_path / "subdir" / "docker-compose.yml"
        compose_file.parent.mkdir(parents=True)
        compose_file.write_text("version: '3'\n")

        runtime = ComposeLabRuntime(compose_file)

        assert runtime.compose_dir == str(tmp_path / "subdir")


class TestRunCompose:
    """Tests for _run_compose deterministic execution."""

    @pytest.fixture
    def runtime(self, tmp_path):
        """Create a ComposeLabRuntime with a temp compose file."""
        from app.runtime.compose_runtime import ComposeLabRuntime

        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3'\n")

        return ComposeLabRuntime(compose_file)

    @pytest.mark.asyncio
    async def test_run_compose_uses_project_directory_and_cwd(self, runtime, tmp_path):
        """Test that --project-directory and cwd are set correctly."""
        captured_cmd = []
        captured_cwd = []

        def mock_run(*args, **kwargs):
            captured_cmd.append(args[0])
            captured_cwd.append(kwargs.get("cwd"))
            return subprocess.CompletedProcess(args[0], 0, stdout="ok", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            await runtime._run_compose(["-p", "test_project", "up", "-d"])

        assert len(captured_cmd) == 1
        cmd = captured_cmd[0]

        # Verify --project-directory is in command
        assert "--project-directory" in cmd
        pd_index = cmd.index("--project-directory")
        assert cmd[pd_index + 1] == str(tmp_path)

        # Verify cwd was set
        assert captured_cwd[0] == str(tmp_path)

    @pytest.mark.asyncio
    async def test_run_compose_redacts_vnc_password_in_stderr(self, runtime):
        """Test that VNC password is redacted from stderr on failure."""
        from app.runtime.compose_runtime import ComposeCommandError

        secret = "super_secret_vnc_password_12345"

        def mock_run(*args, **kwargs):
            e = subprocess.CalledProcessError(1, args[0])
            e.stdout = ""
            e.stderr = f"Error: VNC_PASSWORD={secret} is invalid"
            raise e

        with patch("subprocess.run", side_effect=mock_run):
            with pytest.raises(ComposeCommandError) as exc_info:
                await runtime._run_compose(
                    ["-p", "test_project", "up", "-d"],
                    secrets_for_redaction=[secret],
                )

        # Verify secret is redacted (pattern-based redaction uses [REDACTED])
        assert secret not in exc_info.value.stderr
        assert "[REDACTED]" in exc_info.value.stderr or "***REDACTED***" in exc_info.value.stderr

    @pytest.mark.asyncio
    async def test_run_compose_truncates_large_output(self, runtime):
        """Test that large output is truncated."""
        from app.runtime.compose_runtime import ComposeCommandError

        # Create huge stderr (>16KB)
        huge_stderr = "x" * 50000

        def mock_run(*args, **kwargs):
            e = subprocess.CalledProcessError(1, args[0])
            e.stdout = ""
            e.stderr = huge_stderr
            raise e

        with patch("subprocess.run", side_effect=mock_run):
            with pytest.raises(ComposeCommandError) as exc_info:
                await runtime._run_compose(["-p", "test_project", "up", "-d"])

        # Verify truncation occurred
        assert len(exc_info.value.stderr) < len(huge_stderr)
        assert "<truncated>" in exc_info.value.stderr

    @pytest.mark.asyncio
    async def test_run_compose_suppress_errors_returns_output(self, runtime):
        """Test that suppress_errors returns sanitized output instead of raising."""

        def mock_run(*args, **kwargs):
            e = subprocess.CalledProcessError(1, args[0])
            e.stdout = "some output"
            e.stderr = "some error"
            raise e

        with patch("subprocess.run", side_effect=mock_run):
            stdout, stderr = await runtime._run_compose(
                ["-p", "test_project", "down"],
                suppress_errors=True,
            )

        # Should return without raising
        assert "output" in stdout or "error" in stderr


class TestCollectComposeDiagnostics:
    """Tests for _collect_compose_diagnostics."""

    @pytest.fixture
    def runtime(self, tmp_path):
        """Create a ComposeLabRuntime with a temp compose file."""
        from app.runtime.compose_runtime import ComposeLabRuntime

        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3'\n")

        return ComposeLabRuntime(compose_file)

    def test_diagnostics_include_failure_stderr(self, runtime):
        """Test that diagnostics include stderr when commands fail."""
        call_count = [0]

        def mock_run(*args, **kwargs):
            call_count[0] += 1
            # Return failure for all commands
            return subprocess.CompletedProcess(
                args[0],
                returncode=1,
                stdout="",
                stderr=f"Error: command {call_count[0]} failed",
            )

        with patch("subprocess.run", side_effect=mock_run):
            diagnostics = runtime._collect_compose_diagnostics("test_project")

        # Verify all diagnostic commands were attempted
        assert "compose_ps" in diagnostics
        assert "compose_logs" in diagnostics
        assert "compose_config" in diagnostics

        # Verify stderr is included (with exit code notation)
        assert "(exit_code=1)" in diagnostics["compose_ps"]
        assert "Error:" in diagnostics["compose_ps"]

    def test_diagnostics_redact_secrets(self, runtime):
        """Test that diagnostics redact secrets."""
        secret = "my_secret_value_xyz"

        def mock_run(*args, **kwargs):
            return subprocess.CompletedProcess(
                args[0],
                returncode=0,
                stdout=f"config contains {secret}",
                stderr="",
            )

        with patch("subprocess.run", side_effect=mock_run):
            diagnostics = runtime._collect_compose_diagnostics(
                "test_project",
                secrets=[secret],
            )

        # Verify secret is redacted
        assert secret not in diagnostics["compose_config"]
        assert "***REDACTED***" in diagnostics["compose_config"]

    def test_diagnostics_handle_timeout(self, runtime):
        """Test that diagnostics handle timeout gracefully."""

        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], 30)

        with patch("subprocess.run", side_effect=mock_run):
            diagnostics = runtime._collect_compose_diagnostics("test_project")

        # Verify timeout is noted
        assert "(timed out)" in diagnostics["compose_ps"]
        assert "(timed out)" in diagnostics["compose_logs"]
        assert "(timed out)" in diagnostics["compose_config"]


class TestComposeCommandError:
    """Tests for ComposeCommandError exception."""

    def test_str_returns_short_message(self):
        """Test that __str__ returns short message without full output."""
        from app.runtime.compose_runtime import ComposeCommandError

        error = ComposeCommandError(
            "docker compose failed",
            cmd=["docker", "compose", "up"],
            cwd="/some/path",
            exit_code=1,
            stdout="a" * 10000,
            stderr="b" * 10000,
        )

        # str() should be the short message, not full output
        assert str(error) == "docker compose failed"
        assert len(str(error)) < 100

    def test_attributes_store_full_output(self):
        """Test that attributes store full (sanitized) output."""
        from app.runtime.compose_runtime import ComposeCommandError

        long_stdout = "stdout_content " * 1000
        long_stderr = "stderr_content " * 1000

        error = ComposeCommandError(
            "docker compose failed",
            cmd=["docker", "compose", "up"],
            cwd="/some/path",
            exit_code=1,
            stdout=long_stdout,
            stderr=long_stderr,
        )

        # Attributes should have full content
        assert error.stdout == long_stdout
        assert error.stderr == long_stderr
        assert error.exit_code == 1
        assert error.cwd == "/some/path"


class TestRedactionUtilities:
    """Tests for redaction utility functions."""

    def test_truncate_text_keeps_head_and_tail(self):
        """Test that truncate_text keeps both head and tail."""
        from app.utils.redact import truncate_text

        # Create text that will be truncated
        text = "HEAD" + "x" * 20000 + "TAIL"

        result = truncate_text(text, limit=1000)

        assert "HEAD" in result
        assert "TAIL" in result
        assert "<truncated>" in result
        assert len(result) <= 1000

    def test_redact_explicit_secrets(self):
        """Test that explicit secrets are redacted."""
        from app.utils.redact import redact_explicit_secrets

        text = "The password is abc123 and token is xyz789"
        result = redact_explicit_secrets(text, ["abc123", "xyz789"])

        assert "abc123" not in result
        assert "xyz789" not in result
        assert "***REDACTED***" in result

    def test_sanitize_output_combines_all(self):
        """Test that sanitize_output combines redaction and truncation."""
        from app.utils.redact import sanitize_output

        # Large text with a secret
        secret = "my_super_secret"
        text = f"Error: PASSWORD={secret}\n" + "x" * 50000

        result = sanitize_output(text, secrets=[secret], limit=1000)

        # Secret should be redacted
        assert secret not in result
        # Pattern-based PASSWORD= should also be redacted
        assert "[REDACTED]" in result or "***REDACTED***" in result
        # Should be truncated
        assert len(result) <= 1000

    def test_sanitize_output_handles_none(self):
        """Test that sanitize_output handles None input."""
        from app.utils.redact import sanitize_output

        assert sanitize_output(None) == ""
        assert sanitize_output(None, secrets=["secret"]) == ""
