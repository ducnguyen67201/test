"""Tests for network leak inspection and extended cleanup.

These tests verify:
- Network leak inspection returns correct classification
- Extended cleanup respects mode (networks_only vs remove_exited_lab_containers)
- Nonlab containers block cleanup
- Running containers block cleanup
- No prune commands are ever used
- shell=False is always used
"""

import pytest
from unittest.mock import patch, MagicMock
from subprocess import CompletedProcess

# Mark all tests as not requiring database
pytestmark = pytest.mark.no_db


class TestInspectContainerState:
    """Tests for inspect_container_state function."""

    def test_returns_running_state(self):
        """Test that running containers are identified correctly."""
        from app.services.docker_net import inspect_container_state

        mock_result = CompletedProcess(
            args=[],
            returncode=0,
            stdout="/test-container\ttrue\trunning\toctolab_12345678-1234-1234-1234-123456789abc",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            info = inspect_container_state("abc123")

            assert info is not None
            assert info.name == "test-container"
            assert info.state == "running"
            assert info.project == "octolab_12345678-1234-1234-1234-123456789abc"
            assert info.is_lab is True

            # Verify shell=False
            mock_run.assert_called_once()
            assert mock_run.call_args.kwargs.get("shell") is False

    def test_returns_exited_state(self):
        """Test that exited containers are identified correctly."""
        from app.services.docker_net import inspect_container_state

        mock_result = CompletedProcess(
            args=[],
            returncode=0,
            stdout="/test-container\tfalse\texited\toctolab_12345678-1234-1234-1234-123456789abc",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result):
            info = inspect_container_state("abc123")

            assert info is not None
            assert info.state == "exited"
            assert info.is_lab is True

    def test_identifies_nonlab_container(self):
        """Test that nonlab containers are identified correctly."""
        from app.services.docker_net import inspect_container_state

        mock_result = CompletedProcess(
            args=[],
            returncode=0,
            stdout="/guacamole-guacd-1\tfalse\texited\tguacamole",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result):
            info = inspect_container_state("abc123")

            assert info is not None
            assert info.is_lab is False
            assert info.project == "guacamole"

    def test_returns_none_on_error(self):
        """Test that errors return None."""
        from app.services.docker_net import inspect_container_state

        mock_result = CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Error: No such container",
        )

        with patch("subprocess.run", return_value=mock_result):
            info = inspect_container_state("abc123")
            assert info is None


class TestInspectNetworkLeak:
    """Tests for inspect_network_leak function."""

    def test_returns_empty_for_detached_network(self):
        """Test that detached networks show 0 attached containers."""
        from app.services.docker_net import inspect_network_leak

        with patch("app.services.docker_net.inspect_network_containers", return_value={}):
            info = inspect_network_leak("octolab_test_lab_net")

            assert info is not None
            assert info.attached_containers == 0
            assert info.attached_running == 0
            assert info.attached_exited == 0
            assert info.blocked_by_nonlab is False

    def test_identifies_running_lab_containers(self):
        """Test that running lab containers are correctly counted."""
        from app.services.docker_net import inspect_network_leak, AttachedContainerInfo

        mock_containers = {
            "abc123": {"Name": "octolab-test-1"},
        }

        mock_container_info = AttachedContainerInfo(
            container_id="abc123",
            name="octolab-test-1",
            state="running",
            project="octolab_12345678-1234-1234-1234-123456789abc",
            is_lab=True,
        )

        with patch("app.services.docker_net.inspect_network_containers", return_value=mock_containers):
            with patch("app.services.docker_net.inspect_container_state", return_value=mock_container_info):
                info = inspect_network_leak("octolab_test_lab_net")

                assert info is not None
                assert info.attached_containers == 1
                assert info.attached_running == 1
                assert info.lab_attached == 1
                assert info.blocked_by_nonlab is False

    def test_identifies_nonlab_containers(self):
        """Test that nonlab containers trigger blocked_by_nonlab."""
        from app.services.docker_net import inspect_network_leak, AttachedContainerInfo

        mock_containers = {
            "abc123": {"Name": "guacamole-guacd-1"},
        }

        mock_container_info = AttachedContainerInfo(
            container_id="abc123",
            name="guacamole-guacd-1",
            state="exited",
            project="guacamole",
            is_lab=False,
        )

        with patch("app.services.docker_net.inspect_network_containers", return_value=mock_containers):
            with patch("app.services.docker_net.inspect_container_state", return_value=mock_container_info):
                info = inspect_network_leak("octolab_test_lab_net")

                assert info is not None
                assert info.nonlab_attached == 1
                assert info.blocked_by_nonlab is True


class TestScanNetworkLeaks:
    """Tests for scan_network_leaks function."""

    def test_returns_empty_when_no_networks(self):
        """Test that empty network list returns empty result."""
        from app.services.docker_net import scan_network_leaks

        with patch("app.services.docker_net.list_all_octolab_networks", return_value=[]):
            result = scan_network_leaks()

            assert result.total_candidates == 0
            assert result.detached == 0
            assert result.in_use == 0
            assert result.networks == []

    def test_counts_detached_and_in_use(self):
        """Test that detached and in-use networks are counted correctly."""
        from app.services.docker_net import scan_network_leaks, NetworkLeakInfo

        mock_networks = [
            "octolab_11111111-1111-1111-1111-111111111111_lab_net",
            "octolab_22222222-2222-2222-2222-222222222222_lab_net",
        ]

        def mock_inspect(network_name, **kwargs):
            if "11111111" in network_name:
                return NetworkLeakInfo(
                    network=network_name,
                    attached_containers=0,
                    attached_running=0,
                    attached_exited=0,
                    lab_attached=0,
                    nonlab_attached=0,
                    blocked_by_nonlab=False,
                    sample=[],
                )
            else:
                return NetworkLeakInfo(
                    network=network_name,
                    attached_containers=2,
                    attached_running=0,
                    attached_exited=2,
                    lab_attached=2,
                    nonlab_attached=0,
                    blocked_by_nonlab=False,
                    sample=[],
                )

        with patch("app.services.docker_net.list_all_octolab_networks", return_value=mock_networks):
            with patch("app.services.docker_net.inspect_network_leak", side_effect=mock_inspect):
                result = scan_network_leaks()

                assert result.total_candidates == 2
                assert result.detached == 1
                assert result.in_use == 1
                assert len(result.networks) == 1  # Only in-use networks returned


class TestRemoveLabContainersById:
    """Tests for remove_lab_containers_by_id function."""

    def test_uses_docker_rm_not_rm_f(self):
        """Test that docker rm (not rm -f) is used for safety."""
        from app.services.docker_net import remove_lab_containers_by_id

        mock_result = CompletedProcess(
            args=[],
            returncode=0,
            stdout="abc123\ndef456",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            removed, errors = remove_lab_containers_by_id(["abc123", "def456"])

            assert removed == 2
            assert errors == []

            # Verify docker rm is called (not docker rm -f)
            call_args = mock_run.call_args
            cmd = call_args[0][0]
            assert cmd[0] == "docker"
            assert cmd[1] == "rm"
            assert "-f" not in cmd
            assert mock_run.call_args.kwargs.get("shell") is False

    def test_returns_zero_for_empty_list(self):
        """Test that empty list returns 0 removed."""
        from app.services.docker_net import remove_lab_containers_by_id

        removed, errors = remove_lab_containers_by_id([])
        assert removed == 0
        assert errors == []


class TestExtendedNetworkCleanup:
    """Tests for extended_network_cleanup function."""

    def test_networks_only_mode_skips_exited_containers(self):
        """Test that networks_only mode skips networks with exited containers."""
        from app.services.docker_net import (
            extended_network_cleanup,
            CleanupMode,
            NetworkLeakInfo,
            ContainerStatusInfo,
        )

        mock_networks = ["octolab_11111111-1111-1111-1111-111111111111_lab_net"]

        mock_status = ContainerStatusInfo(running_lab_containers=0)

        mock_leak_info = NetworkLeakInfo(
            network=mock_networks[0],
            attached_containers=1,
            attached_running=0,
            attached_exited=1,
            lab_attached=1,
            nonlab_attached=0,
            blocked_by_nonlab=False,
            sample=[],
        )

        with patch("app.services.docker_net.get_running_container_status", return_value=mock_status):
            with patch("app.services.docker_net.list_all_octolab_networks", return_value=mock_networks):
                with patch("app.services.docker_net.inspect_network_leak", return_value=mock_leak_info):
                    result = extended_network_cleanup(CleanupMode.NETWORKS_ONLY)

                    assert result.networks_found == 1
                    assert result.networks_removed == 0
                    assert result.networks_skipped_in_use_exited == 1
                    assert result.containers_removed == 0

    def test_remove_exited_mode_removes_lab_containers(self):
        """Test that remove_exited mode removes exited lab containers."""
        from app.services.docker_net import (
            extended_network_cleanup,
            CleanupMode,
            NetworkLeakInfo,
            NetworkRemoveResult,
            ContainerStatusInfo,
            AttachedContainerInfo,
        )

        mock_networks = ["octolab_11111111-1111-1111-1111-111111111111_lab_net"]

        mock_status = ContainerStatusInfo(running_lab_containers=0)

        mock_leak_info = NetworkLeakInfo(
            network=mock_networks[0],
            attached_containers=1,
            attached_running=0,
            attached_exited=1,
            lab_attached=1,
            nonlab_attached=0,
            blocked_by_nonlab=False,
            sample=[],
        )

        mock_container_info = AttachedContainerInfo(
            container_id="abc123",
            name="octolab-test-1",
            state="exited",
            project="octolab_11111111-1111-1111-1111-111111111111",
            is_lab=True,
        )

        with patch("app.services.docker_net.get_running_container_status", return_value=mock_status):
            with patch("app.services.docker_net.list_all_octolab_networks", return_value=mock_networks):
                with patch("app.services.docker_net.inspect_network_leak", return_value=mock_leak_info):
                    with patch("app.services.docker_net.inspect_network_containers", return_value={"abc123": {}}):
                        with patch("app.services.docker_net.inspect_container_state", return_value=mock_container_info):
                            with patch("app.services.docker_net.remove_lab_containers_by_id", return_value=(1, [])):
                                with patch("app.services.docker_net.get_network_container_count", return_value=0):
                                    with patch("app.services.docker_net.remove_network", return_value=NetworkRemoveResult.OK):
                                        result = extended_network_cleanup(
                                            CleanupMode.REMOVE_EXITED_LAB_CONTAINERS_THEN_NETWORKS
                                        )

                                        assert result.networks_removed == 1
                                        assert result.containers_removed == 1

    def test_nonlab_containers_block_cleanup(self):
        """Test that nonlab containers block cleanup of that network."""
        from app.services.docker_net import (
            extended_network_cleanup,
            CleanupMode,
            NetworkLeakInfo,
            ContainerStatusInfo,
        )

        mock_networks = ["octolab_11111111-1111-1111-1111-111111111111_lab_net"]

        mock_status = ContainerStatusInfo(running_lab_containers=0)

        # Network has nonlab container attached
        mock_leak_info = NetworkLeakInfo(
            network=mock_networks[0],
            attached_containers=1,
            attached_running=0,
            attached_exited=1,
            lab_attached=0,
            nonlab_attached=1,
            blocked_by_nonlab=True,
            sample=[],
        )

        with patch("app.services.docker_net.get_running_container_status", return_value=mock_status):
            with patch("app.services.docker_net.list_all_octolab_networks", return_value=mock_networks):
                with patch("app.services.docker_net.inspect_network_leak", return_value=mock_leak_info):
                    result = extended_network_cleanup(
                        CleanupMode.REMOVE_EXITED_LAB_CONTAINERS_THEN_NETWORKS
                    )

                    # Network should be skipped due to nonlab container
                    assert result.networks_skipped_blocked_nonlab == 1
                    assert result.networks_removed == 0
                    assert result.containers_removed == 0

    def test_running_containers_block_cleanup(self):
        """Test that running containers block cleanup of that network."""
        from app.services.docker_net import (
            extended_network_cleanup,
            CleanupMode,
            NetworkLeakInfo,
            ContainerStatusInfo,
        )

        mock_networks = ["octolab_11111111-1111-1111-1111-111111111111_lab_net"]

        mock_status = ContainerStatusInfo(running_lab_containers=0)

        # Network has running container attached
        mock_leak_info = NetworkLeakInfo(
            network=mock_networks[0],
            attached_containers=1,
            attached_running=1,
            attached_exited=0,
            lab_attached=1,
            nonlab_attached=0,
            blocked_by_nonlab=False,
            sample=[],
        )

        with patch("app.services.docker_net.get_running_container_status", return_value=mock_status):
            with patch("app.services.docker_net.list_all_octolab_networks", return_value=mock_networks):
                with patch("app.services.docker_net.inspect_network_leak", return_value=mock_leak_info):
                    result = extended_network_cleanup(
                        CleanupMode.REMOVE_EXITED_LAB_CONTAINERS_THEN_NETWORKS
                    )

                    # Network should be skipped due to running container
                    assert result.networks_skipped_in_use_running == 1
                    assert result.networks_removed == 0

    def test_refuses_when_lab_containers_running(self):
        """Test that cleanup refuses when any lab containers are running."""
        from app.services.docker_net import (
            extended_network_cleanup,
            CleanupMode,
            ContainerStatusInfo,
        )

        mock_status = ContainerStatusInfo(running_lab_containers=5)

        with patch("app.services.docker_net.get_running_container_status", return_value=mock_status):
            result = extended_network_cleanup(CleanupMode.NETWORKS_ONLY)

            # Should return early with no action
            assert result.networks_found == 0
            assert result.networks_removed == 0


class TestSecurityInvariants:
    """Tests for security invariants."""

    def test_inspect_container_state_uses_shell_false(self):
        """Test that inspect_container_state uses shell=False."""
        from app.services.docker_net import inspect_container_state

        mock_result = CompletedProcess(
            args=[],
            returncode=0,
            stdout="/test\ttrue\trunning\ttest",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            inspect_container_state("test")
            assert mock_run.call_args.kwargs.get("shell") is False

    def test_remove_lab_containers_uses_shell_false(self):
        """Test that remove_lab_containers_by_id uses shell=False."""
        from app.services.docker_net import remove_lab_containers_by_id

        mock_result = CompletedProcess(
            args=[],
            returncode=0,
            stdout="test",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            remove_lab_containers_by_id(["test"])
            assert mock_run.call_args.kwargs.get("shell") is False

    def test_no_prune_commands_in_extended_cleanup(self):
        """Test that no prune commands are used in extended cleanup."""
        from app.services.docker_net import (
            extended_network_cleanup,
            CleanupMode,
            ContainerStatusInfo,
        )

        mock_status = ContainerStatusInfo(running_lab_containers=0)

        with patch("app.services.docker_net.get_running_container_status", return_value=mock_status):
            with patch("app.services.docker_net.list_all_octolab_networks", return_value=[]):
                with patch("subprocess.run") as mock_run:
                    extended_network_cleanup(CleanupMode.NETWORKS_ONLY)

                    # Check no prune commands were called
                    for call in mock_run.call_args_list:
                        cmd = call[0][0] if call[0] else call.kwargs.get("args", [])
                        if cmd:
                            cmd_str = " ".join(cmd)
                            assert "prune" not in cmd_str.lower()


class TestResponseModels:
    """Tests for response model formats."""

    def test_network_leak_info_response_format(self):
        """Test NetworkLeakInfoResponse has expected fields."""
        from app.api.routes.admin import NetworkLeakInfoResponse, AttachedContainerSample

        sample = AttachedContainerSample(
            container="test-container",
            state="exited",
            project="octolab_test",
        )

        response = NetworkLeakInfoResponse(
            network="octolab_test_lab_net",
            attached_containers=1,
            attached_running=0,
            attached_exited=1,
            lab_attached=1,
            nonlab_attached=0,
            blocked_by_nonlab=False,
            sample=[sample],
        )

        assert response.network == "octolab_test_lab_net"
        assert response.attached_containers == 1
        assert response.blocked_by_nonlab is False
        assert len(response.sample) == 1
        assert response.sample[0].state == "exited"

    def test_extended_cleanup_response_format(self):
        """Test ExtendedCleanupResponse has expected fields."""
        from app.api.routes.admin import ExtendedCleanupResponse

        response = ExtendedCleanupResponse(
            mode="networks_only",
            networks_found=10,
            networks_removed=5,
            networks_failed=0,
            networks_skipped_in_use_running=2,
            networks_skipped_in_use_exited=3,
            networks_skipped_blocked_nonlab=0,
            containers_removed=0,
            message="Cleanup completed.",
            debug=None,
        )

        assert response.mode == "networks_only"
        assert response.networks_found == 10
        assert response.networks_removed == 5
        assert response.networks_skipped_in_use_running == 2
        assert response.networks_skipped_in_use_exited == 3

    def test_extended_cleanup_mode_enum(self):
        """Test ExtendedCleanupMode enum values."""
        from app.api.routes.admin import ExtendedCleanupMode

        assert ExtendedCleanupMode.NETWORKS_ONLY.value == "networks_only"
        assert ExtendedCleanupMode.REMOVE_EXITED_LAB_CONTAINERS_THEN_NETWORKS.value == "remove_exited_lab_containers_then_networks"


class TestCleanupModeEnum:
    """Tests for CleanupMode enum in docker_net."""

    def test_cleanup_mode_values(self):
        """Test CleanupMode enum values."""
        from app.services.docker_net import CleanupMode

        assert CleanupMode.NETWORKS_ONLY.value == "networks_only"
        assert CleanupMode.REMOVE_EXITED_LAB_CONTAINERS_THEN_NETWORKS.value == "remove_exited_lab_containers_then_networks"
