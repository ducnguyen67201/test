"""Firecracker microVM management for OctoLab.

SECURITY:
- Never log tokens or secrets.
- All subprocess calls use shell=False with list args.
- Enforce timeouts and output limits.
- Fail closed on any uncertainty.

This module provides:
- Preflight checks for Firecracker/KVM availability
- VM lifecycle management (create, destroy)
- vsock communication with guest agent
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import signal
import socket
import struct
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from app.config import settings
from app.services.firecracker_paths import (
    PathContainmentError,
    cleanup_lab_state_dir,
    ensure_lab_state_dir,
    lab_log_path,
    lab_pid_path,
    lab_rootfs_path,
    lab_socket_path,
    lab_state_dir,
    lab_token_path,
    redact_path,
    validate_lab_id,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# vsock address family (Linux-specific)
AF_VSOCK = 40  # socket.AF_VSOCK

# vsock special CIDs
VMADDR_CID_ANY = 0xFFFFFFFF
VMADDR_CID_HOST = 2

# Guest agent action allowlist (security: deny-by-default)
ALLOWED_AGENT_ACTIONS = frozenset({"ping", "uname", "id"})

# CID range for guest VMs (3-4294967294; 0-2 are reserved)
MIN_GUEST_CID = 100
MAX_GUEST_CID = 65535

# =============================================================================
# Boot Concurrency Control
# =============================================================================
# Semaphore to limit concurrent VM boots. Under load, multiple simultaneous
# boots can cause timeouts due to resource contention. This serializes boot
# operations to ensure reliable startup.
#
# Serialize VM boots to prevent I/O contention on limited hardware.
# Two VMs loading 247MB images simultaneously causes disk saturation.
# Can increase to 2+ after SSD/RAM upgrade or image optimization.
# The semaphore is module-level (not per-request) for global coordination.
MAX_CONCURRENT_BOOTS = 1
_boot_semaphore: asyncio.Semaphore | None = None


def _get_boot_semaphore() -> asyncio.Semaphore:
    """Get or create the boot semaphore (lazy init for event loop safety).

    The semaphore must be created in the context of a running event loop,
    so we lazily initialize it on first use rather than at module import.
    """
    global _boot_semaphore
    if _boot_semaphore is None:
        _boot_semaphore = asyncio.Semaphore(MAX_CONCURRENT_BOOTS)
    return _boot_semaphore


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class PreflightResult:
    """Result of preflight checks for Firecracker runtime.

    SECURITY: Never include secrets or full paths in this result.
    """

    has_kvm: bool = False
    can_access_kvm: bool = False
    firecracker_found: bool = False
    firecracker_version: str | None = None
    jailer_found: bool = False
    jailer_version: str | None = None
    jailer_usable: bool = False
    kernel_path_exists: bool = False
    rootfs_path_exists: bool = False
    vsock_supported: bool = False
    state_dir_writable: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def can_run(self) -> bool:
        """Check if Firecracker can run (fatal errors only)."""
        return (
            self.has_kvm
            and self.can_access_kvm
            and self.firecracker_found
            and self.kernel_path_exists
            and self.rootfs_path_exists
        )

    @property
    def can_run_safe(self) -> bool:
        """Check if Firecracker can run with full security (jailer)."""
        return self.can_run and self.jailer_usable

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for API response.

        SECURITY: Does not include paths or secrets.
        """
        return {
            "has_kvm": self.has_kvm,
            "can_access_kvm": self.can_access_kvm,
            "firecracker_found": self.firecracker_found,
            "firecracker_version": self.firecracker_version,
            "jailer_found": self.jailer_found,
            "jailer_version": self.jailer_version,
            "jailer_usable": self.jailer_usable,
            "kernel_path_exists": self.kernel_path_exists,
            "rootfs_path_exists": self.rootfs_path_exists,
            "vsock_supported": self.vsock_supported,
            "state_dir_writable": self.state_dir_writable,
            "can_run": self.can_run,
            "can_run_safe": self.can_run_safe,
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass
class VMMetadata:
    """Metadata for a running Firecracker VM.

    SECURITY: token is never logged or included in API responses.
    """

    lab_id: str
    pid: int | None = None
    cid: int | None = None
    api_sock_path: str | None = None
    state_dir: str | None = None
    # token is intentionally not in to_dict()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for API response.

        SECURITY: Does not include token or full paths.
        """
        return {
            "lab_id": self.lab_id,
            "pid": self.pid,
            "cid": self.cid,
            "api_sock_path_redacted": redact_path(self.api_sock_path)
            if self.api_sock_path
            else None,
            "state_dir_redacted": redact_path(self.state_dir)
            if self.state_dir
            else None,
        }


@dataclass
class AgentResponse:
    """Response from guest agent."""

    ok: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    error: str | None = None
    # Version fields from ping (None if not present)
    agent_version: str | None = None
    rootfs_build_id: str | None = None
    # Diag fields (None if not present)
    docker_ready: bool | None = None
    last_compose_status: dict | None = None
    # Docker build fields (None if not present)
    image: str | None = None
    image_id: str | None = None


# =============================================================================
# Preflight Checks
# =============================================================================


def _run_cmd_safe(
    args: list[str],
    timeout: float = 5.0,
    capture_output: bool = True,
) -> tuple[int, str, str]:
    """Run a command safely.

    SECURITY:
    - shell=False always
    - Captures and truncates output
    - Enforces timeout

    Returns:
        Tuple of (returncode, stdout, stderr)
    """
    try:
        result = subprocess.run(
            args,
            shell=False,
            capture_output=capture_output,
            text=True,
            timeout=timeout,
        )
        # Truncate output for safety
        stdout = result.stdout[:2048] if result.stdout else ""
        stderr = result.stderr[:2048] if result.stderr else ""
        return result.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        return -1, "", "command timed out"
    except FileNotFoundError:
        return -1, "", "command not found"
    except Exception as e:
        return -1, "", f"error: {type(e).__name__}"


def _check_kvm() -> tuple[bool, bool]:
    """Check if /dev/kvm exists and is accessible.

    Returns:
        Tuple of (exists, accessible)
    """
    kvm_path = Path("/dev/kvm")

    if not kvm_path.exists():
        return False, False

    # Check if we can open it for read/write
    try:
        with open(kvm_path, "r+b"):
            return True, True
    except PermissionError:
        return True, False
    except Exception:
        return True, False


def _get_binary_version(binary_path: str) -> str | None:
    """Get version string from a binary.

    Returns:
        Version string or None if not available
    """
    rc, stdout, _ = _run_cmd_safe([binary_path, "--version"], timeout=2.0)
    if rc == 0 and stdout:
        # Take first line, truncate
        return stdout.split("\n")[0][:100]
    return None


def _check_vsock_support() -> bool:
    """Check if vsock is available.

    Returns:
        True if vsock appears to be supported
    """
    # Check for vsock modules
    if Path("/dev/vsock").exists():
        return True

    # Try to load the module info
    rc, stdout, _ = _run_cmd_safe(["lsmod"], timeout=2.0)
    if rc == 0 and "vhost_vsock" in stdout:
        return True

    return False


def _check_jailer_usable() -> bool:
    """Check if jailer can be used.

    In WSL2, jailer often fails due to cgroup/namespace issues.

    Returns:
        True if jailer appears usable
    """
    jailer_path = settings.jailer_bin

    # Check if jailer binary exists
    rc, _, _ = _run_cmd_safe(["which", jailer_path], timeout=2.0)
    if rc != 0:
        return False

    # Try to run jailer with minimal args to see if it works
    # This is a best-effort check; actual usability may vary
    rc, _, stderr = _run_cmd_safe([jailer_path, "--version"], timeout=2.0)
    if rc != 0:
        return False

    # Check for common WSL issues
    if Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists():
        # We're in WSL; jailer may not work
        # But we'll let it try and fail gracefully
        pass

    return True


def preflight() -> PreflightResult:
    """Run preflight checks for Firecracker runtime.

    Returns:
        PreflightResult with check results and any errors/warnings

    SECURITY: Never includes secrets or sensitive paths in result.
    """
    result = PreflightResult()

    # Check KVM
    result.has_kvm, result.can_access_kvm = _check_kvm()
    if not result.has_kvm:
        result.errors.append("KVM not available (/dev/kvm missing)")
    elif not result.can_access_kvm:
        result.errors.append("Cannot access /dev/kvm (permission denied)")

    # Check Firecracker binary
    fc_path = settings.firecracker_bin
    rc, _, _ = _run_cmd_safe(["which", fc_path], timeout=2.0)
    result.firecracker_found = rc == 0
    if result.firecracker_found:
        result.firecracker_version = _get_binary_version(fc_path)
    else:
        result.errors.append(f"Firecracker binary not found")

    # Check Jailer binary
    jailer_path = settings.jailer_bin
    rc, _, _ = _run_cmd_safe(["which", jailer_path], timeout=2.0)
    result.jailer_found = rc == 0
    if result.jailer_found:
        result.jailer_version = _get_binary_version(jailer_path)
        result.jailer_usable = _check_jailer_usable()
    else:
        result.warnings.append("Jailer binary not found")

    if not result.jailer_usable:
        if settings.dev_unsafe_allow_no_jailer:
            result.warnings.append(
                "Jailer not usable; running without jailer (UNSAFE, dev only)"
            )
        else:
            result.errors.append(
                "Jailer not usable and OCTOLAB_DEV_UNSAFE_ALLOW_NO_JAILER is not set"
            )

    # Check kernel path
    kernel_path = settings.microvm_kernel_path
    if kernel_path:
        result.kernel_path_exists = Path(kernel_path).exists()
        if not result.kernel_path_exists:
            result.errors.append("Kernel image not found")
    else:
        result.errors.append("OCTOLAB_MICROVM_KERNEL_PATH not set")

    # Check rootfs path
    rootfs_path = settings.microvm_rootfs_base_path
    if rootfs_path:
        result.rootfs_path_exists = Path(rootfs_path).exists()
        if not result.rootfs_path_exists:
            result.errors.append("Base rootfs image not found")
    else:
        result.errors.append("OCTOLAB_MICROVM_ROOTFS_BASE_PATH not set")

    # Check vsock support
    result.vsock_supported = _check_vsock_support()
    if not result.vsock_supported:
        result.warnings.append("vsock may not be available")

    # Check state directory
    state_dir = Path(settings.microvm_state_dir)
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        test_file = state_dir / ".write_test"
        test_file.touch()
        test_file.unlink()
        result.state_dir_writable = True
    except Exception:
        result.state_dir_writable = False
        result.errors.append("State directory not writable")

    return result


# =============================================================================
# CID Management
# =============================================================================


def _generate_cid(lab_id: str) -> int:
    """Generate a deterministic CID from lab ID.

    Uses hash to derive CID, with collision detection on actual use.

    Args:
        lab_id: Lab UUID string

    Returns:
        Guest CID in valid range
    """
    # Hash the lab ID to get a deterministic value
    hash_bytes = hashlib.sha256(lab_id.encode()).digest()
    hash_int = int.from_bytes(hash_bytes[:4], "big")

    # Map to valid CID range
    cid = MIN_GUEST_CID + (hash_int % (MAX_GUEST_CID - MIN_GUEST_CID))

    return cid


# =============================================================================
# Token Management
# =============================================================================


def _generate_token() -> str:
    """Generate a secure per-lab token.

    Returns:
        32-byte hex token

    SECURITY: This token authenticates guest agent requests.
    """
    return secrets.token_hex(32)


def _store_token(lab_id: str, token: str) -> None:
    """Store token securely in lab state directory.

    Args:
        lab_id: Lab UUID string
        token: Authentication token

    SECURITY: Token file is chmod 0600.
    """
    token_path = lab_token_path(lab_id)

    # Write with restrictive permissions
    fd = os.open(
        str(token_path),
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        os.write(fd, token.encode())
    finally:
        os.close(fd)


def _read_token(lab_id: str) -> str | None:
    """Read token from lab state directory.

    Args:
        lab_id: Lab UUID string

    Returns:
        Token string or None if not found
    """
    token_path = lab_token_path(lab_id)
    try:
        return token_path.read_text().strip()
    except Exception:
        return None


# =============================================================================
# VM Lifecycle
# =============================================================================


async def create_vm(
    lab_id: UUID | str,
    network_config: "NetworkConfig | None" = None,
) -> VMMetadata:
    """Create and boot a Firecracker microVM.

    Args:
        lab_id: Server-owned lab ID
        network_config: Optional network configuration with guest IP

    Returns:
        VMMetadata with VM information

    Raises:
        RuntimeError: If VM creation fails
        PathContainmentError: If path security check fails

    SECURITY:
    - Runs preflight checks first
    - Uses jailer if available, fails closed otherwise (unless override set)
    - Never logs token
    """
    safe_lab_id = validate_lab_id(lab_id)
    logger.info(f"Creating microVM for lab ...{safe_lab_id[-6:]}")

    # Acquire boot slot to prevent resource contention
    # Multiple simultaneous boots can cause timeouts under load
    semaphore = _get_boot_semaphore()
    logger.info(f"Lab ...{safe_lab_id[-6:]} waiting for boot slot (max {MAX_CONCURRENT_BOOTS} concurrent)")
    async with semaphore:
        logger.info(f"Lab ...{safe_lab_id[-6:]} acquired boot slot, starting VM boot")

        # Run preflight
        pf = preflight()
        if not pf.can_run:
            raise RuntimeError(f"Preflight failed: {', '.join(pf.errors)}")

        if not pf.jailer_usable and not settings.dev_unsafe_allow_no_jailer:
            raise RuntimeError(
                "Jailer not usable and OCTOLAB_DEV_UNSAFE_ALLOW_NO_JAILER not set. "
                "Cannot start VM without isolation."
            )

        # Create state directory
        state_dir = ensure_lab_state_dir(safe_lab_id)

        # Generate and store token
        token = _generate_token()
        _store_token(safe_lab_id, token)

        # Generate CID
        cid = _generate_cid(safe_lab_id)

        # Prepare paths
        socket_path = lab_socket_path(safe_lab_id)
        log_path = lab_log_path(safe_lab_id)
        pid_path = lab_pid_path(safe_lab_id)
        rootfs_copy = lab_rootfs_path(safe_lab_id)

        # Copy base rootfs to per-lab rootfs (ephemeral)
        base_rootfs = Path(settings.microvm_rootfs_base_path)
        if not base_rootfs.exists():
            raise RuntimeError("Base rootfs not found")

        import shutil

        shutil.copy2(base_rootfs, rootfs_copy)

        # Build Firecracker config
        kernel_path = Path(settings.microvm_kernel_path)
        if not kernel_path.exists():
            raise RuntimeError("Kernel not found")

        # Build boot args with optional network config
        # Linux kernel IP format: ip=<client>::<gateway>:<netmask>::<interface>:none
        boot_args = (
            "console=ttyS0 reboot=k panic=1 pci=off "
            f"octolab.token={token} octolab.vsock_port={settings.microvm_vsock_port}"
        )
        if network_config:
            # Add IP configuration to kernel cmdline
            # This configures eth0 with the specified IP, gateway, and netmask
            boot_args += (
                f" ip={network_config.guest_ip}::{network_config.gateway}:255.255.0.0"
                "::eth0:none"
            )
            logger.info(f"VM will use IP {network_config.guest_ip} via {network_config.gateway}")

        config = {
            "boot-source": {
                "kernel_image_path": str(kernel_path),
                "boot_args": boot_args,
            },
            "drives": [
                {
                    "drive_id": "rootfs",
                    "path_on_host": str(rootfs_copy),
                    "is_root_device": True,
                    "is_read_only": False,
                }
            ],
            "machine-config": {
                "vcpu_count": settings.microvm_vcpu_count,
                "mem_size_mib": settings.microvm_mem_size_mib,
            },
            "vsock": {
                "guest_cid": cid,
                "uds_path": str(state_dir / "vsock.sock"),
            },
        }

        # Add network interface if network_config provided
        if network_config:
            # Generate deterministic MAC from lab_id
            lab_hash = int(safe_lab_id.replace("-", "")[:8], 16)
            guest_mac = f"AA:FC:00:{(lab_hash >> 16) & 0xFF:02X}:{(lab_hash >> 8) & 0xFF:02X}:{lab_hash & 0xFF:02X}"
            config["network-interfaces"] = [
                {
                    "iface_id": "eth0",
                    "guest_mac": guest_mac,
                    "host_dev_name": network_config.tap_name,
                }
            ]
            logger.info(f"VM network: tap={network_config.tap_name}, mac={guest_mac}")

        config_path = state_dir / "vm_config.json"
        config_path.write_text(json.dumps(config, indent=2))

        # Start Firecracker
        # SECURITY: shell=False, list args only
        fc_args = [
            settings.firecracker_bin,
            "--api-sock",
            str(socket_path),
            "--config-file",
            str(config_path),
        ]

        # Create log file
        log_path.touch()

        try:
            # Start process
            proc = await asyncio.create_subprocess_exec(
                *fc_args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=open(log_path, "w"),
                start_new_session=True,  # Detach from parent
            )

            # Store PID
            pid_path.write_text(str(proc.pid))

            logger.info(f"Started Firecracker PID={proc.pid} for lab ...{safe_lab_id[-6:]}")

            # Wait for boot and agent ready
            vsock_sock_path = str(state_dir / "vsock.sock")
            await _wait_for_agent(vsock_sock_path, token, timeout=settings.microvm_boot_timeout_secs)

            return VMMetadata(
                lab_id=safe_lab_id,
                pid=proc.pid,
                cid=cid,
                api_sock_path=str(socket_path),
                state_dir=str(state_dir),
            )

        except StaleRootfsError as e:
            # Stale rootfs detected - cleanup and raise with specific error
            logger.error(f"Stale rootfs for lab ...{safe_lab_id[-6:]}: {e}")
            await destroy_vm(safe_lab_id)
            raise StaleRootfsError(str(e))
        except Exception as e:
            # Cleanup on failure
            logger.error(f"Failed to create VM for lab ...{safe_lab_id[-6:]}: {type(e).__name__}")
            await destroy_vm(safe_lab_id)
            raise RuntimeError(f"VM creation failed: {type(e).__name__}")


async def destroy_vm(lab_id: UUID | str) -> bool:
    """Destroy a Firecracker microVM and clean up state.

    Args:
        lab_id: Server-owned lab ID

    Returns:
        True if VM was destroyed, False if it didn't exist

    SECURITY: Ensures all resources are cleaned up.
    """
    safe_lab_id = validate_lab_id(lab_id)
    logger.info(f"Destroying microVM for lab ...{safe_lab_id[-6:]}")

    destroyed = False

    # Try to read PID and terminate process
    try:
        pid_path = lab_pid_path(safe_lab_id)
        if pid_path.exists():
            pid_str = pid_path.read_text().strip()
            if pid_str.isdigit():
                pid = int(pid_str)
                try:
                    # Try graceful termination first
                    os.kill(pid, signal.SIGTERM)
                    await asyncio.sleep(0.5)

                    # Check if still running
                    try:
                        os.kill(pid, 0)
                        # Still running, force kill
                        os.kill(pid, signal.SIGKILL)
                        await asyncio.sleep(0.2)
                    except ProcessLookupError:
                        pass  # Already dead

                    destroyed = True
                    logger.info(f"Terminated Firecracker PID={pid}")

                except ProcessLookupError:
                    # Process already gone
                    pass
                except PermissionError:
                    logger.warning(f"Permission denied killing PID={pid}")
    except Exception as e:
        logger.warning(f"Error terminating VM process: {type(e).__name__}")

    # Clean up state directory
    try:
        if cleanup_lab_state_dir(safe_lab_id):
            destroyed = True
            logger.info(f"Cleaned up state for lab ...{safe_lab_id[-6:]}")
    except PathContainmentError as e:
        logger.error(f"Path containment error during cleanup: {e}")
    except Exception as e:
        logger.warning(f"Error cleaning up state: {type(e).__name__}")

    return destroyed


# =============================================================================
# Networking (via microvm-netd)
# =============================================================================


@dataclass
class NetworkConfig:
    """Network configuration for a VM.

    SECURITY: None of these fields contain secrets.
    All network params now come from microvm-netd.
    """
    tap_name: str
    bridge_name: str
    guest_ip: str
    host_port: int
    gateway: str
    netmask: str = "255.255.0.0"
    dns: str = "8.8.8.8"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "tap_name": self.tap_name,
            "bridge_name": self.bridge_name,
            "guest_ip": self.guest_ip,
            "host_port": self.host_port,
            "gateway": self.gateway,
            "netmask": self.netmask,
            "dns": self.dns,
        }


async def setup_network_for_lab(
    lab_id: str,
    host_port: int,
) -> NetworkConfig | None:
    """Set up networking for a lab VM via microvm-netd.

    Requests TAP/network allocation from the privileged netd service.
    Network params (guest IP, gateway, netmask, DNS) are returned by netd.

    Args:
        lab_id: Lab UUID string
        host_port: Host port for noVNC access

    Returns:
        NetworkConfig or None on failure

    SECURITY:
    - Network operations performed by netd (runs as root)
    - Backend remains unprivileged
    - NO FALLBACK to direct commands
    """
    from app.services.microvm_net_client import (
        NetworkError,
        NetdUnavailableError,
        NetdPermissionError,
        alloc_vm_net,
    )

    safe_lab_id = validate_lab_id(lab_id)

    try:
        # Request network allocation from netd (returns all network params)
        params = await alloc_vm_net(safe_lab_id)

        logger.info(
            f"Network allocated for lab ...{safe_lab_id[-6:]}: "
            f"tap={params.tap}, ip={params.guest_ip}, gw={params.gateway}"
        )

        return NetworkConfig(
            tap_name=params.tap,
            bridge_name=params.bridge,
            guest_ip=params.guest_ip,
            host_port=host_port,
            gateway=params.gateway,
            netmask=params.netmask,
            dns=params.dns,
        )

    except NetdUnavailableError as e:
        logger.error(
            f"Netd unavailable for lab ...{safe_lab_id[-6:]}: {e.message}. "
            "Ensure microvm-netd is running as root."
        )
        return None

    except NetdPermissionError as e:
        logger.error(
            f"Netd permission denied for lab ...{safe_lab_id[-6:]}: {e.message}. "
            "Check netd is running as root with CAP_NET_ADMIN."
        )
        return None

    except NetworkError as e:
        logger.error(
            f"Network setup failed for lab ...{safe_lab_id[-6:]}: "
            f"{e.code} - {e.message}"
        )
        return None

    except Exception as e:
        logger.error(
            f"Unexpected network error for lab ...{safe_lab_id[-6:]}: "
            f"{type(e).__name__}"
        )
        return None


async def cleanup_network_for_lab(lab_id: str, tap_name: str | None = None) -> bool:
    """Clean up networking for a lab VM via microvm-netd.

    Best-effort cleanup - logs errors but doesn't raise.

    Args:
        lab_id: Lab UUID string
        tap_name: TAP device name (ignored - netd derives from lab_id)

    Returns:
        True if cleanup attempted
    """
    from app.services.microvm_net_client import release_vm_net

    safe_lab_id = validate_lab_id(lab_id)

    try:
        await release_vm_net(safe_lab_id)
        logger.info(f"Network released for lab ...{safe_lab_id[-6:]}")
        return True

    except Exception as e:
        logger.warning(
            f"Network release failed for lab ...{safe_lab_id[-6:]}: "
            f"{type(e).__name__}"
        )
        return False


async def setup_port_forward_for_lab(
    lab_id: str,
    host_port: int,
    guest_port: int = 6080,
) -> bool:
    """Set up port forwarding from host to VM via microvm-netd.

    Args:
        lab_id: Lab UUID string
        host_port: Host port to forward from
        guest_port: Guest port to forward to (default: 6080 for noVNC)

    Returns:
        True if successful

    Raises:
        NetworkError: If setup fails
    """
    from app.services.microvm_net_client import setup_port_forward

    safe_lab_id = validate_lab_id(lab_id)

    result = await setup_port_forward(safe_lab_id, host_port, guest_port)
    logger.info(
        f"Port forward set up for lab ...{safe_lab_id[-6:]}: "
        f"host:{result.host_port} -> {result.guest_ip}:{result.guest_port}"
    )
    return True


async def cleanup_port_forward_for_lab(lab_id: str) -> bool:
    """Clean up port forwarding rules for a lab via microvm-netd.

    Best-effort cleanup - logs errors but doesn't raise.

    Args:
        lab_id: Lab UUID string

    Returns:
        True if cleanup attempted
    """
    from app.services.microvm_net_client import cleanup_port_forward

    safe_lab_id = validate_lab_id(lab_id)

    try:
        await cleanup_port_forward(safe_lab_id)
        logger.info(f"Port forward cleaned up for lab ...{safe_lab_id[-6:]}")
        return True

    except Exception as e:
        logger.warning(
            f"Port forward cleanup failed for lab ...{safe_lab_id[-6:]}: "
            f"{type(e).__name__}"
        )
        return False


# =============================================================================
# Extended Guest Agent Communication (with compose support)
# =============================================================================


def _get_command_timeout(command: str) -> int:
    """Get appropriate timeout for a command.

    Args:
        command: Command name

    Returns:
        Timeout in seconds
    """
    if command == "compose_up":
        return settings.microvm_compose_timeout_secs
    elif command == "diag":
        return settings.microvm_diag_timeout_secs
    elif command == "docker_build":
        # Docker build needs more time (5 minutes)
        return 300
    else:
        return settings.microvm_cmd_timeout_secs


async def send_agent_command(
    lab_id: str,
    command: str,
    timeout: int | None = None,
    **kwargs,
) -> AgentResponse:
    """Send a command to the guest agent via Firecracker's UDS vsock.

    Uses Firecracker's hybrid vsock approach which works in nested virtualization
    (e.g., GCP VMs). The host connects to the vsock.sock UDS, sends "CONNECT <port>",
    and then communicates with the guest agent.

    Supports extended commands: ping, upload_project, compose_up, compose_down, status, diag.

    Args:
        lab_id: Lab UUID string
        command: Command to send
        timeout: Optional timeout override (uses command-specific default if not provided)
        **kwargs: Additional command arguments

    Returns:
        AgentResponse
    """
    safe_lab_id = validate_lab_id(lab_id)

    # Read token
    token = _read_token(safe_lab_id)
    if not token:
        return AgentResponse(ok=False, error="Token not found")

    # Construct vsock socket path using the proper helper (includes lab_ prefix)
    vsock_sock_path = str(lab_state_dir(safe_lab_id) / "vsock.sock")

    # Use command-specific timeout if not overridden
    effective_timeout = timeout if timeout is not None else _get_command_timeout(command)

    # Build request
    request = {
        "token": token,
        "command": command,
        **kwargs,
    }

    try:
        # Connect via Firecracker's UDS vsock (works in nested virtualization)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(effective_timeout)

        try:
            sock.connect(vsock_sock_path)

            # Firecracker hybrid vsock protocol: send "CONNECT <port>\n" first
            sock.sendall(f"CONNECT {settings.microvm_vsock_port}\n".encode())

            # Read the OK response from Firecracker
            connect_response = b""
            while b"\n" not in connect_response:
                chunk = sock.recv(1024)
                if not chunk:
                    return AgentResponse(ok=False, error="No CONNECT response")
                connect_response += chunk

            if not connect_response.startswith(b"OK"):
                return AgentResponse(ok=False, error=f"CONNECT failed: {connect_response.decode().strip()}")

            # Send the actual agent request
            request_bytes = json.dumps(request).encode() + b"\n"
            sock.sendall(request_bytes)

            # Receive response
            response_data = b""
            while len(response_data) < settings.microvm_max_output_bytes:
                try:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    response_data += chunk
                    if b"\n" in response_data:
                        break
                except socket.timeout:
                    break

            # Parse response
            if response_data:
                response_json = json.loads(response_data.decode().strip())
                return AgentResponse(
                    ok=response_json.get("ok", False),
                    stdout=response_json.get("stdout", "")[:settings.microvm_max_output_bytes],
                    stderr=response_json.get("stderr", "")[:settings.microvm_max_output_bytes],
                    exit_code=response_json.get("exit_code", -1),
                    error=response_json.get("error"),
                    # Version fields (present in ping response)
                    agent_version=response_json.get("agent_version"),
                    rootfs_build_id=response_json.get("rootfs_build_id"),
                    # Diag fields (present in diag response)
                    docker_ready=response_json.get("docker_ready"),
                    last_compose_status=response_json.get("last_compose_status"),
                    # Docker build fields (present in docker_build response)
                    image=response_json.get("image"),
                    image_id=response_json.get("image_id"),
                )
            else:
                return AgentResponse(ok=False, error="No response")

        finally:
            sock.close()

    except socket.timeout:
        return AgentResponse(ok=False, error="Timeout")
    except socket.error as e:
        return AgentResponse(ok=False, error=f"Socket error: {e.errno}")
    except json.JSONDecodeError:
        return AgentResponse(ok=False, error="Invalid JSON response")
    except Exception as e:
        return AgentResponse(ok=False, error=f"{type(e).__name__}")


# =============================================================================
# Guest Agent Communication
# =============================================================================


class StaleRootfsError(Exception):
    """Raised when agent identity fields are missing (stale rootfs)."""

    pass


async def _wait_for_agent(
    vsock_sock_path: str,
    token: str,
    timeout: float = 20.0,
) -> AgentResponse:
    """Wait for guest agent to become ready and verify identity.

    Args:
        vsock_sock_path: Path to Firecracker's vsock UDS socket
        token: Authentication token
        timeout: Maximum wait time in seconds

    Returns:
        AgentResponse from successful ping (contains version fields)

    Raises:
        TimeoutError: If agent doesn't become ready in time
        StaleRootfsError: If agent is missing version fields (stale rootfs)
        RuntimeError: If connection fails

    SECURITY:
    - Token is used for auth but never logged.
    - Verifies agent_version and rootfs_build_id are present to detect stale rootfs.
    """
    deadline = time.time() + timeout
    attempt = 0

    while time.time() < deadline:
        attempt += 1
        remaining = deadline - time.time()

        try:
            response = await communicate_with_agent(
                vsock_sock_path,
                token,
                "ping",
                timeout=2.0,
            )

            if response.ok:
                # Enforce agent identity fields (detect stale rootfs)
                if not response.agent_version or not response.rootfs_build_id:
                    logger.error(
                        f"Agent ping missing identity fields: "
                        f"agent_version={response.agent_version}, "
                        f"rootfs_build_id={response.rootfs_build_id}"
                    )
                    raise StaleRootfsError(
                        "Agent missing version/build_id fields. "
                        "Rootfs likely stale - rebuild with: "
                        "sudo infra/firecracker/build-rootfs.sh --with-kernel --deploy"
                    )

                logger.info(
                    f"Agent ready via {vsock_sock_path}: "
                    f"version={response.agent_version}, "
                    f"build_id={response.rootfs_build_id}"
                )
                return response
            else:
                # Agent returned error - log and retry
                logger.debug(
                    f"vsock ping attempt {attempt} returned ok=False "
                    f"({remaining:.1f}s remaining): {response.error}"
                )

        except StaleRootfsError:
            raise  # Don't retry stale rootfs error
        except Exception as e:
            # Log connection attempts for debugging (don't swallow silently)
            logger.debug(
                f"vsock ping attempt {attempt} exception ({remaining:.1f}s remaining): "
                f"{type(e).__name__}: {e}"
            )

        # Always sleep between attempts (was previously only in except block!)
        await asyncio.sleep(0.5)

    raise TimeoutError(f"Agent did not become ready within {timeout}s (after {attempt} attempts)")


async def communicate_with_agent(
    vsock_sock_path: str,
    token: str,
    action: str,
    timeout: float | None = None,
) -> AgentResponse:
    """Send a command to the guest agent via Firecracker's UDS vsock.

    Uses Firecracker's hybrid vsock approach which works in nested virtualization
    (e.g., GCP VMs). The host connects to the vsock.sock UDS, sends "CONNECT <port>",
    and then communicates with the guest agent.

    Args:
        vsock_sock_path: Path to Firecracker's vsock UDS socket
        token: Authentication token
        action: Action to perform (must be in allowlist)
        timeout: Optional timeout override

    Returns:
        AgentResponse with result

    Raises:
        ValueError: If action not in allowlist
        TimeoutError: If operation times out

    SECURITY:
    - Action must be in allowlist
    - Token is never logged
    - Output is size-limited
    """
    if action not in ALLOWED_AGENT_ACTIONS:
        raise ValueError(f"Action not allowed: {action}")

    if timeout is None:
        timeout = settings.microvm_cmd_timeout_secs

    max_output = settings.microvm_max_output_bytes

    # Build request
    request = {
        "token": token,
        "action": action,
    }
    request_bytes = json.dumps(request).encode()

    try:
        # Connect via Firecracker's UDS vsock (works in nested virtualization)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)

        try:
            sock.connect(vsock_sock_path)

            # Firecracker hybrid vsock protocol: send "CONNECT <port>\n" first
            sock.sendall(f"CONNECT {settings.microvm_vsock_port}\n".encode())

            # Read the OK response from Firecracker
            connect_response = b""
            while b"\n" not in connect_response:
                chunk = sock.recv(1024)
                if not chunk:
                    return AgentResponse(ok=False, error="No CONNECT response")
                connect_response += chunk

            if not connect_response.startswith(b"OK"):
                return AgentResponse(ok=False, error=f"CONNECT failed: {connect_response.decode().strip()}")

            # Now send the actual agent request
            sock.sendall(request_bytes)
            sock.sendall(b"\n")

            # Receive response
            response_data = b""
            while len(response_data) < max_output:
                try:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    response_data += chunk
                    if b"\n" in response_data:
                        break
                except socket.timeout:
                    break

            # Parse response
            if response_data:
                # Truncate for safety
                response_data = response_data[:max_output]
                response_json = json.loads(response_data.decode().strip())
                return AgentResponse(
                    ok=response_json.get("ok", False),
                    stdout=response_json.get("stdout", "")[:max_output],
                    stderr=response_json.get("stderr", "")[:max_output],
                    exit_code=response_json.get("exit_code", -1),
                    # Version fields (present in ping response)
                    agent_version=response_json.get("agent_version"),
                    rootfs_build_id=response_json.get("rootfs_build_id"),
                )
            else:
                return AgentResponse(ok=False, error="No response from agent")

        finally:
            sock.close()

    except socket.timeout:
        raise TimeoutError("vsock communication timed out")
    except socket.error as e:
        return AgentResponse(ok=False, error=f"vsock error: {e.errno}")
    except json.JSONDecodeError:
        return AgentResponse(ok=False, error="Invalid JSON response from agent")
    except Exception as e:
        return AgentResponse(ok=False, error=f"{type(e).__name__}")


async def run_agent_command(
    lab_id: UUID | str,
    action: str,
) -> AgentResponse:
    """Run a command on a lab's guest agent.

    Args:
        lab_id: Server-owned lab ID
        action: Action to perform

    Returns:
        AgentResponse with result

    Raises:
        ValueError: If lab not found or action invalid
    """
    safe_lab_id = validate_lab_id(lab_id)

    # Read token
    token = _read_token(safe_lab_id)
    if not token:
        raise ValueError("Token not found for lab")

    # Construct vsock socket path using the proper helper (includes lab_ prefix)
    vsock_sock_path = str(lab_state_dir(safe_lab_id) / "vsock.sock")

    return await communicate_with_agent(vsock_sock_path, token, action)

