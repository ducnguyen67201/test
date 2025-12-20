"""Tests for Docker network management module (docker_net.py).

Tests cover:
- Network name generation
- Container IP lookup
- Network connectivity preflight checks

These tests use mocking for subprocess calls to avoid requiring Docker.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

# Mark all tests in this file as not requiring database
pytestmark = pytest.mark.no_db


class TestGetLabNetworkName:
    """Tests for get_lab_network_name function."""

    def test_network_name_format(self):
        """Network name follows expected format."""
        from app.services.docker_net import get_lab_network_name

        lab_id = UUID("12345678-1234-5678-1234-567812345678")
        result = get_lab_network_name(lab_id)

        assert result == "octolab_12345678-1234-5678-1234-567812345678_lab_net"

    def test_network_name_uses_full_uuid(self):
        """Network name includes full UUID (not truncated)."""
        from app.services.docker_net import get_lab_network_name

        lab_id = UUID("abcdef12-3456-7890-abcd-ef1234567890")
        result = get_lab_network_name(lab_id)

        assert "abcdef12-3456-7890-abcd-ef1234567890" in result


class TestGetContainerIPOnNetwork:
    """Tests for _get_container_ip_on_network function."""

    def test_returns_ip_on_success(self):
        """Returns IP address when docker inspect succeeds."""
        from app.services.docker_net import _get_container_ip_on_network

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "192.168.1.100\n"

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = _get_container_ip_on_network("test-container", "test-network")

            assert result == "192.168.1.100"
            # Verify shell=False is used
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert call_args.kwargs.get("shell") is False

    def test_returns_none_when_not_connected(self):
        """Returns None when container not connected to network."""
        from app.services.docker_net import _get_container_ip_on_network

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "\n"  # Empty IP

        with patch("subprocess.run", return_value=mock_result):
            result = _get_container_ip_on_network("test-container", "test-network")

            assert result is None

    def test_returns_none_on_failure(self):
        """Returns None when docker command fails."""
        from app.services.docker_net import _get_container_ip_on_network

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error: No such container"

        with patch("subprocess.run", return_value=mock_result):
            result = _get_container_ip_on_network("nonexistent", "test-network")

            assert result is None

    def test_returns_none_on_timeout(self):
        """Returns None when command times out."""
        from app.services.docker_net import _get_container_ip_on_network
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5)):
            result = _get_container_ip_on_network("test-container", "test-network")

            assert result is None


class TestNetCheckResult:
    """Tests for NetCheckResult dataclass."""

    def test_repr_shows_status(self):
        """Repr includes status and message."""
        from app.services.docker_net import NetCheckResult, NetCheckStatus

        result = NetCheckResult(
            ok=True,
            status=NetCheckStatus.OK,
            message="Connection successful",
            guacd_container="guacd",
            target_container="octobox-1",
            target_ip="192.168.1.100",
        )

        repr_str = repr(result)
        assert "ok=True" in repr_str
        assert "ok" in repr_str


class TestPreflightNetcheck:
    """Tests for preflight_netcheck function."""

    @pytest.mark.asyncio
    async def test_returns_not_connected_when_guacd_missing(self):
        """Returns GUACD_NOT_CONNECTED when guacd not on network."""
        from app.services.docker_net import preflight_netcheck, NetCheckStatus

        lab_id = UUID("12345678-1234-5678-1234-567812345678")

        # Mock _get_container_ip_on_network to return None for guacd
        with patch("app.services.docker_net._get_container_ip_on_network", return_value=None):
            result = await preflight_netcheck(lab_id)

            assert result.ok is False
            assert result.status == NetCheckStatus.GUACD_NOT_CONNECTED
            assert "not connected" in result.message.lower()

    @pytest.mark.asyncio
    async def test_returns_container_not_found_when_octobox_missing(self):
        """Returns CONTAINER_NOT_FOUND when octobox not on network."""
        from app.services.docker_net import preflight_netcheck, NetCheckStatus

        lab_id = UUID("12345678-1234-5678-1234-567812345678")

        def mock_get_ip(container, network):
            if "guacd" in container.lower():
                return "192.168.1.10"  # guacd connected
            return None  # octobox not found

        with patch("app.services.docker_net._get_container_ip_on_network", side_effect=mock_get_ip):
            result = await preflight_netcheck(lab_id)

            assert result.ok is False
            assert result.status == NetCheckStatus.CONTAINER_NOT_FOUND
            assert "not found" in result.message.lower()

    @pytest.mark.asyncio
    async def test_returns_ok_when_connectivity_succeeds(self):
        """Returns OK when nc connection test succeeds."""
        from app.services.docker_net import preflight_netcheck, NetCheckStatus

        lab_id = UUID("12345678-1234-5678-1234-567812345678")

        def mock_get_ip(container, network):
            if "guacd" in container.lower():
                return "192.168.1.10"
            return "192.168.1.20"  # octobox

        mock_nc_result = MagicMock()
        mock_nc_result.returncode = 0
        mock_nc_result.stdout = ""
        mock_nc_result.stderr = ""

        with patch("app.services.docker_net._get_container_ip_on_network", side_effect=mock_get_ip):
            with patch("subprocess.run", return_value=mock_nc_result) as mock_run:
                result = await preflight_netcheck(lab_id)

                assert result.ok is True
                assert result.status == NetCheckStatus.OK
                assert result.target_ip == "192.168.1.20"
                # Verify shell=False
                call_args = mock_run.call_args
                assert call_args.kwargs.get("shell") is False

    @pytest.mark.asyncio
    async def test_returns_vnc_unreachable_when_nc_fails(self):
        """Returns VNC_UNREACHABLE when nc connection fails."""
        from app.services.docker_net import preflight_netcheck, NetCheckStatus

        lab_id = UUID("12345678-1234-5678-1234-567812345678")

        def mock_get_ip(container, network):
            if "guacd" in container.lower():
                return "192.168.1.10"
            return "192.168.1.20"

        mock_nc_result = MagicMock()
        mock_nc_result.returncode = 1
        mock_nc_result.stdout = ""
        mock_nc_result.stderr = "Connection refused"

        with patch("app.services.docker_net._get_container_ip_on_network", side_effect=mock_get_ip):
            with patch("subprocess.run", return_value=mock_nc_result):
                result = await preflight_netcheck(lab_id)

                assert result.ok is False
                assert result.status == NetCheckStatus.VNC_UNREACHABLE
                assert "unreachable" in result.message.lower() or "refused" in result.message.lower()


class TestShellFalseSecurity:
    """Tests to verify shell=False is used in all subprocess calls."""

    def test_run_docker_cmd_uses_shell_false(self):
        """_run_docker_cmd uses shell=False."""
        from app.services.docker_net import _run_docker_cmd

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            _run_docker_cmd(["docker", "ps"])

            call_args = mock_run.call_args
            assert call_args.kwargs.get("shell") is False

    def test_get_container_ip_uses_shell_false(self):
        """_get_container_ip_on_network uses shell=False."""
        from app.services.docker_net import _get_container_ip_on_network

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="192.168.1.1")
            _get_container_ip_on_network("test", "network")

            call_args = mock_run.call_args
            assert call_args.kwargs.get("shell") is False

    @pytest.mark.asyncio
    async def test_preflight_netcheck_nc_uses_shell_false(self):
        """preflight_netcheck nc test uses shell=False."""
        from app.services.docker_net import preflight_netcheck

        lab_id = UUID("12345678-1234-5678-1234-567812345678")

        def mock_get_ip(container, network):
            return "192.168.1.10"

        nc_result = MagicMock(returncode=0, stdout="", stderr="")

        with patch("app.services.docker_net._get_container_ip_on_network", side_effect=mock_get_ip):
            with patch("subprocess.run", return_value=nc_result) as mock_run:
                await preflight_netcheck(lab_id)

                call_args = mock_run.call_args
                assert call_args.kwargs.get("shell") is False


# =============================================================================
# Network Cleanup Tests
# =============================================================================


class TestIsOctolabLabNetwork:
    """Tests for is_octolab_lab_network function (strict regex matching)."""

    def test_matches_valid_lab_net(self):
        """Matches valid per-lab lab_net network names."""
        from app.services.docker_net import is_octolab_lab_network

        # Valid UUIDs with lab_net suffix
        assert is_octolab_lab_network("octolab_12345678-1234-5678-1234-567812345678_lab_net")
        assert is_octolab_lab_network("octolab_abcdef12-3456-7890-abcd-ef1234567890_lab_net")
        assert is_octolab_lab_network("octolab_00000000-0000-0000-0000-000000000000_lab_net")

    def test_matches_valid_egress_net(self):
        """Matches valid per-lab egress_net network names."""
        from app.services.docker_net import is_octolab_lab_network

        assert is_octolab_lab_network("octolab_12345678-1234-5678-1234-567812345678_egress_net")
        assert is_octolab_lab_network("octolab_abcdef12-3456-7890-abcd-ef1234567890_egress_net")

    def test_rejects_infrastructure_networks(self):
        """CRITICAL: Rejects infrastructure networks like octolab_mvp_default."""
        from app.services.docker_net import is_octolab_lab_network

        # These are NOT per-lab networks - they're infrastructure
        assert not is_octolab_lab_network("octolab_mvp_default")
        assert not is_octolab_lab_network("octolab_default")
        assert not is_octolab_lab_network("octolab_shared_net")

    def test_rejects_partial_uuids(self):
        """Rejects networks with truncated or invalid UUIDs."""
        from app.services.docker_net import is_octolab_lab_network

        # Truncated UUID
        assert not is_octolab_lab_network("octolab_12345678_lab_net")
        # Missing segment
        assert not is_octolab_lab_network("octolab_12345678-1234-5678-1234_lab_net")
        # Invalid characters
        assert not is_octolab_lab_network("octolab_gggggggg-1234-5678-1234-567812345678_lab_net")

    def test_rejects_wrong_suffix(self):
        """Rejects networks with wrong suffix even with valid UUID."""
        from app.services.docker_net import is_octolab_lab_network

        # Wrong suffixes
        assert not is_octolab_lab_network("octolab_12345678-1234-5678-1234-567812345678_default")
        assert not is_octolab_lab_network("octolab_12345678-1234-5678-1234-567812345678_net")
        assert not is_octolab_lab_network("octolab_12345678-1234-5678-1234-567812345678")

    def test_rejects_other_prefixes(self):
        """Rejects networks not starting with octolab_."""
        from app.services.docker_net import is_octolab_lab_network

        assert not is_octolab_lab_network("12345678-1234-5678-1234-567812345678_lab_net")
        assert not is_octolab_lab_network("docker_12345678-1234-5678-1234-567812345678_lab_net")


class TestParseContainersJson:
    """Tests for parse_containers_json function (robust empty handling)."""

    def test_parses_valid_json(self):
        """Parses valid JSON container info."""
        from app.services.docker_net import parse_containers_json

        result = parse_containers_json('{"abc123": {"Name": "container1"}}')
        assert result == {"abc123": {"Name": "container1"}}

    def test_handles_empty_string(self):
        """Handles empty string as empty dict."""
        from app.services.docker_net import parse_containers_json

        assert parse_containers_json("") == {}

    def test_handles_null_string(self):
        """Handles 'null' string as empty dict."""
        from app.services.docker_net import parse_containers_json

        assert parse_containers_json("null") == {}

    def test_handles_no_value_string(self):
        """Handles '<no value>' string as empty dict."""
        from app.services.docker_net import parse_containers_json

        assert parse_containers_json("<no value>") == {}

    def test_handles_map_empty_string(self):
        """Handles 'map[]' (Go template empty map) as empty dict."""
        from app.services.docker_net import parse_containers_json

        assert parse_containers_json("map[]") == {}

    def test_handles_empty_json_object(self):
        """Handles '{}' as empty dict."""
        from app.services.docker_net import parse_containers_json

        assert parse_containers_json("{}") == {}

    def test_handles_nil_string(self):
        """Handles 'nil' string as empty dict."""
        from app.services.docker_net import parse_containers_json

        assert parse_containers_json("nil") == {}

    def test_handles_whitespace(self):
        """Handles whitespace around values."""
        from app.services.docker_net import parse_containers_json

        assert parse_containers_json("  null  ") == {}
        assert parse_containers_json("\n{}\n") == {}

    def test_handles_malformed_json(self):
        """Handles malformed JSON gracefully as empty dict."""
        from app.services.docker_net import parse_containers_json

        assert parse_containers_json("{invalid json}") == {}
        assert parse_containers_json("not json at all") == {}

    def test_handles_non_dict_json(self):
        """Handles valid JSON that's not a dict as empty dict."""
        from app.services.docker_net import parse_containers_json

        assert parse_containers_json("[]") == {}
        assert parse_containers_json('"string"') == {}
        assert parse_containers_json("123") == {}


class TestIsProjectOwnedContainer:
    """Tests for is_project_owned_container function."""

    def test_matches_compose_v2_naming(self):
        """Matches Compose v2 container naming (hyphens)."""
        from app.services.docker_net import is_project_owned_container

        # Compose v2: project_name -> project-name in containers
        assert is_project_owned_container(
            "octolab-12345678-1234-5678-1234-567812345678-octobox-1",
            "octolab_12345678-1234-5678-1234-567812345678"
        )

    def test_rejects_other_containers(self):
        """Rejects containers not belonging to project."""
        from app.services.docker_net import is_project_owned_container

        # Different project
        assert not is_project_owned_container(
            "octolab-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee-octobox-1",
            "octolab_12345678-1234-5678-1234-567812345678"
        )
        # Control-plane container (not project-owned)
        assert not is_project_owned_container(
            "octolab-guacd",
            "octolab_12345678-1234-5678-1234-567812345678"
        )

    def test_handles_underscore_to_hyphen_conversion(self):
        """Verifies underscore->hyphen conversion for compose v2."""
        from app.services.docker_net import is_project_owned_container

        # Project with underscores -> container with hyphens
        assert is_project_owned_container(
            "my-project-service-1",
            "my_project"
        )


class TestListOctolabNetworks:
    """Tests for list_octolab_networks function."""

    def test_returns_empty_list_on_no_networks(self):
        """Returns empty list when no networks exist."""
        from app.services.docker_net import list_octolab_networks

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            result = list_octolab_networks()

            assert result == []

    def test_parses_network_json_output(self):
        """Correctly parses JSON output from docker network ls."""
        from app.services.docker_net import list_octolab_networks

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"Name":"octolab_abc_lab_net","Driver":"bridge","Scope":"local"}\n{"Name":"octolab_def_lab_net","Driver":"bridge","Scope":"local"}\n'

        with patch("subprocess.run", return_value=mock_result):
            result = list_octolab_networks()

            assert len(result) == 2
            assert result[0].name == "octolab_abc_lab_net"
            assert result[0].driver == "bridge"
            assert result[1].name == "octolab_def_lab_net"

    def test_returns_empty_on_command_failure(self):
        """Returns empty list when docker command fails."""
        from app.services.docker_net import list_octolab_networks

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Error"

        with patch("subprocess.run", return_value=mock_result):
            result = list_octolab_networks()

            assert result == []

    def test_uses_shell_false(self):
        """Verifies shell=False is used."""
        from app.services.docker_net import list_octolab_networks

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            list_octolab_networks()

            call_args = mock_run.call_args
            assert call_args.kwargs.get("shell") is False


class TestGetNetworkContainers:
    """Tests for get_network_containers function."""

    def test_returns_container_names(self):
        """Returns list of container names attached to network."""
        from app.services.docker_net import get_network_containers

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "container1 container2 container3 "

        with patch("subprocess.run", return_value=mock_result):
            result = get_network_containers("test_network")

            assert result == ["container1", "container2", "container3"]

    def test_returns_empty_on_no_containers(self):
        """Returns empty list when no containers attached."""
        from app.services.docker_net import get_network_containers

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = " "

        with patch("subprocess.run", return_value=mock_result):
            result = get_network_containers("test_network")

            assert result == []

    def test_returns_empty_on_network_not_found(self):
        """Returns empty list when network doesn't exist."""
        from app.services.docker_net import get_network_containers

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "No such network"

        with patch("subprocess.run", return_value=mock_result):
            result = get_network_containers("nonexistent")

            assert result == []


class TestPreflightCleanupStaleLabNetworks:
    """Tests for preflight_cleanup_stale_lab_networks function (new strict scoping)."""

    def test_ignores_non_lab_networks(self):
        """CRITICAL: Ignores infrastructure networks like octolab_mvp_default."""
        from app.services.docker_net import preflight_cleanup_stale_lab_networks, NetworkInfo

        def mock_run(cmd, **kwargs):
            result = MagicMock()
            if "network" in cmd and "ls" in cmd:
                result.returncode = 0
                # Infrastructure network - should be IGNORED
                result.stdout = '{"Name":"octolab_mvp_default","Driver":"bridge","Scope":"local"}\n'
            elif "network" in cmd and "inspect" in cmd:
                result.returncode = 0
                result.stdout = "{}"  # Empty containers
            else:
                result.returncode = 0
                result.stdout = ""
            return result

        with patch("subprocess.run", side_effect=mock_run):
            result = preflight_cleanup_stale_lab_networks()

            # Should NOT remove infrastructure networks
            assert result.removed_count == 0
            assert result.blocked_networks == []

    def test_removes_empty_lab_networks(self):
        """Removes per-lab networks with no containers."""
        from app.services.docker_net import preflight_cleanup_stale_lab_networks

        def mock_run(cmd, **kwargs):
            result = MagicMock()
            cmd_str = " ".join(cmd)
            if "network" in cmd and "ls" in cmd:
                result.returncode = 0
                # Valid per-lab network with full UUID
                result.stdout = '{"Name":"octolab_12345678-1234-5678-1234-567812345678_lab_net","Driver":"bridge","Scope":"local"}\n'
            elif "network" in cmd and "inspect" in cmd:
                result.returncode = 0
                result.stdout = "{}"  # Empty containers (JSON)
            elif "network" in cmd and "rm" in cmd:
                result.returncode = 0
                result.stdout = ""
            else:
                result.returncode = 0
                result.stdout = ""
            return result

        with patch("subprocess.run", side_effect=mock_run):
            result = preflight_cleanup_stale_lab_networks()

            assert result.removed_count == 1

    def test_skips_networks_with_containers(self):
        """Silently skips networks that have containers attached (active labs)."""
        from app.services.docker_net import preflight_cleanup_stale_lab_networks

        def mock_run(cmd, **kwargs):
            result = MagicMock()
            cmd_str = " ".join(cmd)
            if "network" in cmd and "ls" in cmd:
                result.returncode = 0
                result.stdout = '{"Name":"octolab_12345678-1234-5678-1234-567812345678_lab_net","Driver":"bridge","Scope":"local"}\n'
            elif "network" in cmd and "inspect" in cmd:
                result.returncode = 0
                # Has containers - should be skipped
                result.stdout = '{"abc123": {"Name": "octolab-12345678-1234-5678-1234-567812345678-octobox-1"}}'
            else:
                result.returncode = 0
                result.stdout = ""
            return result

        with patch("subprocess.run", side_effect=mock_run):
            result = preflight_cleanup_stale_lab_networks()

            # Should NOT remove networks with containers
            assert result.removed_count == 0
            # Should NOT report as blocked (preflight doesn't use blocked_networks)
            assert result.blocked_networks == []

    def test_handles_race_condition_silently(self):
        """Handles race condition when network becomes in-use between check and remove."""
        from app.services.docker_net import preflight_cleanup_stale_lab_networks

        def mock_run(cmd, **kwargs):
            result = MagicMock()
            cmd_str = " ".join(cmd)
            if "network" in cmd and "ls" in cmd:
                result.returncode = 0
                result.stdout = '{"Name":"octolab_12345678-1234-5678-1234-567812345678_lab_net","Driver":"bridge","Scope":"local"}\n'
            elif "network" in cmd and "inspect" in cmd:
                result.returncode = 0
                result.stdout = "{}"  # Empty on check
            elif "network" in cmd and "rm" in cmd:
                # Race: became in-use between check and remove
                result.returncode = 1
                result.stderr = "network has active endpoints"
            else:
                result.returncode = 0
                result.stdout = ""
            return result

        with patch("subprocess.run", side_effect=mock_run):
            # Should NOT raise - silently handle race condition
            result = preflight_cleanup_stale_lab_networks()

            # Not removed due to race, but no error
            assert result.removed_count == 0
            assert result.errors == []

    def test_dry_run_does_not_modify(self):
        """Dry run mode doesn't actually remove networks."""
        from app.services.docker_net import preflight_cleanup_stale_lab_networks

        run_calls = []

        def mock_run(cmd, **kwargs):
            run_calls.append(cmd)
            result = MagicMock()
            cmd_str = " ".join(cmd)
            if "network" in cmd and "ls" in cmd:
                result.returncode = 0
                result.stdout = '{"Name":"octolab_12345678-1234-5678-1234-567812345678_lab_net","Driver":"bridge","Scope":"local"}\n'
            elif "network" in cmd and "inspect" in cmd:
                result.returncode = 0
                result.stdout = "{}"  # Empty
            else:
                result.returncode = 0
                result.stdout = ""
            return result

        with patch("subprocess.run", side_effect=mock_run):
            result = preflight_cleanup_stale_lab_networks(dry_run=True)

            # Should report what would be done
            assert result.removed_count == 1
            # But rm should NOT have been called
            rm_calls = [c for c in run_calls if "rm" in c]
            assert len(rm_calls) == 0

    def test_does_not_call_global_prune(self):
        """CRITICAL: Preflight should NOT call global docker network prune."""
        from app.services.docker_net import preflight_cleanup_stale_lab_networks

        run_calls = []

        def mock_run(cmd, **kwargs):
            run_calls.append(cmd)
            result = MagicMock()
            if "network" in cmd and "ls" in cmd:
                result.returncode = 0
                result.stdout = ""  # No networks
            else:
                result.returncode = 0
                result.stdout = ""
            return result

        with patch("subprocess.run", side_effect=mock_run):
            preflight_cleanup_stale_lab_networks()

            # Verify no prune command was called
            prune_calls = [c for c in run_calls if "prune" in c]
            assert len(prune_calls) == 0, "Preflight should NOT call global prune"


class TestNetworkCleanupResult:
    """Tests for NetworkCleanupResult dataclass."""

    def test_default_values(self):
        """Default values are correct."""
        from app.services.docker_net import NetworkCleanupResult

        result = NetworkCleanupResult()

        assert result.pruned_count == 0
        assert result.disconnected_count == 0
        assert result.removed_count == 0
        assert result.blocked_networks == []
        assert result.errors == []


class TestPreflightNetworkCleanup:
    """Tests for async preflight_network_cleanup function."""

    @pytest.mark.asyncio
    async def test_calls_preflight_cleanup(self):
        """Calls preflight_cleanup_stale_lab_networks."""
        from app.services.docker_net import preflight_network_cleanup, NetworkCleanupResult

        mock_result = NetworkCleanupResult(removed_count=1)

        with patch("app.services.docker_net.preflight_cleanup_stale_lab_networks", return_value=mock_result) as mock_cleanup:
            result = await preflight_network_cleanup()

            assert result.removed_count == 1
            mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_never_raises_exception(self):
        """Preflight cleanup NEVER raises - returns empty result on error."""
        from app.services.docker_net import preflight_network_cleanup, NetworkCleanupResult

        # Even if underlying function raises, preflight_network_cleanup should catch
        with patch("app.services.docker_net.preflight_cleanup_stale_lab_networks", side_effect=Exception("Docker error")):
            # Should NOT raise - best-effort only
            result = await preflight_network_cleanup()

            # Returns empty result on error
            assert result.removed_count == 0
            assert result.blocked_networks == []

    @pytest.mark.asyncio
    async def test_returns_cleanup_result(self):
        """Returns the cleanup result from preflight_cleanup_stale_lab_networks."""
        from app.services.docker_net import preflight_network_cleanup, NetworkCleanupResult

        mock_result = NetworkCleanupResult(removed_count=3)

        with patch("app.services.docker_net.preflight_cleanup_stale_lab_networks", return_value=mock_result):
            result = await preflight_network_cleanup()
            assert result.removed_count == 3


class TestTargetedNetworkCleanup:
    """Tests for targeted_network_cleanup function (destroy/failure cleanup)."""

    def test_removes_empty_network(self):
        """Removes network with no containers."""
        from app.services.docker_net import targeted_network_cleanup

        def mock_run(cmd, **kwargs):
            result = MagicMock()
            if "network" in cmd and "rm" in cmd:
                result.returncode = 0
                result.stdout = ""
            else:
                result.returncode = 0
                result.stdout = ""
            return result

        with patch("subprocess.run", side_effect=mock_run):
            removed = targeted_network_cleanup(
                "octolab_12345678-1234-5678-1234-567812345678_lab_net",
                "octolab_12345678-1234-5678-1234-567812345678",
                "/path/to/compose.yml",
            )

            assert removed is True

    def test_removes_project_owned_containers_first(self):
        """Runs compose rm for project-owned containers before removing network."""
        from app.services.docker_net import targeted_network_cleanup

        compose_rm_called = []

        def mock_run(cmd, **kwargs):
            result = MagicMock()
            cmd_list = list(cmd)

            if "network" in cmd_list and "rm" in cmd_list:
                # First call fails (has containers), subsequent calls succeed
                if len(compose_rm_called) == 0:
                    result.returncode = 1
                    result.stderr = "has active endpoints"
                else:
                    result.returncode = 0
                    result.stdout = ""
            elif "network" in cmd_list and "inspect" in cmd_list:
                result.returncode = 0
                # Return project-owned container
                result.stdout = '{"abc123": {"Name": "octolab-12345678-1234-5678-1234-567812345678-octobox-1"}}'
            elif "compose" in cmd_list and "rm" in cmd_list:
                compose_rm_called.append(cmd_list)
                result.returncode = 0
                result.stdout = ""
            else:
                result.returncode = 0
                result.stdout = ""
            return result

        with patch("subprocess.run", side_effect=mock_run):
            removed = targeted_network_cleanup(
                "octolab_12345678-1234-5678-1234-567812345678_lab_net",
                "octolab_12345678-1234-5678-1234-567812345678",
                "/path/to/compose.yml",
            )

            # Compose rm should have been called
            assert len(compose_rm_called) == 1

    def test_force_disconnects_allowlisted_containers(self):
        """Force-disconnects allowlisted containers (like guacd)."""
        from app.services.docker_net import targeted_network_cleanup

        disconnect_calls = []

        def mock_run(cmd, **kwargs):
            result = MagicMock()
            cmd_list = list(cmd)

            if "network" in cmd_list and "rm" in cmd_list:
                # First call fails, then succeeds after disconnect
                if len(disconnect_calls) == 0:
                    result.returncode = 1
                    result.stderr = "has active endpoints"
                else:
                    result.returncode = 0
                    result.stdout = ""
            elif "network" in cmd_list and "inspect" in cmd_list:
                result.returncode = 0
                # Return allowlisted container
                result.stdout = '{"abc123": {"Name": "octolab-guacd"}}'
            elif "network" in cmd_list and "disconnect" in cmd_list:
                disconnect_calls.append(cmd_list)
                result.returncode = 0
                result.stdout = ""
            else:
                result.returncode = 0
                result.stdout = ""
            return result

        with patch("subprocess.run", side_effect=mock_run):
            removed = targeted_network_cleanup(
                "octolab_12345678-1234-5678-1234-567812345678_lab_net",
                "octolab_12345678-1234-5678-1234-567812345678",
                "/path/to/compose.yml",
                allowlist=["octolab-guacd"],
            )

            # Disconnect should have been called
            assert len(disconnect_calls) == 1

    def test_raises_for_unknown_containers(self):
        """Raises NetworkCleanupBlockedError for unknown blocking containers."""
        from app.services.docker_net import targeted_network_cleanup
        from app.runtime.exceptions import NetworkCleanupBlockedError

        def mock_run(cmd, **kwargs):
            result = MagicMock()
            cmd_list = list(cmd)

            if "network" in cmd_list and "rm" in cmd_list:
                result.returncode = 1
                result.stderr = "has active endpoints"
            elif "network" in cmd_list and "inspect" in cmd_list:
                result.returncode = 0
                # Return unknown container (not project-owned, not allowlisted)
                result.stdout = '{"abc123": {"Name": "some-other-container"}}'
            else:
                result.returncode = 0
                result.stdout = ""
            return result

        with patch("subprocess.run", side_effect=mock_run):
            with pytest.raises(NetworkCleanupBlockedError) as exc_info:
                targeted_network_cleanup(
                    "octolab_12345678-1234-5678-1234-567812345678_lab_net",
                    "octolab_12345678-1234-5678-1234-567812345678",
                    "/path/to/compose.yml",
                    allowlist=[],
                )

            assert "some-other-container" in str(exc_info.value)

    def test_project_owned_containers_do_not_block(self):
        """Project-owned containers are handled, not treated as blockers."""
        from app.services.docker_net import targeted_network_cleanup

        call_sequence = []

        def mock_run(cmd, **kwargs):
            result = MagicMock()
            cmd_list = list(cmd)
            call_sequence.append(cmd_list)

            if "network" in cmd_list and "rm" in cmd_list:
                # First rm fails, subsequent succeed (after compose rm)
                rm_count = sum(1 for c in call_sequence if "rm" in c and "network" in c)
                if rm_count <= 1:
                    result.returncode = 1
                    result.stderr = "has active endpoints"
                else:
                    result.returncode = 0
                    result.stdout = ""
            elif "network" in cmd_list and "inspect" in cmd_list:
                inspect_count = sum(1 for c in call_sequence if "inspect" in c)
                if inspect_count <= 1:
                    # First inspect: project-owned container
                    result.returncode = 0
                    result.stdout = '{"abc123": {"Name": "octolab-12345678-1234-5678-1234-567812345678-octobox-1"}}'
                else:
                    # After compose rm: empty
                    result.returncode = 0
                    result.stdout = "{}"
            elif "compose" in cmd_list and "rm" in cmd_list:
                result.returncode = 0
                result.stdout = ""
            else:
                result.returncode = 0
                result.stdout = ""
            return result

        with patch("subprocess.run", side_effect=mock_run):
            # Should NOT raise - project-owned containers are handled via compose rm
            removed = targeted_network_cleanup(
                "octolab_12345678-1234-5678-1234-567812345678_lab_net",
                "octolab_12345678-1234-5678-1234-567812345678",
                "/path/to/compose.yml",
                allowlist=[],  # Empty allowlist
            )

            # Should succeed after compose rm handles the container
            assert removed is True
