"""Tests for compose_runtime teardown and network cleanup.

These tests verify:
- destroy_lab runs compose down with correct arguments
- Label-based network cleanup only removes labeled octolab_* networks
- Networks with containers are not removed
- Provisioning failure triggers cleanup
- No prune commands are ever executed
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


class TestDestroyLabComposeDown:
    """Tests for destroy_lab running compose down."""

    @pytest.fixture
    def runtime(self, tmp_path):
        """Create a ComposeLabRuntime with a temp compose file."""
        from app.runtime.compose_runtime import ComposeLabRuntime

        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3'\n")

        return ComposeLabRuntime(compose_file)

    @pytest.mark.asyncio
    async def test_destroy_lab_runs_compose_down(self, runtime, tmp_path):
        """Test that destroy_lab runs compose down with correct arguments."""
        lab = MockLab()
        captured_commands = []

        def mock_run(*args, **kwargs):
            captured_commands.append({
                "cmd": args[0],
                "cwd": kwargs.get("cwd"),
                "shell": kwargs.get("shell", False),
            })
            return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            with patch("app.runtime.compose_runtime.release_novnc_port", new_callable=AsyncMock):
                await runtime.destroy_lab(lab)

        # Find the compose down command
        down_calls = [c for c in captured_commands if "down" in " ".join(c["cmd"])]
        assert len(down_calls) >= 1, "Expected at least one 'down' command"

        down_cmd = down_calls[0]

        # Verify command structure
        assert down_cmd["cmd"][0:2] == ["docker", "compose"]
        assert "--project-directory" in down_cmd["cmd"]
        assert "--remove-orphans" in down_cmd["cmd"]
        assert f"-p" in down_cmd["cmd"]

        # Verify project name contains lab id
        project_idx = down_cmd["cmd"].index("-p")
        project_name = down_cmd["cmd"][project_idx + 1]
        assert str(lab.id) in project_name

        # Verify cwd is set correctly
        assert down_cmd["cwd"] == str(tmp_path)

        # Verify shell=False (implicit since cmd is a list)
        assert down_cmd["shell"] is False

    @pytest.mark.asyncio
    async def test_destroy_lab_never_calls_prune(self, runtime):
        """Test that destroy_lab never calls docker prune commands."""
        lab = MockLab()
        captured_commands = []

        def mock_run(*args, **kwargs):
            captured_commands.append(args[0])
            return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            with patch("app.runtime.compose_runtime.release_novnc_port", new_callable=AsyncMock):
                await runtime.destroy_lab(lab)

        # Verify no prune commands
        for cmd in captured_commands:
            cmd_str = " ".join(cmd).lower()
            assert "network prune" not in cmd_str, f"Unexpected network prune: {cmd}"
            assert "system prune" not in cmd_str, f"Unexpected system prune: {cmd}"


class TestLabelBasedNetworkCleanup:
    """Tests for label-based network cleanup."""

    @pytest.fixture
    def runtime(self, tmp_path):
        """Create a ComposeLabRuntime with a temp compose file."""
        from app.runtime.compose_runtime import ComposeLabRuntime

        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3'\n")

        return ComposeLabRuntime(compose_file)

    def test_cleanup_only_removes_labeled_octolab_networks(self, runtime):
        """Test that cleanup only removes networks with compose project label AND octolab_ prefix."""
        lab = MockLab()
        project = f"octolab_{lab.id}"

        call_log = []

        def mock_run(*args, **kwargs):
            cmd = args[0]
            cmd_str = " ".join(cmd)
            call_log.append(cmd)

            # network ls with label filter
            if "network ls" in cmd_str and "label=" in cmd_str:
                # Return mix of octolab and non-octolab networks (shouldn't happen but defense-in-depth)
                return subprocess.CompletedProcess(
                    cmd, 0,
                    stdout=f"octolab_{lab.id}_lab_net\noctolab_{lab.id}_egress_net\nother_network\n",
                    stderr=""
                )
            # network inspect for container count
            elif "network inspect" in cmd_str and "len .Containers" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, stdout="0", stderr="")
            # network rm
            elif "network rm" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            else:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            stats = runtime._cleanup_project_networks_by_label(project)

        # Should have found 2 networks (the octolab ones)
        assert stats["networks_found"] == 2

        # Verify network rm was called only for octolab_ networks
        rm_calls = [c for c in call_log if "network rm" in " ".join(c)]
        for rm_call in rm_calls:
            net_name = rm_call[-1]  # Network name is last argument
            assert net_name.startswith("octolab_"), f"Removed non-octolab network: {net_name}"

    def test_cleanup_does_not_remove_network_with_containers(self, runtime):
        """Test that networks with attached containers are not removed."""
        lab = MockLab()
        project = f"octolab_{lab.id}"

        rm_calls = []

        def mock_run(*args, **kwargs):
            cmd = args[0]
            cmd_str = " ".join(cmd)

            # network ls with label filter
            if "network ls" in cmd_str and "label=" in cmd_str:
                return subprocess.CompletedProcess(
                    cmd, 0,
                    stdout=f"octolab_{lab.id}_lab_net\n",
                    stderr=""
                )
            # network inspect - report 2 containers attached
            elif "network inspect" in cmd_str and "len .Containers" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, stdout="2", stderr="")
            # network rm - track calls
            elif "network rm" in cmd_str:
                rm_calls.append(cmd)
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            else:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            stats = runtime._cleanup_project_networks_by_label(project)

        # Should have found 1 network
        assert stats["networks_found"] == 1
        # Should have skipped it (has containers)
        assert stats["networks_skipped_attached"] == 1
        # Should NOT have removed any
        assert stats["networks_removed"] == 0
        # network rm should NOT have been called
        assert len(rm_calls) == 0


class TestDestroyLabLabelCleanup:
    """Tests for destroy_lab using label-based cleanup."""

    @pytest.fixture
    def runtime(self, tmp_path):
        """Create a ComposeLabRuntime with a temp compose file."""
        from app.runtime.compose_runtime import ComposeLabRuntime

        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3'\n")

        return ComposeLabRuntime(compose_file)

    @pytest.mark.asyncio
    async def test_destroy_lab_uses_label_cleanup(self, runtime):
        """Test that destroy_lab calls label-based cleanup after compose down."""
        lab = MockLab()
        project = f"octolab_{lab.id}"

        label_filter_called = []

        def mock_run(*args, **kwargs):
            cmd = args[0]
            cmd_str = " ".join(cmd)

            # Track label-based network listing
            if "network ls" in cmd_str and "label=com.docker.compose.project" in cmd_str:
                label_filter_called.append(cmd)
                return subprocess.CompletedProcess(
                    cmd, 0,
                    stdout=f"octolab_{lab.id}_lab_net\noctolab_{lab.id}_egress_net\n",
                    stderr=""
                )
            # network inspect - empty
            elif "network inspect" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, stdout="0", stderr="")
            # network rm
            elif "network rm" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            # compose down
            elif "compose" in cmd_str and "down" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            else:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            with patch("app.runtime.compose_runtime.release_novnc_port", new_callable=AsyncMock):
                await runtime.destroy_lab(lab)

        # Verify label-based network listing was called
        assert len(label_filter_called) >= 1, "Expected label-based network listing"

        # Verify the filter contained the correct project name
        filter_cmd = label_filter_called[0]
        assert any(f"label=com.docker.compose.project={project}" in arg for arg in filter_cmd)


class TestCreateLabFailureTriggersTeardown:
    """Tests for provisioning failure triggering cleanup."""

    @pytest.fixture
    def runtime(self, tmp_path):
        """Create a ComposeLabRuntime with a temp compose file."""
        from app.runtime.compose_runtime import ComposeLabRuntime

        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3'\n")

        return ComposeLabRuntime(compose_file)

    @pytest.mark.asyncio
    async def test_create_lab_failure_triggers_cleanup(self, runtime):
        """Test that provisioning failure triggers _cleanup_project."""
        from app.runtime.compose_runtime import ComposeCommandError

        lab = MockLab()
        cleanup_called = []

        # Store original method
        original_cleanup = runtime._cleanup_project

        async def mock_cleanup(project, secrets=None):
            cleanup_called.append(project)
            return {"compose_down": "ok"}

        runtime._cleanup_project = mock_cleanup

        up_call_count = [0]

        def mock_run(*args, **kwargs):
            cmd = args[0]
            cmd_str = " ".join(cmd)

            # compose up - fail
            if "up" in cmd_str and "-d" in cmd_str:
                up_call_count[0] += 1
                e = subprocess.CalledProcessError(1, cmd)
                e.stdout = ""
                e.stderr = "simulated failure"
                raise e
            # Everything else succeeds
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        mock_session = AsyncMock()
        mock_recipe = MagicMock()

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

                            with pytest.raises(RuntimeError) as exc_info:
                                await runtime.create_lab(
                                    lab,
                                    mock_recipe,
                                    db_session=mock_session,
                                    vnc_password="test_password",
                                )

        # Verify cleanup was called
        assert len(cleanup_called) >= 1, "Expected _cleanup_project to be called on failure"
        assert str(lab.id) in cleanup_called[0]


class TestListNetworksByComposeProject:
    """Tests for list_networks_by_compose_project function."""

    def test_returns_only_octolab_prefixed_networks(self):
        """Test that only octolab_ prefixed networks are returned."""
        from app.services.docker_net import list_networks_by_compose_project

        project = "octolab_test-uuid"

        def mock_run(*args, **kwargs):
            # Return mixed networks (shouldn't happen but defense-in-depth)
            return subprocess.CompletedProcess(
                args[0], 0,
                stdout="octolab_test-uuid_lab_net\noctolab_test-uuid_egress_net\nother_network\n",
                stderr=""
            )

        with patch("subprocess.run", side_effect=mock_run):
            networks = list_networks_by_compose_project(project)

        # Should only include octolab_ networks
        assert len(networks) == 2
        for net in networks:
            assert net.startswith("octolab_")

    def test_handles_timeout_gracefully(self):
        """Test that timeout returns empty list without raising."""
        from app.services.docker_net import list_networks_by_compose_project

        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], 10)

        with patch("subprocess.run", side_effect=mock_run):
            networks = list_networks_by_compose_project("test_project")

        assert networks == []


class TestGetNetworkContainerCount:
    """Tests for get_network_container_count function."""

    def test_returns_container_count(self):
        """Test that container count is returned correctly."""
        from app.services.docker_net import get_network_container_count

        def mock_run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, stdout="3", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            count = get_network_container_count("test_network")

        assert count == 3

    def test_returns_negative_one_on_error(self):
        """Test that -1 is returned on error."""
        from app.services.docker_net import get_network_container_count

        def mock_run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 1, stdout="", stderr="not found")

        with patch("subprocess.run", side_effect=mock_run):
            count = get_network_container_count("nonexistent_network")

        assert count == -1
