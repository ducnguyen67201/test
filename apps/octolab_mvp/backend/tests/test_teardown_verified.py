"""Tests for verified teardown in compose_runtime.

SECURITY tests included:
- Only operates on octolab_<uuid> projects
- Uses label-based filtering
- Never runs broad prune commands
"""

import subprocess
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.runtime.compose_runtime import (
    _is_lab_project,
    _list_project_containers,
    _rm_containers_force,
    _list_project_networks,
    _rm_networks,
    TeardownResult,
    LAB_PROJECT_RE,
)


# =============================================================================
# _is_lab_project tests
# =============================================================================


class TestIsLabProject:
    """Tests for _is_lab_project validation function."""

    def test_valid_project_name_with_dashes(self):
        """Valid project name with dashed UUID."""
        project = "octolab_12345678-1234-1234-1234-123456789abc"
        assert _is_lab_project(project) is True

    def test_valid_project_name_without_dashes(self):
        """Valid project name with non-dashed UUID."""
        project = "octolab_12345678123412341234123456789abc"
        assert _is_lab_project(project) is True

    def test_valid_project_name_uppercase(self):
        """Valid project name with uppercase letters."""
        project = "octolab_12345678-1234-1234-1234-123456789ABC"
        assert _is_lab_project(project) is True

    def test_invalid_project_name_wrong_prefix(self):
        """Invalid project name with wrong prefix."""
        project = "other_12345678-1234-1234-1234-123456789abc"
        assert _is_lab_project(project) is False

    def test_invalid_project_name_short_uuid(self):
        """Invalid project name with short UUID."""
        project = "octolab_12345678"
        assert _is_lab_project(project) is False

    def test_invalid_project_name_empty(self):
        """Empty project name is invalid."""
        assert _is_lab_project("") is False

    def test_invalid_project_name_malicious(self):
        """Malicious project name is rejected."""
        project = "octolab_$(rm -rf /)"
        assert _is_lab_project(project) is False


# =============================================================================
# _list_project_containers tests (mocked subprocess)
# =============================================================================


class TestListProjectContainers:
    """Tests for _list_project_containers function."""

    def test_returns_empty_list_on_no_containers(self):
        """Returns empty list when no containers match."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            result = _list_project_containers("octolab_abc123")

        assert result == []

    def test_parses_container_output(self):
        """Correctly parses docker ps output."""
        output = "abc123def456\tcontainer-name\tUp 5 minutes\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=output)
            result = _list_project_containers("octolab_abc123")

        assert len(result) == 1
        assert result[0]["id"] == "abc123def456"
        assert result[0]["name"] == "container-name"
        assert "Up" in result[0]["status"]

    def test_handles_multiple_containers(self):
        """Handles multiple containers in output."""
        output = "id1\tname1\tUp\nid2\tname2\tExited\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=output)
            result = _list_project_containers("octolab_abc123")

        assert len(result) == 2

    def test_handles_timeout(self):
        """Returns empty list on timeout."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=[], timeout=10)
            result = _list_project_containers("octolab_abc123")

        assert result == []

    def test_uses_label_filter(self):
        """Verifies label filter is used in command."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            _list_project_containers("octolab_abc123")

        call_args = mock_run.call_args[0][0]
        assert "--filter" in call_args
        assert "label=com.docker.compose.project=octolab_abc123" in call_args


# =============================================================================
# _rm_containers_force tests
# =============================================================================


class TestRmContainersForce:
    """Tests for _rm_containers_force function."""

    def test_returns_zero_for_empty_list(self):
        """Returns (0, []) for empty container list."""
        removed, errors = _rm_containers_force([])
        assert removed == 0
        assert errors == []

    def test_removes_containers_successfully(self):
        """Successfully removes containers."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            removed, errors = _rm_containers_force(["id1", "id2", "id3"])

        assert removed == 3
        assert errors == []

    def test_handles_partial_failure(self):
        """Handles partial failure when some containers fail to remove."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="Error: container not found"
            )
            removed, errors = _rm_containers_force(["id1", "id2"])

        assert len(errors) > 0

    def test_uses_force_flag(self):
        """Verifies -f flag is used."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _rm_containers_force(["id1"])

        call_args = mock_run.call_args[0][0]
        assert "docker" in call_args
        assert "rm" in call_args
        assert "-f" in call_args


# =============================================================================
# _list_project_networks tests
# =============================================================================


class TestListProjectNetworks:
    """Tests for _list_project_networks function."""

    def test_returns_empty_list_on_no_networks(self):
        """Returns empty list when no networks match."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            result = _list_project_networks("octolab_abc123")

        assert result == []

    def test_parses_network_output(self):
        """Correctly parses docker network ls output."""
        output = "octolab_abc123_lab_net\noctolab_abc123_egress_net\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=output)
            result = _list_project_networks("octolab_abc123")

        assert len(result) == 2
        assert "octolab_abc123_lab_net" in result
        assert "octolab_abc123_egress_net" in result


# =============================================================================
# _rm_networks tests
# =============================================================================


class TestRmNetworks:
    """Tests for _rm_networks function."""

    def test_returns_zero_for_empty_list(self):
        """Returns (0, 0, []) for empty network list."""
        removed, remaining, errors = _rm_networks([])
        assert removed == 0
        assert remaining == 0
        assert errors == []

    def test_removes_networks_successfully(self):
        """Successfully removes networks."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            removed, remaining, errors = _rm_networks(["octolab_abc_net"])

        assert removed == 1
        assert remaining == 0
        assert errors == []

    def test_handles_already_removed_network(self):
        """Treats 'not found' as success."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="network not found"
            )
            removed, remaining, errors = _rm_networks(["octolab_abc_net"])

        assert removed == 1  # Counts as removed
        assert remaining == 0

    def test_handles_network_in_use(self):
        """Records error for network in use."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="has active endpoints"
            )
            removed, remaining, errors = _rm_networks(["octolab_abc_net"])

        assert removed == 0
        assert remaining == 1
        assert any("active endpoints" in e for e in errors)

    def test_skips_non_octolab_networks(self):
        """Skips networks not starting with octolab_."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            removed, remaining, errors = _rm_networks(["bridge", "host"])

        # Should not call subprocess.run for non-octolab networks
        mock_run.assert_not_called()


# =============================================================================
# TeardownResult tests
# =============================================================================


class TestTeardownResult:
    """Tests for TeardownResult class."""

    def test_success_when_no_remaining(self):
        """Success is True when no containers or networks remain."""
        result = TeardownResult("octolab_abc")
        result.containers_remaining = 0
        result.networks_remaining = 0

        assert result.success is True

    def test_not_success_when_containers_remain(self):
        """Success is False when containers remain."""
        result = TeardownResult("octolab_abc")
        result.containers_remaining = 1
        result.networks_remaining = 0

        assert result.success is False

    def test_not_success_when_networks_remain(self):
        """Success is False when networks remain."""
        result = TeardownResult("octolab_abc")
        result.containers_remaining = 0
        result.networks_remaining = 1

        assert result.success is False

    def test_to_dict_truncates_errors(self):
        """to_dict truncates errors list."""
        result = TeardownResult("octolab_abc")
        result.errors = ["err1", "err2", "err3", "err4", "err5", "err6", "err7"]

        d = result.to_dict()
        assert len(d["errors"]) == 5  # Truncated to 5


# =============================================================================
# Integration test for destroy_lab (mocked)
# =============================================================================


class TestDestroyLabVerified:
    """Integration tests for verified destroy_lab."""

    @pytest.mark.asyncio
    async def test_destroy_lab_full_sequence(self):
        """Test full teardown sequence with mocked subprocess."""
        from app.runtime.compose_runtime import ComposeLabRuntime
        from pathlib import Path

        # Create mock lab
        lab = MagicMock()
        lab.id = uuid4()

        # Create runtime with mocked compose path
        with patch.object(Path, "exists", return_value=True):
            runtime = ComposeLabRuntime(Path("/fake/docker-compose.yml"))

        # Mock all subprocess calls
        with patch("app.runtime.compose_runtime.ComposeLabRuntime._run_compose") as mock_compose:
            mock_compose.return_value = ("", "")

            with patch("app.runtime.compose_runtime._list_project_containers") as mock_list_containers:
                # First call: 2 containers remaining after compose down
                # Second call: 0 containers after force remove
                mock_list_containers.side_effect = [
                    [{"id": "c1", "name": "n1", "status": "Up"}, {"id": "c2", "name": "n2", "status": "Up"}],
                    [],  # After force remove
                ]

                with patch("app.runtime.compose_runtime._rm_containers_force") as mock_rm_containers:
                    mock_rm_containers.return_value = (2, [])

                    with patch("app.runtime.compose_runtime._list_project_networks") as mock_list_networks:
                        # Networks: 2 before, 0 after
                        mock_list_networks.side_effect = [
                            ["octolab_abc_lab_net", "octolab_abc_egress_net"],
                            [],  # After remove
                        ]

                        with patch("app.runtime.compose_runtime._rm_networks") as mock_rm_networks:
                            mock_rm_networks.return_value = (2, 0, [])

                            with patch("app.services.port_allocator.release_novnc_port") as mock_release:
                                mock_release.return_value = True

                                result = await runtime.destroy_lab(lab)

        # Verify result
        assert result.compose_down_ok is True
        assert result.containers_before == 2
        assert result.containers_removed_force == 2
        assert result.containers_remaining == 0
        assert result.networks_before == 2
        assert result.networks_removed == 2
        assert result.networks_remaining == 0
        assert result.success is True
