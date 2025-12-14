"""Tests for network cleanup retry logic.

Tests the remove_compose_project_networks function which handles the
Docker endpoint cleanup race condition (200-800ms lag after container removal).

Uses mocked subprocess calls to verify:
- Retry on in-use errors succeeds after GC completes
- Network name validation (deny-by-default)
- Label-based network discovery
- Accurate reporting of removed vs skipped networks
"""

import subprocess
from unittest.mock import MagicMock, patch, call

import pytest

from app.services.docker_net import (
    remove_compose_project_networks,
    safe_is_lab_network,
    compose_project_name,
    NetworkRemovalResult,
    NetworkRemoveResult,
    VALID_NETWORK_SUFFIXES,
)


# =============================================================================
# Helper: Subprocess mock factory
# =============================================================================


class SubprocessMocker:
    """Helper to create canned subprocess.run responses."""

    def __init__(self):
        self.call_history = []
        self.responses = {}

    def add_response(self, cmd_pattern: str, returncode: int, stdout: str = "", stderr: str = ""):
        """Add a response for commands matching pattern."""
        if cmd_pattern not in self.responses:
            self.responses[cmd_pattern] = []
        self.responses[cmd_pattern].append({
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
        })

    def _match_pattern(self, cmd: list[str], pattern: str) -> bool:
        """Check if command matches pattern (simple substring match)."""
        cmd_str = " ".join(cmd)
        return pattern in cmd_str

    def mock_run(self, cmd, **kwargs):
        """Mock subprocess.run that returns canned responses."""
        self.call_history.append(cmd)

        cmd_str = " ".join(cmd)

        # Find matching response
        for pattern, responses in self.responses.items():
            if self._match_pattern(cmd, pattern):
                if responses:
                    resp = responses.pop(0)
                    return MagicMock(
                        returncode=resp["returncode"],
                        stdout=resp["stdout"],
                        stderr=resp["stderr"],
                    )

        # Default: success
        return MagicMock(returncode=0, stdout="", stderr="")


# =============================================================================
# Tests: compose_project_name helper
# =============================================================================


class TestComposeProjectName:
    """Tests for compose_project_name helper."""

    def test_generates_correct_format(self):
        """Should generate octolab_<uuid> format."""
        lab_id = "12345678-1234-1234-1234-123456789abc"
        assert compose_project_name(lab_id) == "octolab_12345678-1234-1234-1234-123456789abc"

    def test_lowercases_uuid(self):
        """Should lowercase the UUID."""
        lab_id = "12345678-1234-1234-1234-123456789ABC"
        result = compose_project_name(lab_id)
        assert result == "octolab_12345678-1234-1234-1234-123456789abc"
        assert "ABC" not in result


# =============================================================================
# Tests: safe_is_lab_network validation
# =============================================================================


class TestSafeIsLabNetwork:
    """Tests for safe_is_lab_network validation."""

    def test_allows_lab_net_suffix(self):
        """Should allow network with _lab_net suffix."""
        project = "octolab_12345678-1234-1234-1234-123456789abc"
        network = f"{project}_lab_net"
        assert safe_is_lab_network(project, network) is True

    def test_allows_egress_net_suffix(self):
        """Should allow network with _egress_net suffix."""
        project = "octolab_12345678-1234-1234-1234-123456789abc"
        network = f"{project}_egress_net"
        assert safe_is_lab_network(project, network) is True

    def test_rejects_unknown_suffix(self):
        """Should reject network with unknown suffix."""
        project = "octolab_12345678-1234-1234-1234-123456789abc"
        network = f"{project}_default"
        assert safe_is_lab_network(project, network) is False

    def test_rejects_wrong_project_prefix(self):
        """Should reject network not starting with project name."""
        project = "octolab_12345678-1234-1234-1234-123456789abc"
        network = "octolab_other-uuid_lab_net"
        assert safe_is_lab_network(project, network) is False

    def test_rejects_infrastructure_network(self):
        """Should reject infrastructure networks."""
        project = "octolab_12345678-1234-1234-1234-123456789abc"
        # This doesn't start with the project name
        network = "octolab_mvp_default"
        assert safe_is_lab_network(project, network) is False

    def test_valid_suffixes_immutable(self):
        """VALID_NETWORK_SUFFIXES should be immutable."""
        assert isinstance(VALID_NETWORK_SUFFIXES, frozenset)


# =============================================================================
# Tests: remove_compose_project_networks retry logic
# =============================================================================


class TestRemoveComposeProjectNetworksRetry:
    """Tests for retry logic in remove_compose_project_networks."""

    @patch("app.services.docker_net.subprocess.run")
    def test_rm_fails_once_then_succeeds(self, mock_run):
        """Network rm fails once (GC race), succeeds on retry."""
        project = "octolab_12345678-1234-1234-1234-123456789abc"
        lab_id = "12345678-1234-1234-1234-123456789abc"
        network = f"{project}_lab_net"

        call_count = {"network_rm": 0}

        def mock_run_side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)

            # network ls (list by label)
            if "network ls" in cmd_str and "label=" in cmd_str:
                return MagicMock(returncode=0, stdout=network + "\n", stderr="")

            # network rm
            if "network rm" in cmd_str:
                call_count["network_rm"] += 1
                if call_count["network_rm"] == 1:
                    # First attempt: fails with in-use
                    return MagicMock(returncode=1, stdout="", stderr="network has active endpoints")
                else:
                    # Second attempt: succeeds
                    return MagicMock(returncode=0, stdout="", stderr="")

            # network inspect (returns empty)
            if "network inspect" in cmd_str:
                return MagicMock(returncode=0, stdout="{}", stderr="")

            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = mock_run_side_effect

        result = remove_compose_project_networks(
            project,
            lab_id,
            deadline_secs=5.0,
            backoff_base_ms=10,  # Short for test
            max_retries=3,
        )

        assert result.networks_found == 1
        assert result.networks_removed == 1
        assert result.networks_remaining == 0
        assert len(result.networks_skipped) == 0

    @patch("app.services.docker_net.subprocess.run")
    def test_rm_fails_inspect_shows_containers_then_empty_succeeds(self, mock_run):
        """Network rm fails, inspect shows containers, later empty, rm succeeds."""
        project = "octolab_12345678-1234-1234-1234-123456789abc"
        lab_id = "12345678-1234-1234-1234-123456789abc"
        network = f"{project}_lab_net"

        call_count = {"network_rm": 0, "network_inspect": 0}

        def mock_run_side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)

            # network ls
            if "network ls" in cmd_str and "label=" in cmd_str:
                return MagicMock(returncode=0, stdout=network + "\n", stderr="")

            # network rm
            if "network rm" in cmd_str:
                call_count["network_rm"] += 1
                if call_count["network_rm"] <= 2:
                    return MagicMock(returncode=1, stdout="", stderr="network has active endpoints")
                else:
                    return MagicMock(returncode=0, stdout="", stderr="")

            # network inspect
            if "network inspect" in cmd_str and "Containers" in cmd_str:
                call_count["network_inspect"] += 1
                if call_count["network_inspect"] == 1:
                    # First inspect: has containers (GC not done yet)
                    return MagicMock(
                        returncode=0,
                        stdout='{"abc123": {"Name": "some-container"}}',
                        stderr="",
                    )
                else:
                    # Later inspects: empty
                    return MagicMock(returncode=0, stdout="{}", stderr="")

            # docker ps for container name lookup
            if "docker ps" in cmd_str and "filter" in cmd_str:
                return MagicMock(returncode=0, stdout="some-container", stderr="")

            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = mock_run_side_effect

        result = remove_compose_project_networks(
            project,
            lab_id,
            deadline_secs=5.0,
            backoff_base_ms=10,
            max_retries=5,
        )

        assert result.networks_found == 1
        assert result.networks_removed == 1
        assert result.networks_remaining == 0

    @patch("app.services.docker_net.subprocess.run")
    def test_network_name_not_allowed_not_removed(self, mock_run):
        """Network with invalid name should not be removed."""
        project = "octolab_12345678-1234-1234-1234-123456789abc"
        lab_id = "12345678-1234-1234-1234-123456789abc"
        # Invalid suffix
        bad_network = f"{project}_default"

        def mock_run_side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)

            # network ls returns invalid network
            if "network ls" in cmd_str and "label=" in cmd_str:
                return MagicMock(returncode=0, stdout=bad_network + "\n", stderr="")

            # Should never reach network rm for invalid network
            if "network rm" in cmd_str:
                raise AssertionError("Should not attempt to remove invalid network")

            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = mock_run_side_effect

        result = remove_compose_project_networks(project, lab_id, deadline_secs=2.0)

        assert result.networks_found == 1
        assert result.networks_removed == 0
        assert result.networks_remaining == 1
        assert len(result.networks_skipped) == 1
        assert result.networks_skipped[0].reason == "name_not_allowed"

    @patch("app.services.docker_net.subprocess.run")
    def test_only_label_filtered_networks_attempted(self, mock_run):
        """Only networks from label filter should be attempted for removal."""
        project = "octolab_12345678-1234-1234-1234-123456789abc"
        lab_id = "12345678-1234-1234-1234-123456789abc"
        network = f"{project}_lab_net"

        network_rm_calls = []

        def mock_run_side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)

            # network ls must have label filter
            if "network ls" in cmd_str:
                if f"label=com.docker.compose.project={project}" in cmd_str:
                    return MagicMock(returncode=0, stdout=network + "\n", stderr="")
                else:
                    # Without label filter, return nothing
                    return MagicMock(returncode=0, stdout="", stderr="")

            # Track network rm calls
            if "network rm" in cmd_str:
                network_rm_calls.append(cmd)
                return MagicMock(returncode=0, stdout="", stderr="")

            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = mock_run_side_effect

        result = remove_compose_project_networks(project, lab_id, deadline_secs=2.0)

        # Only one network rm call, for the label-filtered network
        assert len(network_rm_calls) == 1
        assert network in " ".join(network_rm_calls[0])

    @patch("app.services.docker_net.subprocess.run")
    def test_no_networks_found_returns_empty_result(self, mock_run):
        """No networks found should return empty result."""
        project = "octolab_12345678-1234-1234-1234-123456789abc"
        lab_id = "12345678-1234-1234-1234-123456789abc"

        def mock_run_side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)

            if "network ls" in cmd_str:
                return MagicMock(returncode=0, stdout="", stderr="")

            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = mock_run_side_effect

        result = remove_compose_project_networks(project, lab_id, deadline_secs=2.0)

        assert result.networks_found == 0
        assert result.networks_removed == 0
        assert result.networks_remaining == 0

    @patch("app.services.docker_net.subprocess.run")
    def test_allowlisted_containers_force_disconnected(self, mock_run):
        """Allowlisted containers should be force-disconnected and retry succeeds."""
        project = "octolab_12345678-1234-1234-1234-123456789abc"
        lab_id = "12345678-1234-1234-1234-123456789abc"
        network = f"{project}_lab_net"
        allowlisted_container = "octolab-guacd"

        disconnect_calls = []
        rm_calls = {"count": 0}

        def mock_run_side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)

            if "network ls" in cmd_str and "label=" in cmd_str:
                return MagicMock(returncode=0, stdout=network + "\n", stderr="")

            if "network rm" in cmd_str:
                rm_calls["count"] += 1
                if rm_calls["count"] == 1:
                    return MagicMock(returncode=1, stdout="", stderr="has active endpoints")
                return MagicMock(returncode=0, stdout="", stderr="")

            if "network inspect" in cmd_str and "Containers" in cmd_str:
                if rm_calls["count"] == 1:
                    # First time: has allowlisted container
                    return MagicMock(
                        returncode=0,
                        stdout=f'{{"abc": {{"Name": "{allowlisted_container}"}}}}',
                        stderr="",
                    )
                return MagicMock(returncode=0, stdout="{}", stderr="")

            if "network disconnect" in cmd_str:
                disconnect_calls.append(cmd)
                return MagicMock(returncode=0, stdout="", stderr="")

            if "docker ps" in cmd_str and "filter" in cmd_str:
                return MagicMock(returncode=0, stdout=allowlisted_container, stderr="")

            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = mock_run_side_effect

        result = remove_compose_project_networks(
            project,
            lab_id,
            deadline_secs=5.0,
            backoff_base_ms=10,
            allowlist=[allowlisted_container],
        )

        # Should have disconnected the container
        assert len(disconnect_calls) >= 1
        assert result.networks_removed == 1

    @patch("app.services.docker_net.subprocess.run")
    def test_unknown_containers_logged_as_skipped(self, mock_run):
        """Unknown containers should cause skip with warning (not removed)."""
        project = "octolab_12345678-1234-1234-1234-123456789abc"
        lab_id = "12345678-1234-1234-1234-123456789abc"
        network = f"{project}_lab_net"
        unknown_container = "some-random-container"

        def mock_run_side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)

            if "network ls" in cmd_str and "label=" in cmd_str:
                return MagicMock(returncode=0, stdout=network + "\n", stderr="")

            if "network rm" in cmd_str:
                return MagicMock(returncode=1, stdout="", stderr="has active endpoints")

            if "network inspect" in cmd_str and "Containers" in cmd_str:
                return MagicMock(
                    returncode=0,
                    stdout=f'{{"abc": {{"Name": "{unknown_container}"}}}}',
                    stderr="",
                )

            if "docker ps" in cmd_str and "filter" in cmd_str:
                return MagicMock(returncode=0, stdout=unknown_container, stderr="")

            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = mock_run_side_effect

        result = remove_compose_project_networks(
            project,
            lab_id,
            deadline_secs=2.0,
            backoff_base_ms=10,
            max_retries=2,
            allowlist=[],  # Empty allowlist
        )

        assert result.networks_found == 1
        assert result.networks_removed == 0
        assert result.networks_remaining == 1
        assert len(result.networks_skipped) == 1
        assert result.networks_skipped[0].reason == "in_use"
        assert unknown_container in result.networks_skipped[0].containers


# =============================================================================
# Tests: Accurate reporting
# =============================================================================


class TestNetworkRemovalResultAccuracy:
    """Tests for accurate reporting in NetworkRemovalResult."""

    def test_networks_remaining_property(self):
        """networks_remaining should equal found - removed."""
        result = NetworkRemovalResult()
        result.networks_found = 5
        result.networks_removed = 3
        assert result.networks_remaining == 2

    def test_empty_result_has_zero_remaining(self):
        """Empty result should have zero remaining."""
        result = NetworkRemovalResult()
        assert result.networks_remaining == 0

    def test_all_removed_has_zero_remaining(self):
        """All removed should have zero remaining."""
        result = NetworkRemovalResult()
        result.networks_found = 3
        result.networks_removed = 3
        assert result.networks_remaining == 0


# =============================================================================
# Tests: Deadline handling
# =============================================================================


class TestDeadlineHandling:
    """Tests for deadline handling in network cleanup."""

    @patch("app.services.docker_net.subprocess.run")
    def test_exceeds_deadline_stops_retrying(self, mock_run):
        """Should stop retrying when deadline is very short."""
        project = "octolab_12345678-1234-1234-1234-123456789abc"
        lab_id = "12345678-1234-1234-1234-123456789abc"
        network = f"{project}_lab_net"

        rm_call_count = {"count": 0}

        def mock_run_side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)

            if "network ls" in cmd_str:
                return MagicMock(returncode=0, stdout=network + "\n", stderr="")

            if "network rm" in cmd_str:
                rm_call_count["count"] += 1
                # Always fail to trigger retry loop
                return MagicMock(returncode=1, stdout="", stderr="has active endpoints")

            if "network inspect" in cmd_str:
                return MagicMock(returncode=0, stdout="{}", stderr="")

            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = mock_run_side_effect

        result = remove_compose_project_networks(
            project,
            lab_id,
            deadline_secs=0.001,  # Very short deadline
            backoff_base_ms=100,
            max_retries=10,  # High retries but deadline limits
        )

        # Should have timed out and reported network as skipped
        assert result.networks_found == 1
        assert result.networks_removed == 0
        assert result.networks_remaining == 1
        # Should have attempted removal at least once
        assert rm_call_count["count"] >= 1
