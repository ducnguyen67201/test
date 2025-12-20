"""Tests for compose runtime network cleanup with retry logic.

Tests the bounded retry behavior for docker network rm during lab teardown.

These tests verify:
1. NOT_FOUND is treated as success (idempotent)
2. IN_USE with empty containers triggers GC race retry
3. Max retries triggers warning log and returns False
4. Project-owned containers trigger compose rm -sfv
5. Unknown containers raise NetworkCleanupBlockedError
"""

import pytest
from unittest.mock import MagicMock, patch, call

from app.services.docker_net import (
    NetworkRemoveResult,
    classify_network_error,
    remove_network,
)
from app.runtime.exceptions import NetworkCleanupBlockedError

# Mark all tests as not requiring database
pytestmark = pytest.mark.no_db


class TestClassifyNetworkError:
    """Tests for classify_network_error function."""

    def test_not_found_patterns(self):
        """NOT_FOUND returned for 'not found' and 'no such network' patterns."""
        assert classify_network_error("Error: No such network: test") == NetworkRemoveResult.NOT_FOUND
        assert classify_network_error("network test not found") == NetworkRemoveResult.NOT_FOUND

    def test_in_use_active_endpoints(self):
        """IN_USE returned for 'has active endpoints' pattern."""
        assert classify_network_error(
            "Error response from daemon: network test has active endpoints"
        ) == NetworkRemoveResult.IN_USE

    def test_in_use_resource_still_in_use(self):
        """IN_USE returned for 'resource is still in use' pattern."""
        assert classify_network_error(
            "Error: resource is still in use"
        ) == NetworkRemoveResult.IN_USE

    def test_in_use_network_is_in_use(self):
        """IN_USE returned for 'network is in use' pattern."""
        assert classify_network_error(
            "Error response from daemon: network is in use by container abc123"
        ) == NetworkRemoveResult.IN_USE

    def test_error_for_unknown(self):
        """ERROR returned for unknown error messages."""
        assert classify_network_error("something went wrong") == NetworkRemoveResult.ERROR
        assert classify_network_error("") == NetworkRemoveResult.ERROR
        assert classify_network_error(None) == NetworkRemoveResult.ERROR


class TestRemoveNetwork:
    """Tests for remove_network function."""

    def test_success_returns_ok(self):
        """Successful removal returns OK."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            result = remove_network("test_net")
            assert result == NetworkRemoveResult.OK

    def test_not_found_returns_not_found(self):
        """Network not found returns NOT_FOUND (treated as success by caller)."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Error: No such network: test_net"

        with patch("subprocess.run", return_value=mock_result):
            result = remove_network("test_net")
            assert result == NetworkRemoveResult.NOT_FOUND

    def test_not_found_no_warning_logged(self, caplog):
        """NOT_FOUND does not log warnings (idempotent)."""
        import logging
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Error: No such network: test_net"

        with patch("subprocess.run", return_value=mock_result):
            with caplog.at_level(logging.WARNING):
                result = remove_network("test_net")

        assert result == NetworkRemoveResult.NOT_FOUND
        # Should not have any warning logs
        warning_logs = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warning_logs) == 0

    def test_in_use_returns_in_use(self):
        """Active endpoints returns IN_USE for retry."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "network has active endpoints"

        with patch("subprocess.run", return_value=mock_result):
            result = remove_network("test_net")
            assert result == NetworkRemoveResult.IN_USE

    def test_timeout_returns_error(self):
        """Timeout returns ERROR."""
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 30)):
            result = remove_network("test_net", timeout=30)
            assert result == NetworkRemoveResult.ERROR


class TestRemoveNetworkWithRetry:
    """Tests for ComposeLabRuntime._remove_network_with_retry method."""

    @pytest.fixture
    def runtime(self, tmp_path):
        """Create a ComposeLabRuntime instance with a temp compose file."""
        from app.runtime.compose_runtime import ComposeLabRuntime
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3'\nservices:\n  test:\n    image: alpine\n")
        return ComposeLabRuntime(compose_file)

    def test_not_found_is_success(self, runtime):
        """NOT_FOUND is treated as success without warnings."""
        with patch("app.services.docker_net.remove_network") as mock_rm:
            mock_rm.return_value = NetworkRemoveResult.NOT_FOUND

            result = runtime._remove_network_with_retry("test_net", "octolab_test")

            assert result is True
            mock_rm.assert_called_once()

    def test_ok_is_success(self, runtime):
        """OK is treated as success."""
        with patch("app.services.docker_net.remove_network") as mock_rm:
            mock_rm.return_value = NetworkRemoveResult.OK

            result = runtime._remove_network_with_retry("test_net", "octolab_test")

            assert result is True

    def test_retry_in_use_empty_containers_then_success(self, runtime):
        """IN_USE with empty containers triggers retry, then succeeds."""
        with patch("app.services.docker_net.remove_network") as mock_rm, \
             patch("app.services.docker_net.inspect_network_containers") as mock_inspect, \
             patch("time.sleep") as mock_sleep, \
             patch.object(runtime, "_compose_rm_sfv") as mock_compose_rm:

            # First two calls: IN_USE, third call: OK
            mock_rm.side_effect = [
                NetworkRemoveResult.IN_USE,
                NetworkRemoveResult.IN_USE,
                NetworkRemoveResult.OK,
            ]
            # Empty containers (GC race scenario)
            mock_inspect.return_value = {}

            result = runtime._remove_network_with_retry("test_net", "octolab_test")

            assert result is True
            assert mock_rm.call_count == 3
            # Sleep called between retries (not after final success)
            assert mock_sleep.call_count == 2
            # compose rm should NOT be called (no containers)
            mock_compose_rm.assert_not_called()

    def test_retry_gives_up_logs_warning_once(self, runtime, caplog, monkeypatch):
        """After max retries, logs WARNING once and returns False."""
        import logging
        from app import config

        # Monkeypatch the settings on the actual config module
        monkeypatch.setattr(config.settings, "net_rm_max_retries", 3)
        monkeypatch.setattr(config.settings, "net_rm_backoff_ms", 100)
        monkeypatch.setattr(config.settings, "control_plane_containers", [])

        with patch("app.services.docker_net.remove_network") as mock_rm, \
             patch("app.services.docker_net.inspect_network_containers") as mock_inspect, \
             patch("time.sleep") as mock_sleep:

            # Always IN_USE with empty containers
            mock_rm.return_value = NetworkRemoveResult.IN_USE
            mock_inspect.return_value = {}

            with caplog.at_level(logging.WARNING):
                result = runtime._remove_network_with_retry("test_net", "octolab_test")

            assert result is False
            assert mock_rm.call_count == 3
            # Should log warning exactly once
            warning_logs = [r for r in caplog.records if r.levelno == logging.WARNING]
            assert len(warning_logs) == 1
            assert "gave up" in warning_logs[0].message.lower()

    def test_project_owned_triggers_compose_rm_sfv_then_retry(self, runtime):
        """Project-owned containers trigger compose rm -sfv before retry."""
        with patch("app.services.docker_net.remove_network") as mock_rm, \
             patch("app.services.docker_net.inspect_network_containers") as mock_inspect, \
             patch("time.sleep") as mock_sleep, \
             patch.object(runtime, "_compose_rm_sfv") as mock_compose_rm:

            project = "octolab_12345678-1234-5678-1234-567812345678"
            # First call: IN_USE, second call: OK
            mock_rm.side_effect = [
                NetworkRemoveResult.IN_USE,
                NetworkRemoveResult.OK,
            ]
            # Return project-owned container
            mock_inspect.return_value = {
                "abc123": {"Name": "octolab-12345678-1234-5678-1234-567812345678-octobox-1"}
            }

            result = runtime._remove_network_with_retry("test_net", project)

            assert result is True
            assert mock_rm.call_count == 2
            # compose rm -sfv should be called
            mock_compose_rm.assert_called_once_with(project)

    def test_allowlisted_triggers_disconnect_then_retry(self, runtime, monkeypatch):
        """Allowlisted containers trigger force-disconnect before retry."""
        from app import config

        # Monkeypatch the settings
        monkeypatch.setattr(config.settings, "net_rm_max_retries", 6)
        monkeypatch.setattr(config.settings, "net_rm_backoff_ms", 200)
        monkeypatch.setattr(config.settings, "control_plane_containers", ["octolab-guacd"])

        with patch("app.services.docker_net.remove_network") as mock_rm, \
             patch("app.services.docker_net.inspect_network_containers") as mock_inspect, \
             patch("app.services.docker_net.disconnect_container") as mock_disconnect, \
             patch("time.sleep") as mock_sleep:

            # First call: IN_USE, second call: OK
            mock_rm.side_effect = [
                NetworkRemoveResult.IN_USE,
                NetworkRemoveResult.OK,
            ]
            # Return allowlisted container
            mock_inspect.return_value = {
                "abc123": {"Name": "octolab-guacd"}
            }

            result = runtime._remove_network_with_retry("test_net", "octolab_test")

            assert result is True
            assert mock_rm.call_count == 2
            # disconnect should be called with force=True
            mock_disconnect.assert_called_once_with(
                "test_net", "octolab-guacd", force=True, timeout=30
            )

    def test_unknown_container_raises_blocked_error(self, runtime, monkeypatch):
        """Unknown containers raise NetworkCleanupBlockedError."""
        from app import config

        # Monkeypatch the settings
        monkeypatch.setattr(config.settings, "net_rm_max_retries", 6)
        monkeypatch.setattr(config.settings, "net_rm_backoff_ms", 200)
        monkeypatch.setattr(config.settings, "control_plane_containers", [])

        with patch("app.services.docker_net.remove_network") as mock_rm, \
             patch("app.services.docker_net.inspect_network_containers") as mock_inspect:

            mock_rm.return_value = NetworkRemoveResult.IN_USE
            # Return unknown container (not project-owned, not allowlisted)
            mock_inspect.return_value = {
                "abc123": {"Name": "some-other-container"}
            }

            with pytest.raises(NetworkCleanupBlockedError) as exc_info:
                runtime._remove_network_with_retry("test_net", "octolab_test")

            assert "some-other-container" in str(exc_info.value)
            assert "blocked" in str(exc_info.value).lower()


class TestIsProjectOwnedContainer:
    """Tests for _is_project_owned_container helper."""

    @pytest.fixture
    def runtime(self, tmp_path):
        """Create a ComposeLabRuntime instance."""
        from app.runtime.compose_runtime import ComposeLabRuntime
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3'\n")
        return ComposeLabRuntime(compose_file)

    def test_matches_compose_v2_naming(self, runtime):
        """Matches Compose v2 container naming (underscores -> hyphens)."""
        project = "octolab_12345678-1234-5678-1234-567812345678"
        container = "octolab-12345678-1234-5678-1234-567812345678-octobox-1"

        assert runtime._is_project_owned_container(container, project) is True

    def test_rejects_different_project(self, runtime):
        """Rejects containers from different projects."""
        project = "octolab_12345678-1234-5678-1234-567812345678"
        container = "octolab-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee-octobox-1"

        assert runtime._is_project_owned_container(container, project) is False

    def test_rejects_control_plane(self, runtime):
        """Rejects control-plane containers (no project prefix)."""
        project = "octolab_12345678-1234-5678-1234-567812345678"
        container = "octolab-guacd"

        assert runtime._is_project_owned_container(container, project) is False


class TestComposeRmSfv:
    """Tests for _compose_rm_sfv helper."""

    @pytest.fixture
    def runtime(self, tmp_path):
        """Create a ComposeLabRuntime instance."""
        from app.runtime.compose_runtime import ComposeLabRuntime
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3'\n")
        return ComposeLabRuntime(compose_file)

    def test_runs_correct_command(self, runtime):
        """Runs docker compose rm -sfv with correct arguments."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            runtime._compose_rm_sfv("octolab_test")

            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert "docker" in cmd
            assert "compose" in cmd
            assert "-p" in cmd
            assert "octolab_test" in cmd
            assert "rm" in cmd
            assert "-sfv" in cmd

    def test_uses_120s_timeout(self, runtime):
        """Uses 120s timeout as per mandatory timeout table."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            runtime._compose_rm_sfv("octolab_test")

            # Check timeout parameter
            assert mock_run.call_args[1]["timeout"] == 120

    def test_does_not_raise_on_failure(self, runtime):
        """Does not raise on compose rm failure (best-effort)."""
        import subprocess

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("cmd", 120)

            # Should not raise
            runtime._compose_rm_sfv("octolab_test")
