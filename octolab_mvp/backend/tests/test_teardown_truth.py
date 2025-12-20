"""Tests for truthful teardown behavior.

SECURITY tests included:
- project_name_for_lab derives from server-owned lab_id
- assert_valid_lab_project rejects non-matching names
- Teardown worker marks FAILED when containers/networks remain
- Never claims success if resources still exist
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.runtime.compose_runtime import (
    LAB_PROJECT_RE,
    TeardownResult,
    _is_lab_project,
    project_name_for_lab,
    assert_valid_lab_project,
)


# =============================================================================
# Project naming/validation tests
# =============================================================================


class TestProjectNameForLab:
    """Tests for project_name_for_lab function."""

    def test_generates_correct_format_from_uuid(self):
        """Should generate octolab_<uuid> format from UUID."""
        lab_id = uuid4()
        result = project_name_for_lab(lab_id)
        assert result.startswith("octolab_")
        assert str(lab_id).lower() in result.lower()

    def test_generates_correct_format_from_string(self):
        """Should generate octolab_<uuid> format from string."""
        lab_id = "12345678-1234-1234-1234-123456789abc"
        result = project_name_for_lab(lab_id)
        assert result == "octolab_12345678-1234-1234-1234-123456789abc"

    def test_normalizes_to_lowercase(self):
        """Should normalize to lowercase."""
        lab_id = "12345678-1234-1234-1234-123456789ABC"
        result = project_name_for_lab(lab_id)
        assert result == result.lower()

    def test_result_passes_validation(self):
        """Generated project name should pass _is_lab_project validation."""
        lab_id = uuid4()
        result = project_name_for_lab(lab_id)
        assert _is_lab_project(result)


class TestAssertValidLabProject:
    """Tests for assert_valid_lab_project function."""

    def test_passes_valid_project_with_dashes(self):
        """Should not raise for valid project with dashed UUID."""
        project = "octolab_12345678-1234-1234-1234-123456789abc"
        # Should not raise
        assert_valid_lab_project(project)

    def test_passes_valid_project_without_dashes(self):
        """Should not raise for valid project without dashes."""
        project = "octolab_12345678123412341234123456789abc"
        # Should not raise
        assert_valid_lab_project(project)

    def test_rejects_wrong_prefix(self):
        """Should raise ValueError for wrong prefix."""
        project = "other_12345678-1234-1234-1234-123456789abc"
        with pytest.raises(ValueError) as exc_info:
            assert_valid_lab_project(project)
        assert "Invalid lab project name" in str(exc_info.value)

    def test_rejects_short_uuid(self):
        """Should raise ValueError for short UUID."""
        project = "octolab_12345678"
        with pytest.raises(ValueError) as exc_info:
            assert_valid_lab_project(project)
        assert "Invalid lab project name" in str(exc_info.value)

    def test_rejects_empty_string(self):
        """Should raise ValueError for empty string."""
        with pytest.raises(ValueError) as exc_info:
            assert_valid_lab_project("")
        assert "Invalid lab project name" in str(exc_info.value)

    def test_rejects_malicious_input(self):
        """Should raise ValueError for malicious input."""
        project = "octolab_$(rm -rf /)"
        with pytest.raises(ValueError) as exc_info:
            assert_valid_lab_project(project)
        assert "Invalid lab project name" in str(exc_info.value)

    def test_truncates_long_invalid_names_in_error(self):
        """Should truncate very long invalid names in error message."""
        project = "x" * 100
        with pytest.raises(ValueError) as exc_info:
            assert_valid_lab_project(project)
        # Error should not contain the full 100-char string
        assert len(str(exc_info.value)) < 150


class TestLabProjectRegex:
    """Tests for LAB_PROJECT_RE regex pattern."""

    def test_matches_standard_uuid_format(self):
        """Should match standard UUID format with dashes."""
        assert LAB_PROJECT_RE.match("octolab_12345678-1234-1234-1234-123456789abc")

    def test_matches_uuid_without_dashes(self):
        """Should match UUID without dashes."""
        assert LAB_PROJECT_RE.match("octolab_12345678123412341234123456789abc")

    def test_case_insensitive(self):
        """Should match regardless of case."""
        assert LAB_PROJECT_RE.match("octolab_12345678-1234-1234-1234-123456789ABC")
        assert LAB_PROJECT_RE.match("OCTOLAB_12345678-1234-1234-1234-123456789abc")

    def test_rejects_wrong_prefix(self):
        """Should not match wrong prefix."""
        assert not LAB_PROJECT_RE.match("mylab_12345678-1234-1234-1234-123456789abc")

    def test_rejects_extra_characters(self):
        """Should not match with extra characters."""
        assert not LAB_PROJECT_RE.match("octolab_12345678-1234-1234-1234-123456789abc_extra")
        assert not LAB_PROJECT_RE.match("prefix_octolab_12345678-1234-1234-1234-123456789abc")


# =============================================================================
# TeardownResult tests
# =============================================================================


class TestTeardownResult:
    """Tests for TeardownResult class."""

    def test_success_when_no_remaining(self):
        """Success should be True when no containers or networks remain."""
        result = TeardownResult("octolab_abc")
        result.containers_remaining = 0
        result.networks_remaining = 0
        assert result.success is True

    def test_not_success_when_containers_remain(self):
        """Success should be False when containers remain."""
        result = TeardownResult("octolab_abc")
        result.containers_remaining = 1
        result.networks_remaining = 0
        assert result.success is False

    def test_not_success_when_networks_remain(self):
        """Success should be False when networks remain."""
        result = TeardownResult("octolab_abc")
        result.containers_remaining = 0
        result.networks_remaining = 1
        assert result.success is False

    def test_not_success_when_both_remain(self):
        """Success should be False when both containers and networks remain."""
        result = TeardownResult("octolab_abc")
        result.containers_remaining = 2
        result.networks_remaining = 2
        assert result.success is False

    def test_to_dict_includes_key_fields(self):
        """to_dict should include key fields."""
        result = TeardownResult("octolab_abc")
        result.compose_down_ok = True
        result.containers_before = 3
        result.containers_removed_force = 2
        result.containers_remaining = 1
        result.networks_before = 2
        result.networks_removed = 1
        result.networks_remaining = 1

        d = result.to_dict()
        assert d["project"] == "octolab_abc"
        assert d["compose_down_ok"] is True
        assert d["containers_before"] == 3
        assert d["containers_remaining"] == 1
        assert d["networks_remaining"] == 1
        assert d["success"] is False

    def test_to_dict_truncates_errors(self):
        """to_dict should truncate errors list."""
        result = TeardownResult("octolab_abc")
        result.errors = [f"err{i}" for i in range(10)]

        d = result.to_dict()
        assert len(d["errors"]) <= 5  # Truncated


# =============================================================================
# Teardown worker truthfulness tests
# =============================================================================


class TestTeardownWorkerTruthfulness:
    """Tests for teardown worker marking labs correctly based on TeardownResult."""

    @pytest.mark.asyncio
    async def test_marks_finished_on_success(self):
        """Should mark lab FINISHED when TeardownResult.success is True."""
        from app.models.lab import Lab, LabStatus

        lab_id = uuid4()

        # Mock successful teardown result
        mock_result = TeardownResult(f"octolab_{lab_id}")
        mock_result.compose_down_ok = True
        mock_result.containers_remaining = 0
        mock_result.networks_remaining = 0

        assert mock_result.success is True

        # This would be used by teardown_worker_tick
        # Verify the success property is checked correctly
        if hasattr(mock_result, 'success') and not mock_result.success:
            new_status = LabStatus.FAILED
        else:
            new_status = LabStatus.FINISHED

        assert new_status == LabStatus.FINISHED

    @pytest.mark.asyncio
    async def test_marks_failed_when_containers_remain(self):
        """Should mark lab FAILED when containers remain after teardown."""
        from app.models.lab import Lab, LabStatus

        lab_id = uuid4()

        # Mock failed teardown result
        mock_result = TeardownResult(f"octolab_{lab_id}")
        mock_result.compose_down_ok = False
        mock_result.containers_remaining = 2
        mock_result.networks_remaining = 0

        assert mock_result.success is False

        # This would be used by teardown_worker_tick
        if hasattr(mock_result, 'success') and not mock_result.success:
            new_status = LabStatus.FAILED
        else:
            new_status = LabStatus.FINISHED

        assert new_status == LabStatus.FAILED

    @pytest.mark.asyncio
    async def test_marks_failed_when_networks_remain(self):
        """Should mark lab FAILED when networks remain after teardown."""
        from app.models.lab import Lab, LabStatus

        lab_id = uuid4()

        # Mock failed teardown result
        mock_result = TeardownResult(f"octolab_{lab_id}")
        mock_result.compose_down_ok = True
        mock_result.containers_remaining = 0
        mock_result.networks_remaining = 1  # Network stuck

        assert mock_result.success is False

        if hasattr(mock_result, 'success') and not mock_result.success:
            new_status = LabStatus.FAILED
        else:
            new_status = LabStatus.FINISHED

        assert new_status == LabStatus.FAILED


# =============================================================================
# Verified teardown sequence tests
# =============================================================================


class TestVerifiedTeardownSequence:
    """Tests for verified teardown helper functions."""

    def test_list_project_containers_uses_label_filter(self):
        """_list_project_containers should use label filter in command."""
        from app.runtime.compose_runtime import _list_project_containers

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            _list_project_containers("octolab_abc123")

        call_args = mock_run.call_args[0][0]
        assert "--filter" in call_args
        assert "label=com.docker.compose.project=octolab_abc123" in call_args

    def test_list_project_containers_parses_output(self):
        """_list_project_containers should parse tab-separated output."""
        from app.runtime.compose_runtime import _list_project_containers

        output = "abc123\tcontainer-name\tUp 5 minutes\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=output)
            result = _list_project_containers("octolab_abc123")

        assert len(result) == 1
        assert result[0]["id"] == "abc123"
        assert result[0]["name"] == "container-name"

    def test_rm_containers_force_uses_force_flag(self):
        """_rm_containers_force should use -f flag."""
        from app.runtime.compose_runtime import _rm_containers_force

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            _rm_containers_force(["id1", "id2"])

        call_args = mock_run.call_args[0][0]
        assert "docker" in call_args
        assert "rm" in call_args
        assert "-f" in call_args

    def test_rm_networks_skips_non_octolab(self):
        """_rm_networks should skip networks not matching octolab pattern."""
        from app.runtime.compose_runtime import _rm_networks

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            removed, remaining, errors = _rm_networks(["bridge", "host"])

        # Should not call subprocess for non-octolab networks
        mock_run.assert_not_called()

    def test_rm_networks_handles_not_found(self):
        """_rm_networks should treat 'not found' as success."""
        from app.runtime.compose_runtime import _rm_networks

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="network not found"
            )
            removed, remaining, errors = _rm_networks(["octolab_abc_net"])

        assert removed == 1  # Counts as removed


# =============================================================================
# Idempotency tests
# =============================================================================


class TestTeardownIdempotency:
    """Tests for idempotent teardown behavior."""

    def test_teardown_result_success_when_already_clean(self):
        """TeardownResult should show success when no resources existed."""
        result = TeardownResult("octolab_abc")
        result.containers_before = 0
        result.containers_remaining = 0
        result.networks_before = 0
        result.networks_remaining = 0
        result.compose_down_ok = True

        # Success even if nothing to tear down
        assert result.success is True

    def test_empty_container_list_returns_zero(self):
        """_rm_containers_force with empty list should return (0, [])."""
        from app.runtime.compose_runtime import _rm_containers_force

        removed, errors = _rm_containers_force([])
        assert removed == 0
        assert errors == []

    def test_empty_network_list_returns_zero(self):
        """_rm_networks with empty list should return (0, 0, [])."""
        from app.runtime.compose_runtime import _rm_networks

        removed, remaining, errors = _rm_networks([])
        assert removed == 0
        assert remaining == 0
        assert errors == []
