"""Standalone MicroVM Doctor - Health checks WITHOUT app.config dependencies.

This module provides Firecracker/microVM health checks that can run independently
of the application Settings, allowing setup scripts to verify prerequisites
before the full backend environment is configured.

SECURITY:
- Never log secrets or full absolute paths (use basename only)
- All subprocess calls use shell=False with list args
- Enforce hard timeouts on all checks
- Truncate and redact output for safety

USAGE:
  # CLI: Run from backend directory
  python -m app.services.microvm_doctor --pretty

  # Programmatic:
  from app.services.microvm_doctor import run_checks
  result = run_checks()
  if not result["is_ok"]:
      print("Fatal failures detected")
"""

from __future__ import annotations

import argparse
import ctypes
import fcntl
import json
import os
import stat
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, TypedDict


# =============================================================================
# KVM ioctl Constants
# =============================================================================

# KVM_GET_API_VERSION ioctl number: _IO(KVMIO, 0x00) where KVMIO=0xAE
# This is: (0 << 30) | (0xAE << 8) | 0x00 = 0xAE00
KVM_GET_API_VERSION = 0xAE00

# Minimum KVM API version required (Linux KVM has been >= 12 since ~2009)
KVM_API_VERSION_MIN = 12


# =============================================================================
# Constants
# =============================================================================

MAX_DETAILS_LEN = 200  # Max length for details/hint fields
CMD_TIMEOUT_SECS = 3.0  # Timeout for binary version checks

# Default paths (can be overridden via environment)
DEFAULT_FIRECRACKER_BIN = "/usr/local/bin/firecracker"
DEFAULT_JAILER_BIN = "/usr/local/bin/jailer"
DEFAULT_STATE_DIR = "/var/lib/octolab/microvm"

# Environment variable names
ENV_FIRECRACKER_BIN = "OCTOLAB_MICROVM_FIRECRACKER_BIN"
ENV_JAILER_BIN = "OCTOLAB_MICROVM_JAILER_BIN"
ENV_KERNEL_PATH = "OCTOLAB_MICROVM_KERNEL_PATH"
ENV_ROOTFS_PATH = "OCTOLAB_MICROVM_ROOTFS_BASE_PATH"
ENV_STATE_DIR = "OCTOLAB_MICROVM_STATE_DIR"
ENV_DEV_ALLOW_NO_JAILER = "OCTOLAB_DEV_UNSAFE_ALLOW_NO_JAILER"

# Alternative env names (without prefix, for backwards compat)
ALT_ENV_KERNEL_PATH = "MICROVM_KERNEL_PATH"
ALT_ENV_ROOTFS_PATH = "MICROVM_ROOTFS_BASE_PATH"
ALT_ENV_STATE_DIR = "MICROVM_STATE_DIR"
ALT_ENV_DEV_ALLOW_NO_JAILER = "DEV_UNSAFE_ALLOW_NO_JAILER"

# Network daemon configuration
ENV_NETD_SOCK = "OCTOLAB_MICROVM_NETD_SOCK"
DEFAULT_NETD_SOCK = "/run/octolab/microvm-netd.sock"


# =============================================================================
# Type Definitions
# =============================================================================


class CheckResult(TypedDict):
    """Type for a single check result."""
    name: str
    status: str  # "OK", "WARN", "FAIL"
    severity: str  # "info", "warn", "fatal"
    message: str
    hint: str | None


class Summary(TypedDict):
    """Type for the summary counts."""
    ok: int
    warn: int
    fail: int
    fatal: int


class DoctorResult(TypedDict):
    """Type for the full doctor result."""
    checks: list[CheckResult]
    summary: Summary
    is_ok: bool
    generated_at: str


# =============================================================================
# Helper Functions
# =============================================================================


def _redact_path(path: str | Path | None, debug: bool = False) -> str:
    """Redact path to show only basename unless debug mode.

    SECURITY: Never expose full absolute paths by default.
    """
    if not path:
        return "(not set)"
    p = Path(path)
    if debug:
        return str(p)
    return f".../{p.name}" if p.name else "(empty)"


def _truncate(text: str, max_len: int = MAX_DETAILS_LEN) -> str:
    """Truncate text and strip newlines."""
    text = text.replace("\n", " ").replace("\r", "").strip()
    if len(text) > max_len:
        return text[:max_len - 3] + "..."
    return text


def _run_cmd_safe(
    args: list[str],
    timeout: float = CMD_TIMEOUT_SECS,
) -> tuple[int, str, str]:
    """Run a command safely with timeout and output limits.

    SECURITY:
    - shell=False always
    - Output truncated
    - Timeout enforced

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
        stdout = _truncate(result.stdout, 500)
        stderr = _truncate(result.stderr, 500)
        return result.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        return -1, "", "command timed out"
    except FileNotFoundError:
        return -1, "", "command not found"
    except Exception as e:
        return -1, "", f"error: {type(e).__name__}"


def _is_wsl() -> bool:
    """Detect if running under WSL."""
    # Check for WSL interop file
    if Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists():
        return True
    # Check for Microsoft in kernel version
    try:
        version = Path("/proc/version").read_text()
        if "Microsoft" in version or "microsoft" in version:
            return True
    except Exception:
        pass
    # Check for WSL env var
    if os.environ.get("WSL_INTEROP"):
        return True
    return False


def _get_env(
    env: Mapping[str, str],
    primary_key: str,
    alt_key: str | None = None,
    default: str | None = None,
) -> str | None:
    """Get environment variable with fallback to alternate key and default."""
    value = env.get(primary_key)
    if value is None and alt_key:
        value = env.get(alt_key)
    if value is None:
        value = default
    return value


def _make_check(
    name: str,
    passed: bool,
    severity: str,
    message: str,
    hint: str | None = None,
) -> CheckResult:
    """Create a check result dict."""
    status = "OK" if passed else ("WARN" if severity == "warn" else "FAIL")
    return {
        "name": name,
        "status": status,
        "severity": severity,
        "message": _truncate(message),
        "hint": _truncate(hint) if hint else None,
    }


# =============================================================================
# Individual Checks
# =============================================================================


def _check_kvm(env: Mapping[str, str], debug: bool = False) -> CheckResult:
    """Check /dev/kvm exists, is RW accessible, and KVM API actually works.

    SECURITY: This check performs a real ioctl to verify KVM is functional.
    Just having /dev/kvm with RW perms doesn't guarantee KVM works (e.g., WSL
    without nested virtualization enabled has /dev/kvm but ioctl fails).
    """
    kvm_path = Path("/dev/kvm")
    is_wsl = _is_wsl()

    if not kvm_path.exists():
        if is_wsl:
            hint = (
                "Enable nested virtualization in WSL: "
                "1) Edit %USERPROFILE%\\.wslconfig and add [wsl2] nestedVirtualization=true; "
                "2) Run 'wsl --shutdown' in PowerShell; "
                "3) Reopen terminal"
            )
        else:
            hint = "Enable KVM: modprobe kvm_intel or kvm_amd. Check BIOS virtualization settings."

        return _make_check(
            name="kvm",
            passed=False,
            severity="fatal",
            message="/dev/kvm not found",
            hint=hint,
        )

    # Check permissions and perform ioctl check
    fd = None
    try:
        fd = os.open(str(kvm_path), os.O_RDWR)

        # Perform KVM_GET_API_VERSION ioctl to verify KVM is actually usable
        # This is critical: /dev/kvm may exist but ioctl can still fail
        # (e.g., WSL without nested virtualization enabled)
        try:
            api_version = fcntl.ioctl(fd, KVM_GET_API_VERSION)

            if api_version < KVM_API_VERSION_MIN:
                return _make_check(
                    name="kvm",
                    passed=False,
                    severity="fatal",
                    message=f"KVM API version too old: {api_version} (need >= {KVM_API_VERSION_MIN})",
                    hint="Update your kernel or virtualization software",
                )

            return _make_check(
                name="kvm",
                passed=True,
                severity="info",
                message=f"/dev/kvm accessible, API version {api_version}",
            )

        except OSError as ioctl_err:
            # ioctl failed - KVM is not actually usable
            import errno
            err_name = errno.errorcode.get(ioctl_err.errno, str(ioctl_err.errno))

            if is_wsl:
                hint = (
                    "KVM ioctl failed. Ensure WSL nested virtualization is enabled: "
                    "1) Edit %USERPROFILE%\\.wslconfig with [wsl2] nestedVirtualization=true; "
                    "2) Run 'wsl --shutdown'; 3) Reopen terminal"
                )
            else:
                hint = (
                    f"KVM ioctl failed ({err_name}). Check that virtualization is enabled "
                    "in BIOS/UEFI and kvm_intel/kvm_amd module is loaded"
                )

            return _make_check(
                name="kvm",
                passed=False,
                severity="fatal",
                message=f"/dev/kvm open but ioctl failed: {err_name}",
                hint=hint,
            )

    except PermissionError:
        # Include uid/gid/groups in debug mode only
        debug_info = ""
        if debug:
            try:
                import grp
                uid = os.getuid()
                gid = os.getgid()
                groups = [grp.getgrgid(g).gr_name for g in os.getgroups()]
                debug_info = f" (uid={uid}, gid={gid}, groups={groups})"
            except Exception:
                pass

        if is_wsl:
            hint = (
                "Add user to kvm group: sudo usermod -aG kvm $USER && wsl --shutdown "
                "(then reopen terminal). Dev workaround: sudo chmod 666 /dev/kvm"
            )
        else:
            hint = "sudo usermod -aG kvm $USER && newgrp kvm (or logout/login)"

        return _make_check(
            name="kvm",
            passed=False,
            severity="fatal",
            message=f"/dev/kvm exists but not writable{debug_info}",
            hint=hint,
        )
    except Exception as e:
        return _make_check(
            name="kvm",
            passed=False,
            severity="fatal",
            message=f"/dev/kvm error: {type(e).__name__}",
            hint="Check /dev/kvm permissions and ownership",
        )
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass


def _check_firecracker_binary(env: Mapping[str, str], debug: bool = False) -> CheckResult:
    """Check firecracker binary exists and get version."""
    fc_path = _get_env(env, ENV_FIRECRACKER_BIN, default=DEFAULT_FIRECRACKER_BIN)
    if not fc_path:
        fc_path = DEFAULT_FIRECRACKER_BIN

    fc_pathobj = Path(fc_path)

    # Check if binary exists
    if not fc_pathobj.exists():
        return _make_check(
            name="firecracker",
            passed=False,
            severity="fatal",
            message=f"firecracker binary not found at {_redact_path(fc_path, debug)}",
            hint="Install Firecracker: https://github.com/firecracker-microvm/firecracker/releases",
        )

    # Check if executable
    if not os.access(fc_path, os.X_OK):
        return _make_check(
            name="firecracker",
            passed=False,
            severity="fatal",
            message=f"firecracker binary not executable: {_redact_path(fc_path, debug)}",
            hint="Run: chmod +x " + _redact_path(fc_path, debug),
        )

    # Get version
    rc, stdout, stderr = _run_cmd_safe([fc_path, "--version"])
    if rc != 0:
        return _make_check(
            name="firecracker",
            passed=False,
            severity="fatal",
            message=f"firecracker --version failed (exit {rc})",
            hint=f"Check binary integrity. Error: {_truncate(stderr, 100)}",
        )

    version = stdout.split()[0] if stdout else "unknown"
    return _make_check(
        name="firecracker",
        passed=True,
        severity="info",
        message=f"firecracker: {_truncate(version, 80)}",
    )


def _check_jailer_binary(env: Mapping[str, str], debug: bool = False) -> CheckResult:
    """Check jailer binary exists.

    In WSL or with DEV_UNSAFE_ALLOW_NO_JAILER=true, missing jailer is WARN.
    Otherwise, missing jailer is WARN with production note.
    """
    jailer_path = _get_env(env, ENV_JAILER_BIN, default=DEFAULT_JAILER_BIN)
    if not jailer_path:
        jailer_path = DEFAULT_JAILER_BIN

    is_wsl = _is_wsl()
    allow_no_jailer = _get_env(
        env, ENV_DEV_ALLOW_NO_JAILER, ALT_ENV_DEV_ALLOW_NO_JAILER, ""
    )
    allow_no_jailer_bool = allow_no_jailer and allow_no_jailer.lower() in ("true", "1", "yes")

    jailer_pathobj = Path(jailer_path)

    # Check if binary exists
    if not jailer_pathobj.exists() or not os.access(jailer_path, os.X_OK):
        if is_wsl:
            return _make_check(
                name="jailer",
                passed=False,
                severity="warn",
                message="jailer not found (WSL detected)",
                hint="Jailer not required in WSL dev environment. Production requires jailer.",
            )
        if allow_no_jailer_bool:
            return _make_check(
                name="jailer",
                passed=False,
                severity="warn",
                message="jailer not found (DEV_UNSAFE_ALLOW_NO_JAILER=true)",
                hint="Running without jailer is UNSAFE. Only for development.",
            )
        return _make_check(
            name="jailer",
            passed=False,
            severity="warn",
            message="jailer binary not found",
            hint="Production requires jailer; WSL dev can omit.",
        )

    # Get version
    rc, stdout, stderr = _run_cmd_safe([jailer_path, "--version"])
    if rc != 0:
        # jailer exists but version check failed - still usable
        return _make_check(
            name="jailer",
            passed=True,
            severity="warn",
            message="jailer found but --version failed",
            hint=f"Check jailer permissions. Error: {_truncate(stderr, 100)}",
        )

    version = stdout.split()[0] if stdout else "unknown"
    return _make_check(
        name="jailer",
        passed=True,
        severity="info",
        message=f"jailer: {_truncate(version, 80)}",
    )


def _check_kernel_path(env: Mapping[str, str], debug: bool = False) -> CheckResult:
    """Check kernel path is configured, readable, and is a valid ELF binary.

    Verifies:
    - Path is set
    - File exists and is readable
    - First 4 bytes are ELF magic (b"\\x7fELF")
    - e_ident[4] is ELFCLASS64 (2) for 64-bit architecture
    """
    kernel_path = _get_env(env, ENV_KERNEL_PATH, ALT_ENV_KERNEL_PATH)

    if not kernel_path:
        return _make_check(
            name="kernel",
            passed=False,
            severity="fatal",
            message="MICROVM_KERNEL_PATH not set",
            hint="Set MICROVM_KERNEL_PATH to vmlinux kernel image path",
        )

    p = Path(kernel_path)
    if not p.exists():
        return _make_check(
            name="kernel",
            passed=False,
            severity="fatal",
            message=f"kernel not found: {_redact_path(kernel_path, debug)}",
            hint="Download kernel from Firecracker repo or build custom kernel",
        )

    if not p.is_file():
        return _make_check(
            name="kernel",
            passed=False,
            severity="fatal",
            message=f"kernel path is not a file: {_redact_path(kernel_path, debug)}",
            hint="Ensure path points to vmlinux file, not a directory",
        )

    # Check readable and verify ELF format
    try:
        with open(p, "rb") as f:
            # Read ELF header: e_ident[0:16]
            header = f.read(16)

        if len(header) < 16:
            return _make_check(
                name="kernel",
                passed=False,
                severity="fatal",
                message=f"kernel file too small: {_redact_path(kernel_path, debug)}",
                hint="File may be corrupt or truncated",
            )

        # Check ELF magic: b"\x7fELF"
        elf_magic = header[0:4]
        if elf_magic != b"\x7fELF":
            return _make_check(
                name="kernel",
                passed=False,
                severity="fatal",
                message=f"kernel not ELF format: {_redact_path(kernel_path, debug)}",
                hint="File must be an ELF binary (vmlinux), not compressed (bzImage)",
            )

        # Check ELFCLASS64 (e_ident[4] = 2 for 64-bit)
        elf_class = header[4]
        if elf_class != 2:
            elf_class_name = {1: "32-bit", 2: "64-bit"}.get(elf_class, f"unknown({elf_class})")
            return _make_check(
                name="kernel",
                passed=False,
                severity="fatal",
                message=f"kernel not 64-bit ELF: {elf_class_name}",
                hint="Firecracker requires a 64-bit (ELFCLASS64) vmlinux kernel",
            )

        return _make_check(
            name="kernel",
            passed=True,
            severity="info",
            message=f"kernel valid ELF64: {_redact_path(kernel_path, debug)}",
        )

    except PermissionError:
        return _make_check(
            name="kernel",
            passed=False,
            severity="fatal",
            message=f"kernel not readable: {_redact_path(kernel_path, debug)}",
            hint="Check file permissions on kernel image",
        )
    except Exception as e:
        return _make_check(
            name="kernel",
            passed=False,
            severity="fatal",
            message=f"kernel read error: {type(e).__name__}",
            hint="Check file system and permissions",
        )


def _check_rootfs_path(env: Mapping[str, str], debug: bool = False) -> CheckResult:
    """Check rootfs base path is configured and readable."""
    rootfs_path = _get_env(env, ENV_ROOTFS_PATH, ALT_ENV_ROOTFS_PATH)

    if not rootfs_path:
        return _make_check(
            name="rootfs",
            passed=False,
            severity="fatal",
            message="MICROVM_ROOTFS_BASE_PATH not set",
            hint="Set MICROVM_ROOTFS_BASE_PATH to ext4 rootfs image path",
        )

    p = Path(rootfs_path)
    if not p.exists():
        return _make_check(
            name="rootfs",
            passed=False,
            severity="fatal",
            message=f"rootfs not found: {_redact_path(rootfs_path, debug)}",
            hint="Create rootfs image with guest agent installed",
        )

    if not p.is_file():
        return _make_check(
            name="rootfs",
            passed=False,
            severity="fatal",
            message=f"rootfs path is not a file: {_redact_path(rootfs_path, debug)}",
            hint="Ensure path points to ext4 image file, not a directory",
        )

    # Check readable
    try:
        with open(p, "rb") as f:
            f.read(1)
        return _make_check(
            name="rootfs",
            passed=True,
            severity="info",
            message=f"rootfs readable: {_redact_path(rootfs_path, debug)}",
        )
    except PermissionError:
        return _make_check(
            name="rootfs",
            passed=False,
            severity="fatal",
            message=f"rootfs not readable: {_redact_path(rootfs_path, debug)}",
            hint="Check file permissions on rootfs image",
        )


def _check_state_dir(env: Mapping[str, str], debug: bool = False) -> CheckResult:
    """Check state directory exists and is writable.

    IMPORTANT: This check does NOT mutate the filesystem (no auto-create).
    """
    state_dir_path = _get_env(env, ENV_STATE_DIR, ALT_ENV_STATE_DIR, DEFAULT_STATE_DIR)
    state_dir = Path(state_dir_path) if state_dir_path else Path(DEFAULT_STATE_DIR)

    # Check if exists
    if not state_dir.exists():
        return _make_check(
            name="state_dir",
            passed=False,
            severity="fatal",
            message=f"state_dir does not exist: {_redact_path(state_dir, debug)}",
            hint=f"Create directory: sudo mkdir -p {state_dir} && sudo chown $USER {state_dir}",
        )

    if not state_dir.is_dir():
        return _make_check(
            name="state_dir",
            passed=False,
            severity="fatal",
            message=f"state_dir is not a directory: {_redact_path(state_dir, debug)}",
            hint="Ensure path points to a directory, not a file",
        )

    # Check writable (try to create a temp file)
    try:
        test_file = state_dir / ".doctor_write_test"
        test_file.touch()
        test_file.unlink()
    except PermissionError:
        return _make_check(
            name="state_dir",
            passed=False,
            severity="fatal",
            message=f"state_dir not writable: {_redact_path(state_dir, debug)}",
            hint=f"Fix ownership: sudo chown $USER {state_dir}",
        )
    except Exception as e:
        return _make_check(
            name="state_dir",
            passed=False,
            severity="fatal",
            message=f"state_dir write test failed: {type(e).__name__}",
            hint="Check directory permissions and ownership",
        )

    # Check world-writable (security issue) - warn only
    try:
        mode = state_dir.stat().st_mode
        if mode & stat.S_IWOTH:
            return _make_check(
                name="state_dir",
                passed=False,
                severity="warn",
                message=f"state_dir is world-writable (insecure)",
                hint=f"Fix permissions: chmod o-w {state_dir}",
            )
    except Exception:
        pass

    return _make_check(
        name="state_dir",
        passed=True,
        severity="info",
        message=f"state_dir writable: {_redact_path(state_dir, debug)}",
    )


def _check_vsock(env: Mapping[str, str], debug: bool = False) -> CheckResult:
    """Check vsock capability (optional, WARN only)."""
    # Check for /dev/vsock
    if Path("/dev/vsock").exists():
        return _make_check(
            name="vsock",
            passed=True,
            severity="info",
            message="/dev/vsock available",
        )

    # Check for vhost_vsock module
    rc, stdout, _ = _run_cmd_safe(["lsmod"])
    if rc == 0 and "vhost_vsock" in stdout:
        return _make_check(
            name="vsock",
            passed=True,
            severity="info",
            message="vhost_vsock module loaded",
        )

    return _make_check(
        name="vsock",
        passed=False,
        severity="warn",
        message="vsock not available",
        hint="Load module: sudo modprobe vhost_vsock. Required for guest agent communication.",
    )


def _get_netd_log_hint() -> str:
    """Return context-aware hint for finding netd logs.

    Checks whether netd is likely running as systemd service or manual process.
    """
    # Check if systemd unit exists
    netd_unit = Path("/etc/systemd/system/microvm-netd.service")
    netd_unit_user = Path.home() / ".config/systemd/user/microvm-netd.service"

    if netd_unit.exists() or netd_unit_user.exists():
        return "Check microvm-netd logs: journalctl -u microvm-netd"

    # Default: assume manual run (common in WSL dev)
    return (
        "Check the terminal where you ran: sudo python3 infra/microvm/netd/microvm_netd.py\n"
        "If using systemd: journalctl -u microvm-netd"
    )


def _check_socket_permissions_standalone(socket_path: str) -> tuple[bool, str | None]:
    """Check socket file permissions are correct (standalone version).

    Expected: owner root (uid 0), group octolab, mode 0660

    Returns:
        Tuple of (ok, error_message). If ok is True, error_message is None.
    """
    import grp

    try:
        st = Path(socket_path).stat()
    except OSError as e:
        return False, f"Cannot stat socket: {type(e).__name__}"

    # Check owner is root
    if st.st_uid != 0:
        return False, f"Socket owner is UID {st.st_uid}, expected 0 (root)"

    # Check group is octolab (if it exists)
    try:
        grp_info = grp.getgrnam("octolab")
        if st.st_gid != grp_info.gr_gid:
            actual_group = grp.getgrgid(st.st_gid).gr_name if st.st_gid else str(st.st_gid)
            return False, f"Socket group is {actual_group}, expected octolab"
    except KeyError:
        # octolab group doesn't exist - warn but don't fail
        pass

    # Check mode is 0660 (no world access)
    mode = stat.S_IMODE(st.st_mode)
    if mode != 0o660:
        return False, f"Socket mode is {oct(mode)}, expected 0660 (no world access)"

    return True, None


def _check_netd(env: Mapping[str, str], debug: bool = False) -> CheckResult:
    """Check microvm-netd socket exists and responds.

    This check verifies the privileged network helper is running and
    can be reached from the backend.

    SECURITY:
    - netd runs as root to create bridges/TAPs
    - Backend must have access to socket (via group membership)
    - Socket must have correct permissions (root:octolab, 0660)
    - This check only pings - does not create/destroy anything
    """
    socket_path = _get_env(env, ENV_NETD_SOCK, default=DEFAULT_NETD_SOCK)

    # Check if socket file exists
    if not Path(socket_path).exists():
        return _make_check(
            name="netd",
            passed=False,
            severity="fatal",
            message=f"netd socket not found: {_redact_path(socket_path, debug)}",
            hint=(
                "Start microvm-netd: sudo octolabctl netd start "
                "or: sudo systemctl start microvm-netd"
            ),
        )

    # Check if it's a socket
    try:
        mode = Path(socket_path).stat().st_mode
        if not stat.S_ISSOCK(mode):
            return _make_check(
                name="netd",
                passed=False,
                severity="fatal",
                message="netd path exists but is not a socket",
                hint="Remove stale file and restart microvm-netd",
            )
    except Exception as e:
        return _make_check(
            name="netd",
            passed=False,
            severity="fatal",
            message=f"Cannot stat netd socket: {type(e).__name__}",
            hint="Check socket path permissions",
        )

    # Check socket permissions (SECURITY: must be correct before we trust it)
    perm_ok, perm_err = _check_socket_permissions_standalone(socket_path)
    if not perm_ok:
        return _make_check(
            name="netd",
            passed=False,
            severity="fatal",
            message=f"Socket permissions wrong: {perm_err}",
            hint=(
                "Restart netd to fix permissions: sudo octolabctl netd restart\n"
                "Expected: root:octolab with mode 0660"
            ),
        )

    # Try to ping netd
    try:
        from app.services.microvm_net_client import ping_netd_sync

        ok, err = ping_netd_sync(timeout=2.0, socket_path=socket_path)

        if ok:
            return _make_check(
                name="netd",
                passed=True,
                severity="info",
                message="netd running and responding (perms OK)",
            )
        else:
            # Build hint based on how netd might be running
            hint = _get_netd_log_hint()
            return _make_check(
                name="netd",
                passed=False,
                severity="fatal",
                message=f"netd ping failed: {err}",
                hint=hint,
            )

    except ImportError:
        # microvm_net_client not available, fall back to basic socket check
        import socket as sock

        try:
            s = sock.socket(sock.AF_UNIX, sock.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect(socket_path)
            s.sendall(b'{"op": "ping"}')
            response = s.recv(1024)
            s.close()

            if b'"ok": true' in response or b'"ok":true' in response:
                return _make_check(
                    name="netd",
                    passed=True,
                    severity="info",
                    message="netd running (basic check, perms OK)",
                )
            else:
                return _make_check(
                    name="netd",
                    passed=False,
                    severity="fatal",
                    message="netd returned error",
                    hint=_get_netd_log_hint(),
                )

        except sock.timeout:
            return _make_check(
                name="netd",
                passed=False,
                severity="fatal",
                message="netd connection timed out",
                hint="Ensure microvm-netd is running and not blocked",
            )
        except PermissionError:
            return _make_check(
                name="netd",
                passed=False,
                severity="fatal",
                message="Permission denied connecting to netd socket",
                hint=(
                    "Add user to octolab group: sudo usermod -aG octolab $USER\n"
                    "Then restart your session (WSL: wsl --terminate <distro>)"
                ),
            )
        except Exception as e:
            return _make_check(
                name="netd",
                passed=False,
                severity="fatal",
                message=f"netd connection failed: {type(e).__name__}",
                hint="Ensure microvm-netd is running as root",
            )


# =============================================================================
# Main Doctor Function
# =============================================================================


def run_checks(
    env: Mapping[str, str] | None = None,
    debug: bool = False,
) -> DoctorResult:
    """Run all microVM doctor checks.

    Args:
        env: Environment mapping (defaults to os.environ)
        debug: If True, show full paths in output

    Returns:
        DoctorResult with all checks and summary

    SECURITY:
    - All output is redacted (no full paths unless debug=True)
    - Details are truncated
    - Never logs secrets
    - Does NOT import app.config or Settings
    """
    if env is None:
        env = os.environ

    checks: list[CheckResult] = [
        _check_kvm(env, debug),
        _check_firecracker_binary(env, debug),
        _check_jailer_binary(env, debug),
        _check_kernel_path(env, debug),
        _check_rootfs_path(env, debug),
        _check_state_dir(env, debug),
        _check_vsock(env, debug),
        _check_netd(env, debug),
    ]

    # Compute summary counts
    ok_count = sum(1 for c in checks if c["status"] == "OK")
    warn_count = sum(1 for c in checks if c["status"] == "WARN")
    fail_count = sum(1 for c in checks if c["status"] == "FAIL")
    fatal_count = sum(1 for c in checks if c["status"] == "FAIL" and c["severity"] == "fatal")

    # is_ok means no fatal failures
    is_ok = fatal_count == 0

    return {
        "checks": checks,
        "summary": {
            "ok": ok_count,
            "warn": warn_count,
            "fail": fail_count,
            "fatal": fatal_count,
        },
        "is_ok": is_ok,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_fatal_summary(result: DoctorResult) -> str:
    """Get a redacted summary of fatal failures for error messages.

    Returns:
        Semicolon-separated list of fatal check names and hints (truncated).
    """
    fatal_checks = [
        c for c in result["checks"]
        if c["status"] == "FAIL" and c["severity"] == "fatal"
    ]
    if not fatal_checks:
        return "no fatal issues"

    parts = []
    for c in fatal_checks:
        hint = c.get("hint") or c.get("message", "")
        parts.append(f"{c['name']}: {hint}")

    return "; ".join(parts)[:500]


# =============================================================================
# CLI Entry Point
# =============================================================================


def _print_pretty(result: DoctorResult) -> None:
    """Print human-readable doctor report."""
    print()
    print("=" * 60)
    print("MicroVM Doctor Report")
    print("=" * 60)
    print()

    for check in result["checks"]:
        status = check["status"]
        if status == "OK":
            marker = "\033[32m[OK]\033[0m   "
        elif status == "WARN":
            marker = "\033[33m[WARN]\033[0m "
        else:
            marker = "\033[31m[FAIL]\033[0m "

        print(f"  {marker} {check['name']}: {check['message'][:60]}")
        if check["status"] != "OK" and check.get("hint"):
            print(f"           Hint: {check['hint'][:60]}")

    summary = result["summary"]
    print()
    print(f"Summary: OK={summary['ok']} WARN={summary['warn']} FAIL={summary['fail']} (fatal={summary['fatal']})")
    print("=" * 60)

    if result["is_ok"]:
        print()
        print("\033[32mAll critical checks passed!\033[0m")
        if summary["warn"] > 0:
            print(f"({summary['warn']} warning(s) - review above)")
    else:
        print()
        print(f"\033[31mFATAL: {summary['fatal']} critical check(s) failed.\033[0m")
        print("Fix the issues above before starting with OCTOLAB_RUNTIME=firecracker.")


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="MicroVM Doctor - Check Firecracker prerequisites"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Output as human-readable report (default if no --json)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show full paths (not redacted)",
    )

    args = parser.parse_args()

    result = run_checks(debug=args.debug)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_pretty(result)

    # Exit code: 0 if no fatal, 2 if fatal failures
    return 0 if result["is_ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
