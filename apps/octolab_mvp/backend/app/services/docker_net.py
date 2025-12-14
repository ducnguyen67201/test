"""Docker network management for connecting guacd to lab networks.

SECURITY:
- All subprocess calls use shell=False
- Network names are derived from server-owned lab UUIDs only
- Operations are idempotent and time-bounded
- Preflight cleanup ONLY touches per-lab networks (strict UUID regex)
- Never touches infrastructure networks (octolab_mvp_default, etc.)
- Force-disconnect only allowed for allowlisted control-plane containers
"""

import asyncio
import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from uuid import UUID

from app.config import settings

logger = logging.getLogger(__name__)

# Prefix for OctoLab networks (all lab networks use this)
OCTOLAB_NETWORK_PREFIX = "octolab_"

# VNC port inside OctoBox container (DISPLAY :0 = port 5900)
# This is the SINGLE SOURCE OF TRUTH for VNC port.
# Never use 5901 - that would be DISPLAY :1 which we don't use.
VNC_INTERNAL_PORT = 5900

# Strict regex for per-lab networks only
# Matches: octolab_<uuid>_lab_net OR octolab_<uuid>_egress_net
# Does NOT match: octolab_mvp_default, octolab_anything_else
LAB_NETWORK_PATTERN = re.compile(
    r"^octolab_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_(lab_net|egress_net)$"
)

# Strict regex for lab compose projects
# Matches: octolab_<uuid> (exactly)
# Does NOT match: octolab_mvp, octolab-hackvm, guacamole, etc.
LAB_PROJECT_PATTERN = re.compile(
    r"^octolab_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def is_octolab_lab_network(name: str) -> bool:
    """Check if network name is a per-lab network (not infrastructure).

    Returns True only for networks matching the strict pattern:
    octolab_<uuid>_lab_net or octolab_<uuid>_egress_net

    Returns False for infrastructure networks like octolab_mvp_default.
    """
    return bool(LAB_NETWORK_PATTERN.match(name))


def is_lab_project(project: str) -> bool:
    """Check if a compose project name is a lab project (not infrastructure).

    A lab project is exactly: octolab_<uuid>

    Returns False for infrastructure projects like:
    - octolab_mvp (backend/db)
    - octolab-hackvm (dev hackvm)
    - guacamole (guac stack)

    Args:
        project: Compose project name (from com.docker.compose.project label)

    Returns:
        True if this is a lab project (octolab_<uuid> pattern)
    """
    return bool(LAB_PROJECT_PATTERN.match((project or "").strip().lower()))


class NetCheckStatus(Enum):
    """Status of network connectivity check."""

    OK = "ok"
    GUACD_NOT_CONNECTED = "guacd_not_connected"
    VNC_UNREACHABLE = "vnc_unreachable"
    CONTAINER_NOT_FOUND = "container_not_found"
    TIMEOUT = "timeout"
    ERROR = "error"


class NetworkRemoveResult(Enum):
    """Result of docker network rm operation.

    Used to classify the outcome of a network removal attempt.
    NOT_FOUND is treated as success (idempotent cleanup).
    """

    OK = "ok"  # Network was removed
    NOT_FOUND = "not_found"  # Network doesn't exist (treat as success)
    IN_USE = "in_use"  # Has active endpoints / resource still in use
    ERROR = "error"  # Other error


# Error patterns for classifying network removal failures
NETWORK_NOT_FOUND_PATTERNS = ["not found", "no such network"]
NETWORK_IN_USE_PATTERNS = [
    "has active endpoints",
    "resource is still in use",
    "network is in use",
]


def classify_network_error(stderr: str) -> NetworkRemoveResult:
    """Classify a docker network rm error message.

    Args:
        stderr: Error message from docker network rm

    Returns:
        NetworkRemoveResult indicating the type of failure
    """
    stderr_lower = (stderr or "").lower()

    if any(p in stderr_lower for p in NETWORK_NOT_FOUND_PATTERNS):
        return NetworkRemoveResult.NOT_FOUND

    if any(p in stderr_lower for p in NETWORK_IN_USE_PATTERNS):
        return NetworkRemoveResult.IN_USE

    return NetworkRemoveResult.ERROR


@dataclass
class NetCheckResult:
    """Result of network connectivity preflight check."""

    ok: bool
    status: NetCheckStatus
    message: str
    guacd_container: str
    target_container: str | None = None
    target_ip: str | None = None

    def __repr__(self) -> str:
        return f"NetCheckResult(ok={self.ok}, status={self.status.value}, message={self.message!r})"

# Timeout for docker network operations
NETWORK_OP_TIMEOUT = 10.0


class DockerNetError(Exception):
    """Error during Docker network operation."""

    pass


def get_lab_network_name(lab_id: UUID) -> str:
    """Get the Docker network name for a lab.

    Network naming convention matches compose runtime:
    octolab_<lab_id>_lab_net

    Args:
        lab_id: Lab UUID (server-owned, never from client)

    Returns:
        Docker network name
    """
    # Use the same naming as compose_runtime.py
    return f"octolab_{lab_id}_lab_net"


async def connect_container_to_network(
    container_name: str,
    network_name: str,
    alias: str | None = None,
) -> bool:
    """Connect a container to a Docker network.

    Idempotent: If already connected, returns True without error.

    Args:
        container_name: Container name or ID
        network_name: Network name to connect to
        alias: Optional network alias for the container

    Returns:
        True if connected (or already was), False on error

    Security:
        - Uses shell=False
        - All args are validated/derived server-side
    """
    cmd = ["docker", "network", "connect"]
    if alias:
        cmd.extend(["--alias", alias])
    cmd.extend([network_name, container_name])

    try:
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _run_docker_cmd, cmd),
            timeout=NETWORK_OP_TIMEOUT,
        )

        if result.returncode == 0:
            logger.info(f"Connected {container_name} to network {network_name}")
            return True

        # Check for "already connected" error (idempotent)
        if "already" in result.stderr.lower() or "endpoint with name" in result.stderr.lower():
            logger.debug(f"Container {container_name} already connected to {network_name}")
            return True

        logger.warning(
            f"Failed to connect {container_name} to {network_name}: {result.stderr.strip()}"
        )
        return False

    except asyncio.TimeoutError:
        logger.error(
            f"Timeout connecting {container_name} to network {network_name}"
        )
        return False
    except Exception as e:
        logger.error(
            f"Error connecting {container_name} to network {network_name}: {type(e).__name__}"
        )
        return False


async def disconnect_container_from_network(
    container_name: str,
    network_name: str,
    force: bool = True,
) -> bool:
    """Disconnect a container from a Docker network.

    Idempotent: If not connected, returns True without error.

    Args:
        container_name: Container name or ID
        network_name: Network name to disconnect from
        force: Force disconnect even if container is running

    Returns:
        True if disconnected (or already was), False on error
    """
    cmd = ["docker", "network", "disconnect"]
    if force:
        cmd.append("--force")
    cmd.extend([network_name, container_name])

    try:
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _run_docker_cmd, cmd),
            timeout=NETWORK_OP_TIMEOUT,
        )

        if result.returncode == 0:
            logger.info(f"Disconnected {container_name} from network {network_name}")
            return True

        # Check for "not connected" error (idempotent)
        stderr_lower = result.stderr.lower()
        if "is not connected" in stderr_lower or "no such network" in stderr_lower:
            logger.debug(
                f"Container {container_name} not connected to {network_name} (idempotent)"
            )
            return True

        logger.warning(
            f"Failed to disconnect {container_name} from {network_name}: {result.stderr.strip()}"
        )
        return False

    except asyncio.TimeoutError:
        logger.error(
            f"Timeout disconnecting {container_name} from network {network_name}"
        )
        return False
    except Exception as e:
        logger.error(
            f"Error disconnecting {container_name} from network {network_name}: {type(e).__name__}"
        )
        return False


async def connect_guacd_to_lab(lab_id: UUID) -> bool:
    """Connect the guacd container to a lab's network.

    This allows guacd to reach the OctoBox VNC server via Docker DNS.

    Args:
        lab_id: Lab UUID

    Returns:
        True if connected successfully
    """
    network_name = get_lab_network_name(lab_id)
    container_name = settings.guacd_container_name

    return await connect_container_to_network(
        container_name=container_name,
        network_name=network_name,
        alias="guacd",  # Optional alias for easier debugging
    )


async def disconnect_guacd_from_lab(lab_id: UUID) -> bool:
    """Disconnect the guacd container from a lab's network.

    Called during lab teardown to clean up network connections.

    Args:
        lab_id: Lab UUID

    Returns:
        True if disconnected successfully
    """
    network_name = get_lab_network_name(lab_id)
    container_name = settings.guacd_container_name

    return await disconnect_container_from_network(
        container_name=container_name,
        network_name=network_name,
    )


def _run_docker_cmd(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run a docker command synchronously.

    SECURITY: shell=False is always used.

    Args:
        cmd: Command as list of strings

    Returns:
        CompletedProcess result
    """
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=NETWORK_OP_TIMEOUT,
        shell=False,  # SECURITY: Never use shell=True
    )


def _get_container_ip_on_network(
    container_name: str,
    network_name: str,
) -> str | None:
    """Get a container's IP address on a specific network.

    SECURITY: shell=False is always used.

    Args:
        container_name: Container name or ID
        network_name: Docker network name

    Returns:
        IP address string or None if not connected
    """
    # Use docker inspect with Go template to extract IP
    cmd = [
        "docker",
        "inspect",
        "--format",
        f'{{{{(index .NetworkSettings.Networks "{network_name}").IPAddress}}}}',
        container_name,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5.0,
            shell=False,  # SECURITY: Never use shell=True
        )

        if result.returncode == 0:
            ip = result.stdout.strip()
            # Empty string means not connected to this network
            return ip if ip else None
        return None

    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


async def preflight_netcheck(
    lab_id: UUID,
    vnc_port: int = 5900,
    timeout_seconds: float = 5.0,
) -> NetCheckResult:
    """Preflight network connectivity check for Guacamole provisioning.

    Verifies that guacd can reach the lab's OctoBox container on the VNC port.
    This should be called AFTER connecting guacd to the lab network.

    SECURITY: All subprocess calls use shell=False.

    Args:
        lab_id: Lab UUID
        vnc_port: VNC port to test (default 5900 = DISPLAY :0)
        timeout_seconds: Timeout for connectivity test

    Returns:
        NetCheckResult with status and diagnostic message
    """
    guacd_container = settings.guacd_container_name
    network_name = get_lab_network_name(lab_id)
    target_container = f"octolab_{lab_id}-octobox-1"

    # Step 1: Check if guacd is connected to the lab network
    guacd_ip = await asyncio.to_thread(
        _get_container_ip_on_network, guacd_container, network_name
    )

    if not guacd_ip:
        return NetCheckResult(
            ok=False,
            status=NetCheckStatus.GUACD_NOT_CONNECTED,
            message=f"guacd ({guacd_container}) is not connected to network {network_name}",
            guacd_container=guacd_container,
            target_container=target_container,
        )

    # Step 2: Get the octobox container's IP on the lab network
    target_ip = await asyncio.to_thread(
        _get_container_ip_on_network, target_container, network_name
    )

    if not target_ip:
        return NetCheckResult(
            ok=False,
            status=NetCheckStatus.CONTAINER_NOT_FOUND,
            message=f"OctoBox ({target_container}) not found on network {network_name}",
            guacd_container=guacd_container,
            target_container=target_container,
        )

    # Step 3: Test TCP connectivity from guacd to octobox:<vnc_port>
    # Use docker exec with nc (netcat) for connectivity test
    # SECURITY: shell=False, all args are validated/server-derived
    cmd = [
        "docker",
        "exec",
        guacd_container,
        "nc",
        "-z",
        "-w",
        "2",  # 2 second timeout
        target_ip,
        str(vnc_port),
    ]

    def _test_connectivity() -> tuple[bool, str]:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                shell=False,  # SECURITY: Never use shell=True
            )
            if result.returncode == 0:
                return (True, "Connection successful")
            return (False, f"nc exit code {result.returncode}: {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            return (False, "Connection timeout")
        except Exception as e:
            return (False, f"Error: {type(e).__name__}")

    success, error_msg = await asyncio.to_thread(_test_connectivity)

    if success:
        return NetCheckResult(
            ok=True,
            status=NetCheckStatus.OK,
            message=f"guacd can reach {target_container} at {target_ip}:{vnc_port}",
            guacd_container=guacd_container,
            target_container=target_container,
            target_ip=target_ip,
        )

    return NetCheckResult(
        ok=False,
        status=NetCheckStatus.VNC_UNREACHABLE,
        message=f"guacd cannot reach VNC at {target_ip}:{vnc_port}: {error_msg}",
        guacd_container=guacd_container,
        target_container=target_container,
        target_ip=target_ip,
    )


# =============================================================================
# Network Cleanup Functions (Preflight Pool Exhaustion Recovery)
# =============================================================================


@dataclass
class NetworkInfo:
    """Information about a Docker network."""

    name: str
    driver: str
    scope: str
    containers: list[str] = field(default_factory=list)


@dataclass
class NetworkCleanupResult:
    """Result of network cleanup operation."""

    pruned_count: int = 0
    disconnected_count: int = 0
    removed_count: int = 0
    blocked_networks: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _get_network_timeout() -> float:
    """Get configured timeout for network operations."""
    return float(settings.docker_network_timeout_seconds)


def parse_containers_json(stdout: str) -> dict:
    """Parse docker network inspect Containers field output robustly.

    Docker may return various representations for "empty":
    - "" (empty string)
    - "null"
    - "<no value>"
    - "map[]"
    - "{}"
    - "nil"

    All are treated as empty dict. Malformed JSON is also treated as empty.

    Args:
        stdout: Raw stdout from docker network inspect

    Returns:
        dict: Container info dict, or {} if empty/invalid
    """
    stdout = stdout.strip()

    # Handle known empty representations
    if stdout in ("", "null", "<no value>", "map[]", "{}", "nil"):
        return {}

    try:
        obj = json.loads(stdout)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        # Defensive: treat parse failure as empty
        return {}


def inspect_network_containers(network_name: str, timeout: int | None = None) -> dict:
    """Get containers attached to a network with full metadata.

    SECURITY: shell=False is always used.

    Args:
        network_name: Name of the Docker network
        timeout: Timeout in seconds (default: from settings)

    Returns:
        dict: {container_id: {Name: ..., ...}} or {} if empty/error
    """
    effective_timeout = timeout if timeout is not None else _get_network_timeout()
    cmd = [
        "docker", "network", "inspect",
        "--format", "{{json .Containers}}",
        network_name,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
            shell=False,
        )

        if result.returncode != 0:
            # Network may not exist or other error
            return {}

        return parse_containers_json(result.stdout)

    except subprocess.TimeoutExpired:
        logger.debug(f"Timeout inspecting network {network_name}")
        return {}
    except Exception as e:
        logger.debug(f"Error inspecting network {network_name}: {type(e).__name__}")
        return {}


def list_octolab_networks() -> list[NetworkInfo]:
    """List all Docker networks with the octolab_ prefix.

    SECURITY: shell=False is always used.

    Returns:
        List of NetworkInfo objects for each octolab_* network
    """
    cmd = [
        "docker", "network", "ls",
        "--filter", f"name={OCTOLAB_NETWORK_PREFIX}",
        "--format", "{{json .}}",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_get_network_timeout(),
            shell=False,
        )

        if result.returncode != 0:
            logger.warning(f"Failed to list networks: {result.stderr.strip()}")
            return []

        networks = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                networks.append(NetworkInfo(
                    name=data.get("Name", ""),
                    driver=data.get("Driver", ""),
                    scope=data.get("Scope", ""),
                ))
            except json.JSONDecodeError:
                continue

        return networks

    except subprocess.TimeoutExpired:
        logger.error("Timeout listing Docker networks")
        return []
    except Exception as e:
        logger.error(f"Error listing networks: {type(e).__name__}")
        return []


def list_networks_by_compose_project(project_name: str, timeout: float = 10.0) -> list[str]:
    """List Docker networks created by a specific Compose project.

    Uses the com.docker.compose.project label that Docker Compose automatically
    adds to networks it creates. This is more reliable than name-based matching
    because it covers any network naming scheme.

    SECURITY:
    - shell=False is always used
    - project_name must be server-derived, never from client input
    - Additional defense-in-depth: only returns networks starting with octolab_

    Args:
        project_name: Compose project name (server-derived from lab.id)
        timeout: Timeout for docker command

    Returns:
        List of network names belonging to the project
    """
    cmd = [
        "docker", "network", "ls",
        "--filter", f"label=com.docker.compose.project={project_name}",
        "--format", "{{.Name}}",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        if result.returncode != 0:
            logger.debug(f"Failed to list networks for project {project_name}: {result.stderr.strip()[:100]}")
            return []

        # Parse network names and apply defense-in-depth filter
        networks = []
        for line in result.stdout.strip().split("\n"):
            name = line.strip()
            if name and name.startswith(OCTOLAB_NETWORK_PREFIX):
                networks.append(name)
            elif name:
                # Log but skip networks that don't start with octolab_
                # This shouldn't happen with proper labeling, but defense-in-depth
                logger.debug(f"Skipping non-octolab network {name} from project {project_name}")

        return networks

    except subprocess.TimeoutExpired:
        logger.debug(f"Timeout listing networks for project {project_name}")
        return []
    except Exception as e:
        logger.debug(f"Error listing networks for project {project_name}: {type(e).__name__}")
        return []


def get_network_container_count(network_name: str, timeout: float = 10.0) -> int:
    """Get the number of containers attached to a network.

    SECURITY: shell=False is always used.

    Args:
        network_name: Network name (must be server-derived)
        timeout: Timeout for docker command

    Returns:
        Number of attached containers, or -1 on error
    """
    cmd = [
        "docker", "network", "inspect",
        "-f", "{{len .Containers}}",
        network_name,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        if result.returncode != 0:
            # Network might not exist
            return -1

        try:
            return int(result.stdout.strip())
        except ValueError:
            return -1

    except subprocess.TimeoutExpired:
        logger.debug(f"Timeout inspecting network {network_name}")
        return -1
    except Exception as e:
        logger.debug(f"Error inspecting network {network_name}: {type(e).__name__}")
        return -1


def get_network_containers(network_name: str) -> list[str]:
    """Get list of container names attached to a network.

    SECURITY: shell=False is always used.

    Args:
        network_name: Name of the Docker network

    Returns:
        List of container names (not IDs)
    """
    cmd = [
        "docker", "network", "inspect",
        "--format", "{{range .Containers}}{{.Name}} {{end}}",
        network_name,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_get_network_timeout(),
            shell=False,
        )

        if result.returncode != 0:
            # Network may not exist
            return []

        # Parse space-separated container names
        names = result.stdout.strip().split()
        return [n for n in names if n]

    except subprocess.TimeoutExpired:
        logger.error(f"Timeout inspecting network {network_name}")
        return []
    except Exception as e:
        logger.error(f"Error inspecting network {network_name}: {type(e).__name__}")
        return []


def _prune_unused_networks() -> int:
    """Prune Docker networks not used by any container.

    This uses `docker network prune` which only removes networks
    with no attached containers.

    SECURITY: shell=False, scoped to networks with no containers.

    Returns:
        Number of networks pruned
    """
    # Note: --filter "label=..." could be used for more precision,
    # but we rely on the prefix filtering done by the caller
    cmd = ["docker", "network", "prune", "--force"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_get_network_timeout(),
            shell=False,
        )

        if result.returncode != 0:
            logger.warning(f"Network prune returned non-zero: {result.stderr.strip()}")
            return 0

        # Count "Deleted Networks:" lines
        # Output format: "Deleted Networks:\nnetwork1\nnetwork2\n"
        lines = result.stdout.strip().split("\n")
        # Skip the "Deleted Networks:" header
        deleted = [l for l in lines if l and not l.startswith("Deleted")]
        return len(deleted)

    except subprocess.TimeoutExpired:
        logger.error("Timeout during network prune")
        return 0
    except Exception as e:
        logger.error(f"Error during network prune: {type(e).__name__}")
        return 0


def _force_disconnect_container(
    container_name: str,
    network_name: str,
) -> bool:
    """Force-disconnect a container from a network.

    SECURITY: shell=False is always used.

    Args:
        container_name: Container to disconnect
        network_name: Network to disconnect from

    Returns:
        True if successful or already disconnected
    """
    cmd = ["docker", "network", "disconnect", "--force", network_name, container_name]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_get_network_timeout(),
            shell=False,
        )

        if result.returncode == 0:
            logger.info(f"Force-disconnected {container_name} from {network_name}")
            return True

        # Idempotent: already disconnected
        if "is not connected" in result.stderr.lower():
            return True

        logger.warning(
            f"Failed to force-disconnect {container_name} from {network_name}: "
            f"{result.stderr.strip()}"
        )
        return False

    except subprocess.TimeoutExpired:
        logger.error(f"Timeout force-disconnecting {container_name} from {network_name}")
        return False
    except Exception as e:
        logger.error(
            f"Error force-disconnecting {container_name} from {network_name}: "
            f"{type(e).__name__}"
        )
        return False


def _remove_network(network_name: str) -> bool:
    """Remove a Docker network.

    SECURITY: shell=False is always used.

    Args:
        network_name: Network to remove

    Returns:
        True if removed or didn't exist
    """
    cmd = ["docker", "network", "rm", network_name]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_get_network_timeout(),
            shell=False,
        )

        if result.returncode == 0:
            logger.info(f"Removed network {network_name}")
            return True

        # Idempotent: network doesn't exist
        if "no such network" in result.stderr.lower():
            return True

        # Still has containers attached
        if "has active endpoints" in result.stderr.lower():
            logger.warning(f"Cannot remove network {network_name}: has active endpoints")
            return False

        logger.warning(f"Failed to remove network {network_name}: {result.stderr.strip()}")
        return False

    except subprocess.TimeoutExpired:
        logger.error(f"Timeout removing network {network_name}")
        return False
    except Exception as e:
        logger.error(f"Error removing network {network_name}: {type(e).__name__}")
        return False


def remove_network(network_name: str, timeout: int = 30) -> NetworkRemoveResult:
    """Remove a Docker network with explicit result classification.

    This function is idempotent: NOT_FOUND is treated as success by callers.
    No warnings are logged for NOT_FOUND (network already gone is fine).

    SECURITY: shell=False is always used.

    Args:
        network_name: Network to remove
        timeout: Timeout in seconds (default 30s per timeout table)

    Returns:
        NetworkRemoveResult indicating outcome
    """
    cmd = ["docker", "network", "rm", network_name]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        if result.returncode == 0:
            logger.debug(f"Removed network {network_name}")
            return NetworkRemoveResult.OK

        # Classify the error
        classification = classify_network_error(result.stderr)

        # NOT_FOUND is fine - network already gone (no warning needed)
        if classification == NetworkRemoveResult.NOT_FOUND:
            logger.debug(f"Network {network_name} already removed (not found)")
            return NetworkRemoveResult.NOT_FOUND

        # IN_USE is expected during GC race - caller will handle retry
        if classification == NetworkRemoveResult.IN_USE:
            logger.debug(f"Network {network_name} is in use")
            return NetworkRemoveResult.IN_USE

        # Other errors - log at debug (caller decides severity)
        logger.debug(f"Error removing network {network_name}: {result.stderr.strip()[:100]}")
        return NetworkRemoveResult.ERROR

    except subprocess.TimeoutExpired:
        logger.debug(f"Timeout removing network {network_name}")
        return NetworkRemoveResult.ERROR
    except Exception as e:
        logger.debug(f"Exception removing network {network_name}: {type(e).__name__}")
        return NetworkRemoveResult.ERROR


def disconnect_container(
    network_name: str,
    container_name: str,
    *,
    force: bool = True,
    timeout: int = 30,
) -> bool:
    """Disconnect a container from a network (sync version with explicit timeout).

    SECURITY: shell=False is always used.

    Args:
        network_name: Network to disconnect from
        container_name: Container to disconnect
        force: Force disconnect even if container is running
        timeout: Timeout in seconds (default 30s per timeout table)

    Returns:
        True if disconnected or already disconnected
    """
    cmd = ["docker", "network", "disconnect"]
    if force:
        cmd.append("--force")
    cmd.extend([network_name, container_name])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        if result.returncode == 0:
            logger.debug(f"Disconnected {container_name} from {network_name}")
            return True

        # Idempotent: already disconnected or network gone
        stderr_lower = result.stderr.lower()
        if "is not connected" in stderr_lower or "no such network" in stderr_lower:
            logger.debug(f"{container_name} already disconnected from {network_name}")
            return True

        logger.debug(f"Failed to disconnect {container_name} from {network_name}: {result.stderr.strip()[:100]}")
        return False

    except subprocess.TimeoutExpired:
        logger.debug(f"Timeout disconnecting {container_name} from {network_name}")
        return False
    except Exception as e:
        logger.debug(f"Exception disconnecting {container_name} from {network_name}: {type(e).__name__}")
        return False


def _try_remove_network_silent(network_name: str) -> bool:
    """Try to remove a network, returning False silently on "in use" errors.

    This is for preflight cleanup where we don't want to log warnings
    for networks that are actively in use.

    Args:
        network_name: Network to remove

    Returns:
        True if removed, False if in-use/race/error (silent)
    """
    cmd = ["docker", "network", "rm", network_name]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_get_network_timeout(),
            shell=False,
        )

        if result.returncode == 0:
            logger.debug(f"Removed empty network {network_name}")
            return True

        # Idempotent: network doesn't exist
        if "no such network" in result.stderr.lower():
            return True

        # In-use errors (race condition) - silent at DEBUG level
        stderr_lower = result.stderr.lower()
        if any(p in stderr_lower for p in ("has active endpoints", "resource is still in use", "network is in use")):
            logger.debug(f"Network {network_name} is in use, skipping")
            return False

        # Other errors - debug level only for preflight
        logger.debug(f"Failed to remove network {network_name}: {result.stderr.strip()}")
        return False

    except subprocess.TimeoutExpired:
        logger.debug(f"Timeout removing network {network_name}")
        return False
    except Exception as e:
        logger.debug(f"Error removing network {network_name}: {type(e).__name__}")
        return False


# =============================================================================
# Compose Project Network Cleanup (for destroy_lab with retry)
# =============================================================================


def compose_project_name(lab_id: str | UUID) -> str:
    """Generate compose project name from server-owned lab ID.

    SECURITY: Project name is always derived from server-owned lab_id,
    never accepted from client input.

    Args:
        lab_id: UUID or string lab ID

    Returns:
        Normalized project name in format: octolab_<uuid>
    """
    return f"octolab_{str(lab_id).lower()}"


# Valid network suffixes for lab networks (deny-by-default)
VALID_NETWORK_SUFFIXES = frozenset({"_lab_net", "_egress_net"})


def safe_is_lab_network(project: str, network_name: str) -> bool:
    """Check if a network name is valid for removal from this project.

    SECURITY: Deny-by-default. Only allows networks that:
    1. Start with the project name
    2. End with a known suffix (_lab_net, _egress_net)

    Args:
        project: Compose project name (e.g., octolab_<uuid>)
        network_name: Network name to validate

    Returns:
        True if network is safe to remove
    """
    # Must start with project name
    if not network_name.startswith(f"{project}_"):
        return False

    # Must end with known suffix
    for suffix in VALID_NETWORK_SUFFIXES:
        if network_name.endswith(suffix):
            return True

    return False


@dataclass
class NetworkSkippedInfo:
    """Info about a network that couldn't be removed."""

    name: str
    reason: str  # "in_use", "name_not_allowed", "error"
    containers: list[str] = field(default_factory=list)


@dataclass
class NetworkRemovalResult:
    """Result of remove_compose_project_networks operation.

    Provides truthful accounting of what was removed and what remains.
    """

    networks_found: int = 0
    networks_removed: int = 0
    networks_skipped: list[NetworkSkippedInfo] = field(default_factory=list)
    last_errors: list[str] = field(default_factory=list)

    @property
    def networks_remaining(self) -> int:
        """Networks that couldn't be removed."""
        return self.networks_found - self.networks_removed


def _resolve_container_names(container_ids: list[str], timeout: float = 5.0) -> dict[str, str]:
    """Resolve container IDs to names.

    Args:
        container_ids: List of container IDs
        timeout: Timeout for docker command

    Returns:
        Dict mapping container ID -> name (or ID prefix if lookup fails)
    """
    if not container_ids:
        return {}

    result = {}
    for cid in container_ids[:10]:  # Limit to 10 to avoid slowdown
        short_id = cid[:12]
        cmd = ["docker", "ps", "-a", "--filter", f"id={cid}", "--format", "{{.Names}}"]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                result[cid] = proc.stdout.strip()
            else:
                result[cid] = short_id
        except Exception:
            result[cid] = short_id

    return result


def remove_compose_project_networks(
    project: str,
    lab_id: str,
    *,
    deadline_secs: float = 8.0,
    backoff_base_ms: int | None = None,
    max_retries: int | None = None,
    allowlist: list[str] | None = None,
) -> NetworkRemovalResult:
    """Remove all networks belonging to a compose project with retry logic.

    This function handles the Docker endpoint cleanup race (200-800ms lag after
    container removal) by retrying with exponential backoff.

    Algorithm:
    1. List networks by compose project label
    2. For each network:
       a. Validate name matches safe pattern
       b. Try to remove (may fail if in-use due to GC race)
       c. If in-use, inspect containers:
          - If project-owned: unexpected (compose down should have removed)
          - If allowlisted: force-disconnect, retry
          - If empty (GC race): sleep and retry
          - If unknown: skip with warning
       d. Retry with backoff until deadline
    3. Return truthful accounting

    SECURITY:
    - project is derived from server-owned lab.id, never client input
    - Only removes networks matching safe pattern
    - Never runs docker prune
    - shell=False on all subprocess calls
    - Logs container names for debugging but never secrets

    Args:
        project: Compose project name (server-derived)
        lab_id: Lab ID for logging (server-owned)
        deadline_secs: Max time for entire cleanup operation
        backoff_base_ms: Initial backoff in ms (default from settings)
        max_retries: Max retries per network (default from settings)
        allowlist: Containers that can be force-disconnected

    Returns:
        NetworkRemovalResult with truthful accounting
    """
    import time

    # Get defaults from settings
    if backoff_base_ms is None:
        backoff_base_ms = settings.net_rm_backoff_ms
    if max_retries is None:
        max_retries = settings.net_rm_max_retries
    if allowlist is None:
        allowlist = list(settings.control_plane_containers)

    allowlist_set = set(allowlist)
    result = NetworkRemovalResult()
    start_time = time.monotonic()

    # List networks by compose project label
    networks = list_networks_by_compose_project(project)
    result.networks_found = len(networks)

    if not networks:
        return result

    for net_name in networks:
        # Defense-in-depth: validate network name
        if not safe_is_lab_network(project, net_name):
            logger.debug(f"Skipping network {net_name}: name not in allowlist for project {project}")
            result.networks_skipped.append(NetworkSkippedInfo(
                name=net_name,
                reason="name_not_allowed",
            ))
            continue

        # Calculate remaining deadline for this network
        elapsed = time.monotonic() - start_time
        if elapsed >= deadline_secs:
            result.networks_skipped.append(NetworkSkippedInfo(
                name=net_name,
                reason="deadline_exceeded",
            ))
            result.last_errors.append(f"{net_name}: deadline exceeded")
            continue

        # Retry loop with backoff
        removed = False
        backoff_ms = backoff_base_ms

        for attempt in range(1, max(max_retries, 1) + 1):
            # Check deadline
            elapsed = time.monotonic() - start_time
            if elapsed >= deadline_secs:
                break

            # Try to remove
            rm_result = remove_network(net_name, timeout=30)

            if rm_result in (NetworkRemoveResult.OK, NetworkRemoveResult.NOT_FOUND):
                removed = True
                break

            if rm_result == NetworkRemoveResult.IN_USE:
                # Inspect what containers are attached
                containers_info = inspect_network_containers(net_name)

                if containers_info:
                    # Extract container names
                    container_ids = list(containers_info.keys())
                    id_to_name = _resolve_container_names(container_ids)

                    attached_names = []
                    for cid, meta in containers_info.items():
                        if isinstance(meta, dict) and meta.get("Name"):
                            attached_names.append(meta["Name"])
                        elif cid in id_to_name:
                            attached_names.append(id_to_name[cid])

                    if attached_names:
                        # Check if all containers are allowlisted
                        non_allowlisted = [c for c in attached_names if c not in allowlist_set]

                        if not non_allowlisted:
                            # All are allowlisted - force-disconnect and retry
                            for container in attached_names:
                                disconnect_container(net_name, container, force=True, timeout=30)
                            continue  # Retry removal
                        else:
                            # Unknown containers blocking - will skip after max retries
                            pass

                # Either empty (GC race) or has containers - wait and retry
                if attempt < max_retries:
                    sleep_secs = backoff_ms / 1000.0
                    remaining = deadline_secs - (time.monotonic() - start_time)
                    actual_sleep = min(sleep_secs, max(remaining - 0.1, 0))
                    if actual_sleep > 0:
                        time.sleep(actual_sleep)
                    backoff_ms = min(backoff_ms * 2, 1000)  # Cap at 1 second
                    continue

            # ERROR or exhausted retries
            break

        if removed:
            result.networks_removed += 1
        else:
            # Final inspection to report what's blocking
            containers_info = inspect_network_containers(net_name)
            blocking_containers = []

            if containers_info:
                for cid, meta in containers_info.items():
                    if isinstance(meta, dict) and meta.get("Name"):
                        blocking_containers.append(meta["Name"])
                    else:
                        blocking_containers.append(cid[:12])

            result.networks_skipped.append(NetworkSkippedInfo(
                name=net_name,
                reason="in_use" if blocking_containers else "unknown_blocked",
                containers=blocking_containers,
            ))

            # Log warning once per network
            if blocking_containers:
                logger.warning(
                    f"Network {net_name} cleanup blocked for lab {lab_id}: "
                    f"containers={blocking_containers[:5]}"
                )
            else:
                logger.warning(
                    f"Network {net_name} cleanup blocked for lab {lab_id}: unknown reason"
                )

    return result


def preflight_cleanup_stale_lab_networks(*, dry_run: bool = False) -> NetworkCleanupResult:
    """Preflight cleanup: remove ONLY empty per-lab networks.

    This function is strictly scoped for preflight use:
    - Only considers networks matching the strict lab pattern
      (octolab_<uuid>_lab_net or octolab_<uuid>_egress_net)
    - Only removes networks with ZERO attached containers
    - Silent on races (in-use errors logged at DEBUG only)
    - Never logs "blocked by non-allowlisted" messages
    - Never calls global prune
    - Never force-disconnects containers

    SECURITY:
    - Strict regex excludes infrastructure networks (octolab_mvp_default)
    - shell=False on all subprocess calls
    - Best-effort only; never raises

    Args:
        dry_run: If True, only report what would be done

    Returns:
        NetworkCleanupResult (blocked_networks is always empty for preflight)
    """
    result = NetworkCleanupResult()

    # List all octolab_* networks
    networks = list_octolab_networks()

    # Filter to strict lab networks only
    lab_networks = [n for n in networks if is_octolab_lab_network(n.name)]

    if not lab_networks:
        logger.debug("No stale per-lab networks found")
        return result

    # For each lab network, check if empty and remove
    for net in lab_networks:
        containers = inspect_network_containers(net.name)

        if containers:
            # Has containers - skip silently (this is expected for active labs)
            logger.debug(f"Network {net.name} has {len(containers)} containers, skipping")
            continue

        # Empty network - try to remove
        if dry_run:
            logger.debug(f"[dry-run] Would remove empty network {net.name}")
            result.removed_count += 1
        else:
            if _try_remove_network_silent(net.name):
                result.removed_count += 1

    # Log summary only if we actually removed something
    if result.removed_count > 0:
        logger.info(f"Preflight cleanup: removed {result.removed_count} empty lab network(s)")

    return result


async def preflight_network_cleanup() -> NetworkCleanupResult:
    """Async wrapper for preflight network cleanup.

    Called before creating a new lab to ensure address pool space is available.
    This is best-effort and NEVER raises - just logs at DEBUG level on issues.

    Returns:
        NetworkCleanupResult (never raises)
    """
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            preflight_cleanup_stale_lab_networks,
        )
        return result
    except Exception as e:
        # Best-effort: log and return empty result
        logger.debug(f"Preflight network cleanup failed: {type(e).__name__}")
        return NetworkCleanupResult()


# =============================================================================
# Network Count Diagnostics (for pool exhaustion troubleshooting)
# =============================================================================


@dataclass
class NetworkCountInfo:
    """Network count diagnostic information.

    Used to provide actionable hints when pool exhaustion occurs.
    """

    total_count: int = 0
    octolab_count: int = 0
    hint: str = ""


def get_network_counts(timeout: float = 10.0) -> NetworkCountInfo:
    """Get Docker network counts for diagnostics.

    Returns numeric counts only (no full list) to avoid DoS/privacy issues.
    Includes actionable hint if octolab_ network count is high.

    SECURITY:
    - shell=False is always used
    - Only returns counts, not network names
    - Bounded output for safe logging

    Args:
        timeout: Timeout for docker command

    Returns:
        NetworkCountInfo with counts and optional hint
    """
    result = NetworkCountInfo()

    try:
        # Get all network names
        cmd = ["docker", "network", "ls", "--format", "{{.Name}}"]
        proc_result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        if proc_result.returncode != 0:
            return result

        # Count networks
        lines = [l.strip() for l in proc_result.stdout.strip().split("\n") if l.strip()]
        result.total_count = len(lines)

        # Count octolab_ prefixed networks
        result.octolab_count = sum(1 for name in lines if name.startswith(OCTOLAB_NETWORK_PREFIX))

        # Add hint if high count suggests pool exhaustion risk
        if result.octolab_count > 200:
            result.hint = (
                "Docker address pools may be exhausted. "
                "Consider expanding default-address-pools in /etc/docker/daemon.json "
                "and cleaning up leaked networks (see docs/compose-runtime-ops.md)."
            )
        elif result.octolab_count > 100:
            result.hint = (
                f"High octolab network count ({result.octolab_count}). "
                "Monitor for pool exhaustion."
            )

        return result

    except subprocess.TimeoutExpired:
        logger.debug("Timeout getting network counts")
        return result
    except Exception as e:
        logger.debug(f"Error getting network counts: {type(e).__name__}")
        return result


# =============================================================================
# Targeted Cleanup Functions (for destroy_lab / failure cleanup)
# =============================================================================


def is_project_owned_container(container_name: str, project_name: str) -> bool:
    """Check if a container belongs to a compose project.

    Compose v2 naming: <project>-<service>-<replica> (hyphens)
    Our project names use underscores: octolab_<uuid>

    Args:
        container_name: Container name to check
        project_name: Compose project name (e.g., octolab_<uuid>)

    Returns:
        True if container belongs to this project
    """
    # Compose v2 converts underscores to hyphens in container names
    # So project "octolab_abc" creates containers "octolab-abc-service-1"
    normalized_prefix = project_name.replace("_", "-")
    return container_name.startswith(f"{normalized_prefix}-")


def targeted_network_cleanup(
    network_name: str,
    project_name: str,
    compose_file: str,
    allowlist: list[str] | None = None,
) -> bool:
    """Targeted cleanup for a specific lab network during destroy/failure.

    This performs aggressive cleanup for a specific lab:
    1. If network has no containers, remove it
    2. If containers are project-owned, run compose rm -sfv then retry
    3. If containers are in allowlist, force-disconnect then retry
    4. If unknown containers remain, raise NetworkCleanupBlockedError

    Args:
        network_name: Network to clean up
        project_name: Compose project name
        compose_file: Path to compose file
        allowlist: Control-plane containers that can be force-disconnected

    Returns:
        True if network was removed

    Raises:
        NetworkCleanupBlockedError: If unknown containers block removal
    """
    from app.runtime.exceptions import NetworkCleanupBlockedError

    if allowlist is None:
        allowlist = list(settings.control_plane_containers)
    allowlist_set = set(allowlist)

    # First attempt: just try to remove
    if _remove_network(network_name):
        return True

    # Check what containers are attached
    containers_info = inspect_network_containers(network_name)
    if not containers_info:
        # No containers but still failed? Try once more
        return _remove_network(network_name)

    # Extract container names
    attached_names = sorted([
        meta.get("Name", "")
        for meta in containers_info.values()
        if meta.get("Name")
    ])

    if not attached_names:
        # Weird state - no names but has containers?
        return _remove_network(network_name)

    # Partition containers
    project_owned = [c for c in attached_names if is_project_owned_container(c, project_name)]
    allowlisted = [c for c in attached_names if c in allowlist_set and c not in project_owned]
    unknown = [c for c in attached_names if c not in project_owned and c not in allowlist_set]

    # Step 1: If project-owned containers exist, run compose rm -sfv
    if project_owned:
        logger.info(f"Removing project containers for {project_name}: {project_owned}")
        cmd = [
            "docker", "compose",
            "-p", project_name,
            "-f", compose_file,
            "rm", "-sfv",
        ]
        try:
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                shell=False,
            )
        except Exception as e:
            logger.warning(f"compose rm failed for {project_name}: {type(e).__name__}")

        # Retry network removal
        if _remove_network(network_name):
            return True

        # Refresh container list
        containers_info = inspect_network_containers(network_name)
        attached_names = sorted([
            meta.get("Name", "")
            for meta in containers_info.values()
            if meta.get("Name")
        ])
        allowlisted = [c for c in attached_names if c in allowlist_set]
        unknown = [c for c in attached_names if c not in allowlist_set]

    # Step 2: If allowlisted containers remain, force-disconnect them
    if allowlisted and not unknown:
        for container in allowlisted:
            _force_disconnect_container(container, network_name)

        # Retry network removal
        if _remove_network(network_name):
            return True

        # Check again
        containers_info = inspect_network_containers(network_name)
        unknown = [
            meta.get("Name", "")
            for meta in containers_info.values()
            if meta.get("Name") and meta.get("Name") not in allowlist_set
        ]

    # Step 3: If unknown containers remain, raise actionable error
    if unknown:
        raise NetworkCleanupBlockedError(
            message=f"Cannot remove {network_name}: blocked by containers: {','.join(unknown)}. "
                    f"Manual cleanup: docker network disconnect {network_name} <container>",
            network_name=network_name,
            blocking_containers=unknown,
        )

    # Final attempt
    return _remove_network(network_name)


# =============================================================================
# Admin-Only Cleanup Functions
# =============================================================================


@dataclass
class ContainerInfo:
    """Information about a container with its compose project label."""

    name: str
    project: str  # com.docker.compose.project label value


@dataclass
class ContainerStatusInfo:
    """Container status grouped by lab vs non-lab projects.

    Used by admin status endpoint to show accurate counts.
    """

    running_lab_containers: int = 0
    running_lab_projects: int = 0
    running_nonlab_containers: int = 0
    running_total_containers: int = 0
    lab_entries: list[ContainerInfo] = field(default_factory=list)
    nonlab_entries: list[ContainerInfo] = field(default_factory=list)


@dataclass
class AdminCleanupResult:
    """Result of admin network cleanup operation."""

    networks_found: int = 0
    networks_removed: int = 0
    networks_skipped_in_use: int = 0
    containers_found: int = 0
    containers_removed: int = 0
    running_octolab_containers: int = 0
    errors: list[str] = field(default_factory=list)


def list_running_octolab_containers(timeout: float = 10.0) -> list[str]:
    """List running containers with octolab_ prefix.

    DEPRECATED: Use get_running_container_status() instead for accurate lab detection.

    Used to check if any OctoLab containers are running before admin cleanup.
    This function is kept for backwards compatibility but overcounts by including
    infrastructure containers (guacamole, postgres, hackvm).

    SECURITY:
    - shell=False is always used
    - Only returns container names, not full inspect data

    Args:
        timeout: Timeout for docker command

    Returns:
        List of running container names starting with octolab_
    """
    cmd = ["docker", "ps", "--format", "{{.Names}}"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        if result.returncode != 0:
            logger.debug(f"Failed to list running containers: {result.stderr.strip()[:100]}")
            return []

        # Filter to octolab_ prefixed containers
        containers = []
        for line in result.stdout.strip().split("\n"):
            name = line.strip()
            if name and name.startswith(OCTOLAB_NETWORK_PREFIX):
                containers.append(name)

        return containers

    except subprocess.TimeoutExpired:
        logger.debug("Timeout listing running containers")
        return []
    except Exception as e:
        logger.debug(f"Error listing running containers: {type(e).__name__}")
        return []


def get_running_container_status(timeout: float = 10.0) -> ContainerStatusInfo:
    """Get running container status with lab/non-lab partitioning.

    Uses compose project labels to accurately distinguish:
    - Lab containers: project label matches octolab_<uuid> pattern
    - Non-lab containers: project label is something else (guacamole, octolab_mvp, etc.)

    SECURITY:
    - shell=False is always used
    - Only returns container name + project label (no sensitive data)
    - Bounded output (no full docker inspect)

    Args:
        timeout: Timeout for docker command

    Returns:
        ContainerStatusInfo with lab/non-lab counts and entries
    """
    result = ContainerStatusInfo()

    # Get all running containers with name and compose project label
    cmd = [
        "docker", "ps",
        "--format", "{{.Names}}\t{{.Label \"com.docker.compose.project\"}}"
    ]

    try:
        proc_result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        if proc_result.returncode != 0:
            logger.debug(f"Failed to list containers: {proc_result.stderr.strip()[:100]}")
            return result

        # Parse output and partition by lab project pattern
        lab_projects = set()

        for line in proc_result.stdout.strip().split("\n"):
            if not line.strip():
                continue

            # Split by tab (format: name\tproject)
            parts = line.split("\t")
            name = parts[0].strip() if parts else ""
            project = parts[1].strip() if len(parts) > 1 else ""

            if not name:
                continue

            result.running_total_containers += 1
            entry = ContainerInfo(name=name, project=project)

            if is_lab_project(project):
                result.running_lab_containers += 1
                result.lab_entries.append(entry)
                lab_projects.add(project)
            else:
                # Non-lab includes: infrastructure, unlabeled, etc.
                result.running_nonlab_containers += 1
                result.nonlab_entries.append(entry)

        result.running_lab_projects = len(lab_projects)

        return result

    except subprocess.TimeoutExpired:
        logger.debug("Timeout listing running containers")
        return result
    except Exception as e:
        logger.debug(f"Error listing running containers: {type(e).__name__}")
        return result


def list_running_lab_containers(timeout: float = 10.0) -> list[str]:
    """List running containers that belong to LAB projects only.

    This is the corrected version that uses compose project labels to
    only count containers from octolab_<uuid> projects, excluding
    infrastructure containers.

    SECURITY:
    - shell=False is always used
    - Only returns container names

    Args:
        timeout: Timeout for docker command

    Returns:
        List of running container names from lab projects only
    """
    status = get_running_container_status(timeout)
    return [entry.name for entry in status.lab_entries]


def list_stopped_octolab_containers(timeout: float = 10.0) -> list[str]:
    """List stopped containers with octolab_ prefix.

    SECURITY:
    - shell=False is always used
    - Only returns container names

    Args:
        timeout: Timeout for docker command

    Returns:
        List of stopped container names starting with octolab_
    """
    # List all containers (including stopped)
    cmd_all = ["docker", "ps", "-a", "--format", "{{.Names}}"]
    # List running containers
    cmd_running = ["docker", "ps", "--format", "{{.Names}}"]

    try:
        result_all = subprocess.run(
            cmd_all,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        result_running = subprocess.run(
            cmd_running,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        if result_all.returncode != 0:
            return []

        # Get all octolab_ containers
        all_octolab = set()
        for line in result_all.stdout.strip().split("\n"):
            name = line.strip()
            if name and name.startswith(OCTOLAB_NETWORK_PREFIX):
                all_octolab.add(name)

        # Get running octolab_ containers
        running_octolab = set()
        for line in result_running.stdout.strip().split("\n"):
            name = line.strip()
            if name and name.startswith(OCTOLAB_NETWORK_PREFIX):
                running_octolab.add(name)

        # Stopped = all - running
        stopped = all_octolab - running_octolab
        return sorted(stopped)

    except subprocess.TimeoutExpired:
        logger.debug("Timeout listing stopped containers")
        return []
    except Exception as e:
        logger.debug(f"Error listing stopped containers: {type(e).__name__}")
        return []


def remove_container(container_name: str, timeout: float = 30.0) -> bool:
    """Remove a container by name.

    SECURITY:
    - shell=False is always used
    - Container name must be server-derived (starts with octolab_)

    Args:
        container_name: Container name to remove (must start with octolab_)
        timeout: Timeout for docker command

    Returns:
        True if removed or already gone
    """
    # Defense-in-depth: only remove octolab_ containers
    if not container_name.startswith(OCTOLAB_NETWORK_PREFIX):
        logger.warning(f"Refusing to remove non-octolab container: {container_name}")
        return False

    cmd = ["docker", "rm", "-f", container_name]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        if result.returncode == 0:
            logger.debug(f"Removed container {container_name}")
            return True

        # Treat "no such container" as success (idempotent)
        stderr_lower = result.stderr.lower()
        if "no such container" in stderr_lower or "not found" in stderr_lower:
            return True

        logger.debug(f"Failed to remove container {container_name}: {result.stderr.strip()[:100]}")
        return False

    except subprocess.TimeoutExpired:
        logger.debug(f"Timeout removing container {container_name}")
        return False
    except Exception as e:
        logger.debug(f"Error removing container {container_name}: {type(e).__name__}")
        return False


def list_all_octolab_networks(timeout: float = 10.0) -> list[str]:
    """List all Docker networks with octolab_ prefix.

    SECURITY:
    - shell=False is always used
    - Only returns networks matching the strict lab network pattern

    Args:
        timeout: Timeout for docker command

    Returns:
        List of network names matching octolab_<uuid>_(lab_net|egress_net) pattern
    """
    cmd = ["docker", "network", "ls", "--format", "{{.Name}}"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        if result.returncode != 0:
            logger.debug(f"Failed to list networks: {result.stderr.strip()[:100]}")
            return []

        # Filter to strict lab network pattern only
        networks = []
        for line in result.stdout.strip().split("\n"):
            name = line.strip()
            if name and is_octolab_lab_network(name):
                networks.append(name)

        return networks

    except subprocess.TimeoutExpired:
        logger.debug("Timeout listing networks")
        return []
    except Exception as e:
        logger.debug(f"Error listing networks: {type(e).__name__}")
        return []


def admin_cleanup_octolab_resources(
    *,
    remove_stopped_containers: bool = True,
    timeout: float = 30.0,
) -> AdminCleanupResult:
    """Admin-only cleanup of ALL OctoLab networks and optionally stopped containers.

    SECURITY:
    - Refuses if any OctoLab containers are RUNNING
    - Only removes networks matching strict lab pattern (octolab_<uuid>_*)
    - Only removes containers with octolab_ prefix
    - Never runs docker network prune or system prune
    - shell=False on all subprocess calls

    Args:
        remove_stopped_containers: Whether to remove stopped octolab_ containers
        timeout: Timeout for each docker command

    Returns:
        AdminCleanupResult with counts and errors

    Note:
        This function should ONLY be called after verifying the caller is an admin
        via list_running_octolab_containers() check.
    """
    result = AdminCleanupResult()

    # Step 1: Check for running containers (should have been checked by caller, but defense-in-depth)
    running = list_running_octolab_containers(timeout)
    result.running_octolab_containers = len(running)
    if running:
        result.errors.append(f"REFUSED: {len(running)} running octolab containers")
        return result

    # Step 2: Remove stopped containers if requested
    if remove_stopped_containers:
        stopped = list_stopped_octolab_containers(timeout)
        result.containers_found = len(stopped)
        for container in stopped:
            if remove_container(container, timeout):
                result.containers_removed += 1
            else:
                result.errors.append(f"container:{container}")

    # Step 3: Remove networks
    networks = list_all_octolab_networks(timeout)
    result.networks_found = len(networks)

    for net_name in networks:
        # Check if network has containers
        container_count = get_network_container_count(net_name, timeout)

        if container_count == 0:
            # Safe to remove
            rm_result = remove_network(net_name, int(timeout))
            if rm_result in (NetworkRemoveResult.OK, NetworkRemoveResult.NOT_FOUND):
                result.networks_removed += 1
            else:
                result.errors.append(f"network:{net_name}")
        elif container_count > 0:
            result.networks_skipped_in_use += 1
        # container_count == -1 means inspect failed, skip silently

    # Truncate errors list
    if len(result.errors) > 20:
        result.errors = result.errors[:20] + [f"... and {len(result.errors) - 20} more"]

    return result


# =============================================================================
# Runtime Drift Detection and Stop-Labs Functions
# =============================================================================


class RuntimeProjectClassification(Enum):
    """Classification of a runtime lab project against DB state."""

    TRACKED = "tracked"  # DB status is READY, PROVISIONING, or ENDING
    DRIFTED = "drifted"  # DB exists but status is FINISHED/FAILED (should be stopped)
    ORPHANED = "orphaned"  # No DB row found for this lab_id


@dataclass
class RuntimeLabProject:
    """Information about a running lab project from runtime scan."""

    project: str  # Compose project name (octolab_<uuid>)
    lab_id: str  # Extracted UUID from project name
    classification: RuntimeProjectClassification
    db_status: str | None  # DB status if found, None if orphaned
    container_count: int = 0
    sample_containers: list[str] = field(default_factory=list)  # Max 3


@dataclass
class RuntimeDriftResult:
    """Result of runtime drift scan."""

    running_lab_projects_total: int = 0
    running_lab_containers_total: int = 0
    tracked_running_projects: int = 0
    drifted_running_projects: int = 0
    orphaned_running_projects: int = 0
    projects: list[RuntimeLabProject] = field(default_factory=list)


@dataclass
class StopLabsResult:
    """Result of batch stop-labs operation."""

    targets: int = 0
    projects_stopped: int = 0
    projects_failed: int = 0
    networks_removed: int = 0
    networks_failed: int = 0
    errors: list[str] = field(default_factory=list)


def extract_lab_id_from_project(project: str) -> str | None:
    """Extract lab UUID from project name.

    Args:
        project: Compose project name (e.g., octolab_12345678-1234-1234-1234-123456789abc)

    Returns:
        UUID string if valid lab project, None otherwise
    """
    if not is_lab_project(project):
        return None

    # Strip "octolab_" prefix to get UUID
    return project[8:] if project.startswith("octolab_") else None


def scan_running_lab_projects(timeout: float = 10.0) -> dict[str, list[str]]:
    """Scan running containers and group by lab project.

    SECURITY:
    - shell=False is always used
    - Only returns lab projects (octolab_<uuid> pattern)

    Args:
        timeout: Timeout for docker command

    Returns:
        Dict mapping project name to list of container names
    """
    cmd = [
        "docker", "ps",
        "--format", "{{.Names}}\t{{.Label \"com.docker.compose.project\"}}"
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        if result.returncode != 0:
            logger.debug(f"Failed to scan running containers: {result.stderr.strip()[:100]}")
            return {}

        # Group containers by lab project
        projects: dict[str, list[str]] = {}

        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue

            parts = line.split("\t")
            name = parts[0].strip() if parts else ""
            project = parts[1].strip() if len(parts) > 1 else ""

            if not name or not project:
                continue

            # Only include lab projects
            if is_lab_project(project):
                if project not in projects:
                    projects[project] = []
                projects[project].append(name)

        return projects

    except subprocess.TimeoutExpired:
        logger.debug("Timeout scanning running containers")
        return {}
    except Exception as e:
        logger.debug(f"Error scanning running containers: {type(e).__name__}")
        return {}


def stop_lab_project(
    project: str,
    compose_dir: str,
    compose_file: str,
    timeout: float = 120.0,
) -> tuple[bool, list[str]]:
    """Stop a single lab project using docker compose down.

    SECURITY:
    - project must be server-derived (octolab_<uuid> format)
    - shell=False is always used
    - Never runs global prune

    Args:
        project: Compose project name (must match octolab_<uuid> pattern)
        compose_dir: Directory containing compose file
        compose_file: Path to compose file
        timeout: Timeout for compose down

    Returns:
        Tuple of (success, errors)
    """
    errors: list[str] = []

    # Defense-in-depth: verify project matches lab pattern
    if not is_lab_project(project):
        errors.append(f"Invalid project name: {project}")
        return False, errors

    # Step 1: Run docker compose down --remove-orphans
    cmd = [
        "docker", "compose",
        "--project-directory", compose_dir,
        "-f", compose_file,
        "-p", project,
        "down", "--remove-orphans",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        if result.returncode != 0:
            # Log but continue - compose down may partially succeed
            stderr_excerpt = result.stderr.strip()[:200] if result.stderr else "(empty)"
            logger.debug(f"compose down for {project} exited with rc={result.returncode}: {stderr_excerpt}")

    except subprocess.TimeoutExpired:
        errors.append(f"compose down timeout for {project}")
        logger.debug(f"compose down timed out for {project}")
    except Exception as e:
        errors.append(f"compose down error for {project}: {type(e).__name__}")
        logger.debug(f"compose down failed for {project}: {type(e).__name__}")

    return len(errors) == 0, errors


def cleanup_project_networks(
    project: str,
    timeout: float = 30.0,
) -> tuple[int, int]:
    """Clean up networks for a stopped lab project.

    Uses label-based discovery to find networks created by the project.
    Only removes networks with 0 attached containers.

    SECURITY:
    - project must be server-derived (octolab_<uuid> format)
    - shell=False is always used
    - Never runs global prune

    Args:
        project: Compose project name
        timeout: Timeout for network operations

    Returns:
        Tuple of (networks_removed, networks_failed)
    """
    removed = 0
    failed = 0

    # Defense-in-depth: verify project matches lab pattern
    if not is_lab_project(project):
        logger.debug(f"Refusing to cleanup networks for non-lab project: {project}")
        return 0, 0

    # Get networks by label
    networks = list_networks_by_compose_project(project, timeout)

    for net_name in networks:
        # Additional defense: only touch octolab_ prefixed networks
        if not net_name.startswith(OCTOLAB_NETWORK_PREFIX):
            continue

        # Check if network has attached containers
        container_count = get_network_container_count(net_name, timeout)

        if container_count == 0:
            # Safe to remove
            rm_result = remove_network(net_name, int(timeout))
            if rm_result in (NetworkRemoveResult.OK, NetworkRemoveResult.NOT_FOUND):
                removed += 1
                logger.debug(f"Removed network {net_name}")
            else:
                failed += 1
                logger.debug(f"Failed to remove network {net_name}")
        elif container_count > 0:
            # Has containers - skip (shouldn't happen after compose down)
            logger.debug(f"Network {net_name} still has {container_count} containers, skipping")
            failed += 1

    return removed, failed


def stop_lab_projects_batch(
    projects: list[str],
    compose_dir: str,
    compose_file: str,
    timeout_per_project: float = 120.0,
) -> StopLabsResult:
    """Stop multiple lab projects in batch.

    SECURITY:
    - All projects must be server-derived (from runtime scan)
    - Never accepts client-provided project lists
    - shell=False is always used
    - Never runs global prune

    Args:
        projects: List of project names to stop (must be octolab_<uuid> format)
        compose_dir: Directory containing compose file
        compose_file: Path to compose file
        timeout_per_project: Timeout per project for compose down

    Returns:
        StopLabsResult with counts
    """
    result = StopLabsResult(targets=len(projects))

    for project in projects:
        # Verify each project matches lab pattern (defense-in-depth)
        if not is_lab_project(project):
            result.projects_failed += 1
            result.errors.append(f"Invalid project: {project}")
            continue

        # Stop the project
        success, errors = stop_lab_project(
            project,
            compose_dir,
            compose_file,
            timeout_per_project,
        )

        if success:
            result.projects_stopped += 1
        else:
            result.projects_failed += 1
            result.errors.extend(errors)

        # Clean up networks for this project
        net_removed, net_failed = cleanup_project_networks(project)
        result.networks_removed += net_removed
        result.networks_failed += net_failed

    # Truncate errors list
    if len(result.errors) > 20:
        result.errors = result.errors[:20] + [f"... and {len(result.errors) - 20} more"]

    return result


# =============================================================================
# Robust Docker Helpers with State Verification
# =============================================================================


def _sanitize_stderr(stderr: str | None, max_len: int = 400) -> str | None:
    """Sanitize and truncate stderr for safe logging/response.

    Removes potential secrets and truncates to max_len.
    """
    if not stderr:
        return None
    # Basic sanitization - remove potential secret patterns
    sanitized = stderr.strip()
    # Remove VNC password patterns
    sanitized = re.sub(r"VNC_PASSWORD=\S+", "VNC_PASSWORD=***", sanitized)
    sanitized = re.sub(r"password[=:]\s*\S+", "password=***", sanitized, flags=re.IGNORECASE)
    # Truncate
    if len(sanitized) > max_len:
        sanitized = sanitized[:max_len] + "...(truncated)"
    return sanitized if sanitized else None


def list_running_container_ids_for_project(
    project: str,
    timeout: float = 10.0,
) -> list[str]:
    """List running container IDs for a compose project.

    SECURITY:
    - project must be server-derived
    - shell=False is always used
    - Only returns IDs, no sensitive data

    Args:
        project: Compose project name
        timeout: Timeout for docker command

    Returns:
        List of container IDs (short form)
    """
    if not is_lab_project(project):
        logger.debug(f"Refusing to list containers for non-lab project: {project}")
        return []

    cmd = [
        "docker", "ps", "-q",
        "--filter", f"label=com.docker.compose.project={project}",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        if result.returncode != 0:
            logger.debug(f"Failed to list container IDs for {project}: {result.stderr.strip()[:100]}")
            return []

        ids = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        return ids

    except subprocess.TimeoutExpired:
        logger.debug(f"Timeout listing container IDs for {project}")
        return []
    except Exception as e:
        logger.debug(f"Error listing container IDs for {project}: {type(e).__name__}")
        return []


def list_running_container_names_for_project(
    project: str,
    timeout: float = 10.0,
) -> list[str]:
    """List running container names for a compose project.

    SECURITY:
    - project must be server-derived
    - shell=False is always used

    Args:
        project: Compose project name
        timeout: Timeout for docker command

    Returns:
        List of container names
    """
    if not is_lab_project(project):
        logger.debug(f"Refusing to list containers for non-lab project: {project}")
        return []

    cmd = [
        "docker", "ps",
        "--format", "{{.Names}}",
        "--filter", f"label=com.docker.compose.project={project}",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        if result.returncode != 0:
            logger.debug(f"Failed to list container names for {project}: {result.stderr.strip()[:100]}")
            return []

        names = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        return names

    except subprocess.TimeoutExpired:
        logger.debug(f"Timeout listing container names for {project}")
        return []
    except Exception as e:
        logger.debug(f"Error listing container names for {project}: {type(e).__name__}")
        return []


def force_remove_containers(
    container_ids: list[str],
    timeout: float = 30.0,
) -> tuple[int, str | None]:
    """Force remove containers by ID.

    SECURITY:
    - IDs must be server-derived (from list_running_container_ids_for_project)
    - shell=False is always used
    - Returns (rc, sanitized_stderr_excerpt)

    Args:
        container_ids: List of container IDs to remove
        timeout: Timeout for docker command

    Returns:
        Tuple of (return_code, sanitized_stderr_excerpt_or_none)
    """
    if not container_ids:
        return 0, None

    cmd = ["docker", "rm", "-f", *container_ids]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        stderr_excerpt = _sanitize_stderr(result.stderr) if result.returncode != 0 else None
        return result.returncode, stderr_excerpt

    except subprocess.TimeoutExpired:
        logger.debug(f"Timeout force-removing containers")
        return -1, "timeout"
    except Exception as e:
        logger.debug(f"Error force-removing containers: {type(e).__name__}")
        return -1, f"error: {type(e).__name__}"


def list_project_networks_robust(
    project: str,
    timeout: float = 10.0,
) -> list[str]:
    """List networks for a compose project with fallback discovery.

    First tries label-based discovery. If empty, falls back to name-based
    pattern matching as defense-in-depth.

    SECURITY:
    - project must be server-derived (octolab_<uuid> format)
    - shell=False is always used
    - Cap to 50 networks max

    Args:
        project: Compose project name
        timeout: Timeout for docker command

    Returns:
        List of network names (capped to 50)
    """
    if not is_lab_project(project):
        logger.debug(f"Refusing to list networks for non-lab project: {project}")
        return []

    # Try label-based discovery first
    networks = list_networks_by_compose_project(project, timeout)

    if networks:
        return networks[:50]

    # Fallback: name-based pattern matching
    # Extract UUID from project name for pattern matching
    lab_id = extract_lab_id_from_project(project)
    if not lab_id:
        return []

    # List all networks and filter by pattern
    cmd = ["docker", "network", "ls", "--format", "{{.Name}}"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        if result.returncode != 0:
            return []

        # Filter to networks that start with octolab_ and contain the lab UUID
        matched = []
        for line in result.stdout.strip().split("\n"):
            name = line.strip()
            if (name.startswith(OCTOLAB_NETWORK_PREFIX) and
                lab_id in name and
                is_octolab_lab_network(name)):
                matched.append(name)

        return matched[:50]

    except subprocess.TimeoutExpired:
        logger.debug(f"Timeout listing networks for fallback discovery")
        return []
    except Exception as e:
        logger.debug(f"Error in fallback network discovery: {type(e).__name__}")
        return []


def remove_detached_network(
    network_name: str,
    timeout: float = 30.0,
) -> bool:
    """Remove a network only if it has no attached containers.

    SECURITY:
    - network_name must be server-derived
    - shell=False is always used
    - Only removes if container count is 0

    Args:
        network_name: Network to remove
        timeout: Timeout for docker commands

    Returns:
        True if removed or already gone, False if still has containers or error
    """
    # Defense-in-depth: only touch octolab_ prefixed networks
    if not network_name.startswith(OCTOLAB_NETWORK_PREFIX):
        logger.debug(f"Refusing to remove non-octolab network: {network_name}")
        return False

    # Check if network has attached containers
    container_count = get_network_container_count(network_name, timeout)

    if container_count > 0:
        logger.debug(f"Network {network_name} has {container_count} containers, cannot remove")
        return False

    if container_count < 0:
        # Inspect failed - network may not exist
        # Try to remove anyway, treat NOT_FOUND as success
        pass

    # Try to remove
    rm_result = remove_network(network_name, int(timeout))
    return rm_result in (NetworkRemoveResult.OK, NetworkRemoveResult.NOT_FOUND)


# =============================================================================
# State-Driven Stop with Verification
# =============================================================================


@dataclass
class ProjectStopResult:
    """Result of stopping a single project with verification.

    Contains the full verify->act->verify state machine result.
    """

    project: str
    pre_running: int = 0  # Container count before any action
    down_rc: int | None = None  # compose down return code
    down_stderr: str | None = None  # Sanitized stderr excerpt
    remaining_after_down: int = 0  # Containers still running after compose down
    rm_rc: int | None = None  # docker rm -f return code (if used)
    rm_stderr: str | None = None  # Sanitized stderr excerpt
    remaining_final: int = 0  # Containers still running after all attempts
    networks_removed: int = 0
    networks_failed: int = 0
    verified_stopped: bool = False  # True only if remaining_final == 0
    error: str | None = None


@dataclass
class VerifiedStopLabsResult:
    """Result of batch stop-labs operation with verification.

    All counts are verified via docker queries, not assumed from exit codes.
    """

    targets: int = 0
    projects_stopped: int = 0  # Verified: remaining_final == 0
    projects_failed: int = 0  # Verified: remaining_final > 0
    containers_force_removed: int = 0  # Count of containers removed via rm -f
    networks_removed: int = 0
    networks_failed: int = 0
    errors: list[str] = field(default_factory=list)
    results: list[ProjectStopResult] = field(default_factory=list)


def stop_project_verified(
    project: str,
    compose_dir: str,
    compose_file: str,
    timeout: float = 120.0,
) -> ProjectStopResult:
    """Stop a lab project with full state verification.

    Implements verify->act->verify pattern:
    1. Pre-check: count running containers
    2. Act: run compose down
    3. Verify: count remaining containers
    4. Fallback: if containers remain, run docker rm -f
    5. Final verify: count remaining containers
    6. Cleanup: only remove networks if final count is 0

    SECURITY:
    - project must be server-derived (octolab_<uuid> format)
    - shell=False is always used
    - Never runs global prune

    Args:
        project: Compose project name (must match octolab_<uuid> pattern)
        compose_dir: Directory containing compose file
        compose_file: Path to compose file
        timeout: Timeout for compose down

    Returns:
        ProjectStopResult with full verification data
    """
    result = ProjectStopResult(project=project)

    # Defense-in-depth: verify project matches lab pattern
    if not is_lab_project(project):
        result.error = f"Invalid project name: {project}"
        return result

    # Step 0: Pre-check - count running containers
    pre_ids = list_running_container_ids_for_project(project, timeout=10.0)
    result.pre_running = len(pre_ids)

    if result.pre_running == 0:
        # Already stopped - just verify networks are cleaned up
        result.verified_stopped = True
        nets = list_project_networks_robust(project, timeout=10.0)
        for net in nets:
            if remove_detached_network(net, timeout=30.0):
                result.networks_removed += 1
            else:
                result.networks_failed += 1
        return result

    # Step 1: Attempt compose down (best effort)
    cmd = [
        "docker", "compose",
        "--project-directory", compose_dir,
        "-f", compose_file,
        "-p", project,
        "down", "--remove-orphans",
    ]

    try:
        proc_result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=compose_dir,
            shell=False,
        )
        result.down_rc = proc_result.returncode
        if proc_result.returncode != 0:
            result.down_stderr = _sanitize_stderr(proc_result.stderr)
            logger.debug(f"compose down for {project} rc={proc_result.returncode}")
    except subprocess.TimeoutExpired:
        result.down_rc = -1
        result.down_stderr = "timeout"
        logger.debug(f"compose down for {project} timed out")
    except Exception as e:
        result.down_rc = -1
        result.down_stderr = f"error: {type(e).__name__}"
        logger.debug(f"compose down for {project} failed: {type(e).__name__}")

    # Step 2: Verify - count remaining containers after compose down
    ids_after_down = list_running_container_ids_for_project(project, timeout=10.0)
    result.remaining_after_down = len(ids_after_down)

    # Step 3: Fallback - if containers remain, force remove them
    if ids_after_down:
        logger.info(f"Project {project} has {len(ids_after_down)} containers after compose down, using rm -f")
        rm_rc, rm_stderr = force_remove_containers(ids_after_down, timeout=30.0)
        result.rm_rc = rm_rc
        result.rm_stderr = rm_stderr

    # Step 4: Final verify - count remaining containers
    ids_final = list_running_container_ids_for_project(project, timeout=10.0)
    result.remaining_final = len(ids_final)

    # Step 5: Determine if stopped
    result.verified_stopped = (result.remaining_final == 0)

    if not result.verified_stopped:
        result.error = f"Failed to stop: {result.remaining_final} containers still running"
        logger.warning(f"Project {project} still has {result.remaining_final} running containers after all attempts")
        # Do NOT attempt network cleanup if containers still running
        return result

    # Step 6: Clean up networks (only if containers are gone)
    nets = list_project_networks_robust(project, timeout=10.0)
    for net in nets:
        if remove_detached_network(net, timeout=30.0):
            result.networks_removed += 1
            logger.debug(f"Removed network {net}")
        else:
            result.networks_failed += 1
            logger.debug(f"Failed to remove network {net}")

    logger.info(
        f"Project {project} verified stopped: "
        f"pre={result.pre_running}, after_down={result.remaining_after_down}, "
        f"final={result.remaining_final}, networks_removed={result.networks_removed}"
    )

    return result


# =============================================================================
# Network Leak Inspection Types
# =============================================================================


@dataclass
class AttachedContainerInfo:
    """Information about a container attached to a network."""

    container_id: str
    name: str
    state: str  # "running", "exited", or "unknown"
    project: str | None  # com.docker.compose.project label
    is_lab: bool  # True if project matches octolab_<uuid> pattern


@dataclass
class NetworkLeakInfo:
    """Detailed information about a network for leak inspection."""

    network: str
    attached_containers: int
    attached_running: int
    attached_exited: int
    lab_attached: int
    nonlab_attached: int
    blocked_by_nonlab: bool  # True if any nonlab containers are attached
    sample: list[AttachedContainerInfo]  # Up to 5 containers


@dataclass
class NetworkLeaksResult:
    """Result of network leak inspection."""

    total_candidates: int
    detached: int  # Networks with 0 containers
    in_use: int  # Networks with containers attached
    blocked_by_nonlab: int  # Networks with nonlab containers attached
    networks: list[NetworkLeakInfo]


def inspect_container_state(
    container_id: str,
    timeout: float = 10.0,
) -> AttachedContainerInfo | None:
    """Inspect a container to get its state and project label.

    SECURITY: shell=False is always used.

    Args:
        container_id: Container ID to inspect
        timeout: Timeout for docker command

    Returns:
        AttachedContainerInfo or None on error
    """
    # Use docker inspect with multiple format fields
    cmd = [
        "docker", "inspect",
        "--format",
        "{{.Name}}\t{{.State.Running}}\t{{.State.Status}}\t{{index .Config.Labels \"com.docker.compose.project\"}}",
        container_id,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        if result.returncode != 0:
            return None

        parts = result.stdout.strip().split("\t")
        if len(parts) < 3:
            return None

        name = parts[0].lstrip("/")  # Remove leading slash from name
        running = parts[1].lower() == "true"
        status = parts[2].lower() if len(parts) > 2 else "unknown"
        project = parts[3] if len(parts) > 3 and parts[3] else None

        # Determine state
        if running:
            state = "running"
        elif status == "exited":
            state = "exited"
        else:
            state = "unknown"

        return AttachedContainerInfo(
            container_id=container_id,
            name=name,
            state=state,
            project=project,
            is_lab=is_lab_project(project) if project else False,
        )

    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


def inspect_network_leak(
    network_name: str,
    max_sample: int = 5,
    timeout: float = 10.0,
) -> NetworkLeakInfo | None:
    """Inspect a network to determine why it might be "in use".

    Gets attached containers and classifies them by state (running/exited)
    and type (lab/nonlab).

    SECURITY: shell=False is always used.

    Args:
        network_name: Network name to inspect
        max_sample: Maximum number of containers to inspect for sample
        timeout: Timeout for docker commands

    Returns:
        NetworkLeakInfo or None on error
    """
    # Get containers attached to this network
    containers_dict = inspect_network_containers(network_name, timeout=int(timeout))

    if containers_dict is None:
        return None

    result = NetworkLeakInfo(
        network=network_name,
        attached_containers=len(containers_dict),
        attached_running=0,
        attached_exited=0,
        lab_attached=0,
        nonlab_attached=0,
        blocked_by_nonlab=False,
        sample=[],
    )

    if not containers_dict:
        return result

    # Inspect up to max_sample containers
    container_ids = list(containers_dict.keys())[:max_sample]

    for cid in container_ids:
        info = inspect_container_state(cid, timeout)
        if info:
            result.sample.append(info)

            # Update counts
            if info.state == "running":
                result.attached_running += 1
            elif info.state == "exited":
                result.attached_exited += 1

            if info.is_lab:
                result.lab_attached += 1
            else:
                result.nonlab_attached += 1

    # If we only sampled some containers, estimate totals
    # For running/exited, we can only count what we sampled
    # For lab/nonlab blocking, one nonlab is enough to block
    result.blocked_by_nonlab = result.nonlab_attached > 0

    return result


def scan_network_leaks(
    limit: int = 50,
    timeout: float = 30.0,
) -> NetworkLeaksResult:
    """Scan for network leaks and classify attached containers.

    This is the investigative function that shows WHY networks are "in use".

    SECURITY:
    - shell=False is always used
    - Only returns lab networks (octolab_<uuid>_* pattern)
    - Bounded output (capped to limit)
    - No sensitive data returned

    Args:
        limit: Maximum networks to return (default 50)
        timeout: Timeout for docker commands

    Returns:
        NetworkLeaksResult with classification and samples
    """
    result = NetworkLeaksResult(
        total_candidates=0,
        detached=0,
        in_use=0,
        blocked_by_nonlab=0,
        networks=[],
    )

    # Get all candidate networks (lab pattern only)
    networks = list_all_octolab_networks(timeout)
    result.total_candidates = len(networks)

    if not networks:
        return result

    # Cap to 200 for safety
    networks = networks[:200]

    # Inspect each network
    in_use_networks: list[NetworkLeakInfo] = []

    for net_name in networks:
        info = inspect_network_leak(net_name, max_sample=5, timeout=10.0)

        if info is None:
            continue

        if info.attached_containers == 0:
            result.detached += 1
        else:
            result.in_use += 1
            if info.blocked_by_nonlab:
                result.blocked_by_nonlab += 1
            in_use_networks.append(info)

    # Sort: blocked_by_nonlab first, then by attached_containers descending
    in_use_networks.sort(
        key=lambda n: (not n.blocked_by_nonlab, -n.attached_containers)
    )

    # Cap to limit
    result.networks = in_use_networks[:limit]

    return result


# =============================================================================
# Extended Cleanup Functions (with exited container removal)
# =============================================================================


class CleanupMode(str, Enum):
    """Mode for network cleanup operation."""

    NETWORKS_ONLY = "networks_only"
    REMOVE_EXITED_LAB_CONTAINERS_THEN_NETWORKS = "remove_exited_lab_containers_then_networks"


@dataclass
class SkippedNetworkSample:
    """Sample info for a skipped network (for debug output)."""

    network: str
    reason: str
    sample: list[AttachedContainerInfo]


@dataclass
class ExtendedCleanupResult:
    """Result of extended network cleanup operation."""

    mode: str
    networks_found: int
    networks_removed: int
    networks_failed: int
    networks_skipped_in_use_running: int
    networks_skipped_in_use_exited: int
    networks_skipped_blocked_nonlab: int
    containers_removed: int
    skipped_samples: list[SkippedNetworkSample]  # For debug output


def remove_lab_containers_by_id(
    container_ids: list[str],
    timeout: float = 30.0,
) -> tuple[int, list[str]]:
    """Remove lab containers by ID (not running containers).

    SECURITY:
    - Only removes containers if they are NOT running
    - Uses docker rm (without -f) for safety
    - shell=False is always used

    Args:
        container_ids: Container IDs to remove
        timeout: Timeout for docker command

    Returns:
        Tuple of (removed_count, errors)
    """
    if not container_ids:
        return 0, []

    removed = 0
    errors: list[str] = []

    # Use docker rm (not docker rm -f) for safety - won't remove running containers
    cmd = ["docker", "rm", *container_ids]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        if result.returncode == 0:
            # All removed successfully
            removed = len(container_ids)
        else:
            # Some may have failed - count successes by parsing stdout
            # Each removed container prints its ID on a line
            removed_ids = set(result.stdout.strip().split("\n"))
            removed = len([cid for cid in container_ids if cid in removed_ids])

            if result.stderr:
                stderr_excerpt = result.stderr.strip()[:200]
                if stderr_excerpt:
                    errors.append(stderr_excerpt)

    except subprocess.TimeoutExpired:
        errors.append("timeout removing containers")
    except Exception as e:
        errors.append(f"error: {type(e).__name__}")

    return removed, errors


def extended_network_cleanup(
    mode: CleanupMode,
    debug: bool = False,
    timeout: float = 30.0,
) -> ExtendedCleanupResult:
    """Extended cleanup of OctoLab networks with exited container handling.

    SECURITY:
    - Refuses if any RUNNING lab containers exist
    - Only operates on networks matching strict lab pattern
    - Only removes containers if ALL of:
      - container is NOT running
      - container project matches octolab_<uuid> pattern
      - container is attached to a lab network being cleaned
    - If any nonlab containers are attached, refuses to delete that network
    - Never runs docker network prune or system prune
    - shell=False on all subprocess calls

    Args:
        mode: CleanupMode.NETWORKS_ONLY or REMOVE_EXITED_LAB_CONTAINERS_THEN_NETWORKS
        debug: If True, include skipped network samples in result
        timeout: Timeout per operation

    Returns:
        ExtendedCleanupResult with detailed counts
    """
    result = ExtendedCleanupResult(
        mode=mode.value,
        networks_found=0,
        networks_removed=0,
        networks_failed=0,
        networks_skipped_in_use_running=0,
        networks_skipped_in_use_exited=0,
        networks_skipped_blocked_nonlab=0,
        containers_removed=0,
        skipped_samples=[],
    )

    # Step 1: Check for running LAB containers (refuse if any)
    container_status = get_running_container_status(timeout=10.0)
    if container_status.running_lab_containers > 0:
        # This should have been checked by caller, but defense-in-depth
        logger.warning(
            f"Extended cleanup REFUSED: {container_status.running_lab_containers} running lab containers"
        )
        return result

    # Step 2: Get all candidate networks
    networks = list_all_octolab_networks(timeout)
    result.networks_found = len(networks)

    if not networks:
        return result

    # Step 3: Process each network
    for net_name in networks:
        # Inspect network to get attached containers
        info = inspect_network_leak(net_name, max_sample=10, timeout=10.0)

        if info is None:
            result.networks_failed += 1
            continue

        if info.attached_containers == 0:
            # Detached - try to remove
            rm_result = remove_network(net_name, int(timeout))
            if rm_result in (NetworkRemoveResult.OK, NetworkRemoveResult.NOT_FOUND):
                result.networks_removed += 1
            else:
                result.networks_failed += 1
            continue

        # Network has attached containers - classify situation
        has_running = info.attached_running > 0
        has_exited = info.attached_exited > 0
        has_nonlab = info.nonlab_attached > 0

        # Case 1: Running containers attached
        if has_running:
            result.networks_skipped_in_use_running += 1
            if debug:
                result.skipped_samples.append(SkippedNetworkSample(
                    network=net_name,
                    reason="in_use_running",
                    sample=info.sample[:3],
                ))
            continue

        # Case 2: Nonlab containers attached (even if exited)
        if has_nonlab:
            result.networks_skipped_blocked_nonlab += 1
            if debug:
                result.skipped_samples.append(SkippedNetworkSample(
                    network=net_name,
                    reason="blocked_by_nonlab",
                    sample=info.sample[:3],
                ))
            continue

        # Case 3: Only exited lab containers attached
        if has_exited:
            if mode == CleanupMode.NETWORKS_ONLY:
                # Just skip - don't remove containers
                result.networks_skipped_in_use_exited += 1
                if debug:
                    result.skipped_samples.append(SkippedNetworkSample(
                        network=net_name,
                        reason="in_use_exited",
                        sample=info.sample[:3],
                    ))
                continue

            # Mode is REMOVE_EXITED_LAB_CONTAINERS_THEN_NETWORKS
            # Get all container IDs attached to this network
            containers_dict = inspect_network_containers(net_name, timeout=int(timeout))
            if not containers_dict:
                # Race condition - network now empty, try to remove
                rm_result = remove_network(net_name, int(timeout))
                if rm_result in (NetworkRemoveResult.OK, NetworkRemoveResult.NOT_FOUND):
                    result.networks_removed += 1
                else:
                    result.networks_failed += 1
                continue

            # Verify all containers are exited lab containers before removing
            container_ids = list(containers_dict.keys())
            safe_to_remove: list[str] = []

            for cid in container_ids:
                cinfo = inspect_container_state(cid, timeout=5.0)
                if cinfo is None:
                    # Can't verify - skip this container
                    continue
                if cinfo.state == "running":
                    # Running container found - abort
                    logger.debug(f"Found running container {cid} on {net_name}, skipping")
                    break
                if not cinfo.is_lab:
                    # Nonlab container - abort
                    logger.debug(f"Found nonlab container {cid} on {net_name}, skipping")
                    break
                # Safe to remove: exited + lab
                safe_to_remove.append(cid)
            else:
                # All containers are exited lab containers
                if safe_to_remove:
                    removed, _ = remove_lab_containers_by_id(safe_to_remove, timeout)
                    result.containers_removed += removed

                # Re-inspect network to see if now empty
                new_count = get_network_container_count(net_name, timeout)
                if new_count == 0:
                    rm_result = remove_network(net_name, int(timeout))
                    if rm_result in (NetworkRemoveResult.OK, NetworkRemoveResult.NOT_FOUND):
                        result.networks_removed += 1
                    else:
                        result.networks_failed += 1
                else:
                    # Still has containers after removal - something unexpected
                    result.networks_skipped_in_use_exited += 1
                    if debug:
                        result.skipped_samples.append(SkippedNetworkSample(
                            network=net_name,
                            reason="containers_remain_after_removal",
                            sample=[],
                        ))
                continue

            # If we broke out of the loop, something blocked removal
            result.networks_skipped_blocked_nonlab += 1
            if debug:
                result.skipped_samples.append(SkippedNetworkSample(
                    network=net_name,
                    reason="blocked_during_verification",
                    sample=info.sample[:3],
                ))

    # Cap skipped_samples for response
    if len(result.skipped_samples) > 10:
        result.skipped_samples = result.skipped_samples[:10]

    return result


def stop_projects_verified_batch(
    projects: list[str],
    compose_dir: str,
    compose_file: str,
    timeout_per_project: float = 120.0,
) -> VerifiedStopLabsResult:
    """Stop multiple lab projects with full state verification.

    Each project goes through verify->act->verify pattern.

    SECURITY:
    - All projects must be server-derived (from runtime scan)
    - shell=False is always used
    - Never runs global prune

    Args:
        projects: List of project names to stop
        compose_dir: Directory containing compose file
        compose_file: Path to compose file
        timeout_per_project: Timeout per project

    Returns:
        VerifiedStopLabsResult with verified counts and per-project results
    """
    result = VerifiedStopLabsResult(targets=len(projects))

    for project in projects:
        proj_result = stop_project_verified(
            project,
            compose_dir,
            compose_file,
            timeout_per_project,
        )

        result.results.append(proj_result)

        if proj_result.verified_stopped:
            result.projects_stopped += 1
        else:
            result.projects_failed += 1
            if proj_result.error:
                result.errors.append(f"{project}: {proj_result.error}")

        # Count force-removed containers
        if proj_result.rm_rc is not None and proj_result.rm_rc == 0:
            # Estimate force-removed count
            force_removed = proj_result.remaining_after_down - proj_result.remaining_final
            if force_removed > 0:
                result.containers_force_removed += force_removed

        result.networks_removed += proj_result.networks_removed
        result.networks_failed += proj_result.networks_failed

    # Truncate errors list
    if len(result.errors) > 20:
        result.errors = result.errors[:20] + [f"... and {len(result.errors) - 20} more"]

    return result
