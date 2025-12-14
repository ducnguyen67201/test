"""MicroVM Network Daemon Client.

Client for communicating with microvm-netd, the privileged network helper.

SECURITY:
- Connects only via UNIX socket (no network exposure)
- Validates all responses strictly
- Redacts paths in error messages returned to API users
- Keeps full details only in server logs at debug level

Usage:
    from app.services.microvm_net_client import (
        ping_netd, alloc_vm_net, release_vm_net, diag_vm_net
    )

    # Check if netd is running
    ok, err = await ping_netd()

    # Allocate network for VM (new API)
    params = await alloc_vm_net(lab_id)
    # Returns VMNetworkParams with tap, guest_ip, gateway, netmask, dns

    # Release network for VM
    await release_vm_net(lab_id)

    # Diagnose network status
    status = await diag_vm_net(lab_id)
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

DEFAULT_SOCKET_PATH = "/run/octolab/microvm-netd.sock"
DEFAULT_TIMEOUT = 5.0
MAX_RESPONSE_SIZE = 16384


# =============================================================================
# Exceptions
# =============================================================================


class NetworkError(Exception):
    """Base exception for network errors.

    Attributes:
        code: Error code (e.g., "EPERM", "SOCKET_ERROR", "TIMEOUT")
        message: Human-readable error message (redacted for API)
        details: Full error details (for server logs only)
    """

    def __init__(self, code: str, message: str, details: str | None = None):
        self.code = code
        self.message = message
        self.details = details or message
        super().__init__(f"{code}: {message}")


class NetdUnavailableError(NetworkError):
    """Raised when netd socket is not available."""

    def __init__(self, details: str | None = None):
        super().__init__(
            "NETD_UNAVAILABLE",
            "Network daemon not running or not accessible",
            details,
        )


class NetdProtocolError(NetworkError):
    """Raised when netd response is malformed."""

    def __init__(self, details: str | None = None):
        super().__init__(
            "NETD_PROTOCOL_ERROR",
            "Invalid response from network daemon",
            details,
        )


class NetdPermissionError(NetworkError):
    """Raised when netd reports permission denied."""

    def __init__(self, details: str | None = None):
        super().__init__(
            "EPERM",
            "Network operation not permitted (check netd permissions)",
            details,
        )


class NetdCompatError(NetworkError):
    """Raised when netd API is incompatible."""

    def __init__(self, message: str, details: str | None = None):
        super().__init__(
            "NETD_COMPAT_ERROR",
            message,
            details,
        )


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class NetdResult:
    """Result from netd operation."""

    ok: bool
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def bridge(self) -> str | None:
        """Get bridge name from result."""
        if self.result:
            return self.result.get("bridge")
        return None

    @property
    def tap(self) -> str | None:
        """Get TAP name from result."""
        if self.result:
            return self.result.get("tap")
        return None


@dataclass
class VMNetworkParams:
    """Network parameters for a VM.

    Returned by alloc_vm_net and contains all info needed to configure
    the VM's network.
    """

    tap: str          # TAP device name (e.g., "otp1a2b3c4d5e")
    guest_ip: str     # IP for VM (e.g., "10.200.123.45")
    gateway: str      # Gateway IP (e.g., "10.200.0.1")
    netmask: str      # Netmask (e.g., "255.255.0.0")
    dns: str          # DNS server (e.g., "8.8.8.8")
    bridge: str       # Bridge name (e.g., "br-octonet")

    @property
    def cidr_prefix(self) -> int:
        """Get CIDR prefix from netmask."""
        # Convert netmask to CIDR prefix
        netmask_map = {
            "255.255.255.255": 32,
            "255.255.255.0": 24,
            "255.255.0.0": 16,
            "255.0.0.0": 8,
        }
        return netmask_map.get(self.netmask, 16)

    @property
    def guest_ip_cidr(self) -> str:
        """Get guest IP with CIDR notation."""
        return f"{self.guest_ip}/{self.cidr_prefix}"


@dataclass
class VMNetworkDiag:
    """Diagnostic info for a VM's network."""

    lab_id_suffix: str
    tap_name: str
    tap_exists: bool
    tap_state: str | None
    tap_master: str | None
    bridge_name: str
    bridge_exists: bool
    guest_ip: str
    gateway: str
    netmask: str
    dns: str
    healthy: bool


@dataclass
class VMNetdHello:
    """Response from netd hello handshake."""

    api_version: int
    supported_ops: frozenset[str]
    build_id: str | None = None
    name: str = "microvm-netd"


# =============================================================================
# Hello Cache (module-level)
# =============================================================================

# Cache for hello result to avoid repeated handshakes
_hello_cache: VMNetdHello | None = None


def _clear_hello_cache() -> None:
    """Clear the hello cache. For testing."""
    global _hello_cache
    _hello_cache = None


# =============================================================================
# Socket Path Resolution
# =============================================================================


def get_netd_socket_path() -> str:
    """Get the netd socket path from settings or default.

    Returns:
        Socket path string
    """
    try:
        from app.config import settings
        return getattr(settings, "microvm_netd_sock", DEFAULT_SOCKET_PATH)
    except ImportError:
        return DEFAULT_SOCKET_PATH


def netd_socket_exists() -> bool:
    """Check if netd socket exists.

    Returns:
        True if socket file exists
    """
    socket_path = get_netd_socket_path()
    return Path(socket_path).exists()


# =============================================================================
# Low-Level Communication
# =============================================================================


def _send_request_sync(
    request: dict[str, Any],
    socket_path: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> NetdResult:
    """Send request to netd synchronously.

    Args:
        request: Request dict (will be JSON encoded)
        socket_path: Override socket path
        timeout: Socket timeout

    Returns:
        NetdResult

    Raises:
        NetdUnavailableError: Socket not available
        NetdProtocolError: Invalid response
    """
    if socket_path is None:
        socket_path = get_netd_socket_path()

    # Check socket exists
    if not Path(socket_path).exists():
        raise NetdUnavailableError(f"Socket not found: {socket_path}")

    sock = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)

        try:
            sock.connect(socket_path)
        except socket.error as e:
            raise NetdUnavailableError(f"Cannot connect to netd: {e}")

        # Send request
        request_data = json.dumps(request).encode("utf-8")
        sock.sendall(request_data)

        # Receive response
        response_data = b""
        while len(response_data) < MAX_RESPONSE_SIZE:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk
            except socket.timeout:
                break

        if not response_data:
            raise NetdProtocolError("Empty response from netd")

        # Parse response
        try:
            response = json.loads(response_data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise NetdProtocolError(f"Invalid JSON response: {e}")

        # Validate response structure
        if not isinstance(response, dict):
            raise NetdProtocolError("Response is not a dict")

        ok = response.get("ok", False)

        if ok:
            # For hello, the entire response IS the result
            # For other ops, result is in response["result"]
            result = response.get("result") or response
            return NetdResult(ok=True, result=result)
        else:
            # Handle both old format (error={code, message}) and new format (error="CODE", message="...")
            error = response.get("error")
            message = response.get("message")

            if isinstance(error, dict):
                # Old format: {"error": {"code": "...", "message": "..."}}
                error_code = error.get("code", "UNKNOWN")
                error_message = error.get("message", "Unknown error")
            elif isinstance(error, str):
                # New format: {"error": "CODE", "message": "..."}
                error_code = error
                error_message = message or "Unknown error"
            else:
                error_code = "UNKNOWN"
                error_message = str(error) if error else "Unknown error"

            return NetdResult(ok=False, error_code=error_code, error_message=error_message)

    except NetdUnavailableError:
        raise
    except NetdProtocolError:
        raise
    except socket.timeout:
        raise NetdUnavailableError("Connection to netd timed out")
    except Exception as e:
        raise NetdUnavailableError(f"Unexpected error: {type(e).__name__}")
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass


async def _send_request(
    request: dict[str, Any],
    socket_path: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> NetdResult:
    """Send request to netd asynchronously.

    Args:
        request: Request dict
        socket_path: Override socket path
        timeout: Socket timeout

    Returns:
        NetdResult

    Raises:
        NetdUnavailableError: Socket not available
        NetdProtocolError: Invalid response
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: _send_request_sync(request, socket_path, timeout),
    )


# =============================================================================
# Public API
# =============================================================================


async def ping_netd(
    timeout: float = DEFAULT_TIMEOUT,
    socket_path: str | None = None,
) -> tuple[bool, str | None]:
    """Ping netd to check if it's running.

    Args:
        timeout: Socket timeout
        socket_path: Override socket path

    Returns:
        Tuple of (ok, error_message_or_none)
    """
    try:
        result = await _send_request({"op": "ping"}, socket_path, timeout)
        if result.ok:
            return True, None
        return False, result.error_message
    except NetworkError as e:
        return False, e.message
    except Exception as e:
        return False, f"Unexpected error: {type(e).__name__}"


def ping_netd_sync(
    timeout: float = DEFAULT_TIMEOUT,
    socket_path: str | None = None,
) -> tuple[bool, str | None]:
    """Ping netd synchronously.

    For use in doctor checks and other non-async contexts.

    Args:
        timeout: Socket timeout
        socket_path: Override socket path

    Returns:
        Tuple of (ok, error_message_or_none)
    """
    try:
        result = _send_request_sync({"op": "ping"}, socket_path, timeout)
        if result.ok:
            return True, None
        return False, result.error_message
    except NetworkError as e:
        return False, e.message
    except Exception as e:
        return False, f"Unexpected error: {type(e).__name__}"


# =============================================================================
# Hello / Compatibility Check
# =============================================================================

# Required ops for this client version
REQUIRED_OPS = frozenset({"alloc_vm_net", "release_vm_net", "diag_vm_net"})
REQUIRED_API_VERSION = 1


async def hello(
    timeout: float = DEFAULT_TIMEOUT,
    socket_path: str | None = None,
) -> VMNetdHello:
    """Send hello to netd and get API version info.

    Args:
        timeout: Socket timeout
        socket_path: Override socket path

    Returns:
        VMNetdHello with API version and supported ops

    Raises:
        NetdCompatError: If hello fails or response is invalid
        NetdUnavailableError: If netd is not running
    """
    try:
        result = await _send_request({"op": "hello"}, socket_path, timeout)

        if not result.ok:
            # hello op not supported (old netd)
            raise NetdCompatError(
                "microvm-netd handshake failed (missing hello); likely outdated netd",
                f"error: {result.error_code} - {result.error_message}",
            )

        if not result.result:
            raise NetdCompatError(
                "microvm-netd handshake failed (empty response)",
            )

        api_version = result.result.get("api_version")
        supported_ops = result.result.get("supported_ops", [])
        build_id = result.result.get("build_id")
        name = result.result.get("name", "microvm-netd")

        if api_version is None:
            raise NetdCompatError(
                "microvm-netd handshake failed (no api_version in response)",
            )

        return VMNetdHello(
            api_version=api_version,
            supported_ops=frozenset(supported_ops),
            build_id=build_id,
            name=name,
        )

    except NetdCompatError:
        raise
    except NetdUnavailableError:
        raise
    except NetworkError as e:
        raise NetdCompatError(
            f"microvm-netd handshake failed: {e.message}",
            e.details,
        )


def hello_sync(
    timeout: float = DEFAULT_TIMEOUT,
    socket_path: str | None = None,
) -> VMNetdHello:
    """Send hello to netd synchronously.

    For use in doctor checks and other non-async contexts.

    Args:
        timeout: Socket timeout
        socket_path: Override socket path

    Returns:
        VMNetdHello with API version and supported ops

    Raises:
        NetdCompatError: If hello fails or response is invalid
        NetdUnavailableError: If netd is not running
    """
    try:
        result = _send_request_sync({"op": "hello"}, socket_path, timeout)

        if not result.ok:
            raise NetdCompatError(
                "microvm-netd handshake failed (missing hello); likely outdated netd",
                f"error: {result.error_code} - {result.error_message}",
            )

        if not result.result:
            raise NetdCompatError(
                "microvm-netd handshake failed (empty response)",
            )

        api_version = result.result.get("api_version")
        supported_ops = result.result.get("supported_ops", [])
        build_id = result.result.get("build_id")
        name = result.result.get("name", "microvm-netd")

        if api_version is None:
            raise NetdCompatError(
                "microvm-netd handshake failed (no api_version in response)",
            )

        return VMNetdHello(
            api_version=api_version,
            supported_ops=frozenset(supported_ops),
            build_id=build_id,
            name=name,
        )

    except NetdCompatError:
        raise
    except NetdUnavailableError:
        raise
    except NetworkError as e:
        raise NetdCompatError(
            f"microvm-netd handshake failed: {e.message}",
            e.details,
        )


async def ensure_compatible(
    required_ops: frozenset[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    socket_path: str | None = None,
) -> VMNetdHello:
    """Ensure netd is compatible with this client.

    Uses cached hello result to avoid repeated handshakes.
    Raises NetdCompatError if incompatible.

    Args:
        required_ops: Set of required operations (default: REQUIRED_OPS)
        timeout: Socket timeout
        socket_path: Override socket path

    Returns:
        VMNetdHello (cached)

    Raises:
        NetdCompatError: If API mismatch or missing required ops
        NetdUnavailableError: If netd is not running
    """
    global _hello_cache

    if required_ops is None:
        required_ops = REQUIRED_OPS

    # Use cached result if available
    if _hello_cache is not None:
        hello_result = _hello_cache
    else:
        hello_result = await hello(timeout, socket_path)
        _hello_cache = hello_result

    # Validate API version
    if hello_result.api_version != REQUIRED_API_VERSION:
        raise NetdCompatError(
            f"microvm-netd API version mismatch: "
            f"got {hello_result.api_version}, need {REQUIRED_API_VERSION}",
            f"build_id: {hello_result.build_id}",
        )

    # Validate required ops
    missing_ops = required_ops - hello_result.supported_ops
    if missing_ops:
        raise NetdCompatError(
            f"microvm-netd API mismatch (wrong daemon behind socket). "
            f"Required ops: {sorted(required_ops)}; "
            f"supported ops: {sorted(hello_result.supported_ops)}; "
            f"api_version: {hello_result.api_version}",
            f"missing: {sorted(missing_ops)}, build_id: {hello_result.build_id}",
        )

    return hello_result


def ensure_compatible_sync(
    required_ops: frozenset[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    socket_path: str | None = None,
) -> VMNetdHello:
    """Ensure netd is compatible (synchronous version).

    Uses cached hello result to avoid repeated handshakes.

    Args:
        required_ops: Set of required operations (default: REQUIRED_OPS)
        timeout: Socket timeout
        socket_path: Override socket path

    Returns:
        VMNetdHello (cached)

    Raises:
        NetdCompatError: If API mismatch or missing required ops
        NetdUnavailableError: If netd is not running
    """
    global _hello_cache

    if required_ops is None:
        required_ops = REQUIRED_OPS

    # Use cached result if available
    if _hello_cache is not None:
        hello_result = _hello_cache
    else:
        hello_result = hello_sync(timeout, socket_path)
        _hello_cache = hello_result

    # Validate API version
    if hello_result.api_version != REQUIRED_API_VERSION:
        raise NetdCompatError(
            f"microvm-netd API version mismatch: "
            f"got {hello_result.api_version}, need {REQUIRED_API_VERSION}",
            f"build_id: {hello_result.build_id}",
        )

    # Validate required ops
    missing_ops = required_ops - hello_result.supported_ops
    if missing_ops:
        raise NetdCompatError(
            f"microvm-netd API mismatch (wrong daemon behind socket). "
            f"Required ops: {sorted(required_ops)}; "
            f"supported ops: {sorted(hello_result.supported_ops)}; "
            f"api_version: {hello_result.api_version}",
            f"missing: {sorted(missing_ops)}, build_id: {hello_result.build_id}",
        )

    return hello_result


async def create_lab_net(
    lab_id: UUID | str,
    timeout: float = DEFAULT_TIMEOUT,
    socket_path: str | None = None,
) -> dict[str, str]:
    """Create network for a lab.

    Args:
        lab_id: Lab UUID
        timeout: Socket timeout
        socket_path: Override socket path

    Returns:
        Dict with "bridge" and "tap" keys

    Raises:
        NetworkError: If operation fails
    """
    lab_id_str = str(lab_id)
    logger.info(f"Creating network for lab ...{lab_id_str[-6:]}")

    try:
        result = await _send_request(
            {"op": "create", "lab_id": lab_id_str},
            socket_path,
            timeout,
        )

        if not result.ok:
            error_code = result.error_code or "UNKNOWN"

            # Map error codes to specific exceptions
            if error_code == "EPERM":
                raise NetdPermissionError(
                    f"Cannot create network: {result.error_message}"
                )

            raise NetworkError(
                error_code,
                f"Network creation failed: {result.error_message}",
                result.error_message,
            )

        if not result.bridge or not result.tap:
            raise NetdProtocolError("Missing bridge or tap in response")

        logger.info(
            f"Network created for lab ...{lab_id_str[-6:]}: "
            f"bridge={result.bridge}, tap={result.tap}"
        )

        return {"bridge": result.bridge, "tap": result.tap}

    except NetworkError:
        raise
    except Exception as e:
        logger.error(f"Failed to create network for lab ...{lab_id_str[-6:]}: {e}")
        raise NetworkError(
            "CREATE_FAILED",
            "Failed to create lab network",
            str(e),
        )


async def destroy_lab_net(
    lab_id: UUID | str,
    timeout: float = DEFAULT_TIMEOUT,
    socket_path: str | None = None,
) -> bool:
    """Destroy network for a lab.

    Best-effort operation - logs errors but doesn't raise.

    Args:
        lab_id: Lab UUID
        timeout: Socket timeout
        socket_path: Override socket path

    Returns:
        True if successful, False otherwise
    """
    lab_id_str = str(lab_id)
    logger.info(f"Destroying network for lab ...{lab_id_str[-6:]}")

    try:
        result = await _send_request(
            {"op": "destroy", "lab_id": lab_id_str},
            socket_path,
            timeout,
        )

        if result.ok:
            logger.info(f"Network destroyed for lab ...{lab_id_str[-6:]}")
            return True
        else:
            logger.warning(
                f"Network destroy returned error for lab ...{lab_id_str[-6:]}: "
                f"{result.error_code}"
            )
            return False

    except Exception as e:
        logger.warning(
            f"Failed to destroy network for lab ...{lab_id_str[-6:]}: "
            f"{type(e).__name__}"
        )
        return False


async def list_lab_networks(
    timeout: float = DEFAULT_TIMEOUT,
    socket_path: str | None = None,
) -> list[dict[str, str]]:
    """List all lab network interfaces.

    Args:
        timeout: Socket timeout
        socket_path: Override socket path

    Returns:
        List of interface dicts

    Raises:
        NetworkError: If operation fails
    """
    try:
        result = await _send_request({"op": "list"}, socket_path, timeout)

        if not result.ok:
            raise NetworkError(
                result.error_code or "LIST_FAILED",
                "Failed to list lab networks",
                result.error_message,
            )

        interfaces = result.result.get("interfaces", []) if result.result else []
        return interfaces

    except NetworkError:
        raise
    except Exception as e:
        raise NetworkError(
            "LIST_FAILED",
            "Failed to list lab networks",
            str(e),
        )


# =============================================================================
# New API (Preferred)
# =============================================================================


async def alloc_vm_net(
    lab_id: UUID | str,
    timeout: float = DEFAULT_TIMEOUT,
    socket_path: str | None = None,
) -> VMNetworkParams:
    """Allocate network resources for a VM.

    Creates TAP device attached to shared bridge and returns network params.
    This is the preferred API over create_lab_net.

    Args:
        lab_id: Lab UUID
        timeout: Socket timeout
        socket_path: Override socket path

    Returns:
        VMNetworkParams with tap, guest_ip, gateway, netmask, dns

    Raises:
        NetworkError: If operation fails
        NetdCompatError: If netd API is incompatible
    """
    lab_id_str = str(lab_id)

    # Ensure netd is compatible (cached, cheap after first call)
    await ensure_compatible(timeout=timeout, socket_path=socket_path)

    logger.info(f"Allocating network for lab ...{lab_id_str[-6:]}")

    try:
        result = await _send_request(
            {"op": "alloc_vm_net", "lab_id": lab_id_str},
            socket_path,
            timeout,
        )

        if not result.ok:
            error_code = result.error_code or "UNKNOWN"

            # Handle UNKNOWN_OP with improved diagnostics
            if error_code == "UNKNOWN_OP":
                # Clear cache and try hello to get better diagnostics
                _clear_hello_cache()
                try:
                    hello_result = await hello(timeout, socket_path)
                    raise NetdCompatError(
                        f"microvm-netd does not support alloc_vm_net. "
                        f"Supported ops: {sorted(hello_result.supported_ops)}; "
                        f"api_version: {hello_result.api_version}",
                        f"build_id: {hello_result.build_id}",
                    )
                except NetdCompatError:
                    raise
                except Exception:
                    raise NetdCompatError(
                        "microvm-netd does not support alloc_vm_net (old daemon?)",
                        result.error_message,
                    )

            if error_code == "EPERM":
                raise NetdPermissionError(
                    f"Cannot allocate network: {result.error_message}"
                )

            raise NetworkError(
                error_code,
                f"Network allocation failed: {result.error_message}",
                result.error_message,
            )

        if not result.result:
            raise NetdProtocolError("Missing result in response")

        # Extract required fields
        tap = result.result.get("tap")
        guest_ip = result.result.get("guest_ip")
        gateway = result.result.get("gateway")
        netmask = result.result.get("netmask")
        dns = result.result.get("dns")
        bridge = result.result.get("bridge")

        if not all([tap, guest_ip, gateway, netmask, dns, bridge]):
            raise NetdProtocolError("Missing required fields in response")

        params = VMNetworkParams(
            tap=tap,
            guest_ip=guest_ip,
            gateway=gateway,
            netmask=netmask,
            dns=dns,
            bridge=bridge,
        )

        logger.info(
            f"Network allocated for lab ...{lab_id_str[-6:]}: "
            f"tap={params.tap}, ip={params.guest_ip}"
        )

        return params

    except NetworkError:
        raise
    except Exception as e:
        logger.error(f"Failed to allocate network for lab ...{lab_id_str[-6:]}: {e}")
        raise NetworkError(
            "ALLOC_FAILED",
            "Failed to allocate VM network",
            str(e),
        )


async def release_vm_net(
    lab_id: UUID | str,
    timeout: float = DEFAULT_TIMEOUT,
    socket_path: str | None = None,
) -> bool:
    """Release network resources for a VM.

    Destroys TAP device. Best-effort operation - logs errors but doesn't raise.
    This is the preferred API over destroy_lab_net.

    Args:
        lab_id: Lab UUID
        timeout: Socket timeout
        socket_path: Override socket path

    Returns:
        True if successful, False otherwise
    """
    lab_id_str = str(lab_id)

    # Ensure netd is compatible (cached, cheap after first call)
    # Best-effort: log warning but don't fail teardown
    try:
        await ensure_compatible(timeout=timeout, socket_path=socket_path)
    except NetdCompatError as e:
        logger.warning(f"Netd compat check failed during release: {e.message}")
        # Continue anyway - try to release

    logger.info(f"Releasing network for lab ...{lab_id_str[-6:]}")

    try:
        result = await _send_request(
            {"op": "release_vm_net", "lab_id": lab_id_str},
            socket_path,
            timeout,
        )

        if result.ok:
            logger.info(f"Network released for lab ...{lab_id_str[-6:]}")
            return True
        else:
            # Log UNKNOWN_OP with more context
            if result.error_code == "UNKNOWN_OP":
                logger.warning(
                    f"release_vm_net not supported for lab ...{lab_id_str[-6:]}. "
                    "Netd may be outdated."
                )
            else:
                logger.warning(
                    f"Network release returned error for lab ...{lab_id_str[-6:]}: "
                    f"{result.error_code}"
                )
            return False

    except Exception as e:
        logger.warning(
            f"Failed to release network for lab ...{lab_id_str[-6:]}: "
            f"{type(e).__name__}"
        )
        return False


async def diag_vm_net(
    lab_id: UUID | str,
    timeout: float = DEFAULT_TIMEOUT,
    socket_path: str | None = None,
) -> VMNetworkDiag:
    """Diagnose network status for a VM.

    Reports if TAP exists, bridge status, and network params.

    Args:
        lab_id: Lab UUID
        timeout: Socket timeout
        socket_path: Override socket path

    Returns:
        VMNetworkDiag with diagnostic info

    Raises:
        NetworkError: If operation fails
    """
    lab_id_str = str(lab_id)

    try:
        result = await _send_request(
            {"op": "diag_vm_net", "lab_id": lab_id_str},
            socket_path,
            timeout,
        )

        if not result.ok:
            raise NetworkError(
                result.error_code or "DIAG_FAILED",
                f"Network diagnosis failed: {result.error_message}",
                result.error_message,
            )

        if not result.result:
            raise NetdProtocolError("Missing result in response")

        r = result.result
        tap = r.get("tap", {})
        bridge = r.get("bridge", {})
        net_params = r.get("network_params", {})

        return VMNetworkDiag(
            lab_id_suffix=r.get("lab_id_suffix", lab_id_str[-6:]),
            tap_name=tap.get("name", ""),
            tap_exists=tap.get("exists", False),
            tap_state=tap.get("state"),
            tap_master=tap.get("master"),
            bridge_name=bridge.get("name", ""),
            bridge_exists=bridge.get("exists", False),
            guest_ip=net_params.get("guest_ip", ""),
            gateway=net_params.get("gateway", ""),
            netmask=net_params.get("netmask", ""),
            dns=net_params.get("dns", ""),
            healthy=r.get("healthy", False),
        )

    except NetworkError:
        raise
    except Exception as e:
        raise NetworkError(
            "DIAG_FAILED",
            "Failed to diagnose VM network",
            str(e),
        )


def alloc_vm_net_sync(
    lab_id: UUID | str,
    timeout: float = DEFAULT_TIMEOUT,
    socket_path: str | None = None,
) -> VMNetworkParams:
    """Synchronous version of alloc_vm_net.

    For use in doctor checks and other non-async contexts.

    Args:
        lab_id: Lab UUID
        timeout: Socket timeout
        socket_path: Override socket path

    Returns:
        VMNetworkParams with tap, guest_ip, gateway, netmask, dns

    Raises:
        NetworkError: If operation fails
    """
    lab_id_str = str(lab_id)

    result = _send_request_sync(
        {"op": "alloc_vm_net", "lab_id": lab_id_str},
        socket_path,
        timeout,
    )

    if not result.ok:
        error_code = result.error_code or "UNKNOWN"

        if error_code == "EPERM":
            raise NetdPermissionError(
                f"Cannot allocate network: {result.error_message}"
            )

        raise NetworkError(
            error_code,
            f"Network allocation failed: {result.error_message}",
            result.error_message,
        )

    if not result.result:
        raise NetdProtocolError("Missing result in response")

    return VMNetworkParams(
        tap=result.result.get("tap", ""),
        guest_ip=result.result.get("guest_ip", ""),
        gateway=result.result.get("gateway", ""),
        netmask=result.result.get("netmask", ""),
        dns=result.result.get("dns", ""),
        bridge=result.result.get("bridge", ""),
    )


# =============================================================================
# Testing/Verification
# =============================================================================


async def verify_netd_can_create_network(
    test_lab_id: str = "00000000-0000-0000-0000-000000000001",
    timeout: float = DEFAULT_TIMEOUT,
    socket_path: str | None = None,
) -> tuple[bool, str | None]:
    """Verify netd can create and destroy a test network.

    Creates a test bridge/tap, then immediately destroys it.
    Used by doctor checks to verify netd has necessary permissions.

    Args:
        test_lab_id: Fake lab ID for testing (will be destroyed)
        timeout: Socket timeout
        socket_path: Override socket path

    Returns:
        Tuple of (success, error_message_or_none)
    """
    try:
        # Try to create
        await create_lab_net(test_lab_id, timeout, socket_path)

        # Clean up
        await destroy_lab_net(test_lab_id, timeout, socket_path)

        return True, None

    except NetdPermissionError as e:
        return False, f"Permission denied: {e.details}"
    except NetworkError as e:
        return False, f"{e.code}: {e.message}"
    except Exception as e:
        return False, f"Unexpected error: {type(e).__name__}"


def verify_netd_can_create_network_sync(
    test_lab_id: str = "00000000-0000-0000-0000-000000000001",
    timeout: float = DEFAULT_TIMEOUT,
    socket_path: str | None = None,
) -> tuple[bool, str | None]:
    """Synchronous version of verify_netd_can_create_network.

    For use in doctor checks.

    Args:
        test_lab_id: Fake lab ID for testing
        timeout: Socket timeout
        socket_path: Override socket path

    Returns:
        Tuple of (success, error_message_or_none)
    """
    try:
        # Try to create
        result = _send_request_sync(
            {"op": "create", "lab_id": test_lab_id},
            socket_path,
            timeout,
        )

        if not result.ok:
            if result.error_code == "EPERM":
                return False, "Permission denied: netd cannot create bridges"
            return False, f"{result.error_code}: {result.error_message}"

        # Clean up
        _send_request_sync(
            {"op": "destroy", "lab_id": test_lab_id},
            socket_path,
            timeout,
        )

        return True, None

    except NetdUnavailableError as e:
        return False, e.message
    except Exception as e:
        return False, f"Unexpected error: {type(e).__name__}"


# =============================================================================
# Port Forwarding
# =============================================================================


@dataclass
class PortForwardResult:
    """Result from port forward operation."""

    host_port: int
    guest_ip: str
    guest_port: int


async def setup_port_forward(
    lab_id: UUID | str,
    host_port: int,
    guest_port: int = 6080,
    timeout: float = DEFAULT_TIMEOUT,
    socket_path: str | None = None,
) -> PortForwardResult:
    """Set up port forwarding from host to VM.

    Creates iptables DNAT rules to forward traffic from host_port to
    the VM's guest_ip:guest_port.

    Args:
        lab_id: Lab UUID
        host_port: Host port to forward from
        guest_port: Guest port to forward to (default: 6080 for noVNC)
        timeout: Socket timeout
        socket_path: Override socket path

    Returns:
        PortForwardResult with host_port, guest_ip, guest_port

    Raises:
        NetworkError: If operation fails
    """
    lab_id_str = str(lab_id)
    logger.info(
        f"Setting up port forward for lab ...{lab_id_str[-6:]}: "
        f"host:{host_port} -> guest:{guest_port}"
    )

    try:
        result = await _send_request(
            {
                "op": "setup_port_forward",
                "lab_id": lab_id_str,
                "host_port": host_port,
                "guest_port": guest_port,
            },
            socket_path,
            timeout,
        )

        if not result.ok:
            error_code = result.error_code or "UNKNOWN"

            if error_code == "EPERM":
                raise NetdPermissionError(
                    f"Cannot setup port forward: {result.error_message}"
                )

            raise NetworkError(
                error_code,
                f"Port forward setup failed: {result.error_message}",
                result.error_message,
            )

        if not result.result:
            raise NetdProtocolError("Missing result in response")

        r = result.result
        logger.info(
            f"Port forward set up for lab ...{lab_id_str[-6:]}: "
            f"{r.get('host_port')} -> {r.get('guest_ip')}:{r.get('guest_port')}"
        )

        return PortForwardResult(
            host_port=r.get("host_port", host_port),
            guest_ip=r.get("guest_ip", ""),
            guest_port=r.get("guest_port", guest_port),
        )

    except NetworkError:
        raise
    except Exception as e:
        logger.error(
            f"Failed to setup port forward for lab ...{lab_id_str[-6:]}: {e}"
        )
        raise NetworkError(
            "PORT_FORWARD_FAILED",
            "Failed to setup port forwarding",
            str(e),
        )


async def cleanup_port_forward(
    lab_id: UUID | str,
    timeout: float = DEFAULT_TIMEOUT,
    socket_path: str | None = None,
) -> bool:
    """Clean up port forwarding rules for a lab.

    Removes iptables DNAT rules. Best-effort operation - logs errors
    but doesn't raise.

    Args:
        lab_id: Lab UUID
        timeout: Socket timeout
        socket_path: Override socket path

    Returns:
        True if successful, False otherwise
    """
    lab_id_str = str(lab_id)
    logger.info(f"Cleaning up port forward for lab ...{lab_id_str[-6:]}")

    try:
        result = await _send_request(
            {"op": "cleanup_port_forward", "lab_id": lab_id_str},
            socket_path,
            timeout,
        )

        if result.ok:
            logger.info(f"Port forward cleaned up for lab ...{lab_id_str[-6:]}")
            return True
        else:
            logger.warning(
                f"Port forward cleanup returned error for lab ...{lab_id_str[-6:]}: "
                f"{result.error_code}"
            )
            return False

    except Exception as e:
        logger.warning(
            f"Failed to cleanup port forward for lab ...{lab_id_str[-6:]}: "
            f"{type(e).__name__}"
        )
        return False
