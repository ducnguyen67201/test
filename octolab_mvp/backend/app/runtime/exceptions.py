"""Runtime exceptions for lab provisioning.

These exceptions represent operational failures during lab lifecycle management.
They are designed to be caught by the lab service and converted to user-friendly
HTTP responses with actionable guidance.

SECURITY: Exception messages may be exposed to users via API responses.
Never include secrets, internal paths, or container IDs in messages.
"""

from __future__ import annotations


class NetworkPoolExhaustedError(Exception):
    """Docker has no free subnets for new networks.

    This occurs when Docker's default address pool (172.17-31.x.x) is exhausted.
    Each docker-compose project creates a bridge network consuming one /16 subnet.

    Recovery:
    - Wait for labs to finish (teardown releases networks)
    - Run cleanup: docker network prune
    - Ops: Expand Docker's default-address-pools in daemon.json

    Attributes:
        cleaned_count: Number of networks cleaned during preflight attempt
        blocked_networks: Networks that couldn't be cleaned (containers attached)
    """

    def __init__(
        self,
        message: str = "Docker network pool exhausted",
        *,
        cleaned_count: int = 0,
        blocked_networks: list[str] | None = None,
    ):
        super().__init__(message)
        self.cleaned_count = cleaned_count
        self.blocked_networks = blocked_networks or []


class NetworkCleanupBlockedError(Exception):
    """Network removal blocked by non-allowlisted container.

    During preflight cleanup, we found a stale octolab_* network that has
    containers attached which are not in the CONTROL_PLANE_CONTAINERS allowlist.
    We refuse to force-disconnect unknown containers for safety.

    This typically indicates:
    - A lab container that didn't get cleaned up properly
    - Manual docker-compose up left containers running
    - Another process using octolab_ prefixed networks

    Recovery:
    - Identify the blocking container: docker network inspect <network>
    - Stop the container manually if safe
    - Then retry lab creation

    Attributes:
        network_name: The network that couldn't be cleaned
        blocking_containers: Container names blocking cleanup
    """

    def __init__(
        self,
        message: str = "Network cleanup blocked by attached containers",
        *,
        network_name: str = "",
        blocking_containers: list[str] | None = None,
    ):
        super().__init__(message)
        self.network_name = network_name
        self.blocking_containers = blocking_containers or []


class LabProvisioningError(Exception):
    """Generic lab provisioning failure.

    Base class for provisioning errors that don't fit more specific categories.
    Prefer using more specific exceptions when the cause is known.
    """

    pass


class ContainerStartupError(Exception):
    """Container failed to start or become healthy.

    This occurs when docker-compose up succeeds but the container doesn't
    reach a healthy state within the timeout period.

    Attributes:
        container_name: Name of the container that failed
        exit_code: Container exit code if it exited
    """

    def __init__(
        self,
        message: str = "Container failed to start",
        *,
        container_name: str = "",
        exit_code: int | None = None,
    ):
        super().__init__(message)
        self.container_name = container_name
        self.exit_code = exit_code
