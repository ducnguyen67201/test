#!/usr/bin/env python3
"""MicroVM Network Daemon - Privileged network helper for Firecracker labs.

This daemon runs as root and handles network operations that require CAP_NET_ADMIN:
- Creating/managing a shared Linux bridge (br-octonet)
- Creating/configuring per-lab TAP devices
- Setting up NAT for outbound VM traffic
- Blocking GCP metadata server access (169.254.169.254)

ARCHITECTURE:
- ONE shared bridge (br-octonet) on 10.200.0.0/16 subnet
- Per-lab TAP devices attached to the shared bridge
- Deterministic guest IPs derived from lab_id hash
- MASQUERADE NAT for outbound traffic

SECURITY:
- Runs as root, listens only on UNIX socket with restrictive permissions
- NEVER accepts interface names from clients - derives ALL names from lab_id
- Implements strict deny-by-default: limited set of operations
- Uses shell=False for all subprocess calls
- Logs minimally (no secrets, redacted paths)
- Blocks GCP metadata server to prevent credential theft

Protocol (JSON over UNIX socket):
  Request (new API - preferred):
    {"op": "hello"}                              # Handshake - returns API version and supported ops
    {"op": "ping"}
    {"op": "alloc_vm_net", "lab_id": "<uuid>"}   # Allocate network for VM
    {"op": "release_vm_net", "lab_id": "<uuid>"} # Release network for VM
    {"op": "diag_vm_net", "lab_id": "<uuid>"}    # Diagnose network status
    {"op": "list"}

  Legacy (deprecated, maps to new API):
    {"op": "create", "lab_id": "<uuid>"}   -> alloc_vm_net
    {"op": "destroy", "lab_id": "<uuid>"}  -> release_vm_net

  Response:
    {"ok": true, ...}
    {"ok": false, "error": "ERROR_CODE", "message": "..."}

  hello response:
    {"ok": true, "name": "microvm-netd", "api_version": 1, "supported_ops": [...], "build_id": "..."}

  alloc_vm_net result includes:
    - tap: TAP device name
    - guest_ip: IP address for the VM
    - gateway: Gateway IP (10.200.0.1)
    - netmask: Subnet mask (255.255.0.0)
    - dns: DNS server (8.8.8.8)

Usage:
  # As root:
  python3 microvm_netd.py

  # Or via systemd:
  systemctl start microvm-netd
"""

from __future__ import annotations

import argparse
import grp
import json
import logging
import os
import pwd
import re
import signal
import socket
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

# =============================================================================
# Configuration
# =============================================================================

# API versioning for handshake
API_VERSION = 1
BUILD_ID = "netd-1"

# Socket configuration
DEFAULT_SOCKET_PATH = "/run/octolab/microvm-netd.sock"
DEFAULT_PIDFILE_PATH = "/run/octolab/microvm-netd.pid"
DEFAULT_LOG_PATH = "/var/log/octolab/microvm-netd.log"
FALLBACK_LOG_PATH = "/var/lib/octolab/microvm/microvm-netd.log"
RUN_DIR = "/run/octolab"
SOCKET_MODE = 0o660  # rw-rw---- (root + group)
RUN_DIR_MODE = 0o750  # rwxr-x--- (root + octolab group)
SOCKET_GROUP = "octolab"  # Group that can access the socket

# Interface naming - must fit Linux IFNAMSIZ (15 chars max)
# Format: otp<10-hex> = 13 chars for TAP devices
TAP_PREFIX = "otp"     # 3 chars + 10 hex = 13 chars
IFNAME_MAX_LEN = 15

# Shared bridge configuration (ONE bridge for all VMs)
SHARED_BRIDGE_NAME = "br-octonet"  # Fixed name, not per-lab

# Network configuration for VM connectivity
# VMs get IPs in 10.200.x.x/16 range, bridge acts as gateway
BRIDGE_GATEWAY_IP = "10.200.0.1/16"   # Gateway IP with subnet
BRIDGE_SUBNET = "10.200.0.0/16"       # For NAT rule
BRIDGE_GATEWAY = "10.200.0.1"         # Gateway without prefix
BRIDGE_NETMASK = "255.255.0.0"        # /16 netmask
DNS_SERVER = "8.8.8.8"                # Public DNS for VMs

# GCP metadata server - must be blocked for security
METADATA_SERVER_IP = "169.254.169.254"

# Legacy bridge prefix (deprecated, for cleanup only)
LEGACY_BRIDGE_PREFIX = "obr"  # Old per-lab bridges

# Timeouts
CMD_TIMEOUT_SECS = 5.0
SOCKET_TIMEOUT_SECS = 30.0
MAX_REQUEST_SIZE = 4096

# Logging
LOG_FORMAT = "%(asctime)s [netd] %(levelname)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# =============================================================================
# Setup Logging
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT,
)
logger = logging.getLogger("microvm-netd")


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class NetworkResult:
    """Result of a network allocation."""
    tap: str
    guest_ip: str
    gateway: str
    netmask: str
    dns: str


# =============================================================================
# Validation
# =============================================================================

# UUID regex for strict validation
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def validate_lab_id(lab_id: str) -> str:
    """Validate and normalize lab_id.

    SECURITY: Strict validation prevents injection attacks.

    Args:
        lab_id: Lab UUID string

    Returns:
        Normalized lowercase UUID string

    Raises:
        ValueError: If lab_id is not a valid UUID
    """
    if not lab_id or not isinstance(lab_id, str):
        raise ValueError("lab_id must be a non-empty string")

    lab_id = lab_id.strip().lower()

    if not UUID_PATTERN.match(lab_id):
        raise ValueError("lab_id must be a valid UUID")

    # Also try to parse as UUID to catch edge cases
    try:
        UUID(lab_id)
    except Exception:
        raise ValueError("lab_id must be a valid UUID")

    return lab_id


def derive_tap_name(lab_id: str) -> str:
    """Derive deterministic TAP name from lab_id.

    SECURITY: Names are NEVER taken from client input.
    Names are derived purely from server-owned lab_id.

    Args:
        lab_id: Validated lab UUID string

    Returns:
        TAP interface name

    Raises:
        ValueError: If resulting name exceeds IFNAMSIZ
    """
    # Use first 10 hex chars from UUID (without dashes)
    hex_part = lab_id.replace("-", "")[:10]
    tap = f"{TAP_PREFIX}{hex_part}"

    # Safety check (should never fail with our prefix lengths)
    if len(tap) > IFNAME_MAX_LEN:
        raise ValueError(f"Interface name too long: {tap}")

    return tap


def derive_guest_ip(lab_id: str) -> str:
    """Derive deterministic guest IP from lab_id.

    Uses a hash of the lab_id to generate a unique IP in 10.200.x.y/16.
    - Third octet (x): derived from first 4 hex chars
    - Fourth octet (y): derived from next 4 hex chars
    - Avoids .0 and .1 in last octet (network/gateway)

    Args:
        lab_id: Validated lab UUID string

    Returns:
        Guest IP address (e.g., "10.200.123.45")
    """
    # Use hash for better distribution
    hex_part = lab_id.replace("-", "")

    # Third octet: 1-254 (avoid 0)
    third = (int(hex_part[:4], 16) % 254) + 1

    # Fourth octet: 2-254 (avoid 0=network, 1=gateway)
    fourth = (int(hex_part[4:8], 16) % 253) + 2

    return f"10.200.{third}.{fourth}"


def derive_interface_names(lab_id: str) -> tuple[str, str]:
    """Derive deterministic bridge and TAP names from lab_id.

    DEPRECATED: Use derive_tap_name() instead. Bridge is now shared.

    SECURITY: Names are NEVER taken from client input.
    Names are derived purely from server-owned lab_id.

    Args:
        lab_id: Validated lab UUID string

    Returns:
        Tuple of (bridge_name, tap_name) - bridge is now always SHARED_BRIDGE_NAME

    Raises:
        ValueError: If resulting names exceed IFNAMSIZ
    """
    tap = derive_tap_name(lab_id)
    return SHARED_BRIDGE_NAME, tap


# =============================================================================
# Network Operations
# =============================================================================

def run_cmd(args: list[str], timeout: float = CMD_TIMEOUT_SECS) -> tuple[int, str, str]:
    """Run a command safely.

    SECURITY:
    - shell=False always
    - Timeout enforced
    - Output truncated

    Args:
        args: Command arguments as list
        timeout: Command timeout in seconds

    Returns:
        Tuple of (returncode, stdout, stderr)
    """
    try:
        result = subprocess.run(
            args,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = result.stdout[:2048] if result.stdout else ""
        stderr = result.stderr[:2048] if result.stderr else ""
        return result.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        return -1, "", "command timed out"
    except FileNotFoundError:
        return -1, "", "command not found"
    except Exception as e:
        return -1, "", f"error: {type(e).__name__}"


def interface_exists(name: str) -> bool:
    """Check if a network interface exists."""
    rc, _, _ = run_cmd(["ip", "link", "show", name])
    return rc == 0


def create_bridge(bridge_name: str) -> tuple[bool, str]:
    """Create a Linux bridge with gateway IP and NAT.

    Args:
        bridge_name: Bridge interface name (server-derived)

    Returns:
        Tuple of (success, error_code_or_empty)
    """
    # Check if already exists (idempotent)
    if interface_exists(bridge_name):
        logger.info(f"Bridge {bridge_name} already exists (idempotent)")
        # Still ensure gateway IP and NAT are configured (idempotent)
        _ensure_gateway_and_nat(bridge_name)
        return True, ""

    # Create bridge
    rc, _, stderr = run_cmd(["ip", "link", "add", bridge_name, "type", "bridge"])
    if rc != 0:
        if "File exists" in stderr:
            # Race condition - bridge was created between check and create
            _ensure_gateway_and_nat(bridge_name)
            return True, ""
        if "Operation not permitted" in stderr:
            return False, "EPERM"
        logger.error(f"Failed to create bridge {bridge_name}: {stderr[:100]}")
        return False, "CREATE_FAILED"

    # Bring up bridge
    rc, _, stderr = run_cmd(["ip", "link", "set", bridge_name, "up"])
    if rc != 0:
        logger.error(f"Failed to bring up bridge {bridge_name}: {stderr[:100]}")
        # Try to clean up
        run_cmd(["ip", "link", "del", bridge_name])
        return False, "UP_FAILED"

    # Configure gateway IP and NAT
    _ensure_gateway_and_nat(bridge_name)

    logger.info(f"Created bridge: {bridge_name}")
    return True, ""


def _ensure_gateway_and_nat(bridge_name: str) -> None:
    """Ensure gateway IP is assigned, NAT is configured, and metadata blocked.

    This is idempotent - safe to call multiple times.

    Args:
        bridge_name: Bridge interface name
    """
    # Assign gateway IP to bridge (idempotent - fails gracefully if exists)
    rc, stdout, stderr = run_cmd([
        "ip", "addr", "add", BRIDGE_GATEWAY_IP, "dev", bridge_name
    ])
    if rc == 0:
        logger.info(f"Assigned gateway IP {BRIDGE_GATEWAY_IP} to {bridge_name}")
    elif "File exists" in stderr or "RTNETLINK answers" in stderr:
        logger.debug(f"Gateway IP already assigned to {bridge_name}")
    else:
        logger.warning(f"Failed to assign gateway IP: {stderr[:100]}")

    # Enable IP forwarding (idempotent)
    rc, _, _ = run_cmd(["sysctl", "-w", "net.ipv4.ip_forward=1"])
    if rc == 0:
        logger.debug("IP forwarding enabled")

    # Block GCP metadata server (SECURITY: prevent credential theft)
    # Check if rule exists first
    rc, _, _ = run_cmd([
        "iptables", "-C", "FORWARD",
        "-s", BRIDGE_SUBNET, "-d", METADATA_SERVER_IP,
        "-j", "DROP"
    ])
    if rc != 0:
        # Rule doesn't exist, add it at the beginning of FORWARD chain
        rc, _, stderr = run_cmd([
            "iptables", "-I", "FORWARD", "1",
            "-s", BRIDGE_SUBNET, "-d", METADATA_SERVER_IP,
            "-j", "DROP"
        ])
        if rc == 0:
            logger.info(f"Blocked metadata server {METADATA_SERVER_IP} for {BRIDGE_SUBNET}")
        else:
            logger.warning(f"Failed to block metadata server: {stderr[:100]}")
    else:
        logger.debug("Metadata server block already exists")

    # Add MASQUERADE rule for NAT (idempotent - iptables handles duplicates)
    # First check if rule exists
    rc, stdout, _ = run_cmd([
        "iptables", "-t", "nat", "-C", "POSTROUTING",
        "-s", BRIDGE_SUBNET, "!", "-d", BRIDGE_SUBNET,
        "-j", "MASQUERADE"
    ])
    if rc != 0:
        # Rule doesn't exist, add it
        rc, _, stderr = run_cmd([
            "iptables", "-t", "nat", "-A", "POSTROUTING",
            "-s", BRIDGE_SUBNET, "!", "-d", BRIDGE_SUBNET,
            "-j", "MASQUERADE"
        ])
        if rc == 0:
            logger.info(f"Added NAT rule for {BRIDGE_SUBNET}")
        else:
            logger.warning(f"Failed to add NAT rule: {stderr[:100]}")
    else:
        logger.debug("NAT rule already exists")


def create_tap(tap_name: str, bridge_name: str) -> tuple[bool, str]:
    """Create a TAP device and attach to bridge.

    Args:
        tap_name: TAP interface name (server-derived)
        bridge_name: Bridge to attach to (server-derived)

    Returns:
        Tuple of (success, error_code_or_empty)
    """
    # Check if already exists (idempotent)
    if interface_exists(tap_name):
        logger.info(f"TAP {tap_name} already exists (idempotent)")
        return True, ""

    # Create TAP device
    rc, _, stderr = run_cmd(["ip", "tuntap", "add", "dev", tap_name, "mode", "tap"])
    if rc != 0:
        if "File exists" in stderr:
            return True, ""
        if "Operation not permitted" in stderr:
            return False, "EPERM"
        logger.error(f"Failed to create TAP {tap_name}: {stderr[:100]}")
        return False, "CREATE_FAILED"

    # Attach to bridge
    rc, _, stderr = run_cmd(["ip", "link", "set", tap_name, "master", bridge_name])
    if rc != 0:
        logger.error(f"Failed to attach TAP to bridge: {stderr[:100]}")
        run_cmd(["ip", "link", "del", tap_name])
        return False, "ATTACH_FAILED"

    # Bring up TAP
    rc, _, stderr = run_cmd(["ip", "link", "set", tap_name, "up"])
    if rc != 0:
        logger.error(f"Failed to bring up TAP {tap_name}: {stderr[:100]}")
        run_cmd(["ip", "link", "del", tap_name])
        return False, "UP_FAILED"

    logger.info(f"Created TAP: {tap_name} -> {bridge_name}")
    return True, ""


def destroy_interface(name: str) -> tuple[bool, str]:
    """Destroy a network interface.

    Args:
        name: Interface name (server-derived)

    Returns:
        Tuple of (success, error_code_or_empty)
    """
    if not interface_exists(name):
        logger.info(f"Interface {name} does not exist (idempotent destroy)")
        return True, ""

    rc, _, stderr = run_cmd(["ip", "link", "del", name])
    if rc != 0:
        if "Cannot find device" in stderr:
            # Race condition - already gone
            return True, ""
        if "Operation not permitted" in stderr:
            return False, "EPERM"
        logger.error(f"Failed to delete {name}: {stderr[:100]}")
        return False, "DELETE_FAILED"

    logger.info(f"Deleted interface: {name}")
    return True, ""


def list_lab_interfaces() -> list[dict[str, str]]:
    """List all lab-related interfaces.

    Returns:
        List of dicts with interface info
    """
    result = []

    rc, stdout, _ = run_cmd(["ip", "-j", "link", "show"])
    if rc != 0:
        # Fallback to non-JSON
        rc, stdout, _ = run_cmd(["ip", "link", "show"])
        if rc != 0:
            return result

        # Parse text output
        for line in stdout.split("\n"):
            # Check for shared bridge
            if SHARED_BRIDGE_NAME in line:
                result.append({"name": SHARED_BRIDGE_NAME, "type": "bridge"})
            # Check for TAP devices
            elif TAP_PREFIX in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    name = parts[1].strip().split("@")[0]
                    if name.startswith(TAP_PREFIX):
                        result.append({"name": name, "type": "tap"})
            # Check for legacy bridges (for cleanup)
            elif LEGACY_BRIDGE_PREFIX in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    name = parts[1].strip().split("@")[0]
                    if name.startswith(LEGACY_BRIDGE_PREFIX):
                        result.append({"name": name, "type": "bridge", "legacy": True})
        return result

    # Parse JSON output
    try:
        interfaces = json.loads(stdout)
        for iface in interfaces:
            name = iface.get("ifname", "")
            if name == SHARED_BRIDGE_NAME:
                result.append({"name": name, "type": "bridge"})
            elif name.startswith(TAP_PREFIX):
                result.append({"name": name, "type": "tap"})
            elif name.startswith(LEGACY_BRIDGE_PREFIX):
                result.append({"name": name, "type": "bridge", "legacy": True})
    except json.JSONDecodeError:
        pass

    return result


def ensure_shared_bridge() -> tuple[bool, str]:
    """Ensure the shared bridge exists with proper configuration.

    This is called on first allocation or daemon startup.
    Idempotent - safe to call multiple times.

    Returns:
        Tuple of (success, error_code_or_empty)
    """
    return create_bridge(SHARED_BRIDGE_NAME)


# =============================================================================
# Request Handlers
# =============================================================================

def handle_ping() -> dict[str, Any]:
    """Handle ping request."""
    import time
    return {"ok": True, "result": {"status": "ok", "version": "1.0", "ts": int(time.time())}}


def handle_create(lab_id: str) -> dict[str, Any]:
    """Handle create request (DEPRECATED - use alloc_vm_net).

    Creates TAP for a lab using the shared bridge.

    Args:
        lab_id: Lab UUID

    Returns:
        Response dict
    """
    # Delegate to new API
    return handle_alloc_vm_net(lab_id)


def handle_alloc_vm_net(lab_id: str) -> dict[str, Any]:
    """Allocate network resources for a VM.

    Creates TAP device attached to shared bridge and returns network params.

    Args:
        lab_id: Lab UUID

    Returns:
        Response dict with tap, guest_ip, gateway, netmask, dns
    """
    try:
        safe_lab_id = validate_lab_id(lab_id)
    except ValueError as e:
        return {"ok": False, "error": {"code": "INVALID_LAB_ID", "message": str(e)}}

    # Ensure shared bridge exists (idempotent)
    ok, err = ensure_shared_bridge()
    if not ok:
        return {"ok": False, "error": {"code": err, "message": f"Failed to create shared bridge: {err}"}}

    # Derive TAP name and guest IP
    tap_name = derive_tap_name(safe_lab_id)
    guest_ip = derive_guest_ip(safe_lab_id)

    # Create and attach TAP to shared bridge
    ok, err = create_tap(tap_name, SHARED_BRIDGE_NAME)
    if not ok:
        return {"ok": False, "error": {"code": err, "message": f"Failed to create TAP: {err}"}}

    logger.info(f"Allocated network for lab ...{safe_lab_id[-6:]}: tap={tap_name}, ip={guest_ip}")

    return {
        "ok": True,
        "result": {
            "tap": tap_name,
            "guest_ip": guest_ip,
            "gateway": BRIDGE_GATEWAY,
            "netmask": BRIDGE_NETMASK,
            "dns": DNS_SERVER,
            "bridge": SHARED_BRIDGE_NAME,
            "lab_id_suffix": safe_lab_id[-6:],
        },
    }


def handle_destroy(lab_id: str) -> dict[str, Any]:
    """Handle destroy request (DEPRECATED - use release_vm_net).

    Destroys TAP for a lab. Bridge is shared and NOT destroyed.

    Args:
        lab_id: Lab UUID

    Returns:
        Response dict
    """
    # Delegate to new API
    return handle_release_vm_net(lab_id)


def handle_release_vm_net(lab_id: str) -> dict[str, Any]:
    """Release network resources for a VM.

    Destroys TAP device. Bridge is shared and NOT destroyed.

    Args:
        lab_id: Lab UUID

    Returns:
        Response dict
    """
    try:
        safe_lab_id = validate_lab_id(lab_id)
    except ValueError as e:
        return {"ok": False, "error": {"code": "INVALID_LAB_ID", "message": str(e)}}

    tap_name = derive_tap_name(safe_lab_id)

    # Destroy TAP only (bridge is shared, never destroyed per-lab)
    ok, err = destroy_interface(tap_name)
    if not ok:
        return {"ok": False, "error": {"code": err, "message": f"Failed to destroy TAP: {err}"}}

    logger.info(f"Released network for lab ...{safe_lab_id[-6:]}: tap={tap_name}")

    return {
        "ok": True,
        "result": {
            "tap_deleted": tap_name,
            "lab_id_suffix": safe_lab_id[-6:],
        },
    }


def handle_diag_vm_net(lab_id: str) -> dict[str, Any]:
    """Diagnose network status for a VM.

    Reports if TAP exists, bridge status, and network params.

    Args:
        lab_id: Lab UUID

    Returns:
        Response dict with diagnostic info
    """
    try:
        safe_lab_id = validate_lab_id(lab_id)
    except ValueError as e:
        return {"ok": False, "error": {"code": "INVALID_LAB_ID", "message": str(e)}}

    tap_name = derive_tap_name(safe_lab_id)
    guest_ip = derive_guest_ip(safe_lab_id)

    # Check interface status
    tap_exists = interface_exists(tap_name)
    bridge_exists = interface_exists(SHARED_BRIDGE_NAME)

    # Get TAP details if it exists
    tap_state = "unknown"
    tap_master = None
    if tap_exists:
        rc, stdout, _ = run_cmd(["ip", "-j", "link", "show", tap_name])
        if rc == 0:
            try:
                data = json.loads(stdout)
                if data:
                    tap_state = data[0].get("operstate", "unknown").lower()
                    tap_master = data[0].get("master")
            except (json.JSONDecodeError, IndexError, KeyError):
                pass

    # Check if we can reach gateway (basic connectivity test)
    gateway_reachable = False
    if bridge_exists:
        rc, _, _ = run_cmd(["ip", "addr", "show", SHARED_BRIDGE_NAME])
        gateway_reachable = rc == 0

    return {
        "ok": True,
        "result": {
            "lab_id_suffix": safe_lab_id[-6:],
            "tap": {
                "name": tap_name,
                "exists": tap_exists,
                "state": tap_state if tap_exists else None,
                "master": tap_master,
            },
            "bridge": {
                "name": SHARED_BRIDGE_NAME,
                "exists": bridge_exists,
            },
            "network_params": {
                "guest_ip": guest_ip,
                "gateway": BRIDGE_GATEWAY,
                "netmask": BRIDGE_NETMASK,
                "dns": DNS_SERVER,
            },
            "healthy": tap_exists and bridge_exists and tap_master == SHARED_BRIDGE_NAME,
        },
    }


def handle_list() -> dict[str, Any]:
    """Handle list request."""
    interfaces = list_lab_interfaces()
    return {"ok": True, "result": {"interfaces": interfaces, "count": len(interfaces)}}


def handle_hello() -> dict[str, Any]:
    """Handle hello request - handshake/version check.

    Returns API version and list of supported operations.
    This is a pure function with no side effects.
    """
    # Get supported ops from registry (defined below)
    supported_ops = sorted(OP_REGISTRY.keys())

    return {
        "ok": True,
        "name": "microvm-netd",
        "api_version": API_VERSION,
        "supported_ops": supported_ops,
        "build_id": BUILD_ID,
    }


# =============================================================================
# Port Forwarding
# =============================================================================


def handle_setup_port_forward(lab_id: str, host_port: int, guest_port: int = 6080) -> dict[str, Any]:
    """Set up iptables DNAT for port forwarding.

    Forwards host_port to guest_ip:guest_port.

    Args:
        lab_id: Lab UUID string (for rule comment and IP derivation)
        host_port: Host port to listen on
        guest_port: Guest port to forward to (default 6080)

    Returns:
        Response dict

    SECURITY:
    - Rules are tagged with lab_id for precise cleanup
    - Only forwards specific port to specific guest IP
    - shell=False
    """
    try:
        safe_lab_id = validate_lab_id(lab_id)
    except ValueError as e:
        return {"ok": False, "error": {"code": "INVALID_LAB_ID", "message": str(e)}}

    # Validate port numbers
    if not isinstance(host_port, int) or host_port < 1 or host_port > 65535:
        return {"ok": False, "error": {"code": "INVALID_PORT", "message": f"Invalid host_port: {host_port}"}}
    if not isinstance(guest_port, int) or guest_port < 1 or guest_port > 65535:
        return {"ok": False, "error": {"code": "INVALID_PORT", "message": f"Invalid guest_port: {guest_port}"}}

    guest_ip = derive_guest_ip(safe_lab_id)
    comment = f"octolab_{safe_lab_id[-12:]}"

    # DNAT rule: redirect incoming traffic on host_port to guest
    dnat_args = [
        "iptables", "-t", "nat", "-A", "PREROUTING",
        "-p", "tcp",
        "--dport", str(host_port),
        "-j", "DNAT",
        "--to-destination", f"{guest_ip}:{guest_port}",
        "-m", "comment", "--comment", comment,
    ]
    rc, _, stderr = run_cmd(dnat_args)
    if rc != 0:
        return {"ok": False, "error": {"code": "DNAT_FAILED", "message": f"Failed to add DNAT rule: {stderr[:100]}"}}

    # Also add OUTPUT chain rule for local access (127.0.0.1)
    output_args = [
        "iptables", "-t", "nat", "-A", "OUTPUT",
        "-p", "tcp",
        "-d", "127.0.0.1",
        "--dport", str(host_port),
        "-j", "DNAT",
        "--to-destination", f"{guest_ip}:{guest_port}",
        "-m", "comment", "--comment", comment,
    ]
    rc, _, stderr = run_cmd(output_args)
    if rc != 0:
        logger.warning(f"Failed to add OUTPUT DNAT rule: {stderr[:100]}")
        # Non-fatal for local-only testing

    logger.info(f"Set up port forward: {host_port} -> {guest_ip}:{guest_port} (lab ...{safe_lab_id[-6:]})")

    return {
        "ok": True,
        "result": {
            "host_port": host_port,
            "guest_ip": guest_ip,
            "guest_port": guest_port,
            "lab_id_suffix": safe_lab_id[-6:],
        },
    }


def handle_cleanup_port_forward(lab_id: str) -> dict[str, Any]:
    """Remove iptables port forwarding rules for a lab.

    Args:
        lab_id: Lab UUID string

    Returns:
        Response dict

    SECURITY: Uses comment matching to remove only this lab's rules.
    """
    try:
        safe_lab_id = validate_lab_id(lab_id)
    except ValueError as e:
        return {"ok": False, "error": {"code": "INVALID_LAB_ID", "message": str(e)}}

    comment = f"octolab_{safe_lab_id[-12:]}"
    deleted_count = 0

    # Remove rules by comment from nat PREROUTING and OUTPUT chains
    for chain in ["PREROUTING", "OUTPUT"]:
        # List rules with line numbers
        rc, stdout, _ = run_cmd(["iptables", "-t", "nat", "-L", chain, "--line-numbers", "-n"])
        if rc != 0:
            continue

        # Find matching rule numbers (parse in reverse to delete from end first)
        lines = stdout.strip().split("\n")
        rule_nums = []
        for line in lines:
            if comment in line:
                parts = line.split()
                if parts and parts[0].isdigit():
                    rule_nums.append(int(parts[0]))

        # Delete in reverse order to preserve line numbers
        for rule_num in sorted(rule_nums, reverse=True):
            rc, _, _ = run_cmd(["iptables", "-t", "nat", "-D", chain, str(rule_num)])
            if rc == 0:
                deleted_count += 1

    logger.info(f"Cleaned up port forwarding for lab ...{safe_lab_id[-6:]}: deleted {deleted_count} rules")

    return {
        "ok": True,
        "result": {
            "deleted_rules": deleted_count,
            "lab_id_suffix": safe_lab_id[-6:],
        },
    }


# =============================================================================
# Operation Registry
# =============================================================================

# Registry maps op name to (handler, requires_lab_id, extra_params)
# extra_params is a list of (param_name, required, default) tuples
# This is the single source of truth for supported operations
OP_REGISTRY: dict[str, tuple[Any, bool, list]] = {
    "hello": (handle_hello, False, []),
    "ping": (handle_ping, False, []),
    "list": (handle_list, False, []),
    # New API (preferred)
    "alloc_vm_net": (handle_alloc_vm_net, True, []),
    "release_vm_net": (handle_release_vm_net, True, []),
    "diag_vm_net": (handle_diag_vm_net, True, []),
    # Port forwarding
    "setup_port_forward": (handle_setup_port_forward, True, [
        ("host_port", True, None),
        ("guest_port", False, 6080),
    ]),
    "cleanup_port_forward": (handle_cleanup_port_forward, True, []),
    # Legacy API (deprecated, for backward compatibility)
    "create": (handle_create, True, []),
    "destroy": (handle_destroy, True, []),
}


def process_request(request_data: bytes) -> bytes:
    """Process a single request.

    Uses OP_REGISTRY to dispatch operations.

    Args:
        request_data: Raw request bytes

    Returns:
        Response bytes (JSON)
    """
    try:
        request = json.loads(request_data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return json.dumps({
            "ok": False,
            "error": "INVALID_JSON",
            "message": "Invalid JSON request",
        }).encode("utf-8")

    op = request.get("op")

    # Look up operation in registry
    if op not in OP_REGISTRY:
        return json.dumps({
            "ok": False,
            "error": "UNKNOWN_OP",
            "message": f"Unknown operation: {op}",
        }).encode("utf-8")

    handler, requires_lab_id, extra_params = OP_REGISTRY[op]

    # Check for lab_id if required
    if requires_lab_id:
        lab_id = request.get("lab_id")
        if not lab_id:
            return json.dumps({
                "ok": False,
                "error": "MISSING_LAB_ID",
                "message": "lab_id required",
            }).encode("utf-8")

        # Build kwargs from extra_params
        kwargs = {}
        for param_name, required, default in extra_params:
            value = request.get(param_name, default)
            if required and value is None:
                return json.dumps({
                    "ok": False,
                    "error": "MISSING_PARAM",
                    "message": f"Missing required parameter: {param_name}",
                }).encode("utf-8")
            kwargs[param_name] = value

        response = handler(lab_id, **kwargs)
    else:
        response = handler()

    return json.dumps(response).encode("utf-8")


# =============================================================================
# Socket Server
# =============================================================================

class NetdServer:
    """Unix socket server for microvm-netd."""

    def __init__(self, socket_path: str = DEFAULT_SOCKET_PATH):
        self.socket_path = socket_path
        self.running = False
        self.server_socket: socket.socket | None = None

    def setup_socket(self) -> None:
        """Create and configure the UNIX socket.

        SECURITY:
        - Socket directory owned by root:octolab with mode 0750 (group can access)
        - Socket file owned by root:octolab with mode 0660 (group can read/write)
        - If group doesn't exist, logs remediation steps
        """
        # Normalize and validate socket path (prevent path traversal)
        socket_path = os.path.realpath(self.socket_path)
        if not socket_path.startswith("/run/octolab/") and socket_path != self.socket_path:
            # Only allow override if explicitly set (e.g., for tests)
            if os.environ.get("OCTOLAB_MICROVM_NETD_SOCK") != self.socket_path:
                logger.warning(
                    f"Socket path {socket_path} is not under /run/octolab/. "
                    "Using anyway for testing purposes."
                )

        socket_dir = Path(socket_path).parent

        # Try to get octolab group info
        octolab_gid = None
        try:
            grp_info = grp.getgrnam(SOCKET_GROUP)
            octolab_gid = grp_info.gr_gid
        except KeyError:
            logger.warning(
                f"Group '{SOCKET_GROUP}' not found. Socket will only be accessible by root.\n"
                f"  REMEDIATION:\n"
                f"    sudo groupadd -f {SOCKET_GROUP}\n"
                f"    sudo usermod -aG {SOCKET_GROUP} $USER\n"
                f"    # Then restart your session (WSL: wsl --terminate <distro>)"
            )

        # Create socket directory if needed
        if not socket_dir.exists():
            socket_dir.mkdir(parents=True, mode=0o750 if octolab_gid else 0o755)
            logger.info(f"Created socket directory: {socket_dir}")

        # Set directory ownership and permissions
        try:
            if octolab_gid is not None:
                os.chown(socket_dir, 0, octolab_gid)
                os.chmod(socket_dir, 0o750)  # rwxr-x--- (root + octolab group)
                logger.info(f"Socket directory group set to: {SOCKET_GROUP}")
            else:
                os.chmod(socket_dir, 0o755)  # rwxr-xr-x (fallback)
        except PermissionError:
            logger.warning("Could not set socket directory permissions (not running as root?)")

        # Remove existing socket file (avoid stale permissions)
        socket_file = Path(socket_path)
        if socket_file.exists():
            try:
                if socket_file.is_socket():
                    socket_file.unlink()
                    logger.info("Removed stale socket file")
                else:
                    logger.error(f"Path exists but is not a socket: {socket_path}")
                    raise RuntimeError(f"Cannot create socket: {socket_path} exists and is not a socket")
            except OSError as e:
                logger.error(f"Failed to remove existing socket: {e}")
                raise

        # Create socket
        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_socket.bind(socket_path)

        # Set socket file ownership and permissions
        try:
            if octolab_gid is not None:
                os.chown(socket_path, 0, octolab_gid)
                logger.info(f"Socket file group set to: {SOCKET_GROUP}")
            os.chmod(socket_path, SOCKET_MODE)  # rw-rw---- (0660)
        except PermissionError:
            logger.warning("Could not set socket file permissions (not running as root?)")

        self.server_socket.listen(5)
        logger.info(f"Listening on: {socket_path}")

    def handle_client(self, client_socket: socket.socket, addr: Any) -> None:
        """Handle a single client connection."""
        try:
            client_socket.settimeout(SOCKET_TIMEOUT_SECS)

            # Read request (up to max size)
            data = client_socket.recv(MAX_REQUEST_SIZE)
            if not data:
                return

            # Process and respond
            response = process_request(data)
            client_socket.sendall(response)

        except socket.timeout:
            logger.warning("Client timeout")
        except Exception as e:
            logger.error(f"Client error: {type(e).__name__}")
            try:
                error_response = json.dumps({
                    "ok": False,
                    "error": {"code": "INTERNAL_ERROR", "message": "Internal server error"},
                }).encode("utf-8")
                client_socket.sendall(error_response)
            except Exception:
                pass
        finally:
            try:
                client_socket.close()
            except Exception:
                pass

    def run(self) -> None:
        """Run the server main loop."""
        self.setup_socket()
        self.running = True

        logger.info("microvm-netd started")

        while self.running:
            try:
                self.server_socket.settimeout(1.0)  # Allow periodic shutdown check
                try:
                    client_socket, addr = self.server_socket.accept()
                    # Handle in thread for concurrent requests
                    thread = threading.Thread(
                        target=self.handle_client,
                        args=(client_socket, addr),
                        daemon=True,
                    )
                    thread.start()
                except socket.timeout:
                    continue
            except Exception as e:
                if self.running:
                    logger.error(f"Accept error: {type(e).__name__}")

        logger.info("microvm-netd stopped")

    def stop(self) -> None:
        """Stop the server."""
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass

        # Clean up socket file
        try:
            Path(self.socket_path).unlink(missing_ok=True)
        except Exception:
            pass


# =============================================================================
# Daemon Hygiene Helpers
# =============================================================================


def _ensure_run_directory(group: str) -> None:
    """Ensure /run/octolab exists with correct permissions.

    Creates directory if needed, sets owner root:octolab and mode 0750.
    """
    run_path = Path(RUN_DIR)

    # Get octolab group info
    octolab_gid = None
    try:
        grp_info = grp.getgrnam(group)
        octolab_gid = grp_info.gr_gid
    except KeyError:
        logger.warning(
            f"Group '{group}' not found. Run directory may not be accessible by backend."
        )

    if not run_path.exists():
        run_path.mkdir(parents=True, mode=RUN_DIR_MODE)
        logger.info(f"Created run directory: {RUN_DIR}")

    # Set ownership and permissions
    try:
        if octolab_gid is not None:
            os.chown(RUN_DIR, 0, octolab_gid)
        os.chmod(RUN_DIR, RUN_DIR_MODE)
    except PermissionError:
        logger.warning("Could not set run directory permissions")


def _setup_logging(log_file: str, debug: bool) -> logging.FileHandler | None:
    """Configure file logging with redaction filter.

    Args:
        log_file: Path to log file
        debug: Enable debug level logging

    Returns:
        File handler or None if setup failed
    """
    # Set log level
    if debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    # Try primary log path, then fallback
    log_path = Path(log_file)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # Try fallback path
        log_path = Path(FALLBACK_LOG_PATH)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            logger.warning(f"Cannot create log directory for {log_file}")
            return None

    try:
        handler = logging.FileHandler(str(log_path))
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
        logger.addHandler(handler)
        logger.info(f"Logging to: {log_path}")
        return handler
    except PermissionError:
        logger.warning(f"Cannot write to log file: {log_path}")
        return None


def _write_pidfile(pidfile: str) -> bool:
    """Write PID file atomically.

    Args:
        pidfile: Path to PID file

    Returns:
        True if successful
    """
    pid = os.getpid()
    pidfile_path = Path(pidfile)

    try:
        # Write to temp file then rename (atomic)
        temp_path = pidfile_path.with_suffix(".tmp")
        temp_path.write_text(f"{pid}\n")
        temp_path.rename(pidfile_path)
        logger.debug(f"Wrote PID {pid} to {pidfile}")
        return True
    except OSError as e:
        logger.error(f"Failed to write PID file: {e}")
        return False


def _remove_pidfile(pidfile: str) -> None:
    """Remove PID file best-effort."""
    try:
        Path(pidfile).unlink(missing_ok=True)
    except Exception:
        pass


def _check_existing_socket(socket_path: str) -> bool:
    """Check if another netd is running on the socket.

    Returns:
        True if another netd is alive (caller should exit)
        False if socket is stale (caller should clean up and proceed)
    """
    import socket as sock

    if not Path(socket_path).exists():
        return False

    # Try to ping existing socket
    try:
        s = sock.socket(sock.AF_UNIX, sock.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(socket_path)
        s.sendall(b'{"op": "ping"}')
        response = s.recv(1024)
        s.close()

        if b'"ok": true' in response or b'"ok":true' in response:
            return True  # Another netd is running
    except (ConnectionRefusedError, sock.timeout, OSError):
        # Socket exists but no one listening - stale
        logger.info("Found stale socket file, removing")
        try:
            Path(socket_path).unlink()
        except OSError:
            pass
    return False


# =============================================================================
# Main
# =============================================================================

_server: NetdServer | None = None
_pidfile_path: str | None = None


def signal_handler(signum: int, frame: Any) -> None:
    """Handle shutdown signals."""
    global _server, _pidfile_path
    logger.info(f"Received signal {signum}, shutting down...")
    if _server:
        _server.stop()
    if _pidfile_path:
        _remove_pidfile(_pidfile_path)


def main() -> int:
    """Main entry point."""
    global _server, _pidfile_path

    parser = argparse.ArgumentParser(description="MicroVM Network Daemon")
    parser.add_argument(
        "--socket-path",
        "--socket",
        dest="socket_path",
        default=DEFAULT_SOCKET_PATH,
        help=f"Socket path (default: {DEFAULT_SOCKET_PATH})",
    )
    parser.add_argument(
        "--pidfile",
        default=DEFAULT_PIDFILE_PATH,
        help=f"PID file path (default: {DEFAULT_PIDFILE_PATH})",
    )
    parser.add_argument(
        "--log-file",
        default=DEFAULT_LOG_PATH,
        help=f"Log file path (default: {DEFAULT_LOG_PATH})",
    )
    parser.add_argument(
        "--group",
        default=SOCKET_GROUP,
        help=f"Group for socket access (default: {SOCKET_GROUP})",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Normalize and validate socket path (no ../)
    socket_path = os.path.realpath(args.socket_path)
    if ".." in args.socket_path:
        print("ERROR: Socket path must not contain '..'", file=sys.stderr)
        return 1

    # Check if running as root
    if os.geteuid() != 0:
        logger.error("microvm-netd must run as root (requires CAP_NET_ADMIN)")
        return 1

    # Setup file logging
    _setup_logging(args.log_file, args.debug)

    # Ensure run directory exists with correct permissions
    _ensure_run_directory(args.group)

    # Check if another netd is already running
    if _check_existing_socket(socket_path):
        logger.info("Another microvm-netd is already running")
        print("microvm-netd is already running", file=sys.stderr)
        return 0  # Exit 0 = idempotent success

    # Write PID file
    _pidfile_path = args.pidfile
    if not _write_pidfile(args.pidfile):
        logger.error("Failed to write PID file")
        return 1

    # Setup signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Log startup info
    logger.info(
        f"microvm-netd starting: api_version={API_VERSION}, "
        f"supported_ops={len(OP_REGISTRY)}"
    )

    # Run server
    _server = NetdServer(socket_path=socket_path)
    try:
        _server.run()
    except KeyboardInterrupt:
        pass
    finally:
        _server.stop()
        _remove_pidfile(args.pidfile)

    return 0


if __name__ == "__main__":
    sys.exit(main())
