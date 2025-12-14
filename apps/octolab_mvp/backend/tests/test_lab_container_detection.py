"""Tests for label-based lab container detection.

These tests verify that the docker_net module correctly distinguishes
between lab containers (octolab_<uuid> projects) and infrastructure
containers (guacamole, octolab_mvp, octolab-hackvm, etc.).

This prevents the miscount regression where the admin panel showed
"35 running OctoLab containers" when there were only 2 actual lab
projects running.
"""

import pytest
from unittest.mock import patch, MagicMock
import subprocess

# Mark all tests as not requiring database
pytestmark = pytest.mark.no_db


class TestIsLabProject:
    """Tests for is_lab_project() function."""

    def test_matches_valid_lab_project(self):
        """Test that valid lab project names are recognized."""
        from app.services.docker_net import is_lab_project

        # Valid lab project names
        assert is_lab_project("octolab_12345678-1234-1234-1234-123456789abc") is True
        assert is_lab_project("octolab_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee") is True
        assert is_lab_project("octolab_00000000-0000-0000-0000-000000000000") is True

    def test_rejects_infrastructure_projects(self):
        """Test that infrastructure projects are NOT recognized as labs."""
        from app.services.docker_net import is_lab_project

        # Infrastructure projects should NOT be labs
        assert is_lab_project("octolab_mvp") is False
        assert is_lab_project("octolab-hackvm") is False
        assert is_lab_project("guacamole") is False
        assert is_lab_project("octolab") is False

    def test_rejects_partial_uuid(self):
        """Test that partial UUIDs are rejected."""
        from app.services.docker_net import is_lab_project

        # Incomplete UUIDs
        assert is_lab_project("octolab_12345678") is False
        assert is_lab_project("octolab_12345678-1234") is False
        assert is_lab_project("octolab_12345678-1234-1234-1234") is False

    def test_handles_case_insensitivity(self):
        """Test that uppercase UUIDs are normalized."""
        from app.services.docker_net import is_lab_project

        # Uppercase should be lowercased and matched
        assert is_lab_project("OCTOLAB_12345678-1234-1234-1234-123456789ABC") is True
        assert is_lab_project("Octolab_AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE") is True

    def test_handles_empty_and_none(self):
        """Test that empty/None values don't crash."""
        from app.services.docker_net import is_lab_project

        assert is_lab_project("") is False
        assert is_lab_project(None) is False
        assert is_lab_project("   ") is False


class TestLabProjectPattern:
    """Tests for LAB_PROJECT_PATTERN regex."""

    def test_pattern_matches_valid_uuid(self):
        """Test that the regex correctly matches lab project format."""
        from app.services.docker_net import LAB_PROJECT_PATTERN

        # Valid patterns
        assert LAB_PROJECT_PATTERN.match("octolab_12345678-1234-1234-1234-123456789abc")
        assert LAB_PROJECT_PATTERN.match("octolab_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

    def test_pattern_rejects_infrastructure(self):
        """Test that the regex rejects non-lab patterns."""
        from app.services.docker_net import LAB_PROJECT_PATTERN

        # Invalid patterns
        assert not LAB_PROJECT_PATTERN.match("octolab_mvp")
        assert not LAB_PROJECT_PATTERN.match("guacamole")
        assert not LAB_PROJECT_PATTERN.match("octolab-hackvm")
        # Suffix after UUID
        assert not LAB_PROJECT_PATTERN.match("octolab_12345678-1234-1234-1234-123456789abc_extra")


class TestGetRunningContainerStatus:
    """Tests for get_running_container_status() function."""

    def test_partitions_lab_and_nonlab_containers(self):
        """Test that containers are correctly partitioned by project label."""
        from app.services.docker_net import get_running_container_status

        # Mock docker ps output with mixed containers
        mock_output = (
            "octolab_12345678-1234-1234-1234-123456789abc-octobox-1\toctolab_12345678-1234-1234-1234-123456789abc\n"
            "octolab_12345678-1234-1234-1234-123456789abc-gateway-1\toctolab_12345678-1234-1234-1234-123456789abc\n"
            "octolab_12345678-1234-1234-1234-123456789abc-target-1\toctolab_12345678-1234-1234-1234-123456789abc\n"
            "octolab-guacamole-1\tguacamole\n"
            "octolab-guacd-1\tguacamole\n"
            "octolab-guac-db-1\tguacamole\n"
            "octolab-postgres-1\toctolab_mvp\n"
        )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = mock_output

        with patch("subprocess.run", return_value=mock_result):
            status = get_running_container_status(timeout=10.0)

        # Verify partitioning
        assert status.running_lab_containers == 3  # octobox, gateway, target
        assert status.running_lab_projects == 1  # one lab project
        assert status.running_nonlab_containers == 4  # guacamole (3) + postgres (1)
        assert status.running_total_containers == 7

        # Verify lab entries
        lab_names = [e.name for e in status.lab_entries]
        assert "octolab_12345678-1234-1234-1234-123456789abc-octobox-1" in lab_names
        assert "octolab_12345678-1234-1234-1234-123456789abc-gateway-1" in lab_names

        # Verify non-lab entries include guacamole
        nonlab_names = [e.name for e in status.nonlab_entries]
        assert "octolab-guacamole-1" in nonlab_names
        assert "octolab-postgres-1" in nonlab_names

    def test_handles_multiple_lab_projects(self):
        """Test that multiple lab projects are counted correctly."""
        from app.services.docker_net import get_running_container_status

        # Two different lab projects
        mock_output = (
            "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111-octobox-1\toctolab_aaaaaaaa-bbbb-cccc-dddd-111111111111\n"
            "octolab_aaaaaaaa-bbbb-cccc-dddd-111111111111-gateway-1\toctolab_aaaaaaaa-bbbb-cccc-dddd-111111111111\n"
            "octolab_aaaaaaaa-bbbb-cccc-dddd-222222222222-octobox-1\toctolab_aaaaaaaa-bbbb-cccc-dddd-222222222222\n"
        )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = mock_output

        with patch("subprocess.run", return_value=mock_result):
            status = get_running_container_status(timeout=10.0)

        assert status.running_lab_containers == 3
        assert status.running_lab_projects == 2  # Two different projects

    def test_handles_no_running_containers(self):
        """Test behavior when no containers are running."""
        from app.services.docker_net import get_running_container_status

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            status = get_running_container_status(timeout=10.0)

        assert status.running_lab_containers == 0
        assert status.running_lab_projects == 0
        assert status.running_nonlab_containers == 0
        assert status.running_total_containers == 0

    def test_handles_containers_without_compose_label(self):
        """Test that containers without compose labels are counted as non-lab."""
        from app.services.docker_net import get_running_container_status

        # Container with empty/missing project label
        mock_output = (
            "k3d-octolab-server-0\t\n"  # No compose label
            "some-random-container\t\n"  # No compose label
        )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = mock_output

        with patch("subprocess.run", return_value=mock_result):
            status = get_running_container_status(timeout=10.0)

        assert status.running_lab_containers == 0
        assert status.running_nonlab_containers == 2
        assert status.running_total_containers == 2


class TestListRunningLabContainers:
    """Tests for list_running_lab_containers() function."""

    def test_returns_only_lab_containers(self):
        """Test that only lab containers are returned."""
        from app.services.docker_net import list_running_lab_containers

        mock_output = (
            "octolab_12345678-1234-1234-1234-123456789abc-octobox-1\toctolab_12345678-1234-1234-1234-123456789abc\n"
            "octolab-guacamole-1\tguacamole\n"
            "octolab-postgres-1\toctolab_mvp\n"
        )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = mock_output

        with patch("subprocess.run", return_value=mock_result):
            containers = list_running_lab_containers(timeout=10.0)

        assert len(containers) == 1
        assert containers[0] == "octolab_12345678-1234-1234-1234-123456789abc-octobox-1"


class TestContainerStatusInfo:
    """Tests for ContainerStatusInfo dataclass."""

    def test_default_values(self):
        """Test that dataclass has correct defaults."""
        from app.services.docker_net import ContainerStatusInfo

        status = ContainerStatusInfo()

        assert status.running_lab_containers == 0
        assert status.running_lab_projects == 0
        assert status.running_nonlab_containers == 0
        assert status.running_total_containers == 0
        assert status.lab_entries == []
        assert status.nonlab_entries == []


class TestContainerInfo:
    """Tests for ContainerInfo dataclass."""

    def test_fields(self):
        """Test that dataclass has correct fields."""
        from app.services.docker_net import ContainerInfo

        info = ContainerInfo(name="test-container", project="test-project")

        assert info.name == "test-container"
        assert info.project == "test-project"
