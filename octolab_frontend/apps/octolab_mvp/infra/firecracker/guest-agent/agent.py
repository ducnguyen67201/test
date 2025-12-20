#!/usr/bin/env python3
"""OctoLab Guest Agent for Firecracker microVMs.

This agent runs inside the guest VM and handles commands from the host via vsock.
It manages Docker Compose project deployment, lifecycle, and network configuration.

SECURITY:
- Only allows actions in explicit allowlist
- Requires exact token match for authentication
- Enforces output size limits
- Hard timeout per request
- shell=False for all subprocess calls
- Writes only under /opt/octolab (and /etc/resolv.conf for DNS)
- Never logs tokens

Protocol (JSON-over-line):
  Request:  {"token": "...", "command": "...", ...}
  Response: {"ok": true/false, "stdout": "...", "stderr": "...", "exit_code": int}

Commands:
  ping              - Health check
  upload_project    - Upload compose project (base64-encoded tar.gz)
  compose_up        - Run docker compose up -d
  compose_down      - Run docker compose down
  status            - Get container status
  diag              - Get diagnostic information
  configure_network - Configure eth0 with IP/gateway/DNS (for outbound networking)

configure_network expects:
  - guest_ip: IP address for eth0 (e.g., "10.200.123.45")
  - gateway: Gateway IP (e.g., "10.200.0.1")
  - netmask: Netmask (optional, defaults to "255.255.0.0")
  - dns: DNS server (optional, defaults to "8.8.8.8")

Usage:
  Run at boot via systemd. Token and vsock port are passed via kernel cmdline:
    octolab.token=<token> octolab.vsock_port=<port>
"""

import base64
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# =============================================================================
# Constants
# =============================================================================

AF_VSOCK = 40  # socket.AF_VSOCK on Linux
VMADDR_CID_ANY = 0xFFFFFFFF
VMADDR_CID_HOST = 2

DEFAULT_VSOCK_PORT = 5000
MAX_REQUEST_SIZE = 100 * 1024 * 1024  # 100 MB for project uploads
MAX_OUTPUT_SIZE = 65536  # 64 KB
REQUEST_TIMEOUT = 300.0  # 5 minutes for compose operations
SHORT_TIMEOUT = 30.0  # For simple commands

# Directories
PROJECT_BASE = Path("/opt/octolab")
PROJECT_DIR = PROJECT_BASE / "project"
PROJECT_TAR = PROJECT_BASE / "project.tgz"
COMPOSE_STATUS_FILE = PROJECT_BASE / "last_compose_status.json"

# Build metadata file (written by build-rootfs.sh)
BUILD_METADATA_FILE = Path("/etc/octolab-build.json")

# Fallback agent version (if build metadata not found)
AGENT_VERSION_FALLBACK = "1.0.0"

# Build metadata (loaded at startup)
_build_metadata: dict[str, Any] | None = None

# Allowed commands (security: deny-by-default)
ALLOWED_COMMANDS = frozenset({
    "ping",
    "upload_project",
    "compose_up",
    "compose_down",
    "status",
    "diag",  # Diagnostic command for debugging
    "configure_network",  # Set up eth0 with IP/gateway/DNS
})

# Docker readiness configuration (can be overridden via env var)
DEFAULT_DOCKER_TIMEOUT = 60  # seconds
DOCKER_POLL_INTERVAL = 1.0  # Poll every 1 second

# Current project name (set on upload)
current_project_name: str | None = None


# =============================================================================
# Helper Functions
# =============================================================================


def log(msg: str) -> None:
    """Log message with timestamp."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


def parse_cmdline() -> dict:
    """Parse kernel command line for octolab parameters."""
    params = {}
    try:
        with open("/proc/cmdline", "r") as f:
            cmdline = f.read()

        for part in cmdline.split():
            if part.startswith("octolab."):
                key, _, value = part.partition("=")
                params[key] = value
    except Exception:
        pass

    return params


def get_token() -> str:
    """Get authentication token from kernel cmdline."""
    params = parse_cmdline()
    return params.get("octolab.token", "")


def get_vsock_port() -> int:
    """Get vsock port from kernel cmdline."""
    params = parse_cmdline()
    try:
        return int(params.get("octolab.vsock_port", DEFAULT_VSOCK_PORT))
    except ValueError:
        return DEFAULT_VSOCK_PORT


def validate_project_name(name: str) -> bool:
    """Validate project name is safe.

    SECURITY: Prevent directory traversal and injection.
    """
    if not name:
        return False
    # Only alphanumeric, underscore, hyphen
    if not re.match(r"^[a-zA-Z0-9_-]+$", name):
        return False
    # No path components
    if ".." in name or "/" in name or "\\" in name:
        return False
    return len(name) <= 100


def run_cmd(
    args: list[str],
    timeout: float = REQUEST_TIMEOUT,
    cwd: Path | str | None = None,
) -> dict[str, Any]:
    """Run a command safely.

    SECURITY:
    - shell=False always
    - Bounded output
    - Enforced timeout
    """
    try:
        result = subprocess.run(
            args,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout[:MAX_OUTPUT_SIZE],
            "stderr": result.stderr[:MAX_OUTPUT_SIZE],
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "stdout": "",
            "stderr": "Command timed out",
            "exit_code": -1,
        }
    except FileNotFoundError as e:
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Command not found: {e.filename}",
            "exit_code": -1,
        }
    except Exception as e:
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Error: {type(e).__name__}",
            "exit_code": -1,
        }


def ensure_project_dirs() -> None:
    """Ensure project directories exist."""
    PROJECT_BASE.mkdir(parents=True, exist_ok=True, mode=0o755)


def load_build_metadata() -> dict[str, Any]:
    """Load build metadata from /etc/octolab-build.json.

    Returns:
        Build metadata dict, or fallback dict if file not found.

    SECURITY: Only reads from known path, returns sanitized data.
    """
    global _build_metadata

    # Return cached value if already loaded
    if _build_metadata is not None:
        return _build_metadata

    try:
        if BUILD_METADATA_FILE.exists():
            data = json.loads(BUILD_METADATA_FILE.read_text())
            _build_metadata = {
                "agent_version": str(data.get("agent_version", AGENT_VERSION_FALLBACK)),
                "build_id": str(data.get("build_id", "unknown")),
                "build_date": str(data.get("build_date", "")),
                "git_sha": str(data.get("git_sha", "")),
            }
            log(f"Loaded build metadata: build_id={_build_metadata['build_id']}")
        else:
            log(f"Build metadata file not found: {BUILD_METADATA_FILE}")
            _build_metadata = {
                "agent_version": AGENT_VERSION_FALLBACK,
                "build_id": "unknown",
                "build_date": "",
                "git_sha": "",
            }
    except Exception as e:
        log(f"Failed to load build metadata: {type(e).__name__}")
        _build_metadata = {
            "agent_version": AGENT_VERSION_FALLBACK,
            "build_id": "unknown",
            "build_date": "",
            "git_sha": "",
        }

    return _build_metadata


def get_agent_version() -> str:
    """Get agent version from build metadata."""
    return load_build_metadata()["agent_version"]


def get_rootfs_build_id() -> str:
    """Get rootfs build ID from build metadata."""
    return load_build_metadata()["build_id"]


def get_docker_timeout() -> int:
    """Get Docker ready timeout from env var or default.

    Reads OCTOLAB_VM_DOCKER_TIMEOUT environment variable.
    """
    try:
        return int(os.getenv("OCTOLAB_VM_DOCKER_TIMEOUT", str(DEFAULT_DOCKER_TIMEOUT)))
    except ValueError:
        return DEFAULT_DOCKER_TIMEOUT


def wait_for_docker(timeout_seconds: int | None = None) -> bool:
    """Wait for Docker daemon to become ready.

    Polls `docker info` until it succeeds or timeout.

    Args:
        timeout_seconds: Maximum wait time in seconds (uses env var if None)

    Returns:
        True if Docker is ready, False if timeout reached.

    SECURITY: Only runs `docker info`, no arbitrary commands.
    """
    if timeout_seconds is None:
        timeout_seconds = get_docker_timeout()

    start_time = time.time()
    log(f"Waiting for Docker daemon (timeout={timeout_seconds}s)...")

    while time.time() - start_time < timeout_seconds:
        try:
            result = subprocess.run(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                shell=False,
            )
            if result.returncode == 0:
                elapsed = time.time() - start_time
                log(f"Docker daemon is ready (took {elapsed:.1f}s)")
                return True
        except Exception:
            pass  # Retry on any exception
        time.sleep(DOCKER_POLL_INTERVAL)

    log(f"Docker daemon did not become ready within {timeout_seconds} seconds")
    return False


def save_compose_status(project_name: str, success: bool, error: str | None = None) -> None:
    """Save last compose operation status for diagnostics.

    SECURITY: Only writes to controlled path, no secrets.
    """
    try:
        status = {
            "project": project_name,
            "success": success,
            "error": error[:500] if error else None,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        COMPOSE_STATUS_FILE.write_text(json.dumps(status))
    except Exception:
        pass  # Best effort, don't fail on status save


def load_compose_status() -> dict | None:
    """Load last compose operation status.

    Returns:
        Status dict or None if not available.
    """
    try:
        if COMPOSE_STATUS_FILE.exists():
            return json.loads(COMPOSE_STATUS_FILE.read_text())
    except Exception:
        pass
    return None


# =============================================================================
# Command Handlers
# =============================================================================


def handle_ping(request: dict) -> dict[str, Any]:
    """Handle ping command - health check with version info.

    Returns:
        Response with agent_version and rootfs_build_id for backend validation.

    SECURITY: Backend uses these fields to detect stale rootfs/agent mismatches.
    """
    metadata = load_build_metadata()
    return {
        "ok": True,
        "stdout": "pong",
        "stderr": "",
        "exit_code": 0,
        # Version fields for backend enforcement
        "agent_version": metadata["agent_version"],
        "rootfs_build_id": metadata["build_id"],
    }


def handle_upload_project(request: dict) -> dict[str, Any]:
    """Handle project upload.

    Expects request with:
    - data: base64-encoded tar.gz content
    - project: project name (validated)

    SECURITY:
    - Validates project name
    - Writes only to PROJECT_BASE
    """
    global current_project_name

    try:
        data_b64 = request.get("data")
        project_name = request.get("project")

        if not data_b64:
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Missing data field",
                "exit_code": -1,
            }

        if not project_name or not validate_project_name(project_name):
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Invalid project name",
                "exit_code": -1,
            }

        # Decode base64
        try:
            data = base64.b64decode(data_b64)
        except Exception:
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Invalid base64 data",
                "exit_code": -1,
            }

        # Size check
        if len(data) > MAX_REQUEST_SIZE:
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Data too large",
                "exit_code": -1,
            }

        # Ensure directories
        ensure_project_dirs()

        # Write tar file
        PROJECT_TAR.write_bytes(data)

        # Clear and recreate project dir
        if PROJECT_DIR.exists():
            result = run_cmd(["rm", "-rf", str(PROJECT_DIR)], timeout=SHORT_TIMEOUT)
            if not result["ok"]:
                return {
                    "ok": False,
                    "stdout": "",
                    "stderr": f"Failed to clear project dir: {result['stderr']}",
                    "exit_code": -1,
                }

        PROJECT_DIR.mkdir(parents=True, exist_ok=True)

        # Extract tar
        result = run_cmd(
            ["tar", "-xzf", str(PROJECT_TAR), "-C", str(PROJECT_DIR)],
            timeout=60,
        )

        if not result["ok"]:
            return {
                "ok": False,
                "stdout": "",
                "stderr": f"Tar extraction failed: {result['stderr'][:200]}",
                "exit_code": -1,
            }

        # Verify docker-compose.yml exists
        compose_file = PROJECT_DIR / "docker-compose.yml"
        if not compose_file.exists():
            # Check subdirectories
            found = list(PROJECT_DIR.glob("**/docker-compose.yml"))
            if found:
                compose_file = found[0]
                log(f"Found compose file at: {compose_file}")
            else:
                return {
                    "ok": False,
                    "stdout": "",
                    "stderr": "docker-compose.yml not found in archive",
                    "exit_code": -1,
                }

        # Store project name
        current_project_name = project_name

        log(f"Project uploaded: {project_name}")

        return {
            "ok": True,
            "stdout": f"Project uploaded: {project_name}",
            "stderr": "",
            "exit_code": 0,
        }

    except Exception as e:
        log(f"upload_project error: {type(e).__name__}")
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Error: {type(e).__name__}",
            "exit_code": -1,
        }


def handle_compose_up(request: dict) -> dict[str, Any]:
    """Handle compose up command.

    SECURITY:
    - Only runs from PROJECT_DIR
    - Project name validated
    - Waits for Docker to be ready before proceeding
    - shell=False for all subprocess calls

    Returns dict with:
    - ok: bool
    - docker_ready: bool (always present for debugging)
    - stdout, stderr, exit_code: from compose command
    - summary: human-readable error summary (on failure)
    """
    global current_project_name

    # Track docker_ready state for response
    docker_ready = False

    try:
        project_name = request.get("project") or current_project_name

        if not project_name or not validate_project_name(project_name):
            return {
                "ok": False,
                "docker_ready": docker_ready,
                "stdout": "",
                "stderr": "Invalid project name",
                "exit_code": -1,
                "summary": "invalid_project_name",
            }

        compose_file = PROJECT_DIR / "docker-compose.yml"
        compose_file_exists = compose_file.exists()
        if not compose_file_exists:
            # Check subdirectories
            found = list(PROJECT_DIR.glob("**/docker-compose.yml"))
            if found:
                compose_file = found[0]
                compose_file_exists = True
            else:
                save_compose_status(project_name, False, "No compose file found")
                return {
                    "ok": False,
                    "docker_ready": docker_ready,
                    "stdout": "",
                    "stderr": "No compose file found",
                    "exit_code": -1,
                    "summary": "compose_file=no",
                }

        # Wait for Docker daemon to become ready (with retry loop)
        timeout = get_docker_timeout()
        docker_ready = wait_for_docker(timeout)
        if not docker_ready:
            error_msg = f"Docker daemon not ready within {timeout}s"
            save_compose_status(project_name, False, error_msg)
            return {
                "ok": False,
                "docker_ready": False,
                "stdout": "",
                "stderr": error_msg,
                "exit_code": -1,
                "summary": "docker_not_ready",
            }

        log(f"Running compose up for project: {project_name}")
        log(f"Compose file: {compose_file}")

        # Pull images first (bounded timeout, non-fatal warnings)
        log(f"Pulling images for project {project_name}...")
        pull_result = run_cmd(
            [
                "docker", "compose",
                "-f", str(compose_file),
                "-p", project_name,
                "pull",
            ],
            timeout=120.0,  # 2 minutes for pull
            cwd=compose_file.parent,
        )
        if pull_result["ok"]:
            log("Image pull complete.")
        else:
            # Non-fatal: images may already exist locally
            log(f"Image pull warning: {pull_result['stderr'][:200] if pull_result['stderr'] else 'no output'}")

        # Run docker compose up
        result = run_cmd(
            [
                "docker", "compose",
                "-f", str(compose_file),
                "-p", project_name,
                "up", "-d",
            ],
            timeout=REQUEST_TIMEOUT,
            cwd=compose_file.parent,
        )

        # Always add docker_ready to result
        result["docker_ready"] = docker_ready

        # Build summary for debugging
        if result["ok"]:
            save_compose_status(project_name, True)
            log(f"compose_up OK: {result['stdout'][:100] if result['stdout'] else 'no output'}")
            result["summary"] = "ok"
        else:
            # Extract last line of stderr for concise error reporting
            last_err_line = ""
            if result.get("stderr"):
                lines = result["stderr"].strip().splitlines()
                if lines:
                    last_err_line = lines[-1][:200]

            summary = f"exit={result['exit_code']}, last_line={last_err_line}"
            result["summary"] = summary

            save_compose_status(project_name, False, last_err_line or result.get("stderr", "unknown")[:200])
            log(f"compose_up FAILED: {summary}")

        return result

    except Exception as e:
        log(f"compose_up error: {type(e).__name__}")
        save_compose_status(project_name if 'project_name' in dir() else "unknown", False, str(type(e).__name__))
        return {
            "ok": False,
            "docker_ready": docker_ready,
            "stdout": "",
            "stderr": f"Error: {type(e).__name__}",
            "exit_code": -1,
            "summary": f"exception={type(e).__name__}",
        }


def handle_compose_down(request: dict) -> dict[str, Any]:
    """Handle compose down command.

    SECURITY:
    - Only runs from PROJECT_DIR
    - Project name validated
    """
    global current_project_name

    try:
        project_name = request.get("project") or current_project_name

        if not project_name or not validate_project_name(project_name):
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Invalid project name",
                "exit_code": -1,
            }

        compose_file = PROJECT_DIR / "docker-compose.yml"
        if not compose_file.exists():
            # Check subdirectories
            found = list(PROJECT_DIR.glob("**/docker-compose.yml"))
            if found:
                compose_file = found[0]
            else:
                # Nothing to tear down
                return {
                    "ok": True,
                    "stdout": "No compose file found, nothing to do",
                    "stderr": "",
                    "exit_code": 0,
                }

        log(f"Running compose down for project: {project_name}")

        # Run docker compose down
        result = run_cmd(
            [
                "docker", "compose",
                "-f", str(compose_file),
                "-p", project_name,
                "down", "--remove-orphans", "--volumes",
            ],
            timeout=REQUEST_TIMEOUT,
            cwd=compose_file.parent,
        )

        return result

    except Exception as e:
        log(f"compose_down error: {type(e).__name__}")
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Error: {type(e).__name__}",
            "exit_code": -1,
        }


def handle_status(request: dict) -> dict[str, Any]:
    """Handle status command - get docker container status."""
    try:
        # Get container status
        result = run_cmd(
            ["docker", "ps", "--format", "{{json .}}"],
            timeout=SHORT_TIMEOUT,
        )

        if not result["ok"]:
            return result

        # Parse output
        containers = []
        for line in result["stdout"].strip().split("\n"):
            if line:
                try:
                    container = json.loads(line)
                    containers.append({
                        "id": container.get("ID", "")[:12],
                        "name": container.get("Names", ""),
                        "status": container.get("Status", ""),
                        "ports": container.get("Ports", ""),
                    })
                except json.JSONDecodeError:
                    pass

        return {
            "ok": True,
            "stdout": json.dumps(containers, indent=2),
            "stderr": "",
            "exit_code": 0,
        }

    except Exception as e:
        log(f"status error: {type(e).__name__}")
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Error: {type(e).__name__}",
            "exit_code": -1,
        }


def handle_diag(request: dict) -> dict[str, Any]:
    """Handle diagnostic command - collect lightweight debugging information.

    Returns structured diagnostics for compose_up debugging:
    - docker_ready: whether Docker daemon is responsive
    - last_compose_status: result of last compose operation
    - summary: brief text summary of system state

    SECURITY:
    - Only reads system state, no modifications
    - Returns only non-sensitive data (booleans, small strings)
    - Does NOT dump full docker logs or environment variables
    - Has its own small timeout on internal operations
    """
    try:
        # Quick Docker readiness check (short timeout)
        docker_ready = wait_for_docker(timeout_seconds=5)

        # Load last compose status
        last_compose_status = load_compose_status()

        # Build brief summary (truncated, safe)
        summary_parts = []

        # Container count
        ps_result = run_cmd(["docker", "ps", "-q"], timeout=5.0)
        if ps_result["ok"]:
            container_count = len([l for l in ps_result["stdout"].strip().split("\n") if l])
            summary_parts.append(f"containers={container_count}")
        else:
            summary_parts.append("containers=unknown")

        # Image count
        images_result = run_cmd(["docker", "images", "-q"], timeout=5.0)
        if images_result["ok"]:
            image_count = len([l for l in images_result["stdout"].strip().split("\n") if l])
            summary_parts.append(f"images={image_count}")

        # Project dir status
        if PROJECT_DIR.exists():
            compose_exists = (PROJECT_DIR / "docker-compose.yml").exists()
            summary_parts.append(f"compose_file={'yes' if compose_exists else 'no'}")
        else:
            summary_parts.append("project_dir=missing")

        summary = ", ".join(summary_parts)

        return {
            "ok": True,
            "docker_ready": docker_ready,
            "last_compose_status": last_compose_status,
            "summary": summary[:500],  # Truncate for safety
            # Keep legacy fields for compatibility
            "stdout": summary[:500],
            "stderr": "",
            "exit_code": 0,
        }

    except Exception as e:
        log(f"diag error: {type(e).__name__}")
        return {
            "ok": False,
            "docker_ready": False,
            "last_compose_status": None,
            "summary": f"Error: {type(e).__name__}",
            "stdout": "",
            "stderr": f"Error: {type(e).__name__}",
            "exit_code": -1,
        }


def handle_configure_network(request: dict) -> dict[str, Any]:
    """Configure the VM's network interface (eth0).

    Expects request with:
    - guest_ip: IP address for eth0 (e.g., "10.200.123.45")
    - gateway: Gateway IP (e.g., "10.200.0.1")
    - netmask: Netmask (e.g., "255.255.0.0") - optional, defaults to 255.255.0.0
    - dns: DNS server (e.g., "8.8.8.8") - optional, defaults to 8.8.8.8
    - interface: Interface name - optional, defaults to "eth0"

    SECURITY:
    - Only configures specified interface (eth0)
    - Validates IP formats
    - Only writes to /etc/resolv.conf
    - Uses shell=False for all commands
    """
    try:
        guest_ip = request.get("guest_ip")
        gateway = request.get("gateway")
        netmask = request.get("netmask", "255.255.0.0")
        dns = request.get("dns", "8.8.8.8")
        interface = request.get("interface", "eth0")

        # Validate required parameters
        if not guest_ip:
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Missing guest_ip",
                "exit_code": -1,
            }
        if not gateway:
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Missing gateway",
                "exit_code": -1,
            }

        # Validate IP format (basic check)
        ip_pattern = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
        for label, value in [("guest_ip", guest_ip), ("gateway", gateway),
                              ("netmask", netmask), ("dns", dns)]:
            if not ip_pattern.match(value):
                return {
                    "ok": False,
                    "stdout": "",
                    "stderr": f"Invalid {label} format: {value}",
                    "exit_code": -1,
                }

        # Validate interface name (security: prevent injection)
        if not re.match(r"^eth[0-9]$", interface):
            return {
                "ok": False,
                "stdout": "",
                "stderr": f"Invalid interface name: {interface}",
                "exit_code": -1,
            }

        log(f"Configuring network: ip={guest_ip}, gw={gateway}, dns={dns}")

        # Convert netmask to CIDR prefix
        netmask_to_cidr = {
            "255.255.255.255": "32",
            "255.255.255.0": "24",
            "255.255.0.0": "16",
            "255.0.0.0": "8",
        }
        cidr = netmask_to_cidr.get(netmask, "16")

        # Step 1: Bring up the interface
        result = run_cmd(["ip", "link", "set", interface, "up"], timeout=10.0)
        if not result["ok"]:
            return {
                "ok": False,
                "stdout": result["stdout"],
                "stderr": f"Failed to bring up {interface}: {result['stderr']}",
                "exit_code": result["exit_code"],
            }

        # Step 2: Flush any existing IP addresses
        run_cmd(["ip", "addr", "flush", "dev", interface], timeout=10.0)

        # Step 3: Add IP address with CIDR
        result = run_cmd(
            ["ip", "addr", "add", f"{guest_ip}/{cidr}", "dev", interface],
            timeout=10.0
        )
        if not result["ok"]:
            # Check if already exists (idempotent)
            if "File exists" not in result["stderr"]:
                return {
                    "ok": False,
                    "stdout": result["stdout"],
                    "stderr": f"Failed to set IP: {result['stderr']}",
                    "exit_code": result["exit_code"],
                }

        # Step 4: Add default route via gateway
        # First delete any existing default route
        run_cmd(["ip", "route", "del", "default"], timeout=10.0)

        result = run_cmd(
            ["ip", "route", "add", "default", "via", gateway, "dev", interface],
            timeout=10.0
        )
        if not result["ok"]:
            # Check if already exists (idempotent)
            if "File exists" not in result["stderr"]:
                return {
                    "ok": False,
                    "stdout": result["stdout"],
                    "stderr": f"Failed to set gateway: {result['stderr']}",
                    "exit_code": result["exit_code"],
                }

        # Step 5: Configure DNS
        try:
            with open("/etc/resolv.conf", "w") as f:
                f.write(f"nameserver {dns}\n")
            log(f"DNS configured: {dns}")
        except Exception as e:
            log(f"Warning: Failed to configure DNS: {e}")
            # Non-fatal - network may still work

        # Verify connectivity (optional - try to ping gateway)
        ping_result = run_cmd(["ping", "-c", "1", "-W", "2", gateway], timeout=5.0)

        # Build summary
        summary_parts = [
            f"ip={guest_ip}/{cidr}",
            f"gw={gateway}",
            f"dns={dns}",
            f"ping_gw={'ok' if ping_result['ok'] else 'fail'}",
        ]
        summary = ", ".join(summary_parts)

        log(f"Network configured: {summary}")

        return {
            "ok": True,
            "stdout": summary,
            "stderr": "",
            "exit_code": 0,
            "network_config": {
                "ip": guest_ip,
                "cidr": cidr,
                "gateway": gateway,
                "dns": dns,
                "interface": interface,
                "gateway_reachable": ping_result["ok"],
            },
        }

    except Exception as e:
        log(f"configure_network error: {type(e).__name__}")
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Error: {type(e).__name__}",
            "exit_code": -1,
        }


# Command dispatcher
COMMAND_HANDLERS = {
    "ping": handle_ping,
    "upload_project": handle_upload_project,
    "compose_up": handle_compose_up,
    "compose_down": handle_compose_down,
    "status": handle_status,
    "diag": handle_diag,
    "configure_network": handle_configure_network,
}


# =============================================================================
# Request Handling
# =============================================================================


def handle_request(request_data: bytes, expected_token: str) -> bytes:
    """Handle a single request.

    Args:
        request_data: Raw request JSON
        expected_token: Expected authentication token

    Returns:
        Response JSON bytes
    """
    try:
        request = json.loads(request_data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return json.dumps({
            "ok": False,
            "error": "Invalid JSON",
        }).encode() + b"\n"

    # Authenticate
    token = request.get("token", "")
    if not token or token != expected_token:
        log("Authentication failed")
        return json.dumps({
            "ok": False,
            "error": "Authentication failed",
        }).encode() + b"\n"

    # Get command (support both "command" and "action" keys)
    command = request.get("command", request.get("action", ""))
    if not command:
        return json.dumps({
            "ok": False,
            "error": "No command specified",
        }).encode() + b"\n"

    if command not in ALLOWED_COMMANDS:
        return json.dumps({
            "ok": False,
            "error": f"Unknown command: {command}",
        }).encode() + b"\n"

    # Execute command
    log(f"Executing command: {command}")
    handler = COMMAND_HANDLERS[command]
    result = handler(request)

    return json.dumps(result).encode() + b"\n"


def handle_client(conn: socket.socket, expected_token: str) -> None:
    """Handle a connected client.

    Args:
        conn: Client socket
        expected_token: Expected authentication token
    """
    conn.settimeout(REQUEST_TIMEOUT)

    try:
        # Receive request (potentially large for project uploads)
        data = b""
        while len(data) < MAX_REQUEST_SIZE:
            try:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break
            except socket.timeout:
                break

        if not data:
            return

        # Handle request
        response = handle_request(data.strip(), expected_token)

        # Send response
        conn.sendall(response)

    except Exception as e:
        log(f"Connection error: {type(e).__name__}")
        try:
            conn.sendall(json.dumps({
                "ok": False,
                "error": "Internal error",
            }).encode() + b"\n")
        except Exception:
            pass

    finally:
        try:
            conn.close()
        except Exception:
            pass


# =============================================================================
# Main Entry Point
# =============================================================================


def main() -> int:
    """Main entry point."""
    log("OctoLab Guest Agent starting...")

    # Load and log build metadata early
    metadata = load_build_metadata()
    log(f"Agent version: {metadata['agent_version']}, rootfs build_id: {metadata['build_id']}")

    # Get configuration from kernel cmdline
    token = get_token()
    port = get_vsock_port()

    if not token:
        log("ERROR: No token found in kernel cmdline (octolab.token=...)")
        return 1

    log(f"Listening on vsock port {port}")

    # Ensure project directories
    ensure_project_dirs()

    # Create vsock server
    try:
        server = socket.socket(AF_VSOCK, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((VMADDR_CID_ANY, port))
        server.listen(5)
    except Exception as e:
        log(f"ERROR: Failed to create vsock server: {e}")
        return 1

    # Handle SIGTERM gracefully
    def handle_sigterm(signum, frame):
        log("Received SIGTERM, shutting down...")
        server.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)

    # Print ready marker for boot detection
    print("AGENT_READY", flush=True)
    log("Agent ready, waiting for connections...")

    while True:
        try:
            conn, addr = server.accept()
            log(f"Connection from CID {addr[0]}")
            handle_client(conn, token)
        except KeyboardInterrupt:
            log("Interrupted, shutting down...")
            break
        except Exception as e:
            log(f"Error accepting connection: {type(e).__name__}")
            time.sleep(0.1)

    server.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
