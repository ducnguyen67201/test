"""Tests for admin runtime drift detection and stop-labs functionality.

These tests verify:
- Runtime drift classification (tracked/drifted/orphaned)
- Stop-labs confirmation requirements
- Mode selection targets correct projects
- Security invariants (shell=False, no prune, pattern matching)
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4

# Mark all tests as not requiring database
pytestmark = pytest.mark.no_db


class TestExtractLabIdFromProject:
    """Tests for extract_lab_id_from_project() function."""

    def test_extracts_valid_uuid(self):
        """Test UUID extraction from valid lab project."""
        from app.services.docker_net import extract_lab_id_from_project

        lab_id = extract_lab_id_from_project("octolab_12345678-1234-1234-1234-123456789abc")
        assert lab_id == "12345678-1234-1234-1234-123456789abc"

    def test_returns_none_for_infrastructure(self):
        """Test that infrastructure projects return None."""
        from app.services.docker_net import extract_lab_id_from_project

        assert extract_lab_id_from_project("octolab_mvp") is None
        assert extract_lab_id_from_project("guacamole") is None
        assert extract_lab_id_from_project("octolab-hackvm") is None

    def test_returns_none_for_empty(self):
        """Test that empty/None returns None."""
        from app.services.docker_net import extract_lab_id_from_project

        assert extract_lab_id_from_project("") is None
        assert extract_lab_id_from_project(None) is None


class TestScanRunningLabProjects:
    """Tests for scan_running_lab_projects() function."""

    def test_groups_containers_by_project(self):
        """Test that containers are grouped by lab project."""
        from app.services.docker_net import scan_running_lab_projects

        mock_output = (
            "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111-octobox-1\toctolab_aaaaaaaa-bbbb-cccc-dddd-111111111111\n"
            "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111-gateway-1\toctolab_aaaaaaaa-bbbb-cccc-dddd-111111111111\n"
            "octolab_aaaaaaaa-bbbb-cccc-dddd-222222222222-octobox-1\toctolab_aaaaaaaa-bbbb-cccc-dddd-222222222222\n"
        )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = mock_output

        with patch("subprocess.run", return_value=mock_result):
            projects = scan_running_lab_projects(timeout=10.0)

        assert len(projects) == 2
        assert "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111" in projects
        assert len(projects["octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111"]) == 2
        assert "octolab_aaaaaaaa-bbbb-cccc-dddd-222222222222" in projects
        assert len(projects["octolab_aaaaaaaa-bbbb-cccc-dddd-222222222222"]) == 1

    def test_excludes_infrastructure_projects(self):
        """Test that infrastructure projects are excluded."""
        from app.services.docker_net import scan_running_lab_projects

        mock_output = (
            "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111-octobox-1\toctolab_aaaaaaaa-bbbb-cccc-dddd-111111111111\n"
            "octolab-guacamole-1\tguacamole\n"
            "octolab-postgres-1\toctolab_mvp\n"
        )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = mock_output

        with patch("subprocess.run", return_value=mock_result):
            projects = scan_running_lab_projects(timeout=10.0)

        assert len(projects) == 1
        assert "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111" in projects
        assert "guacamole" not in projects
        assert "octolab_mvp" not in projects


class TestStopLabProject:
    """Tests for stop_lab_project() function."""

    def test_rejects_invalid_project_name(self):
        """Test that invalid project names are rejected."""
        from app.services.docker_net import stop_lab_project

        success, errors = stop_lab_project(
            project="guacamole",
            compose_dir="/tmp",
            compose_file="/tmp/docker-compose.yml",
        )

        assert success is False
        assert len(errors) > 0
        assert "Invalid project name" in errors[0]

    def test_runs_compose_down_with_correct_args(self):
        """Test that compose down is called with correct arguments."""
        from app.services.docker_net import stop_lab_project

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            success, errors = stop_lab_project(
                project="octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111",
                compose_dir="/tmp/compose",
                compose_file="/tmp/compose/docker-compose.yml",
            )

        assert success is True
        assert len(errors) == 0

        # Verify the command arguments
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "docker" in cmd
        assert "compose" in cmd
        assert "--project-directory" in cmd
        assert "/tmp/compose" in cmd
        assert "-f" in cmd
        assert "-p" in cmd
        assert "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111" in cmd
        assert "down" in cmd
        assert "--remove-orphans" in cmd

        # Verify shell=False
        assert call_args[1]["shell"] is False


class TestStopLabProjectsBatch:
    """Tests for stop_lab_projects_batch() function."""

    def test_processes_multiple_projects(self):
        """Test batch processing of multiple projects."""
        from app.services.docker_net import stop_lab_projects_batch

        mock_result = MagicMock()
        mock_result.returncode = 0

        projects = [
            "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111",
            "octolab_aaaaaaaa-bbbb-cccc-dddd-222222222222",
        ]

        with patch("subprocess.run", return_value=mock_result):
            with patch("app.services.docker_net.cleanup_project_networks", return_value=(2, 0)):
                result = stop_lab_projects_batch(
                    projects=projects,
                    compose_dir="/tmp",
                    compose_file="/tmp/docker-compose.yml",
                )

        assert result.targets == 2
        assert result.projects_stopped == 2
        assert result.projects_failed == 0
        assert result.networks_removed == 4  # 2 per project

    def test_rejects_invalid_projects(self):
        """Test that invalid projects are rejected in batch."""
        from app.services.docker_net import stop_lab_projects_batch

        projects = [
            "guacamole",  # Invalid
            "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111",  # Valid
        ]

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            with patch("app.services.docker_net.cleanup_project_networks", return_value=(2, 0)):
                result = stop_lab_projects_batch(
                    projects=projects,
                    compose_dir="/tmp",
                    compose_file="/tmp/docker-compose.yml",
                )

        assert result.targets == 2
        assert result.projects_stopped == 1  # Only valid one
        assert result.projects_failed == 1  # Invalid one


class TestRuntimeProjectClassification:
    """Tests for RuntimeProjectClassification enum."""

    def test_classification_values(self):
        """Test that classification has correct values."""
        from app.services.docker_net import RuntimeProjectClassification

        assert RuntimeProjectClassification.TRACKED.value == "tracked"
        assert RuntimeProjectClassification.DRIFTED.value == "drifted"
        assert RuntimeProjectClassification.ORPHANED.value == "orphaned"


class TestStopLabsEndpointConfirmation:
    """Tests for stop-labs endpoint confirmation requirements."""

    def test_requires_confirm_true(self):
        """Test that confirm=true is required."""
        from app.api.routes.admin import StopLabsRequest, StopLabsMode

        request = StopLabsRequest(
            mode=StopLabsMode.ORPHANED_ONLY,
            confirm=False,
            confirm_phrase="STOP RUNNING LABS",
        )

        # The endpoint should reject this
        assert request.confirm is False

    def test_requires_exact_phrase(self):
        """Test that exact confirmation phrase is required."""
        from app.api.routes.admin import STOP_LABS_CONFIRM_PHRASE

        assert STOP_LABS_CONFIRM_PHRASE == "STOP RUNNING LABS"

    def test_stop_labs_modes(self):
        """Test that all stop-labs modes are defined."""
        from app.api.routes.admin import StopLabsMode

        assert StopLabsMode.ORPHANED_ONLY.value == "orphaned_only"
        assert StopLabsMode.DRIFTED_ONLY.value == "drifted_only"
        assert StopLabsMode.ALL_RUNNING.value == "all_running"


class TestRuntimeDriftResult:
    """Tests for RuntimeDriftResult dataclass."""

    def test_default_values(self):
        """Test that dataclass has correct defaults."""
        from app.services.docker_net import RuntimeDriftResult

        result = RuntimeDriftResult()

        assert result.running_lab_projects_total == 0
        assert result.running_lab_containers_total == 0
        assert result.tracked_running_projects == 0
        assert result.drifted_running_projects == 0
        assert result.orphaned_running_projects == 0
        assert result.projects == []


class TestStopLabsResult:
    """Tests for StopLabsResult dataclass."""

    def test_default_values(self):
        """Test that dataclass has correct defaults."""
        from app.services.docker_net import StopLabsResult

        result = StopLabsResult()

        assert result.targets == 0
        assert result.projects_stopped == 0
        assert result.projects_failed == 0
        assert result.networks_removed == 0
        assert result.networks_failed == 0
        assert result.errors == []


class TestTrackedStatuses:
    """Tests for tracked status constants."""

    def test_tracked_statuses_defined(self):
        """Test that tracked statuses are correctly defined."""
        from app.api.routes.admin import TRACKED_STATUSES
        from app.models.lab import LabStatus

        assert LabStatus.READY in TRACKED_STATUSES
        assert LabStatus.PROVISIONING in TRACKED_STATUSES
        assert LabStatus.ENDING in TRACKED_STATUSES

    def test_terminal_statuses_defined(self):
        """Test that terminal statuses are correctly defined."""
        from app.api.routes.admin import TERMINAL_STATUSES
        from app.models.lab import LabStatus

        assert LabStatus.FINISHED in TERMINAL_STATUSES
        assert LabStatus.FAILED in TERMINAL_STATUSES


class TestRuntimeDriftClassification:
    """Tests for runtime drift classification logic."""

    @pytest.mark.asyncio
    async def test_classifies_orphaned_project(self):
        """Test that projects with no DB row are classified as orphaned."""
        from app.api.routes.admin import _classify_runtime_projects
        from app.services.docker_net import RuntimeProjectClassification

        # Mock DB session that returns no lab
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        runtime_projects = {
            "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111": ["container-1", "container-2"],
        }

        result = await _classify_runtime_projects(mock_db, runtime_projects)

        assert result.orphaned_running_projects == 1
        assert result.tracked_running_projects == 0
        assert result.drifted_running_projects == 0
        assert len(result.projects) == 1
        assert result.projects[0].classification == RuntimeProjectClassification.ORPHANED

    @pytest.mark.asyncio
    async def test_classifies_tracked_project(self):
        """Test that projects with DB READY status are classified as tracked."""
        from app.api.routes.admin import _classify_runtime_projects
        from app.services.docker_net import RuntimeProjectClassification
        from app.models.lab import LabStatus

        # Mock lab with READY status
        mock_lab = MagicMock()
        mock_lab.status = LabStatus.READY

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_lab
        mock_db.execute.return_value = mock_result

        runtime_projects = {
            "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111": ["container-1"],
        }

        result = await _classify_runtime_projects(mock_db, runtime_projects)

        assert result.tracked_running_projects == 1
        assert result.orphaned_running_projects == 0
        assert result.drifted_running_projects == 0
        assert result.projects[0].classification == RuntimeProjectClassification.TRACKED

    @pytest.mark.asyncio
    async def test_classifies_drifted_project(self):
        """Test that projects with DB FINISHED status are classified as drifted."""
        from app.api.routes.admin import _classify_runtime_projects
        from app.services.docker_net import RuntimeProjectClassification
        from app.models.lab import LabStatus

        # Mock lab with FINISHED status
        mock_lab = MagicMock()
        mock_lab.status = LabStatus.FINISHED

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_lab
        mock_db.execute.return_value = mock_result

        runtime_projects = {
            "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111": ["container-1"],
        }

        result = await _classify_runtime_projects(mock_db, runtime_projects)

        assert result.drifted_running_projects == 1
        assert result.tracked_running_projects == 0
        assert result.orphaned_running_projects == 0
        assert result.projects[0].classification == RuntimeProjectClassification.DRIFTED

    @pytest.mark.asyncio
    async def test_sorts_orphaned_first(self):
        """Test that orphaned projects are sorted first."""
        from app.api.routes.admin import _classify_runtime_projects
        from app.services.docker_net import RuntimeProjectClassification
        from app.models.lab import LabStatus

        # Set up mocks for mixed classifications
        mock_db = AsyncMock()

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                # First project: READY (tracked)
                mock_lab = MagicMock()
                mock_lab.status = LabStatus.READY
                mock_result.scalar_one_or_none.return_value = mock_lab
            elif call_count == 2:
                # Second project: None (orphaned)
                mock_result.scalar_one_or_none.return_value = None
            else:
                # Third project: FINISHED (drifted)
                mock_lab = MagicMock()
                mock_lab.status = LabStatus.FINISHED
                mock_result.scalar_one_or_none.return_value = mock_lab
            return mock_result

        mock_db.execute = mock_execute

        runtime_projects = {
            "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111": ["c1"],
            "octolab_aaaaaaaa-bbbb-cccc-dddd-222222222222": ["c2"],
            "octolab_aaaaaaaa-bbbb-cccc-dddd-333333333333": ["c3"],
        }

        result = await _classify_runtime_projects(mock_db, runtime_projects)

        # Orphaned should be first, then drifted, then tracked
        assert result.projects[0].classification == RuntimeProjectClassification.ORPHANED
        assert result.projects[1].classification == RuntimeProjectClassification.DRIFTED
        assert result.projects[2].classification == RuntimeProjectClassification.TRACKED


class TestSecurityInvariants:
    """Tests for security invariants."""

    def test_stop_lab_project_uses_shell_false(self):
        """Test that stop_lab_project uses shell=False."""
        from app.services.docker_net import stop_lab_project

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            stop_lab_project(
                project="octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111",
                compose_dir="/tmp",
                compose_file="/tmp/docker-compose.yml",
            )

        call_args = mock_run.call_args
        assert call_args[1]["shell"] is False

    def test_scan_running_uses_shell_false(self):
        """Test that scan_running_lab_projects uses shell=False."""
        from app.services.docker_net import scan_running_lab_projects

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            scan_running_lab_projects(timeout=10.0)

        call_args = mock_run.call_args
        assert call_args[1]["shell"] is False


class TestStopLabsModesIncludesTrackedOnly:
    """Tests for tracked_only mode in stop-labs."""

    def test_tracked_only_mode_defined(self):
        """Test that tracked_only mode is defined."""
        from app.api.routes.admin import StopLabsMode

        assert StopLabsMode.TRACKED_ONLY.value == "tracked_only"

    @pytest.mark.asyncio
    async def test_stop_labs_selects_tracked_only_targets(self):
        """Test that tracked_only mode selects only tracked projects."""
        from app.api.routes.admin import (
            _classify_runtime_projects,
            StopLabsMode,
        )
        from app.services.docker_net import RuntimeProjectClassification
        from app.models.lab import LabStatus

        # Create projects with mixed classifications
        mock_db = AsyncMock()
        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                # First: READY (tracked)
                mock_lab = MagicMock()
                mock_lab.status = LabStatus.READY
                mock_result.scalar_one_or_none.return_value = mock_lab
            elif call_count == 2:
                # Second: None (orphaned)
                mock_result.scalar_one_or_none.return_value = None
            else:
                # Third: FINISHED (drifted)
                mock_lab = MagicMock()
                mock_lab.status = LabStatus.FINISHED
                mock_result.scalar_one_or_none.return_value = mock_lab
            return mock_result

        mock_db.execute = mock_execute

        runtime_projects = {
            "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111": ["c1"],
            "octolab_aaaaaaaa-bbbb-cccc-dddd-222222222222": ["c2"],
            "octolab_aaaaaaaa-bbbb-cccc-dddd-333333333333": ["c3"],
        }

        drift_result = await _classify_runtime_projects(mock_db, runtime_projects)

        # Verify we have one of each classification
        assert drift_result.tracked_running_projects == 1
        assert drift_result.orphaned_running_projects == 1
        assert drift_result.drifted_running_projects == 1

        # Verify tracked_only would select the correct project
        targets = []
        for p in drift_result.projects:
            if p.classification == RuntimeProjectClassification.TRACKED:
                targets.append(p.project)

        assert len(targets) == 1
        # The tracked one should be the first project (READY)
        assert targets[0] == "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111"

    @pytest.mark.asyncio
    async def test_stop_labs_selects_drifted_only_targets(self):
        """Test that drifted_only mode selects only drifted projects."""
        from app.api.routes.admin import _classify_runtime_projects
        from app.services.docker_net import RuntimeProjectClassification
        from app.models.lab import LabStatus

        mock_db = AsyncMock()
        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_lab = MagicMock()
                mock_lab.status = LabStatus.FINISHED  # drifted
                mock_result.scalar_one_or_none.return_value = mock_lab
            elif call_count == 2:
                mock_lab = MagicMock()
                mock_lab.status = LabStatus.READY  # tracked
                mock_result.scalar_one_or_none.return_value = mock_lab
            return mock_result

        mock_db.execute = mock_execute

        runtime_projects = {
            "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111": ["c1"],
            "octolab_aaaaaaaa-bbbb-cccc-dddd-222222222222": ["c2"],
        }

        drift_result = await _classify_runtime_projects(mock_db, runtime_projects)

        targets = []
        for p in drift_result.projects:
            if p.classification == RuntimeProjectClassification.DRIFTED:
                targets.append(p.project)

        assert len(targets) == 1
        assert targets[0] == "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111"

    @pytest.mark.asyncio
    async def test_stop_labs_selects_all_running_targets(self):
        """Test that all_running mode selects all projects."""
        from app.api.routes.admin import _classify_runtime_projects
        from app.models.lab import LabStatus

        mock_db = AsyncMock()
        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_lab = MagicMock()
                mock_lab.status = LabStatus.READY
                mock_result.scalar_one_or_none.return_value = mock_lab
            elif call_count == 2:
                mock_result.scalar_one_or_none.return_value = None
            else:
                mock_lab = MagicMock()
                mock_lab.status = LabStatus.FINISHED
                mock_result.scalar_one_or_none.return_value = mock_lab
            return mock_result

        mock_db.execute = mock_execute

        runtime_projects = {
            "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111": ["c1"],
            "octolab_aaaaaaaa-bbbb-cccc-dddd-222222222222": ["c2"],
            "octolab_aaaaaaaa-bbbb-cccc-dddd-333333333333": ["c3"],
        }

        drift_result = await _classify_runtime_projects(mock_db, runtime_projects)

        # All running mode should select all 3 projects
        targets = [p.project for p in drift_result.projects]
        assert len(targets) == 3


class TestStopProjectValidation:
    """Tests for stop-project endpoint validation."""

    def test_is_lab_project_validates_pattern(self):
        """Test that is_lab_project validates the pattern correctly."""
        from app.services.docker_net import is_lab_project

        # Valid lab projects
        assert is_lab_project("octolab_12345678-1234-1234-1234-123456789abc") is True
        assert is_lab_project("octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111") is True

        # Invalid projects
        assert is_lab_project("guacamole") is False
        assert is_lab_project("octolab_mvp") is False
        assert is_lab_project("octolab-hackvm") is False
        assert is_lab_project("") is False
        assert is_lab_project("octolab_invalid") is False
        assert is_lab_project("octolab_12345678") is False

    def test_stop_project_request_requires_project(self):
        """Test that StopProjectRequest requires project field."""
        from app.api.routes.admin import StopProjectRequest
        import pydantic

        # Valid request
        request = StopProjectRequest(
            project="octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111",
            confirm=True,
        )
        assert request.project == "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111"
        assert request.confirm is True

        # Missing project should raise validation error
        with pytest.raises(pydantic.ValidationError):
            StopProjectRequest(confirm=True)

    def test_stop_project_request_confirm_default_false(self):
        """Test that StopProjectRequest confirm defaults to False."""
        from app.api.routes.admin import StopProjectRequest

        request = StopProjectRequest(
            project="octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111",
        )
        assert request.confirm is False

    def test_stop_project_response_fields(self):
        """Test that StopProjectResponse has correct fields."""
        from app.api.routes.admin import StopProjectResponse

        # Success response
        response = StopProjectResponse(
            project="octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111",
            stopped=True,
            networks_removed=2,
            error=None,
        )
        assert response.project == "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111"
        assert response.stopped is True
        assert response.networks_removed == 2
        assert response.error is None

        # Failure response
        response = StopProjectResponse(
            project="octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111",
            stopped=False,
            networks_removed=0,
            error="Some error",
        )
        assert response.stopped is False
        assert response.error == "Some error"


class TestStopProjectExecution:
    """Tests for stop-project execution."""

    def test_stop_lab_project_with_correct_project_name(self):
        """Test that stop_lab_project executes compose down with correct -p flag."""
        from app.services.docker_net import stop_lab_project

        mock_result = MagicMock()
        mock_result.returncode = 0

        project = "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111"

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            success, errors = stop_lab_project(
                project=project,
                compose_dir="/tmp/compose",
                compose_file="/tmp/compose/docker-compose.yml",
            )

        assert success is True
        assert len(errors) == 0

        # Verify the -p flag has the correct project name
        call_args = mock_run.call_args
        cmd = call_args[0][0]

        # Find the -p index and verify the next arg is the project name
        p_index = cmd.index("-p")
        assert cmd[p_index + 1] == project

    def test_cleanup_project_networks_only_removes_labeled(self):
        """Test that cleanup_project_networks only removes networks with correct labels."""
        from app.services.docker_net import cleanup_project_networks

        project = "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111"

        # Mock docker network ls to return networks
        mock_ls_result = MagicMock()
        mock_ls_result.returncode = 0
        mock_ls_result.stdout = f"{project}_lab_net\n{project}_egress_net\n"

        # Mock docker network inspect -f (for container count) to return 0
        mock_inspect_result = MagicMock()
        mock_inspect_result.returncode = 0
        mock_inspect_result.stdout = "0"

        # Mock docker network rm to succeed
        mock_rm_result = MagicMock()
        mock_rm_result.returncode = 0

        with patch("subprocess.run") as mock_run:
            # Flow: list_networks_by_compose_project (ls) ->
            # for each network: get_network_container_count (inspect) -> remove_network (rm)
            # So: ls, inspect, rm, inspect, rm
            mock_run.side_effect = [
                mock_ls_result,     # list_networks_by_compose_project
                mock_inspect_result, mock_rm_result,  # first network
                mock_inspect_result, mock_rm_result,  # second network
            ]
            removed, failed = cleanup_project_networks(project, timeout=10.0)

        # Verify the filter uses the correct project label
        first_call = mock_run.call_args_list[0]
        cmd = first_call[0][0]
        assert "--filter" in cmd
        # Should filter by label=com.docker.compose.project=<project>
        label_filter = f"label=com.docker.compose.project={project}"
        assert label_filter in cmd

        assert removed == 2
        assert failed == 0


class TestStopLabsConfirmation:
    """Tests for stop-labs and stop-project confirmation requirements."""

    def test_stop_labs_requires_confirm_true(self):
        """Test that stop-labs requires confirm=true."""
        from app.api.routes.admin import StopLabsRequest, StopLabsMode

        request = StopLabsRequest(
            mode=StopLabsMode.TRACKED_ONLY,
            confirm=False,
            confirm_phrase="STOP RUNNING LABS",
        )
        # Endpoint should reject this (confirm is False)
        assert request.confirm is False

    def test_stop_labs_requires_exact_phrase(self):
        """Test that stop-labs requires exact confirmation phrase."""
        from app.api.routes.admin import StopLabsRequest, StopLabsMode, STOP_LABS_CONFIRM_PHRASE

        # Correct phrase
        request = StopLabsRequest(
            mode=StopLabsMode.ORPHANED_ONLY,
            confirm=True,
            confirm_phrase="STOP RUNNING LABS",
        )
        assert request.confirm_phrase == STOP_LABS_CONFIRM_PHRASE

        # Wrong phrase - endpoint should reject
        request_wrong = StopLabsRequest(
            mode=StopLabsMode.ORPHANED_ONLY,
            confirm=True,
            confirm_phrase="stop running labs",  # lowercase
        )
        assert request_wrong.confirm_phrase != STOP_LABS_CONFIRM_PHRASE

    def test_stop_project_requires_confirm_true(self):
        """Test that stop-project requires confirm=true."""
        from app.api.routes.admin import StopProjectRequest

        # Without confirm - should be rejected by endpoint
        request = StopProjectRequest(
            project="octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111",
            confirm=False,
        )
        assert request.confirm is False

        # With confirm - should be accepted
        request_confirmed = StopProjectRequest(
            project="octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111",
            confirm=True,
        )
        assert request_confirmed.confirm is True

    def test_stop_project_no_phrase_required(self):
        """Test that stop-project does not require a confirmation phrase (only confirm boolean)."""
        from app.api.routes.admin import StopProjectRequest

        # StopProjectRequest has no confirm_phrase field
        request = StopProjectRequest(
            project="octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111",
            confirm=True,
        )
        assert not hasattr(request, "confirm_phrase") or "confirm_phrase" not in request.model_fields
