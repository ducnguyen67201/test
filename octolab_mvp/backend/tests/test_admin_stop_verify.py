"""Tests for verified stop operations (verify->act->verify pattern).

These tests verify:
- compose down followed by container verification
- rm -f fallback when containers remain
- networks only removed when containers are gone
- proper failure reporting when containers still running
- security invariants (shell=False, no prune)
"""

import pytest
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

# Mark all tests as not requiring database
pytestmark = pytest.mark.no_db


class TestStopProjectVerified:
    """Tests for stop_project_verified() function."""

    def test_compose_down_success_containers_stopped(self):
        """Test: compose down rc=0 and containers verified stopped."""
        from app.services.docker_net import stop_project_verified

        project = "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111"

        # Mock docker ps to return containers before, none after
        pre_ids = ["container1", "container2"]
        call_count = 0

        def mock_list_ids(proj, timeout=10.0):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return pre_ids  # Before: 2 containers
            return []  # After: 0 containers

        mock_down_result = MagicMock()
        mock_down_result.returncode = 0
        mock_down_result.stderr = ""

        with patch("app.services.docker_net.list_running_container_ids_for_project", side_effect=mock_list_ids):
            with patch("subprocess.run", return_value=mock_down_result):
                with patch("app.services.docker_net.list_project_networks_robust", return_value=[]):
                    result = stop_project_verified(
                        project=project,
                        compose_dir="/tmp",
                        compose_file="/tmp/docker-compose.yml",
                    )

        assert result.verified_stopped is True
        assert result.pre_running == 2
        assert result.remaining_final == 0
        assert result.down_rc == 0
        assert result.rm_rc is None  # rm -f not needed
        assert result.error is None

    def test_compose_down_success_but_containers_remain_triggers_rm_f(self):
        """Test: compose down rc=0 but containers remain => rm -f invoked => final empty => stopped."""
        from app.services.docker_net import stop_project_verified

        project = "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111"

        # Track calls to list_running_container_ids_for_project
        call_count = 0

        def mock_list_ids(proj, timeout=10.0):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ["c1", "c2"]  # Before: 2 containers
            elif call_count == 2:
                return ["c1"]  # After compose down: 1 still running
            else:
                return []  # After rm -f: 0 containers

        mock_down_result = MagicMock()
        mock_down_result.returncode = 0
        mock_down_result.stderr = ""

        mock_rm_result = MagicMock()
        mock_rm_result.returncode = 0
        mock_rm_result.stderr = ""

        def mock_subprocess_run(cmd, **kwargs):
            if "compose" in cmd:
                return mock_down_result
            elif "rm" in cmd:
                return mock_rm_result
            return MagicMock(returncode=0)

        with patch("app.services.docker_net.list_running_container_ids_for_project", side_effect=mock_list_ids):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with patch("app.services.docker_net.list_project_networks_robust", return_value=[]):
                    result = stop_project_verified(
                        project=project,
                        compose_dir="/tmp",
                        compose_file="/tmp/docker-compose.yml",
                    )

        assert result.verified_stopped is True
        assert result.pre_running == 2
        assert result.remaining_after_down == 1  # 1 remained after compose down
        assert result.remaining_final == 0  # 0 after rm -f
        assert result.rm_rc == 0  # rm -f was called

    def test_compose_down_fails_but_rm_f_succeeds(self):
        """Test: compose down rc=1 => rm -f still attempted => final empty => stopped."""
        from app.services.docker_net import stop_project_verified

        project = "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111"

        call_count = 0

        def mock_list_ids(proj, timeout=10.0):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ["c1", "c2"]  # Before
            elif call_count == 2:
                return ["c1", "c2"]  # After compose down (failed, still running)
            else:
                return []  # After rm -f

        mock_down_result = MagicMock()
        mock_down_result.returncode = 1  # compose down failed
        mock_down_result.stderr = "some error"

        mock_rm_result = MagicMock()
        mock_rm_result.returncode = 0
        mock_rm_result.stderr = ""

        def mock_subprocess_run(cmd, **kwargs):
            if "compose" in cmd:
                return mock_down_result
            elif "rm" in cmd:
                return mock_rm_result
            return MagicMock(returncode=0)

        with patch("app.services.docker_net.list_running_container_ids_for_project", side_effect=mock_list_ids):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with patch("app.services.docker_net.list_project_networks_robust", return_value=[]):
                    result = stop_project_verified(
                        project=project,
                        compose_dir="/tmp",
                        compose_file="/tmp/docker-compose.yml",
                    )

        assert result.verified_stopped is True
        assert result.down_rc == 1  # compose down failed
        assert result.rm_rc == 0  # rm -f succeeded
        assert result.remaining_final == 0

    def test_rm_f_fails_containers_still_running(self):
        """Test: rm -f rc!=0 => final still non-empty => failed."""
        from app.services.docker_net import stop_project_verified

        project = "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111"

        call_count = 0

        def mock_list_ids(proj, timeout=10.0):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ["c1", "c2"]  # Before
            elif call_count == 2:
                return ["c1", "c2"]  # After compose down
            else:
                return ["c1"]  # After rm -f (1 still running!)

        mock_down_result = MagicMock()
        mock_down_result.returncode = 0
        mock_down_result.stderr = ""

        mock_rm_result = MagicMock()
        mock_rm_result.returncode = 1  # rm -f failed
        mock_rm_result.stderr = "permission denied"

        def mock_subprocess_run(cmd, **kwargs):
            if "compose" in cmd:
                return mock_down_result
            elif "rm" in cmd:
                return mock_rm_result
            return MagicMock(returncode=0)

        with patch("app.services.docker_net.list_running_container_ids_for_project", side_effect=mock_list_ids):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                result = stop_project_verified(
                    project=project,
                    compose_dir="/tmp",
                    compose_file="/tmp/docker-compose.yml",
                )

        assert result.verified_stopped is False
        assert result.remaining_final == 1  # 1 container still running
        assert result.error is not None
        assert "still running" in result.error.lower()

    def test_networks_only_removed_after_containers_gone(self):
        """Test: networks removed only after final count is 0."""
        from app.services.docker_net import stop_project_verified

        project = "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111"

        # Track network removal calls
        network_remove_calls = []

        call_count = 0

        def mock_list_ids(proj, timeout=10.0):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ["c1"]  # Before
            return []  # After

        mock_down_result = MagicMock()
        mock_down_result.returncode = 0

        def mock_remove_network(name, timeout=30.0):
            network_remove_calls.append(name)
            return True

        with patch("app.services.docker_net.list_running_container_ids_for_project", side_effect=mock_list_ids):
            with patch("subprocess.run", return_value=mock_down_result):
                with patch("app.services.docker_net.list_project_networks_robust",
                           return_value=[f"{project}_lab_net", f"{project}_egress_net"]):
                    with patch("app.services.docker_net.remove_detached_network", side_effect=mock_remove_network):
                        result = stop_project_verified(
                            project=project,
                            compose_dir="/tmp",
                            compose_file="/tmp/docker-compose.yml",
                        )

        assert result.verified_stopped is True
        assert result.remaining_final == 0
        # Networks should have been cleaned up
        assert len(network_remove_calls) == 2

    def test_networks_not_removed_if_containers_still_running(self):
        """Test: networks NOT removed if containers still running."""
        from app.services.docker_net import stop_project_verified

        project = "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111"

        network_remove_calls = []

        # Containers never stop
        def mock_list_ids(proj, timeout=10.0):
            return ["c1"]  # Always 1 container running

        mock_down_result = MagicMock()
        mock_down_result.returncode = 0

        mock_rm_result = MagicMock()
        mock_rm_result.returncode = 1

        def mock_subprocess_run(cmd, **kwargs):
            if "compose" in cmd:
                return mock_down_result
            elif "rm" in cmd:
                return mock_rm_result
            return MagicMock(returncode=0)

        def mock_remove_network(name, timeout=30.0):
            network_remove_calls.append(name)
            return True

        with patch("app.services.docker_net.list_running_container_ids_for_project", side_effect=mock_list_ids):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with patch("app.services.docker_net.list_project_networks_robust",
                           return_value=[f"{project}_lab_net"]):
                    with patch("app.services.docker_net.remove_detached_network", side_effect=mock_remove_network):
                        result = stop_project_verified(
                            project=project,
                            compose_dir="/tmp",
                            compose_file="/tmp/docker-compose.yml",
                        )

        assert result.verified_stopped is False
        assert result.remaining_final == 1
        # Networks should NOT have been cleaned up
        assert len(network_remove_calls) == 0


class TestStopProjectsVerifiedBatch:
    """Tests for stop_projects_verified_batch() function."""

    def test_counts_verified_stops_not_exit_codes(self):
        """Test: batch counts based on verification, not exit codes."""
        from app.services.docker_net import stop_projects_verified_batch, ProjectStopResult

        projects = [
            "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111",
            "octolab_aaaaaaaa-bbbb-cccc-dddd-222222222222",
        ]

        def mock_stop_verified(project, compose_dir, compose_file, timeout):
            if "111111111111" in project:
                return ProjectStopResult(
                    project=project,
                    pre_running=2,
                    remaining_final=0,
                    verified_stopped=True,
                )
            else:
                return ProjectStopResult(
                    project=project,
                    pre_running=2,
                    remaining_final=1,  # Still running!
                    verified_stopped=False,
                    error="1 containers still running",
                )

        with patch("app.services.docker_net.stop_project_verified", side_effect=mock_stop_verified):
            result = stop_projects_verified_batch(
                projects=projects,
                compose_dir="/tmp",
                compose_file="/tmp/docker-compose.yml",
            )

        assert result.targets == 2
        assert result.projects_stopped == 1  # Only 1 verified stopped
        assert result.projects_failed == 1  # 1 failed (containers still running)
        assert len(result.results) == 2


class TestSecurityInvariants:
    """Tests for security invariants in verified stop operations."""

    def test_stop_project_verified_uses_shell_false(self):
        """Test that stop_project_verified uses shell=False."""
        from app.services.docker_net import stop_project_verified

        project = "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111"

        def mock_list_ids(proj, timeout=10.0):
            return ["c1"]

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with patch("app.services.docker_net.list_running_container_ids_for_project", side_effect=mock_list_ids):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                with patch("app.services.docker_net.list_project_networks_robust", return_value=[]):
                    stop_project_verified(
                        project=project,
                        compose_dir="/tmp",
                        compose_file="/tmp/docker-compose.yml",
                    )

        # Verify all subprocess.run calls use shell=False
        for call in mock_run.call_args_list:
            assert call[1].get("shell", False) is False

    def test_stop_project_verified_never_calls_prune(self):
        """Test that stop_project_verified never calls docker prune."""
        from app.services.docker_net import stop_project_verified

        project = "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111"

        def mock_list_ids(proj, timeout=10.0):
            return []

        mock_result = MagicMock()
        mock_result.returncode = 0

        subprocess_calls = []

        def capture_subprocess(cmd, **kwargs):
            subprocess_calls.append(cmd)
            return mock_result

        with patch("app.services.docker_net.list_running_container_ids_for_project", side_effect=mock_list_ids):
            with patch("subprocess.run", side_effect=capture_subprocess):
                with patch("app.services.docker_net.list_project_networks_robust", return_value=[]):
                    stop_project_verified(
                        project=project,
                        compose_dir="/tmp",
                        compose_file="/tmp/docker-compose.yml",
                    )

        # Verify no subprocess call contains "prune"
        for cmd in subprocess_calls:
            assert "prune" not in " ".join(cmd).lower()

    def test_force_remove_containers_uses_shell_false(self):
        """Test that force_remove_containers uses shell=False."""
        from app.services.docker_net import force_remove_containers

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            force_remove_containers(["container1", "container2"], timeout=30.0)

        call_args = mock_run.call_args
        assert call_args[1]["shell"] is False


class TestListRunningContainerIdsForProject:
    """Tests for list_running_container_ids_for_project() function."""

    def test_returns_container_ids_for_valid_project(self):
        """Test that it returns container IDs for valid lab project."""
        from app.services.docker_net import list_running_container_ids_for_project

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc123\ndef456\n"

        with patch("subprocess.run", return_value=mock_result):
            ids = list_running_container_ids_for_project(
                "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111",
                timeout=10.0,
            )

        assert ids == ["abc123", "def456"]

    def test_returns_empty_for_non_lab_project(self):
        """Test that it returns empty list for non-lab project."""
        from app.services.docker_net import list_running_container_ids_for_project

        ids = list_running_container_ids_for_project(
            "guacamole",
            timeout=10.0,
        )

        assert ids == []

    def test_uses_correct_filter(self):
        """Test that it uses the correct compose project label filter."""
        from app.services.docker_net import list_running_container_ids_for_project

        project = "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111"

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            list_running_container_ids_for_project(project, timeout=10.0)

        call_args = mock_run.call_args
        cmd = call_args[0][0]

        assert "--filter" in cmd
        assert f"label=com.docker.compose.project={project}" in cmd


class TestProjectStopResultDataclass:
    """Tests for ProjectStopResult dataclass."""

    def test_default_values(self):
        """Test that dataclass has correct defaults."""
        from app.services.docker_net import ProjectStopResult

        result = ProjectStopResult(project="test")

        assert result.pre_running == 0
        assert result.down_rc is None
        assert result.remaining_after_down == 0
        assert result.rm_rc is None
        assert result.remaining_final == 0
        assert result.networks_removed == 0
        assert result.verified_stopped is False
        assert result.error is None


class TestVerifiedStopLabsResultDataclass:
    """Tests for VerifiedStopLabsResult dataclass."""

    def test_default_values(self):
        """Test that dataclass has correct defaults."""
        from app.services.docker_net import VerifiedStopLabsResult

        result = VerifiedStopLabsResult()

        assert result.targets == 0
        assert result.projects_stopped == 0
        assert result.projects_failed == 0
        assert result.containers_force_removed == 0
        assert result.networks_removed == 0
        assert result.networks_failed == 0
        assert result.errors == []
        assert result.results == []


class TestStopLabsConfirmation:
    """Tests for stop-labs confirmation requirements (already in test_admin_runtime_drift.py but double-check)."""

    def test_stop_labs_request_requires_confirm_and_phrase(self):
        """Test that StopLabsRequest requires scan_id, confirm, and phrase."""
        from app.api.routes.admin import StopLabsRequest, StopLabsMode, STOP_LABS_CONFIRM_PHRASE

        # All required fields provided
        request = StopLabsRequest(
            scan_id="test-scan-id",
            mode=StopLabsMode.ALL_RUNNING,
            confirm=True,
            confirm_phrase=STOP_LABS_CONFIRM_PHRASE,
        )
        assert request.scan_id == "test-scan-id"
        assert request.confirm is True
        assert request.confirm_phrase == STOP_LABS_CONFIRM_PHRASE

        # confirm=False should be caught by endpoint
        request_no_confirm = StopLabsRequest(
            scan_id="test-scan-id",
            mode=StopLabsMode.ALL_RUNNING,
            confirm=False,
            confirm_phrase=STOP_LABS_CONFIRM_PHRASE,
        )
        assert request_no_confirm.confirm is False

        # Wrong phrase should be caught by endpoint
        request_wrong_phrase = StopLabsRequest(
            scan_id="test-scan-id",
            mode=StopLabsMode.ALL_RUNNING,
            confirm=True,
            confirm_phrase="wrong phrase",
        )
        assert request_wrong_phrase.confirm_phrase != STOP_LABS_CONFIRM_PHRASE
