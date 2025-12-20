"""Tests for compose_runtime cleanup and network diagnostics.

These tests verify:
- _cleanup_project is called on provisioning failure
- Network count diagnostics are collected (numeric only)
- No broad prune commands are executed
- Pool exhaustion errors include network counts
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import uuid4

import pytest

# Mark all tests as not requiring database
pytestmark = pytest.mark.no_db


class MockLab:
    """Mock Lab object for testing."""

    def __init__(self, lab_id=None, owner_id=None):
        self.id = lab_id or uuid4()
        self.owner_id = owner_id or uuid4()


class TestNetworkCountDiagnostics:
    """Tests for get_network_counts function."""

    def test_returns_numeric_counts_only(self):
        """Test that only counts are returned, not network names."""
        from app.services.docker_net import get_network_counts

        mock_output = "bridge\nhost\noctolab_abc_lab_net\noctolab_abc_egress_net\noctolab_def_lab_net\n"

        def mock_run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, stdout=mock_output, stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            result = get_network_counts()

        # Should have counts, not lists
        assert result.total_count == 5
        assert result.octolab_count == 3
        # Hint should be empty for low count
        assert result.hint == ""

    def test_hint_when_high_count(self):
        """Test that hint is provided when octolab count is high."""
        from app.services.docker_net import get_network_counts

        # Generate 250 octolab networks
        networks = ["bridge", "host"] + [f"octolab_{i}_lab_net" for i in range(250)]
        mock_output = "\n".join(networks)

        def mock_run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, stdout=mock_output, stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            result = get_network_counts()

        assert result.octolab_count == 250
        assert "address pools may be exhausted" in result.hint
        assert "daemon.json" in result.hint

    def test_handles_timeout_gracefully(self):
        """Test that timeout returns empty result without raising."""
        from app.services.docker_net import get_network_counts

        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], 10)

        with patch("subprocess.run", side_effect=mock_run):
            result = get_network_counts()

        # Should return empty counts, not raise
        assert result.total_count == 0
        assert result.octolab_count == 0

    def test_handles_error_gracefully(self):
        """Test that errors return empty result without raising."""
        from app.services.docker_net import get_network_counts

        def mock_run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 1, stdout="", stderr="error")

        with patch("subprocess.run", side_effect=mock_run):
            result = get_network_counts()

        assert result.total_count == 0
        assert result.octolab_count == 0


class TestCleanupProject:
    """Tests for _cleanup_project method."""

    @pytest.fixture
    def runtime(self, tmp_path):
        """Create a ComposeLabRuntime with a temp compose file."""
        from app.runtime.compose_runtime import ComposeLabRuntime

        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3'\n")

        return ComposeLabRuntime(compose_file)

    @pytest.mark.asyncio
    async def test_cleanup_calls_compose_down(self, runtime):
        """Test that _cleanup_project calls compose down."""
        captured_commands = []

        def mock_run(*args, **kwargs):
            captured_commands.append(args[0])
            return subprocess.CompletedProcess(args[0], 0, stdout="ok", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            result = await runtime._cleanup_project("test_project")

        # Should have called compose down
        down_calls = [cmd for cmd in captured_commands if "down" in cmd]
        assert len(down_calls) >= 1

        # Verify --remove-orphans is used
        down_cmd = down_calls[0]
        assert "--remove-orphans" in down_cmd

        # Should NOT have --volumes (preserve evidence)
        assert "--volumes" not in down_cmd

    @pytest.mark.asyncio
    async def test_cleanup_never_calls_prune(self, runtime):
        """Test that _cleanup_project never calls docker network/system prune."""
        captured_commands = []

        def mock_run(*args, **kwargs):
            captured_commands.append(args[0])
            return subprocess.CompletedProcess(args[0], 0, stdout="ok", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            await runtime._cleanup_project("test_project")

        # Should never call docker network prune or docker system prune
        # Note: "remove-orphans" contains "prune" as substring, so we check for explicit prune commands
        for cmd in captured_commands:
            cmd_str = " ".join(cmd).lower()
            assert "network prune" not in cmd_str, f"Unexpected network prune: {cmd}"
            assert "system prune" not in cmd_str, f"Unexpected system prune: {cmd}"

    @pytest.mark.asyncio
    async def test_cleanup_is_best_effort(self, runtime):
        """Test that _cleanup_project doesn't raise on failures."""

        def mock_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, args[0], stdout="", stderr="error")

        with patch("subprocess.run", side_effect=mock_run):
            # Should not raise
            result = await runtime._cleanup_project("test_project")

        # Should have error info in result
        assert "compose_down" in result
        assert "error" in result["compose_down"]


class TestCleanupOnFailure:
    """Tests for cleanup being called on provisioning failure."""

    @pytest.fixture
    def runtime(self, tmp_path):
        """Create a ComposeLabRuntime with a temp compose file."""
        from app.runtime.compose_runtime import ComposeLabRuntime

        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3'\n")

        return ComposeLabRuntime(compose_file)

    @pytest.mark.asyncio
    async def test_cleanup_called_on_pool_exhaustion(self, runtime):
        """Test that cleanup is invoked when pool exhaustion occurs."""
        from app.runtime.compose_runtime import ComposeCommandError

        lab = MockLab()
        call_count = {"up": 0, "down": 0}

        def mock_run(*args, **kwargs):
            cmd_str = " ".join(args[0])
            if "up" in cmd_str:
                call_count["up"] += 1
                e = subprocess.CalledProcessError(1, args[0])
                e.stdout = ""
                e.stderr = "could not find an available, non-overlapping ipv4 address pool"
                raise e
            elif "down" in cmd_str:
                call_count["down"] += 1
                return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")
            else:
                return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

        # Mock database session and port allocator
        mock_session = AsyncMock()

        with patch("subprocess.run", side_effect=mock_run):
            with patch("app.runtime.compose_runtime.allocate_novnc_port", return_value=30000):
                with patch("app.runtime.compose_runtime.release_novnc_port"):
                    with patch("app.runtime.compose_runtime.preflight_network_cleanup") as mock_preflight:
                        mock_preflight.return_value = MagicMock(removed_count=0)
                        with patch("app.runtime.compose_runtime.settings") as mock_settings:
                            mock_settings.compose_bind_host = "127.0.0.1"
                            mock_settings.vnc_auth_mode = "password"
                            mock_settings.guac_enabled = False
                            mock_settings.dev_force_cmdlog_rebuild = False
                            mock_settings.net_rm_max_retries = 1
                            mock_settings.net_rm_backoff_ms = 100
                            mock_settings.control_plane_containers = []

                            from app.runtime.exceptions import NetworkPoolExhaustedError

                            with pytest.raises(NetworkPoolExhaustedError) as exc_info:
                                await runtime.create_lab(
                                    lab,
                                    MagicMock(),
                                    db_session=mock_session,
                                    vnc_password="test_password",
                                )

        # Verify pool exhaustion error includes network info
        assert "octolab_networks=" in str(exc_info.value)


class TestDiagnosticsIncludeNetworkCounts:
    """Tests for diagnostics including network counts."""

    @pytest.fixture
    def runtime(self, tmp_path):
        """Create a ComposeLabRuntime with a temp compose file."""
        from app.runtime.compose_runtime import ComposeLabRuntime

        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3'\n")

        return ComposeLabRuntime(compose_file)

    def test_diagnostics_include_network_counts(self, runtime):
        """Test that _collect_compose_diagnostics includes network counts."""
        mock_compose_output = subprocess.CompletedProcess(
            ["docker", "compose"], 0, stdout="ok", stderr=""
        )
        mock_network_output = "bridge\nhost\noctolab_abc_lab_net\noctolab_abc_egress_net\n"

        call_count = [0]

        def mock_run(*args, **kwargs):
            call_count[0] += 1
            cmd = args[0]
            if cmd[0:2] == ["docker", "network"]:
                return subprocess.CompletedProcess(cmd, 0, stdout=mock_network_output, stderr="")
            return mock_compose_output

        with patch("subprocess.run", side_effect=mock_run):
            diagnostics = runtime._collect_compose_diagnostics("test_project")

        # Should include network counts
        assert "network_total_count" in diagnostics
        assert "network_octolab_count" in diagnostics
        assert diagnostics["network_total_count"] == "4"
        assert diagnostics["network_octolab_count"] == "2"


class TestNoAutomaticPrune:
    """Tests ensuring no automatic prune commands are ever executed."""

    def test_preflight_cleanup_never_calls_global_prune(self):
        """Test that preflight cleanup doesn't call docker network/system prune."""
        from app.services.docker_net import preflight_cleanup_stale_lab_networks

        captured_commands = []

        def mock_run(*args, **kwargs):
            captured_commands.append(args[0])
            cmd_str = " ".join(args[0])

            if "network ls" in cmd_str:
                # Return some networks
                return subprocess.CompletedProcess(
                    args[0], 0,
                    stdout='{"Name":"octolab_abc_lab_net","Driver":"bridge","Scope":"local"}\n',
                    stderr=""
                )
            elif "network inspect" in cmd_str:
                # Return empty containers (eligible for removal)
                return subprocess.CompletedProcess(args[0], 0, stdout="{}", stderr="")
            elif "network rm" in cmd_str:
                return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")
            else:
                return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            preflight_cleanup_stale_lab_networks()

        # Verify no prune commands
        for cmd in captured_commands:
            cmd_str = " ".join(cmd).lower()
            assert "prune" not in cmd_str, f"Unexpected prune command: {cmd}"
            assert "system" not in cmd_str, f"Unexpected system command: {cmd}"
