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
  docker_build      - Build Docker image from Dockerfile + source files

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
    "docker_build",  # Build Docker image from Dockerfile + source files
    "wait_for_images",  # Wait for pre-baked images to be loaded
    "container_logs",  # Get container logs for debugging crash loops
    "net_test",  # Test network connectivity (DNS + HTTP)
    "iptables_check",  # Check if kernel has netfilter support
    "exec",  # Execute command inside a running container
})

# Marker file written by octolab-load-images.service when images are loaded
IMAGES_LOADED_MARKER = Path("/var/lib/octolab/.images-loaded")

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


def handle_container_logs(request: dict) -> dict[str, Any]:
    """Handle container_logs command - get logs from a specific container.

    Used for debugging crash-looping containers.

    Expects request with:
    - container: Container name or ID (required)
    - tail: Number of lines to return (optional, default 100, max 500)

    SECURITY:
    - Only reads logs, no modifications
    - Limits output size to prevent memory exhaustion
    - Container name is validated (alphanumeric, dash, underscore only)
    """
    container = request.get("container", "")
    tail = min(int(request.get("tail", 100)), 500)  # Cap at 500 lines

    # Validate container name (security: prevent injection)
    if not container or not all(c.isalnum() or c in "-_" for c in container):
        return {
            "ok": False,
            "logs": "",
            "stderr": "Invalid container name",
            "exit_code": 1,
        }

    try:
        result = run_cmd(
            ["docker", "logs", "--tail", str(tail), container],
            timeout=SHORT_TIMEOUT,
        )

        # Docker logs outputs to both stdout and stderr
        # Combine them for complete picture
        logs = result["stdout"]
        if result["stderr"]:
            logs += "\n--- stderr ---\n" + result["stderr"]

        return {
            "ok": result["ok"],
            "logs": logs[:50000],  # Truncate to 50KB max
            "stderr": "" if result["ok"] else result["stderr"][:500],
            "exit_code": result["exit_code"],
        }

    except Exception as e:
        log(f"container_logs error: {type(e).__name__}")
        return {
            "ok": False,
            "logs": "",
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


def handle_docker_build(request: dict) -> dict[str, Any]:
    """Build Docker image from Dockerfile and source files.

    Expects request with:
    - project: str - project name (used as image tag)
    - dockerfile: str - Dockerfile content
    - source_files: list[{filename, content}] - additional source files (optional)

    Returns:
        {ok: true, image: str, stdout: ..., stderr: ..., exit_code: 0} on success
        {ok: false, error: str, stderr: str, exit_code: int} on failure

    SECURITY:
    - Validates project name
    - Writes only under PROJECT_BASE/build
    - Blocks dangerous Dockerfile directives (--privileged, COPY --from external)
    - Enforces build timeout
    - Resource limits via --memory and --cpu-quota
    """
    try:
        project_name = request.get("project")
        dockerfile_content = request.get("dockerfile")
        source_files = request.get("source_files", [])

        # Validate project name
        if not project_name or not validate_project_name(project_name):
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Invalid project name",
                "exit_code": -1,
            }

        # Validate Dockerfile content
        if not dockerfile_content or not isinstance(dockerfile_content, str):
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Missing or invalid dockerfile content",
                "exit_code": -1,
            }

        # Size check for Dockerfile (64KB max)
        if len(dockerfile_content) > 65536:
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Dockerfile too large (max 64KB)",
                "exit_code": -1,
            }

        # Basic Dockerfile security checks
        dockerfile_lower = dockerfile_content.lower()
        if "--privileged" in dockerfile_lower:
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Dockerfile contains disallowed directive: --privileged",
                "exit_code": -1,
            }

        # Block COPY --from with external URLs (allow internal multi-stage)
        # Pattern: COPY --from=http or COPY --from=https
        if re.search(r"copy\s+--from\s*=\s*(https?://|ftp://)", dockerfile_lower):
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Dockerfile contains disallowed external COPY --from",
                "exit_code": -1,
            }

        # Must start with FROM
        lines = dockerfile_content.strip().split("\n")
        non_comment_lines = [l for l in lines if l.strip() and not l.strip().startswith("#")]
        if not non_comment_lines or not non_comment_lines[0].strip().upper().startswith("FROM"):
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Dockerfile must start with FROM instruction",
                "exit_code": -1,
            }

        # Validate source_files
        if not isinstance(source_files, list):
            return {
                "ok": False,
                "stdout": "",
                "stderr": "source_files must be a list",
                "exit_code": -1,
            }

        # Limit number of source files
        if len(source_files) > 20:
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Too many source files (max 20)",
                "exit_code": -1,
            }

        # Create build directory
        build_dir = PROJECT_BASE / "build" / project_name
        if build_dir.exists():
            result = run_cmd(["rm", "-rf", str(build_dir)], timeout=SHORT_TIMEOUT)
            if not result["ok"]:
                return {
                    "ok": False,
                    "stdout": "",
                    "stderr": f"Failed to clear build dir: {result['stderr']}",
                    "exit_code": -1,
                }

        build_dir.mkdir(parents=True, exist_ok=True)

        # Write Dockerfile
        dockerfile_path = build_dir / "Dockerfile"
        dockerfile_path.write_text(dockerfile_content)
        log(f"Wrote Dockerfile for project {project_name}")

        # Write source files
        for sf in source_files:
            if not isinstance(sf, dict):
                continue
            filename = sf.get("filename", "")
            content = sf.get("content", "")

            # Validate filename (security: prevent path traversal)
            if not filename or "/" in filename or "\\" in filename or ".." in filename:
                log(f"Skipping invalid filename: {filename[:50]}")
                continue

            # Size limit per file (1MB)
            if len(content) > 1_000_000:
                log(f"Skipping oversized file: {filename}")
                continue

            file_path = build_dir / filename
            file_path.write_text(content)
            log(f"Wrote source file: {filename}")

        # Wait for Docker daemon
        docker_ready = wait_for_docker(timeout_seconds=30)
        if not docker_ready:
            return {
                "ok": False,
                "docker_ready": False,
                "stdout": "",
                "stderr": "Docker daemon not ready",
                "exit_code": -1,
            }

        # Build image with resource limits
        image_tag = f"octolab/{project_name}:latest"
        log(f"Building image: {image_tag}")

        build_result = run_cmd(
            [
                "docker", "build",
                "--tag", image_tag,
                "--memory", "2g",  # Memory limit
                "--cpu-quota", "100000",  # CPU quota (100% of 1 CPU)
                "--no-cache",  # Fresh build each time
                "--progress", "plain",  # Readable output
                ".",
            ],
            timeout=300.0,  # 5 minute timeout
            cwd=build_dir,
        )

        if not build_result["ok"]:
            log(f"docker_build FAILED: {build_result['stderr'][:200]}")
            return {
                "ok": False,
                "docker_ready": True,
                "stdout": build_result["stdout"],
                "stderr": build_result["stderr"],
                "exit_code": build_result["exit_code"],
                "summary": "build_failed",
            }

        # Get image ID
        inspect_result = run_cmd(
            ["docker", "inspect", "--format", "{{.Id}}", image_tag],
            timeout=SHORT_TIMEOUT,
        )

        image_id = inspect_result["stdout"].strip() if inspect_result["ok"] else "unknown"

        log(f"docker_build OK: {image_tag} (id={image_id[:20]}...)")

        return {
            "ok": True,
            "docker_ready": True,
            "image": image_tag,
            "image_id": image_id,
            "stdout": build_result["stdout"],
            "stderr": build_result["stderr"],
            "exit_code": 0,
            "summary": "ok",
        }

    except Exception as e:
        log(f"docker_build error: {type(e).__name__}")
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Error: {type(e).__name__}",
            "exit_code": -1,
        }


def handle_wait_for_images(request: dict) -> dict[str, Any]:
    """Wait for pre-baked Docker images to be loaded.

    The octolab-load-images.service loads images from /var/lib/octolab/images/
    on first boot. This command waits for that process to complete by polling
    for the marker file.

    Expects request with:
    - timeout: int - Max wait time in seconds (optional, defaults to 120)

    Returns:
        {ok: true, images_ready: true, waited_seconds: float} on success
        {ok: false, images_ready: false, error: str} on timeout/failure

    SECURITY:
    - Only checks for marker file existence, no modifications
    - Bounded timeout
    """
    try:
        timeout = request.get("timeout", 120)
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            timeout = 120
        timeout = min(timeout, 300)  # Cap at 5 minutes

        log(f"Waiting for images to be loaded (timeout={timeout}s)...")

        # If marker already exists, return immediately
        if IMAGES_LOADED_MARKER.exists():
            log("Images already loaded (marker exists)")
            return {
                "ok": True,
                "images_ready": True,
                "waited_seconds": 0,
                "stdout": "Images already loaded",
                "stderr": "",
                "exit_code": 0,
            }

        # Poll for marker file
        start_time = time.time()
        poll_interval = 1.0

        while time.time() - start_time < timeout:
            if IMAGES_LOADED_MARKER.exists():
                elapsed = time.time() - start_time
                log(f"Images loaded after {elapsed:.1f}s")
                return {
                    "ok": True,
                    "images_ready": True,
                    "waited_seconds": elapsed,
                    "stdout": f"Images loaded after {elapsed:.1f}s",
                    "stderr": "",
                    "exit_code": 0,
                }
            time.sleep(poll_interval)

        # Timeout
        elapsed = time.time() - start_time
        log(f"Timeout waiting for images after {elapsed:.1f}s")
        return {
            "ok": False,
            "images_ready": False,
            "waited_seconds": elapsed,
            "stdout": "",
            "stderr": f"Images not loaded within {timeout}s",
            "exit_code": -1,
        }

    except Exception as e:
        log(f"wait_for_images error: {type(e).__name__}")
        return {
            "ok": False,
            "images_ready": False,
            "stdout": "",
            "stderr": f"Error: {type(e).__name__}",
            "exit_code": -1,
        }


def handle_net_test(request: dict) -> dict[str, Any]:
    """Test network connectivity from the VM.

    Tests DNS resolution and HTTP connectivity by running curl.
    Since octobox uses host networking, this tests the same network path.

    Expects request with:
    - url: URL to test (optional, defaults to https://google.com)

    Returns:
        {ok: true, dns_ok: bool, http_ok: bool, http_code: int, ...}

    SECURITY:
    - Only tests connectivity, no modifications
    - URL is validated (must be http/https)
    - Bounded timeout
    """
    url = request.get("url", "https://google.com")

    # Validate URL (security: only allow http/https)
    if not url.startswith("http://") and not url.startswith("https://"):
        return {
            "ok": False,
            "error": "URL must start with http:// or https://",
            "exit_code": -1,
        }

    # Test 1: DNS resolution (via getent or nslookup)
    # Extract hostname from URL
    import re
    hostname_match = re.match(r"https?://([^/:]+)", url)
    hostname = hostname_match.group(1) if hostname_match else "google.com"

    dns_result = run_cmd(["getent", "hosts", hostname], timeout=10.0)
    dns_ok = dns_result["ok"]
    dns_output = dns_result["stdout"].strip() if dns_result["ok"] else dns_result["stderr"]

    # Test 2: HTTP connectivity via curl
    curl_result = run_cmd(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--connect-timeout", "10", url],
        timeout=15.0
    )
    http_ok = curl_result["ok"]
    http_code = int(curl_result["stdout"].strip()) if curl_result["ok"] and curl_result["stdout"].strip().isdigit() else 0

    # Test 3: Also try curl with verbose output for debugging
    curl_verbose = run_cmd(
        ["curl", "-v", "-s", "-o", "/dev/null", "--connect-timeout", "5", url],
        timeout=10.0
    )

    return {
        "ok": dns_ok and http_ok and http_code in (200, 301, 302),
        "dns_ok": dns_ok,
        "dns_output": dns_output[:200],
        "http_ok": http_ok,
        "http_code": http_code,
        "curl_stderr": curl_verbose["stderr"][:500] if curl_verbose["stderr"] else "",
        "stdout": f"dns={dns_ok}, http={http_code}",
        "stderr": "",
        "exit_code": 0 if (dns_ok and http_ok) else 1,
    }


def handle_iptables_check(request: dict) -> dict[str, Any]:
    """Check if kernel has netfilter/iptables and macvlan/ipvlan support.

    Runs iptables -L to test if netfilter is available in the kernel.
    Also checks for macvlan/ipvlan support as alternatives.

    Returns:
        {ok: true, netfilter_available: bool, macvlan_available: bool, ...}
    """
    # Try to run iptables -L
    iptables_result = run_cmd(["iptables", "-L", "-n"], timeout=10.0)

    # Check /proc/net/ip_tables_names for kernel module
    tables_available = False
    try:
        with open("/proc/net/ip_tables_names", "r") as f:
            tables = f.read().strip()
            tables_available = bool(tables)
    except Exception:
        pass

    # Check kernel config if available
    kernel_config = ""
    macvlan_config = ""
    ipvlan_config = ""
    try:
        import subprocess
        result = subprocess.run(["zcat", "/proc/config.gz"], capture_output=True, timeout=5)
        if result.returncode == 0:
            config = result.stdout.decode()
            netfilter_lines = [l for l in config.split("\n") if "NETFILTER" in l or "NF_" in l][:10]
            kernel_config = "\n".join(netfilter_lines)
            macvlan_lines = [l for l in config.split("\n") if "MACVLAN" in l]
            macvlan_config = "\n".join(macvlan_lines)
            ipvlan_lines = [l for l in config.split("\n") if "IPVLAN" in l]
            ipvlan_config = "\n".join(ipvlan_lines)
    except Exception:
        pass

    # Try to create a test macvlan interface
    macvlan_works = False
    macvlan_test = run_cmd(
        ["ip", "link", "add", "test_macvlan", "link", "eth0", "type", "macvlan", "mode", "bridge"],
        timeout=5.0
    )
    if macvlan_test["ok"]:
        macvlan_works = True
        run_cmd(["ip", "link", "del", "test_macvlan"], timeout=5.0)

    # Try ipvlan
    ipvlan_works = False
    ipvlan_test = run_cmd(
        ["ip", "link", "add", "test_ipvlan", "link", "eth0", "type", "ipvlan", "mode", "l2"],
        timeout=5.0
    )
    if ipvlan_test["ok"]:
        ipvlan_works = True
        run_cmd(["ip", "link", "del", "test_ipvlan"], timeout=5.0)

    netfilter_available = iptables_result["ok"] or tables_available

    return {
        "ok": True,
        "netfilter_available": netfilter_available,
        "iptables_works": iptables_result["ok"],
        "iptables_output": iptables_result["stdout"][:500] if iptables_result["ok"] else "",
        "iptables_error": iptables_result["stderr"][:500] if not iptables_result["ok"] else "",
        "tables_file_exists": tables_available,
        "kernel_config_sample": kernel_config[:500],
        "macvlan_works": macvlan_works,
        "macvlan_config": macvlan_config,
        "macvlan_error": macvlan_test["stderr"][:200] if not macvlan_works else "",
        "ipvlan_works": ipvlan_works,
        "ipvlan_config": ipvlan_config,
        "ipvlan_error": ipvlan_test["stderr"][:200] if not ipvlan_works else "",
        "stdout": f"netfilter={netfilter_available}, macvlan={macvlan_works}, ipvlan={ipvlan_works}",
        "stderr": "",
        "exit_code": 0,
    }


def handle_exec(request: dict) -> dict[str, Any]:
    """Execute a command inside a running container.

    Args:
        request: {container: str, cmd: str, timeout: int (optional)}

    Returns:
        {ok: bool, stdout: str, stderr: str, exit_code: int}
    """
    container = request.get("container")
    cmd = request.get("cmd")
    timeout = request.get("timeout", 30)

    if not container:
        return {"ok": False, "error": "container is required", "stdout": "", "stderr": "", "exit_code": -1}
    if not cmd:
        return {"ok": False, "error": "cmd is required", "stdout": "", "stderr": "", "exit_code": -1}

    # Find the container (it may have a project prefix)
    ps_result = run_cmd(["docker", "ps", "--format", "{{.Names}}"], timeout=10.0)
    if not ps_result["ok"]:
        return {"ok": False, "error": f"Failed to list containers: {ps_result['stderr']}", "stdout": "", "stderr": "", "exit_code": -1}

    containers = ps_result["stdout"].strip().split("\n")
    target_container = None

    for c in containers:
        # Match by name ending (handles project prefixes like octolab_xxx-octobox-1)
        if container in c or c.endswith(container) or c.endswith(f"-{container}-1"):
            target_container = c
            break

    if not target_container:
        return {
            "ok": False,
            "error": f"Container '{container}' not found. Available: {containers}",
            "stdout": "",
            "stderr": "",
            "exit_code": -1
        }

    # Execute command in container
    exec_result = run_cmd(
        ["docker", "exec", target_container, "sh", "-c", cmd],
        timeout=float(timeout)
    )

    return {
        "ok": exec_result["ok"],
        "stdout": exec_result["stdout"],
        "stderr": exec_result["stderr"],
        "exit_code": exec_result["exit_code"],
    }


# Command dispatcher
COMMAND_HANDLERS = {
    "ping": handle_ping,
    "upload_project": handle_upload_project,
    "compose_up": handle_compose_up,
    "compose_down": handle_compose_down,
    "status": handle_status,
    "diag": handle_diag,
    "container_logs": handle_container_logs,
    "configure_network": handle_configure_network,
    "docker_build": handle_docker_build,
    "wait_for_images": handle_wait_for_images,
    "net_test": handle_net_test,
    "iptables_check": handle_iptables_check,
    "exec": handle_exec,
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
