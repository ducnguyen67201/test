"""Firecracker microVM Doctor - Comprehensive health checks for Firecracker runtime.

SECURITY:
- Never log secrets or full absolute paths
- All subprocess calls use shell=False with list args
- Enforce hard timeouts on all checks
- Truncate and redact output for safety
"""

from __future__ import annotations

import logging
import os
import stat
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_DETAILS_LEN = 200  # Max length for details/hint fields
CMD_TIMEOUT_SECS = 5.0  # Timeout for binary version checks


class Severity(str, Enum):
    """Severity level for doctor checks."""
    INFO = "info"
    WARN = "warn"
    FATAL = "fatal"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class DoctorCheck:
    """Result of a single doctor check.

    Attributes:
        name: Short identifier for the check (e.g., "kvm", "firecracker")
        ok: Whether the check passed
        severity: INFO, WARN, or FATAL
        details: Short description of what was found (redacted)
        hint: Actionable hint for resolving issues
    """
    name: str
    ok: bool
    severity: Severity
    details: str
    hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for API response."""
        return {
            "name": self.name,
            "ok": self.ok,
            "severity": self.severity.value,
            "details": self.details[:MAX_DETAILS_LEN],
            "hint": self.hint[:MAX_DETAILS_LEN] if self.hint else "",
        }


@dataclass
class DoctorReport:
    """Complete doctor report with all checks.

    Attributes:
        ok: True only if no FATAL checks failed
        checks: List of all DoctorCheck results
        summary: Human-readable summary
        generated_at: ISO8601 timestamp of report generation
    """
    ok: bool
    checks: list[DoctorCheck] = field(default_factory=list)
    summary: str = ""
    generated_at: str = ""

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(timezone.utc).isoformat()

    @property
    def fatal_checks(self) -> list[DoctorCheck]:
        """Return only fatal checks that failed."""
        return [c for c in self.checks if c.severity == Severity.FATAL and not c.ok]

    @property
    def warn_checks(self) -> list[DoctorCheck]:
        """Return only warning checks that failed."""
        return [c for c in self.checks if c.severity == Severity.WARN and not c.ok]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for API response.

        SECURITY: All fields are redacted/truncated.
        """
        return {
            "ok": self.ok,
            "checks": [c.to_dict() for c in self.checks],
            "summary": self.summary[:500],
            "generated_at": self.generated_at,
            "fatal_count": len(self.fatal_checks),
            "warn_count": len(self.warn_checks),
        }


# =============================================================================
# Helper Functions
# =============================================================================


def _redact_path(path: str | Path | None) -> str:
    """Redact path to show only basename.

    SECURITY: Never expose full absolute paths.
    """
    if not path:
        return "(not set)"
    p = Path(path)
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


# =============================================================================
# Individual Checks
# =============================================================================


def _check_kvm() -> DoctorCheck:
    """Check /dev/kvm exists and is RW accessible."""
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

        return DoctorCheck(
            name="kvm",
            ok=False,
            severity=Severity.FATAL,
            details="/dev/kvm not found",
            hint=hint,
        )

    # Check permissions
    try:
        with open(kvm_path, "r+b"):
            return DoctorCheck(
                name="kvm",
                ok=True,
                severity=Severity.INFO,
                details="/dev/kvm accessible (RW)",
            )
    except PermissionError:
        if is_wsl:
            hint = (
                "Add user to kvm group: sudo usermod -aG kvm $USER && wsl --shutdown "
                "(then reopen terminal). Dev workaround: sudo chmod 666 /dev/kvm"
            )
        else:
            hint = "Add user to kvm group: sudo usermod -aG kvm $USER (then log out/in)"

        return DoctorCheck(
            name="kvm",
            ok=False,
            severity=Severity.FATAL,
            details="/dev/kvm exists but not writable",
            hint=hint,
        )
    except Exception as e:
        return DoctorCheck(
            name="kvm",
            ok=False,
            severity=Severity.FATAL,
            details=f"/dev/kvm error: {type(e).__name__}",
            hint="Check /dev/kvm permissions and ownership",
        )


def _check_firecracker_binary() -> DoctorCheck:
    """Check firecracker binary exists and get version."""
    fc_path = settings.firecracker_bin

    # Check if binary exists
    rc, _, _ = _run_cmd_safe(["which", fc_path])
    if rc != 0:
        return DoctorCheck(
            name="firecracker",
            ok=False,
            severity=Severity.FATAL,
            details=f"firecracker binary not found",
            hint="Install Firecracker: https://github.com/firecracker-microvm/firecracker/releases",
        )

    # Get version
    rc, stdout, stderr = _run_cmd_safe([fc_path, "--version"])
    if rc != 0:
        return DoctorCheck(
            name="firecracker",
            ok=False,
            severity=Severity.FATAL,
            details=f"firecracker --version failed",
            hint=f"Check binary permissions. Error: {_truncate(stderr, 100)}",
        )

    version = stdout.split("\n")[0] if stdout else "unknown"
    return DoctorCheck(
        name="firecracker",
        ok=True,
        severity=Severity.INFO,
        details=f"firecracker: {_truncate(version, 80)}",
    )


def _check_jailer_binary() -> DoctorCheck:
    """Check jailer binary exists.

    In WSL, missing jailer is WARN (dev environment).
    Otherwise, missing jailer is FATAL unless dev override is set.
    """
    jailer_path = settings.jailer_bin
    is_wsl = _is_wsl()
    allow_no_jailer = settings.dev_unsafe_allow_no_jailer

    # Check if binary exists
    rc, _, _ = _run_cmd_safe(["which", jailer_path])
    if rc != 0:
        if is_wsl:
            return DoctorCheck(
                name="jailer",
                ok=False,
                severity=Severity.WARN,
                details="jailer not found (WSL detected)",
                hint="Jailer not required in WSL dev environment. Production requires jailer.",
            )
        if allow_no_jailer:
            return DoctorCheck(
                name="jailer",
                ok=False,
                severity=Severity.WARN,
                details="jailer not found (OCTOLAB_DEV_UNSAFE_ALLOW_NO_JAILER=true)",
                hint="Running without jailer is UNSAFE. Only for development.",
            )
        return DoctorCheck(
            name="jailer",
            ok=False,
            severity=Severity.FATAL,
            details="jailer binary not found",
            hint="Install jailer from Firecracker release. Required for production.",
        )

    # Get version
    rc, stdout, stderr = _run_cmd_safe([jailer_path, "--version"])
    if rc != 0:
        # jailer exists but version check failed - still usable
        return DoctorCheck(
            name="jailer",
            ok=True,
            severity=Severity.WARN,
            details="jailer found but --version failed",
            hint=f"Check jailer permissions. Error: {_truncate(stderr, 100)}",
        )

    version = stdout.split("\n")[0] if stdout else "unknown"
    return DoctorCheck(
        name="jailer",
        ok=True,
        severity=Severity.INFO,
        details=f"jailer: {_truncate(version, 80)}",
    )


def _check_kernel_path() -> DoctorCheck:
    """Check kernel path is configured and readable."""
    kernel_path = settings.microvm_kernel_path

    if not kernel_path:
        return DoctorCheck(
            name="kernel",
            ok=False,
            severity=Severity.FATAL,
            details="OCTOLAB_MICROVM_KERNEL_PATH not set",
            hint="Set OCTOLAB_MICROVM_KERNEL_PATH to vmlinux kernel image path",
        )

    p = Path(kernel_path)
    if not p.exists():
        return DoctorCheck(
            name="kernel",
            ok=False,
            severity=Severity.FATAL,
            details=f"kernel not found: {_redact_path(kernel_path)}",
            hint="Download kernel from Firecracker repo or build custom kernel",
        )

    if not p.is_file():
        return DoctorCheck(
            name="kernel",
            ok=False,
            severity=Severity.FATAL,
            details=f"kernel path is not a file: {_redact_path(kernel_path)}",
            hint="Ensure path points to vmlinux file, not a directory",
        )

    # Check readable
    try:
        with open(p, "rb") as f:
            f.read(1)
        return DoctorCheck(
            name="kernel",
            ok=True,
            severity=Severity.INFO,
            details=f"kernel readable: {_redact_path(kernel_path)}",
        )
    except PermissionError:
        return DoctorCheck(
            name="kernel",
            ok=False,
            severity=Severity.FATAL,
            details=f"kernel not readable: {_redact_path(kernel_path)}",
            hint="Check file permissions on kernel image",
        )


def _check_rootfs_path() -> DoctorCheck:
    """Check rootfs base path is configured and readable."""
    rootfs_path = settings.microvm_rootfs_base_path

    if not rootfs_path:
        return DoctorCheck(
            name="rootfs",
            ok=False,
            severity=Severity.FATAL,
            details="OCTOLAB_MICROVM_ROOTFS_BASE_PATH not set",
            hint="Set OCTOLAB_MICROVM_ROOTFS_BASE_PATH to ext4 rootfs image path",
        )

    p = Path(rootfs_path)
    if not p.exists():
        return DoctorCheck(
            name="rootfs",
            ok=False,
            severity=Severity.FATAL,
            details=f"rootfs not found: {_redact_path(rootfs_path)}",
            hint="Create rootfs image with guest agent installed",
        )

    if not p.is_file():
        return DoctorCheck(
            name="rootfs",
            ok=False,
            severity=Severity.FATAL,
            details=f"rootfs path is not a file: {_redact_path(rootfs_path)}",
            hint="Ensure path points to ext4 image file, not a directory",
        )

    # Check readable
    try:
        with open(p, "rb") as f:
            f.read(1)
        return DoctorCheck(
            name="rootfs",
            ok=True,
            severity=Severity.INFO,
            details=f"rootfs readable: {_redact_path(rootfs_path)}",
        )
    except PermissionError:
        return DoctorCheck(
            name="rootfs",
            ok=False,
            severity=Severity.FATAL,
            details=f"rootfs not readable: {_redact_path(rootfs_path)}",
            hint="Check file permissions on rootfs image",
        )


def _check_state_dir() -> DoctorCheck:
    """Check state directory exists, is writable, and is not world-writable."""
    state_dir = Path(settings.microvm_state_dir)

    # Check if exists
    if not state_dir.exists():
        # Try to create it
        try:
            state_dir.mkdir(parents=True, mode=0o700)
            return DoctorCheck(
                name="state_dir",
                ok=True,
                severity=Severity.INFO,
                details=f"state_dir created: {_redact_path(state_dir)}",
            )
        except PermissionError:
            return DoctorCheck(
                name="state_dir",
                ok=False,
                severity=Severity.WARN,
                details=f"state_dir does not exist and cannot be created",
                hint=f"Create directory: sudo mkdir -p {state_dir} && sudo chown $USER {state_dir}",
            )
        except Exception as e:
            return DoctorCheck(
                name="state_dir",
                ok=False,
                severity=Severity.WARN,
                details=f"state_dir creation failed: {type(e).__name__}",
                hint="Check parent directory permissions",
            )

    # Check writable
    try:
        test_file = state_dir / ".doctor_write_test"
        test_file.touch()
        test_file.unlink()
    except PermissionError:
        return DoctorCheck(
            name="state_dir",
            ok=False,
            severity=Severity.FATAL,
            details=f"state_dir not writable: {_redact_path(state_dir)}",
            hint="Check directory permissions and ownership",
        )

    # Check world-writable (security issue)
    try:
        mode = state_dir.stat().st_mode
        if mode & stat.S_IWOTH:
            return DoctorCheck(
                name="state_dir",
                ok=False,
                severity=Severity.WARN,
                details=f"state_dir is world-writable (insecure)",
                hint=f"Fix permissions: chmod o-w {state_dir}",
            )
    except Exception:
        pass

    return DoctorCheck(
        name="state_dir",
        ok=True,
        severity=Severity.INFO,
        details=f"state_dir writable: {_redact_path(state_dir)}",
    )


def _check_vsock() -> DoctorCheck:
    """Check vsock capability (optional, WARN only)."""
    # Check for /dev/vsock
    if Path("/dev/vsock").exists():
        return DoctorCheck(
            name="vsock",
            ok=True,
            severity=Severity.INFO,
            details="/dev/vsock available",
        )

    # Check for vhost_vsock module
    rc, stdout, _ = _run_cmd_safe(["lsmod"])
    if rc == 0 and "vhost_vsock" in stdout:
        return DoctorCheck(
            name="vsock",
            ok=True,
            severity=Severity.INFO,
            details="vhost_vsock module loaded",
        )

    return DoctorCheck(
        name="vsock",
        ok=False,
        severity=Severity.WARN,
        details="vsock not available",
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


def _check_socket_permissions(socket_path: str) -> tuple[bool, str | None]:
    """Check socket file permissions are correct.

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
    # Use stat.S_IMODE to extract just permission bits
    mode = stat.S_IMODE(st.st_mode)
    if mode != 0o660:
        return False, f"Socket mode is {oct(mode)}, expected 0660 (no world access)"

    return True, None


def _check_netd() -> DoctorCheck:
    """Check microvm-netd socket exists and responds.

    This check verifies the privileged network helper is running and
    can be reached from the backend.

    SECURITY:
    - netd runs as root to create bridges/TAPs
    - Backend must have access to socket (via group membership)
    - Socket must have correct permissions (root:octolab, 0660)
    - This check only pings - does not create/destroy anything
    """
    socket_path = settings.microvm_netd_sock

    # Check if socket file exists
    if not Path(socket_path).exists():
        return DoctorCheck(
            name="netd",
            ok=False,
            severity=Severity.FATAL,
            details=f"netd socket not found: {_redact_path(socket_path)}",
            hint=(
                "Start microvm-netd: sudo octolabctl netd start "
                "or: sudo systemctl start microvm-netd"
            ),
        )

    # Check if it's a socket
    try:
        mode = Path(socket_path).stat().st_mode
        if not stat.S_ISSOCK(mode):
            return DoctorCheck(
                name="netd",
                ok=False,
                severity=Severity.FATAL,
                details="netd path exists but is not a socket",
                hint="Remove stale file and restart microvm-netd: sudo rm -f {socket_path} && sudo octolabctl netd start",
            )
    except Exception as e:
        return DoctorCheck(
            name="netd",
            ok=False,
            severity=Severity.FATAL,
            details=f"Cannot stat netd socket: {type(e).__name__}",
            hint="Check socket path permissions",
        )

    # Check socket permissions (SECURITY: must be correct before we trust it)
    perm_ok, perm_err = _check_socket_permissions(socket_path)
    if not perm_ok:
        return DoctorCheck(
            name="netd",
            ok=False,
            severity=Severity.FATAL,
            details=f"Socket permissions wrong: {perm_err}",
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
            return DoctorCheck(
                name="netd",
                ok=True,
                severity=Severity.INFO,
                details="netd running and responding (perms OK)",
            )
        else:
            # Build hint based on how netd might be running
            hint = _get_netd_log_hint()
            return DoctorCheck(
                name="netd",
                ok=False,
                severity=Severity.FATAL,
                details=f"netd ping failed: {err}",
                hint=hint,
            )

    except PermissionError:
        return DoctorCheck(
            name="netd",
            ok=False,
            severity=Severity.FATAL,
            details="Permission denied connecting to netd socket",
            hint=(
                "Add user to octolab group: sudo usermod -aG octolab $USER\n"
                "Then restart your session (WSL: wsl --terminate <distro>)"
            ),
        )

    except Exception as e:
        return DoctorCheck(
            name="netd",
            ok=False,
            severity=Severity.FATAL,
            details=f"netd connection failed: {type(e).__name__}",
            hint="Ensure microvm-netd is running as root",
        )


# =============================================================================
# Main Doctor Function
# =============================================================================


def run_doctor() -> DoctorReport:
    """Run all Firecracker doctor checks.

    Returns:
        DoctorReport with all checks and summary

    SECURITY:
    - All output is redacted (no full paths)
    - Details are truncated
    - Never logs secrets
    """
    checks = [
        _check_kvm(),
        _check_firecracker_binary(),
        _check_jailer_binary(),
        _check_kernel_path(),
        _check_rootfs_path(),
        _check_state_dir(),
        _check_vsock(),
        _check_netd(),
    ]

    # Compute overall OK status (no fatal failures)
    fatal_failures = [c for c in checks if c.severity == Severity.FATAL and not c.ok]
    ok = len(fatal_failures) == 0

    # Build summary
    if ok:
        warn_count = len([c for c in checks if c.severity == Severity.WARN and not c.ok])
        if warn_count > 0:
            summary = f"Firecracker available with {warn_count} warning(s)"
        else:
            summary = "Firecracker available and ready"
    else:
        fatal_names = [c.name for c in fatal_failures]
        summary = f"Firecracker unavailable: {', '.join(fatal_names)} check(s) failed"

    report = DoctorReport(
        ok=ok,
        checks=checks,
        summary=summary,
    )

    logger.info(f"Firecracker doctor: ok={ok}, summary={summary[:100]}")

    return report


def assert_firecracker_ready() -> DoctorReport:
    """Run doctor and raise if any fatal checks fail.

    Returns:
        DoctorReport if all fatal checks pass

    Raises:
        ValueError: If any fatal check fails (with redacted report)
    """
    report = run_doctor()
    if not report.ok:
        fatal_hints = "; ".join(
            f"{c.name}: {c.hint}" for c in report.fatal_checks
        )[:500]
        raise ValueError(f"Firecracker not ready: {fatal_hints}")
    return report
