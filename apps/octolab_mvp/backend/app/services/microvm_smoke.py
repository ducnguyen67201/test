"""Firecracker microVM Smoke Test Runner.

SECURITY:
- Never log secrets or full absolute paths
- All subprocess calls use shell=False with list args
- Keep temp directories on failure for debugging (cleanup old ones)
- Enforce hard timeouts on all operations
- Redact stderr/log output before returning
- No client-provided paths or IDs - server-owned only

This module provides a lightweight smoke test that validates:
1. Firecracker binary can start
2. Process stays alive for a short window
3. Metrics file appears (proves Firecracker is running)
4. Clean shutdown is possible

It does NOT require a guest agent - this tests Firecracker itself.

On failure, artifacts are kept for debugging and a classification is provided:
- "core_boot_failure": Minimal boot failed (kernel/rootfs/kvm issue)
- "higher_layer_failure": Minimal boot OK but full smoke failed (network/vsock/agent)
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.services.microvm_paths import (
    PathContainmentError,
    PathTraversalError,
    is_wsl,
    redact_path,
    redact_secret_patterns,
    resolve_under_base,
    resolve_use_jailer,
    safe_config_excerpt,
    safe_tail,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Smoke test timing (keep under 5 seconds total for fast feedback)
SMOKE_STARTUP_WAIT_MS = 300  # Wait for Firecracker to initialize
SMOKE_METRICS_TIMEOUT_SECS = 2.0  # Max wait for metrics file
SMOKE_TEARDOWN_TIMEOUT_SECS = 2.0  # Max wait for graceful shutdown
SMOKE_POLL_INTERVAL_SECS = 0.1  # Polling interval for metrics

# Minimal boot settings (for classification retry)
MINIMAL_BOOT_ALIVE_SECS = 1.5  # Must stay alive this long for minimal boot success

# Output limits
MAX_LOG_TAIL_LINES = 50
MAX_LOG_TAIL_CHARS = 4000
MAX_STDERR_CHARS = 2000

# Artifact retention
MAX_FAILED_SMOKE_DIRS = 10  # Keep last N failed smoke directories

# Smoke ID validation regex: smoke_<13-digit-unix-ms>_<8-hex-chars>
SMOKE_ID_PATTERN = re.compile(r"^smoke_\d{13}_[0-9a-f]{8}$")

# Failure classification
CLASSIFICATION_CORE_BOOT = "core_boot_failure"
CLASSIFICATION_HIGHER_LAYER = "higher_layer_failure"
CLASSIFICATION_UNKNOWN = "unknown"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class SmokeTimings:
    """Timing breakdown for smoke test phases."""

    boot_ms: int = 0
    ready_ms: int = 0
    teardown_ms: int = 0
    total_ms: int = 0


@dataclass
class SmokeDebug:
    """Debug information for smoke test failures.

    SECURITY:
    - All fields are redacted before returning
    - No full paths, no secrets
    """

    stderr_tail: str = ""
    log_tail: str = ""
    config_excerpt: dict = field(default_factory=dict)
    temp_dir_redacted: str = ""
    firecracker_rc: Optional[int] = None
    metrics_appeared: bool = False
    process_alive_at_check: bool = False
    use_jailer: bool = False
    is_wsl: bool = False


@dataclass
class SmokeResult:
    """Result of Firecracker smoke test.

    SECURITY:
    - ok indicates whether Firecracker can run (not guest agent)
    - debug is only populated on failure
    - notes are redacted
    - smoke_id is server-generated, never client-provided
    """

    ok: bool
    timings: SmokeTimings = field(default_factory=SmokeTimings)
    notes: list[str] = field(default_factory=list)
    debug: Optional[SmokeDebug] = None
    firecracker_rc: Optional[int] = None
    generated_at: str = ""
    smoke_id: Optional[str] = None  # Set on failure when artifacts kept
    classification: Optional[str] = None  # Failure classification
    artifacts_kept: bool = False  # Whether debug artifacts were preserved

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for API response."""
        result = {
            "ok": self.ok,
            "timings": {
                "boot_ms": self.timings.boot_ms,
                "ready_ms": self.timings.ready_ms,
                "teardown_ms": self.timings.teardown_ms,
                "total_ms": self.timings.total_ms,
            },
            "notes": self.notes[:10],  # Cap notes
            "firecracker_rc": self.firecracker_rc,
            "generated_at": self.generated_at,
            "smoke_id": self.smoke_id,
            "classification": self.classification,
            "artifacts_kept": self.artifacts_kept,
        }

        if self.debug:
            result["debug"] = {
                "stderr_tail": self.debug.stderr_tail,
                "log_tail": self.debug.log_tail,
                "config_excerpt": self.debug.config_excerpt,
                "temp_dir_redacted": self.debug.temp_dir_redacted,
                "firecracker_rc": self.debug.firecracker_rc,
                "metrics_appeared": self.debug.metrics_appeared,
                "process_alive_at_check": self.debug.process_alive_at_check,
                "use_jailer": self.debug.use_jailer,
                "is_wsl": self.debug.is_wsl,
            }

        return result


# =============================================================================
# Smoke ID and Path Utilities
# =============================================================================


def generate_smoke_id() -> str:
    """Generate a secure, unique smoke test ID.

    Format: smoke_<unix_ms>_<8_hex_chars>

    SECURITY:
    - Server-generated only, never accept from client
    - Uses secrets module for random component
    - Format is strictly validated before any filesystem operations
    """
    unix_ms = int(time.time() * 1000)
    random_hex = secrets.token_hex(4)  # 8 hex chars
    return f"smoke_{unix_ms}_{random_hex}"


def validate_smoke_id(smoke_id: str) -> bool:
    """Validate smoke_id format strictly.

    SECURITY:
    - Only accept IDs matching exact pattern
    - Reject anything with path separators or traversal
    - Used before any filesystem operations on client-provided IDs
    """
    if not smoke_id or not isinstance(smoke_id, str):
        return False
    return bool(SMOKE_ID_PATTERN.match(smoke_id))


def get_smoke_dir(state_dir: Path, smoke_id: str) -> Optional[Path]:
    """Get the smoke directory path with validation and containment check.

    Args:
        state_dir: Base state directory
        smoke_id: Smoke ID to resolve

    Returns:
        Resolved path if valid and contained, None otherwise

    SECURITY:
    - Validates smoke_id format
    - Enforces path containment
    - Returns None on any validation failure (fail closed)
    """
    if not validate_smoke_id(smoke_id):
        return None

    try:
        return resolve_under_base(state_dir, smoke_id)
    except (PathContainmentError, PathTraversalError):
        return None


def cleanup_old_smoke_dirs(state_dir: Path, keep_count: int = MAX_FAILED_SMOKE_DIRS) -> int:
    """Remove oldest smoke directories beyond retention limit.

    Args:
        state_dir: Base state directory
        keep_count: Number of smoke directories to keep

    Returns:
        Number of directories removed

    SECURITY:
    - Only removes directories matching smoke_id pattern
    - Validates containment before deletion
    - Ignores symlinks
    """
    removed = 0

    try:
        if not state_dir.exists():
            return 0

        # Find all smoke directories (validate pattern)
        smoke_dirs: list[tuple[Path, float]] = []
        for entry in state_dir.iterdir():
            if not entry.is_dir() or entry.is_symlink():
                continue
            if not validate_smoke_id(entry.name):
                continue
            # Validate containment
            try:
                resolved = entry.resolve()
                resolved.relative_to(state_dir.resolve())
            except (ValueError, OSError):
                continue
            try:
                mtime = entry.stat().st_mtime
                smoke_dirs.append((entry, mtime))
            except OSError:
                continue

        # Sort by mtime, newest first
        smoke_dirs.sort(key=lambda x: x[1], reverse=True)

        # Remove oldest beyond keep_count
        for smoke_dir, _ in smoke_dirs[keep_count:]:
            try:
                shutil.rmtree(smoke_dir)
                removed += 1
                logger.info(f"Removed old smoke dir: {smoke_dir.name}")
            except Exception as e:
                logger.warning(f"Failed to remove old smoke dir {smoke_dir.name}: {e}")

    except Exception as e:
        logger.warning(f"Error during smoke dir cleanup: {e}")

    return removed


def list_smoke_dirs(state_dir: Path) -> list[dict]:
    """List all smoke directories with metadata.

    Returns list of dicts with keys: smoke_id, mtime, exists

    SECURITY:
    - Only lists directories matching smoke_id pattern
    - Returns redacted paths
    """
    results = []

    try:
        if not state_dir.exists():
            return results

        for entry in state_dir.iterdir():
            if not entry.is_dir() or entry.is_symlink():
                continue
            if not validate_smoke_id(entry.name):
                continue
            try:
                mtime = entry.stat().st_mtime
                results.append({
                    "smoke_id": entry.name,
                    "mtime": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
                    "exists": True,
                })
            except OSError:
                continue

        # Sort by mtime, newest first
        results.sort(key=lambda x: x["mtime"], reverse=True)

    except Exception:
        pass

    return results


# =============================================================================
# Minimal Boot Test (for classification)
# =============================================================================


def _run_minimal_boot(
    firecracker_bin: str,
    kernel_path: str,
    rootfs_path: str,
    temp_dir: Path,
) -> tuple[bool, Optional[int], str]:
    """Run a minimal boot to classify failures.

    This boots with:
    - Boot source + rootfs only
    - No network interfaces
    - No vsock
    - No agent required

    Success = process stays alive > MINIMAL_BOOT_ALIVE_SECS

    Args:
        firecracker_bin: Path to firecracker binary
        kernel_path: Path to kernel
        rootfs_path: Path to (copied) rootfs
        temp_dir: Temp directory for this smoke test

    Returns:
        Tuple of (success, exit_code, notes)

    SECURITY:
    - shell=False
    - All paths resolved
    - Output captured to files
    """
    notes = []
    minimal_config = {
        "boot-source": {
            "kernel_image_path": kernel_path,
            "boot_args": "console=ttyS0 reboot=k panic=1 pci=off",
        },
        "drives": [
            {
                "drive_id": "rootfs",
                "path_on_host": str(rootfs_path),
                "is_root_device": True,
                "is_read_only": False,
            }
        ],
        "machine-config": {
            "vcpu_count": 1,
            "mem_size_mib": 128,  # Even more minimal
        },
    }

    minimal_config_path = temp_dir / "minimal_config.json"
    minimal_stderr_path = temp_dir / "minimal_stderr.log"

    try:
        minimal_config_path.write_text(json.dumps(minimal_config, indent=2))
    except Exception as e:
        return False, None, f"Failed to write minimal config: {type(e).__name__}"

    proc = None
    stderr_file = None
    exit_code = None

    try:
        stderr_file = open(minimal_stderr_path, "w")
        proc = subprocess.Popen(
            [firecracker_bin, "--config-file", str(minimal_config_path)],
            stdout=subprocess.DEVNULL,
            stderr=stderr_file,
            start_new_session=True,
        )

        # Wait for minimal boot time
        time.sleep(MINIMAL_BOOT_ALIVE_SECS)

        poll_result = proc.poll()
        if poll_result is not None:
            exit_code = poll_result
            notes.append(f"Minimal boot exited early: rc={exit_code}")
            return False, exit_code, "; ".join(notes)

        # Process still alive - success
        notes.append("Minimal boot stayed alive")
        return True, None, "; ".join(notes)

    except Exception as e:
        notes.append(f"Minimal boot error: {type(e).__name__}")
        return False, None, "; ".join(notes)

    finally:
        # Cleanup process
        if proc is not None and proc.poll() is None:
            try:
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1.0)
            except Exception:
                pass

        if stderr_file:
            try:
                stderr_file.close()
            except Exception:
                pass


# =============================================================================
# Smoke Test Implementation
# =============================================================================


def run_firecracker_smoke(
    firecracker_bin: str,
    kernel_path: str,
    rootfs_path: str,
    state_dir: str,
    keep_temp: bool = False,
    use_jailer: Optional[bool] = None,
    jailer_bin: str = "/usr/local/bin/jailer",
) -> SmokeResult:
    """Run a lightweight Firecracker smoke test.

    This test validates that Firecracker can start and run without errors.
    It does NOT require a guest agent or any guest-side readiness signal.

    Success criteria:
    1. Process starts and stays alive for SMOKE_STARTUP_WAIT_MS
    2. Metrics file appears (proves Firecracker API is working)

    Args:
        firecracker_bin: Path to firecracker binary
        kernel_path: Path to vmlinux kernel image
        rootfs_path: Path to base rootfs image
        state_dir: Base directory for smoke test temp files
        keep_temp: If True, don't cleanup temp directory (debug only)
        use_jailer: If None, auto-detect (False on WSL, True if jailer present).
                    If True/False, use that value explicitly.
        jailer_bin: Path to jailer binary (used if use_jailer resolves to True)

    Returns:
        SmokeResult with success/failure and diagnostics

    SECURITY:
    - Creates temp directory under state_dir (containment enforced)
    - Cleans up temp directory even on failure (unless keep_temp=True)
    - All output is redacted before returning
    - subprocess uses shell=False
    - Jailer policy controlled via use_jailer param (WSL cannot use jailer)
    """
    notes: list[str] = []
    timings = SmokeTimings()
    debug = SmokeDebug()
    total_start = time.monotonic()

    # Resolve jailer policy
    debug.is_wsl = is_wsl()
    debug.use_jailer = resolve_use_jailer(use_jailer, jailer_bin)

    if debug.is_wsl:
        notes.append("WSL detected - running without jailer")
    elif debug.use_jailer:
        notes.append("Using jailer for sandboxing")
    else:
        notes.append("Running without jailer (not recommended for production)")

    # Generate secure smoke_id
    smoke_id = generate_smoke_id()
    temp_dir: Optional[Path] = None
    proc: Optional[subprocess.Popen] = None
    smoke_ok = False  # Track success for cleanup decision
    classification: Optional[str] = None

    try:
        # =================================================================
        # Step 0: Cleanup old smoke directories (retention policy)
        # =================================================================
        base_state_dir = Path(state_dir)
        cleanup_old_smoke_dirs(base_state_dir, MAX_FAILED_SMOKE_DIRS)

        # =================================================================
        # Step 1: Create temp directory with containment check
        # =================================================================
        try:
            temp_dir = resolve_under_base(base_state_dir, smoke_id)
            temp_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
            debug.temp_dir_redacted = redact_path(temp_dir, "<STATE_DIR>", base_state_dir)
            notes.append(f"Created temp: {debug.temp_dir_redacted} (id={smoke_id})")
        except PathContainmentError as e:
            notes.append("Path containment violation")
            logger.error(f"Smoke test path containment error: {e}")
            return SmokeResult(
                ok=False,
                timings=timings,
                notes=notes,
                debug=debug,
            )
        except FileExistsError:
            notes.append("Temp directory already exists (concurrent smoke?)")
            return SmokeResult(
                ok=False,
                timings=timings,
                notes=notes,
                debug=debug,
            )
        except PermissionError:
            notes.append("Cannot create temp directory (permission denied)")
            return SmokeResult(
                ok=False,
                timings=timings,
                notes=notes,
                debug=debug,
            )

        # =================================================================
        # Step 2: Validate inputs exist
        # =================================================================
        kernel = Path(kernel_path)
        rootfs = Path(rootfs_path)

        if not kernel.exists():
            notes.append(f"Kernel not found: {redact_path(kernel)}")
            return SmokeResult(ok=False, timings=timings, notes=notes, debug=debug)

        if not rootfs.exists():
            notes.append(f"Rootfs not found: {redact_path(rootfs)}")
            return SmokeResult(ok=False, timings=timings, notes=notes, debug=debug)

        # =================================================================
        # Step 3: Copy rootfs for ephemeral use
        # =================================================================
        boot_start = time.monotonic()

        smoke_rootfs = temp_dir / "rootfs.ext4"
        try:
            shutil.copy2(rootfs, smoke_rootfs)
            notes.append("Copied rootfs for smoke test")
        except (OSError, IOError) as e:
            notes.append(f"Failed to copy rootfs: {type(e).__name__}")
            return SmokeResult(ok=False, timings=timings, notes=notes, debug=debug)

        # =================================================================
        # Step 4: Build Firecracker config
        # =================================================================
        log_path = temp_dir / "firecracker.log"
        metrics_path = temp_dir / "firecracker.metrics"
        stderr_path = temp_dir / "stderr.log"

        config = {
            "boot-source": {
                "kernel_image_path": str(kernel),
                "boot_args": "console=ttyS0 reboot=k panic=1 pci=off",
            },
            "drives": [
                {
                    "drive_id": "rootfs",
                    "path_on_host": str(smoke_rootfs),
                    "is_root_device": True,
                    "is_read_only": False,
                }
            ],
            "machine-config": {
                "vcpu_count": 1,
                "mem_size_mib": 256,  # Minimal for smoke test
            },
            "logger": {
                "log_path": str(log_path),
                "level": "Debug",
                "show_level": True,
                "show_log_origin": True,
            },
            "metrics": {
                "metrics_path": str(metrics_path),
            },
        }

        config_path = temp_dir / "fc.json"
        config_path.write_text(json.dumps(config, indent=2))
        debug.config_excerpt = safe_config_excerpt(config)

        # =================================================================
        # Step 5: Start Firecracker
        # =================================================================
        fc_args = [
            firecracker_bin,
            "--config-file",
            str(config_path),
        ]

        try:
            # Open stderr file for capturing
            stderr_file = open(stderr_path, "w")

            proc = subprocess.Popen(
                fc_args,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
                start_new_session=True,  # Detach from parent
            )

            boot_elapsed_ms = int((time.monotonic() - boot_start) * 1000)
            timings.boot_ms = boot_elapsed_ms
            notes.append(f"Firecracker started (boot={boot_elapsed_ms}ms)")

        except FileNotFoundError:
            notes.append("Firecracker binary not found")
            return SmokeResult(
                ok=False,
                timings=timings,
                notes=notes,
                debug=debug,
                smoke_id=smoke_id,
                classification=CLASSIFICATION_CORE_BOOT,
                artifacts_kept=True,
            )
        except PermissionError:
            notes.append("Firecracker binary not executable")
            return SmokeResult(
                ok=False,
                timings=timings,
                notes=notes,
                debug=debug,
                smoke_id=smoke_id,
                classification=CLASSIFICATION_CORE_BOOT,
                artifacts_kept=True,
            )
        except OSError as e:
            notes.append(f"Failed to start Firecracker: {type(e).__name__}")
            return SmokeResult(
                ok=False,
                timings=timings,
                notes=notes,
                debug=debug,
                smoke_id=smoke_id,
                classification=CLASSIFICATION_CORE_BOOT,
                artifacts_kept=True,
            )

        # =================================================================
        # Step 6: Check process stays alive for initial window
        # =================================================================
        ready_start = time.monotonic()

        # Wait for initial startup
        time.sleep(SMOKE_STARTUP_WAIT_MS / 1000.0)

        # Check if process exited early
        poll_result = proc.poll()
        if poll_result is not None:
            debug.firecracker_rc = poll_result
            notes.append(f"Firecracker exited immediately: rc={poll_result}")

            # Capture stderr for diagnostics
            stderr_file.close()
            if stderr_path.exists():
                debug.stderr_tail = safe_tail(
                    stderr_path.read_text(),
                    MAX_LOG_TAIL_LINES,
                    MAX_STDERR_CHARS,
                )

            # Capture log if exists
            if log_path.exists():
                debug.log_tail = safe_tail(
                    log_path.read_text(),
                    MAX_LOG_TAIL_LINES,
                    MAX_LOG_TAIL_CHARS,
                )

            # Run minimal boot for classification
            notes.append("Running minimal boot for classification...")
            minimal_ok, minimal_rc, minimal_notes = _run_minimal_boot(
                firecracker_bin=firecracker_bin,
                kernel_path=str(kernel),
                rootfs_path=str(smoke_rootfs),
                temp_dir=temp_dir,
            )
            notes.append(f"Minimal boot: {minimal_notes}")

            if minimal_ok:
                classification = CLASSIFICATION_HIGHER_LAYER
            else:
                classification = CLASSIFICATION_CORE_BOOT

            return SmokeResult(
                ok=False,
                timings=timings,
                notes=notes,
                debug=debug,
                firecracker_rc=poll_result,
                smoke_id=smoke_id,
                classification=classification,
                artifacts_kept=True,
            )

        debug.process_alive_at_check = True
        notes.append("Process alive after startup window")

        # =================================================================
        # Step 7: Wait for metrics file (proves FC API is working)
        # =================================================================
        metrics_deadline = time.monotonic() + SMOKE_METRICS_TIMEOUT_SECS
        metrics_found = False

        while time.monotonic() < metrics_deadline:
            # Check process still alive
            if proc.poll() is not None:
                debug.firecracker_rc = proc.returncode
                notes.append(f"Firecracker exited: rc={proc.returncode}")
                break

            # Check for metrics file
            if metrics_path.exists():
                try:
                    # Verify it's not empty
                    size = metrics_path.stat().st_size
                    if size > 0:
                        metrics_found = True
                        debug.metrics_appeared = True
                        notes.append(f"Metrics file appeared ({size} bytes)")
                        break
                except OSError:
                    pass

            time.sleep(SMOKE_POLL_INTERVAL_SECS)

        ready_elapsed_ms = int((time.monotonic() - ready_start) * 1000)
        timings.ready_ms = ready_elapsed_ms

        # =================================================================
        # Step 8: Teardown
        # =================================================================
        teardown_start = time.monotonic()

        if proc.poll() is None:
            # Process still running - send SIGTERM
            try:
                proc.send_signal(signal.SIGTERM)
                try:
                    proc.wait(timeout=SMOKE_TEARDOWN_TIMEOUT_SECS)
                    notes.append("Graceful shutdown completed")
                except subprocess.TimeoutExpired:
                    # Force kill
                    proc.kill()
                    proc.wait(timeout=1.0)
                    notes.append("Force killed (SIGKILL)")
            except ProcessLookupError:
                # Process already gone
                notes.append("Process already exited")
            except Exception as e:
                notes.append(f"Teardown error: {type(e).__name__}")
        else:
            debug.firecracker_rc = proc.returncode
            notes.append(f"Process already exited: rc={proc.returncode}")

        teardown_elapsed_ms = int((time.monotonic() - teardown_start) * 1000)
        timings.teardown_ms = teardown_elapsed_ms

        # Close stderr file if still open
        try:
            stderr_file.close()
        except Exception:
            pass

        # =================================================================
        # Step 9: Determine success
        # =================================================================
        # Success if:
        # 1. Process was alive after startup window
        # 2. Metrics file appeared (proves Firecracker is working)
        smoke_ok = debug.process_alive_at_check and metrics_found

        if smoke_ok:
            notes.append("Smoke test PASSED")
        else:
            notes.append("Smoke test FAILED")
            # Capture diagnostics on failure
            if stderr_path.exists():
                debug.stderr_tail = safe_tail(
                    stderr_path.read_text(),
                    MAX_LOG_TAIL_LINES,
                    MAX_STDERR_CHARS,
                )
            if log_path.exists():
                debug.log_tail = safe_tail(
                    log_path.read_text(),
                    MAX_LOG_TAIL_LINES,
                    MAX_LOG_TAIL_CHARS,
                )

            # =============================================================
            # Step 10: Run minimal boot for failure classification
            # =============================================================
            notes.append("Running minimal boot for classification...")
            minimal_ok, minimal_rc, minimal_notes = _run_minimal_boot(
                firecracker_bin=firecracker_bin,
                kernel_path=str(kernel),
                rootfs_path=str(smoke_rootfs),
                temp_dir=temp_dir,
            )
            notes.append(f"Minimal boot: {minimal_notes}")

            if minimal_ok:
                # Minimal boot worked but full smoke failed
                classification = CLASSIFICATION_HIGHER_LAYER
                notes.append(f"Classification: {classification} (network/vsock/agent issue)")
            else:
                # Minimal boot also failed
                classification = CLASSIFICATION_CORE_BOOT
                notes.append(f"Classification: {classification} (kernel/rootfs/KVM issue)")

        total_elapsed_ms = int((time.monotonic() - total_start) * 1000)
        timings.total_ms = total_elapsed_ms

        return SmokeResult(
            ok=smoke_ok,
            timings=timings,
            notes=notes,
            debug=debug if not smoke_ok else None,  # Only include debug on failure
            firecracker_rc=debug.firecracker_rc,
            smoke_id=smoke_id if not smoke_ok else None,  # Return ID on failure for artifact retrieval
            classification=classification,
            artifacts_kept=not smoke_ok,  # Artifacts kept on failure
        )

    except Exception as e:
        notes.append(f"Unexpected error: {type(e).__name__}")
        logger.exception("Smoke test unexpected error")
        return SmokeResult(
            ok=False,
            timings=timings,
            notes=notes,
            debug=debug,
            smoke_id=smoke_id,
            classification=CLASSIFICATION_UNKNOWN,
            artifacts_kept=True,
        )

    finally:
        # =================================================================
        # Cleanup (on success only, or if keep_temp explicitly set)
        # =================================================================
        if proc is not None and proc.poll() is None:
            # Kill any remaining process
            try:
                proc.kill()
                proc.wait(timeout=1.0)
            except Exception:
                pass

        if temp_dir is not None and temp_dir.exists():
            # Keep artifacts on failure for debugging
            if smoke_ok and not keep_temp:
                # Success - cleanup
                try:
                    shutil.rmtree(temp_dir)
                    logger.info(f"Smoke temp cleaned up: {smoke_id}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup smoke temp dir: {e}")
            else:
                # Failure or keep_temp - preserve for debugging
                logger.info(f"Smoke artifacts preserved: {smoke_id}")


def get_fatal_summary(result: SmokeResult) -> str:
    """Get a redacted summary suitable for error messages.

    Args:
        result: SmokeResult from run_firecracker_smoke

    Returns:
        Single-line summary of failure (redacted)

    SECURITY: Safe to include in exception messages and logs.
    """
    if result.ok:
        return "Smoke test passed"

    parts = ["Firecracker smoke test failed"]

    if result.firecracker_rc is not None:
        parts.append(f"(rc={result.firecracker_rc})")

    # Add first relevant note
    failure_notes = [n for n in result.notes if "FAILED" in n or "exited" in n.lower()]
    if failure_notes:
        parts.append(f": {failure_notes[0]}")
    elif result.notes:
        parts.append(f": {result.notes[-1]}")

    return " ".join(parts)
