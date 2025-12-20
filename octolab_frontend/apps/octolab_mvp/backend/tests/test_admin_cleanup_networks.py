"""Tests for admin network cleanup functionality.

These tests verify:
- Admin cleanup refuses if any OctoLab containers are running
- Admin cleanup only removes octolab_<uuid>_* networks
- Admin cleanup never calls docker network/system prune
- Admin authorization is enforced
"""

import subprocess
from unittest.mock import patch, MagicMock

import pytest

# Mark all tests as not requiring database
pytestmark = pytest.mark.no_db


class TestListRunningOctolabContainers:
    """Tests for list_running_octolab_containers function."""

    def test_returns_only_octolab_containers(self):
        """Test that only octolab_ prefixed containers are returned."""
        from app.services.docker_net import list_running_octolab_containers

        def mock_run(*args, **kwargs):
            # Mix of octolab and non-octolab containers
            return subprocess.CompletedProcess(
                args[0], 0,
                stdout="octolab_abc-octobox-1\noctolab_abc-target-web-1\nnginx\nredis\n",
                stderr=""
            )

        with patch("subprocess.run", side_effect=mock_run):
            containers = list_running_octolab_containers()

        assert len(containers) == 2
        for c in containers:
            assert c.startswith("octolab_")

    def test_returns_empty_on_error(self):
        """Test that errors return empty list without raising."""
        from app.services.docker_net import list_running_octolab_containers

        def mock_run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 1, stdout="", stderr="error")

        with patch("subprocess.run", side_effect=mock_run):
            containers = list_running_octolab_containers()

        assert containers == []


class TestListAllOctolabNetworks:
    """Tests for list_all_octolab_networks function."""

    def test_returns_only_strict_lab_networks(self):
        """Test that only strict lab pattern networks are returned."""
        from app.services.docker_net import list_all_octolab_networks

        def mock_run(*args, **kwargs):
            # Mix of lab networks and infrastructure networks
            return subprocess.CompletedProcess(
                args[0], 0,
                stdout=(
                    "bridge\n"
                    "host\n"
                    "octolab_12345678-1234-1234-1234-123456789abc_lab_net\n"
                    "octolab_12345678-1234-1234-1234-123456789abc_egress_net\n"
                    "octolab_mvp_default\n"
                    "my_other_network\n"
                ),
                stderr=""
            )

        with patch("subprocess.run", side_effect=mock_run):
            networks = list_all_octolab_networks()

        # Should only include the strict lab pattern networks
        assert len(networks) == 2
        assert "octolab_12345678-1234-1234-1234-123456789abc_lab_net" in networks
        assert "octolab_12345678-1234-1234-1234-123456789abc_egress_net" in networks
        assert "octolab_mvp_default" not in networks
        assert "bridge" not in networks


class TestAdminCleanupOctolabResources:
    """Tests for admin_cleanup_octolab_resources function."""

    def test_refuses_if_running_containers_exist(self):
        """Test that cleanup refuses if any OctoLab containers are running."""
        from app.services.docker_net import admin_cleanup_octolab_resources

        call_log = []

        def mock_run(*args, **kwargs):
            call_log.append(args[0])
            cmd_str = " ".join(args[0])

            # docker ps returns running octolab container
            if "docker ps" in cmd_str and "-a" not in cmd_str:
                return subprocess.CompletedProcess(
                    args[0], 0,
                    stdout="octolab_abc-octobox-1\n",
                    stderr=""
                )
            return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            result = admin_cleanup_octolab_resources()

        # Should have refused
        assert result.running_octolab_containers == 1
        assert "REFUSED" in result.errors[0]
        assert result.networks_removed == 0

        # Should NOT have attempted network rm
        rm_calls = [c for c in call_log if "network rm" in " ".join(c)]
        assert len(rm_calls) == 0

    def test_removes_only_lab_networks(self):
        """Test that only strict lab pattern networks are removed."""
        from app.services.docker_net import admin_cleanup_octolab_resources

        rm_calls = []

        def mock_run(*args, **kwargs):
            cmd = args[0]
            cmd_str = " ".join(cmd)

            # docker ps - no running containers
            if "docker ps" in cmd_str and "-a" not in cmd_str:
                return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

            # docker ps -a - no stopped containers
            if "docker ps" in cmd_str and "-a" in cmd_str:
                return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

            # network ls
            if "network ls" in cmd_str:
                return subprocess.CompletedProcess(
                    args[0], 0,
                    stdout=(
                        "octolab_12345678-1234-1234-1234-123456789abc_lab_net\n"
                        "octolab_12345678-1234-1234-1234-123456789abc_egress_net\n"
                    ),
                    stderr=""
                )

            # network inspect - 0 containers
            if "network inspect" in cmd_str:
                return subprocess.CompletedProcess(args[0], 0, stdout="0", stderr="")

            # network rm
            if "network rm" in cmd_str:
                rm_calls.append(cmd)
                return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

            return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            result = admin_cleanup_octolab_resources(remove_stopped_containers=False)

        # Should have removed 2 networks
        assert result.networks_found == 2
        assert result.networks_removed == 2
        assert len(rm_calls) == 2

    def test_does_not_remove_network_with_containers(self):
        """Test that networks with attached containers are skipped."""
        from app.services.docker_net import admin_cleanup_octolab_resources

        rm_calls = []

        def mock_run(*args, **kwargs):
            cmd = args[0]
            cmd_str = " ".join(cmd)

            # docker ps - no running containers
            if "docker ps" in cmd_str:
                return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

            # network ls
            if "network ls" in cmd_str:
                return subprocess.CompletedProcess(
                    args[0], 0,
                    stdout="octolab_12345678-1234-1234-1234-123456789abc_lab_net\n",
                    stderr=""
                )

            # network inspect - has 2 containers
            if "network inspect" in cmd_str:
                return subprocess.CompletedProcess(args[0], 0, stdout="2", stderr="")

            # network rm
            if "network rm" in cmd_str:
                rm_calls.append(cmd)
                return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

            return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            result = admin_cleanup_octolab_resources(remove_stopped_containers=False)

        # Should have skipped the network
        assert result.networks_found == 1
        assert result.networks_skipped_in_use == 1
        assert result.networks_removed == 0
        assert len(rm_calls) == 0

    def test_never_calls_prune(self):
        """Test that cleanup never calls docker network/system prune."""
        from app.services.docker_net import admin_cleanup_octolab_resources

        call_log = []

        def mock_run(*args, **kwargs):
            call_log.append(args[0])
            cmd_str = " ".join(args[0])

            # docker ps - no running containers
            if "docker ps" in cmd_str:
                return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

            # network ls
            if "network ls" in cmd_str:
                return subprocess.CompletedProcess(
                    args[0], 0,
                    stdout="octolab_12345678-1234-1234-1234-123456789abc_lab_net\n",
                    stderr=""
                )

            # network inspect - 0 containers
            if "network inspect" in cmd_str:
                return subprocess.CompletedProcess(args[0], 0, stdout="0", stderr="")

            # network rm
            if "network rm" in cmd_str:
                return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

            return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            admin_cleanup_octolab_resources()

        # Verify no prune commands
        for cmd in call_log:
            cmd_str = " ".join(cmd).lower()
            assert "network prune" not in cmd_str, f"Unexpected network prune: {cmd}"
            assert "system prune" not in cmd_str, f"Unexpected system prune: {cmd}"


class TestRemoveContainer:
    """Tests for remove_container function."""

    def test_refuses_non_octolab_containers(self):
        """Test that non-octolab containers are refused."""
        from app.services.docker_net import remove_container

        rm_calls = []

        def mock_run(*args, **kwargs):
            rm_calls.append(args[0])
            return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            result = remove_container("nginx")

        assert result is False
        assert len(rm_calls) == 0  # Should not have called docker rm

    def test_removes_octolab_container(self):
        """Test that octolab_ containers are removed."""
        from app.services.docker_net import remove_container

        def mock_run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            result = remove_container("octolab_abc-octobox-1")

        assert result is True


class TestIsOctolabLabNetwork:
    """Tests for is_octolab_lab_network function."""

    def test_matches_lab_networks(self):
        """Test that strict lab pattern is matched."""
        from app.services.docker_net import is_octolab_lab_network

        # Should match
        assert is_octolab_lab_network("octolab_12345678-1234-1234-1234-123456789abc_lab_net") is True
        assert is_octolab_lab_network("octolab_12345678-1234-1234-1234-123456789abc_egress_net") is True
        assert is_octolab_lab_network("octolab_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_lab_net") is True

    def test_rejects_infrastructure_networks(self):
        """Test that infrastructure networks are rejected."""
        from app.services.docker_net import is_octolab_lab_network

        # Should NOT match
        assert is_octolab_lab_network("octolab_mvp_default") is False
        assert is_octolab_lab_network("bridge") is False
        assert is_octolab_lab_network("host") is False
        assert is_octolab_lab_network("octolab_something_else") is False
