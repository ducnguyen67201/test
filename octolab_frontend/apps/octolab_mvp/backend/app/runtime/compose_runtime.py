"""Docker Compose-backed LabRuntime implementation.

Network Cleanup with Retry (GC Race Handling)
---------------------------------------------
Docker endpoint cleanup has ~200-800ms lag after container removal. This can cause
network removal to fail on first attempt even though no containers remain. The
teardown flow handles this with:

1. `docker compose down --remove-orphans` stops containers
2. Force-remove any remaining containers (label-scoped)
3. `remove_compose_project_networks()` removes networks with retry logic:
   - Lists networks by compose project label
   - Validates names match expected pattern (defense-in-depth)
   - Retries with exponential backoff on "in-use" errors
   - Force-disconnects allowlisted containers (e.g., guacd)
   - Returns truthful accounting of removed vs skipped

Verification Steps (for local testing)
--------------------------------------
1. Create a lab via API: POST /labs
2. Wait for lab to reach READY state
3. Delete the lab: DELETE /labs/{id}
4. Check logs for "Teardown verified" message showing:
   - success=true (both containers and networks removed)
   - networks_remaining=0
5. If networks remain on first attempt, logs will show:
   - Warning with blocking container names (if any)
   - Error details in teardown result

To verify retry behavior works:
1. Set OCTOLAB_NET_RM_MAX_RETRIES=1 (minimal retries)
2. Create and delete a lab quickly (race more likely)
3. With default settings (retries=6, backoff=200ms), networks should
   typically be removed on first DELETE even under race conditions.

No manual docker commands required for normal operation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Sequence
from subprocess import CalledProcessError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.lab import Lab
from app.models.recipe import Recipe
from app.runtime.base import LabRuntime
from app.runtime.exceptions import NetworkPoolExhaustedError, NetworkCleanupBlockedError
from app.services.port_allocator import allocate_novnc_port, release_novnc_port
from app.services.docker_net import (
    preflight_network_cleanup,
    get_network_counts,
    list_networks_by_compose_project,
    get_network_container_count,
    remove_compose_project_networks,
    NetworkRemovalResult,
)
from app.utils.redact import (
    redact_argv,
    redact_text,
    truncate_text,
    sanitize_subprocess_error,
    sanitize_output,
)

logger = logging.getLogger(__name__)


class ComposeCommandError(RuntimeError):
    """Error from docker compose command with sanitized diagnostics.

    Stores sanitized stdout/stderr for debugging while keeping the
    exception message short and safe for propagation to clients.

    Attributes:
        cmd: Command that was executed (safe to log)
        cwd: Working directory
        exit_code: Process exit code
        stdout: Sanitized stdout (secrets redacted, truncated)
        stderr: Sanitized stderr (secrets redacted, truncated)
    """

    def __init__(
        self,
        message: str,
        *,
        cmd: list[str],
        cwd: str,
        exit_code: int | None = None,
        stdout: str = "",
        stderr: str = "",
    ):
        super().__init__(message)
        self.cmd = cmd
        self.cwd = cwd
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    def __str__(self) -> str:
        """Return short message without full output (output is in attributes)."""
        return self.args[0] if self.args else "docker compose failed"

# Timeout for docker compose build with cache busting
_TIMEOUT_COMPOSE_BUILD = 300  # 5 minutes for image build

# Timeouts per the mandatory timeout table
_TIMEOUT_NETWORK_RM = 30
_TIMEOUT_NETWORK_INSPECT = 30
_TIMEOUT_NETWORK_DISCONNECT = 30
_TIMEOUT_COMPOSE_RM = 120
_TIMEOUT_COMPOSE_DOWN = 120

# Error patterns indicating Docker subnet/network pool exhaustion
POOL_EXHAUSTED_PATTERNS = [
    "pool overlaps with other one on this address space",
    "could not find an available, non-overlapping ipv4 address pool",
    "no available ip addresses in pool",
    "failed to allocate subnet",
]

# Regex to validate lab project names (security: only operate on octolab_<uuid> projects)
import re
from uuid import UUID as PyUUID

LAB_PROJECT_RE = re.compile(r"^octolab_[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$", re.IGNORECASE)


def _is_lab_project(project: str) -> bool:
    """Validate that a project name matches the expected octolab_<uuid> pattern.

    SECURITY: Only operate on projects matching this pattern to prevent
    accidental cleanup of unrelated Docker resources.
    """
    return bool(LAB_PROJECT_RE.match(project))


def _normalize_project_name(name: str) -> str:
    """Normalize project name for docker compose.

    Docker Compose project names must be lowercase and can only contain
    alphanumeric characters, underscores, and hyphens.

    Args:
        name: Raw project name (may contain UUIDs)

    Returns:
        Normalized, lowercase project name
    """
    # Lowercase first
    normalized = name.lower()
    # Replace any disallowed characters with underscore
    normalized = re.sub(r"[^a-z0-9_-]", "_", normalized)
    return normalized


def project_name_for_lab(lab_id: PyUUID | str) -> str:
    """Generate project name from server-owned lab ID.

    SECURITY: Project name is always derived from server-owned lab_id,
    never accepted from client input.

    Args:
        lab_id: UUID or string lab ID

    Returns:
        Normalized project name in format: octolab_<uuid>
    """
    raw_name = f"octolab_{lab_id}"
    return _normalize_project_name(raw_name)


def assert_valid_lab_project(project: str) -> None:
    """Assert that a project name matches the expected octolab_<uuid> pattern.

    SECURITY: Call this before any Docker operations to ensure we only
    operate on valid lab projects.

    Args:
        project: Project name to validate

    Raises:
        ValueError: If project name doesn't match expected pattern
    """
    if not _is_lab_project(project):
        raise ValueError(
            f"Invalid lab project name: {project[:50]}. "
            f"Expected format: octolab_<uuid>"
        )


class TeardownResult:
    """Structured result of verified teardown operation.

    Provides truthful accounting of what was cleaned up and what remains.
    """

    def __init__(self, project: str):
        self.project = project
        self.compose_down_ok: bool = False
        self.containers_before: int = 0
        self.containers_removed_force: int = 0
        self.containers_remaining: int = 0
        self.networks_before: int = 0
        self.networks_removed: int = 0
        self.networks_remaining: int = 0
        self.errors: list[str] = []

    @property
    def success(self) -> bool:
        """Teardown is successful only if no containers or networks remain."""
        return self.containers_remaining == 0 and self.networks_remaining == 0

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/debugging."""
        return {
            "project": self.project,
            "compose_down_ok": self.compose_down_ok,
            "containers_before": self.containers_before,
            "containers_removed_force": self.containers_removed_force,
            "containers_remaining": self.containers_remaining,
            "networks_before": self.networks_before,
            "networks_removed": self.networks_removed,
            "networks_remaining": self.networks_remaining,
            "errors": self.errors[:5],  # Truncate for logging
            "success": self.success,
        }


def _list_project_containers(project: str, all_states: bool = True) -> list[dict]:
    """List containers belonging to a compose project using label filter.

    SECURITY: Uses label-based filtering (com.docker.compose.project) which is
    reliable and scoped. Never uses name-based matching.

    Args:
        project: Compose project name
        all_states: Include stopped containers (docker ps -a)

    Returns:
        List of dicts with keys: id, name, status (truncated for safety)
    """
    cmd = [
        "docker", "ps",
        "--filter", f"label=com.docker.compose.project={project}",
        "--format", "{{.ID}}\t{{.Names}}\t{{.Status}}",
    ]
    if all_states:
        cmd.insert(2, "-a")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            shell=False,
            timeout=10.0,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []

        containers = []
        for line in result.stdout.strip().split("\n"):
            parts = line.split("\t")
            if len(parts) >= 2:
                containers.append({
                    "id": parts[0][:12],  # Short ID
                    "name": parts[1][:80],  # Truncate name
                    "status": parts[2][:50] if len(parts) > 2 else "",
                })
        return containers

    except (subprocess.TimeoutExpired, Exception) as e:
        logger.debug(f"Failed to list containers for project {project}: {type(e).__name__}")
        return []


def _rm_containers_force(container_ids: list[str]) -> tuple[int, list[str]]:
    """Force-remove containers by ID.

    SECURITY: Uses explicit container IDs (not names) with shell=False.

    Args:
        container_ids: List of container IDs to remove

    Returns:
        Tuple of (removed_count, error_messages)
    """
    if not container_ids:
        return 0, []

    # Process in batches to avoid command line length issues
    batch_size = 10
    removed = 0
    errors = []

    for i in range(0, len(container_ids), batch_size):
        batch = container_ids[i:i + batch_size]
        cmd = ["docker", "rm", "-f"] + batch

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=False,
                timeout=30.0,
            )
            if result.returncode == 0:
                removed += len(batch)
            else:
                # Some may have succeeded, some failed
                stderr = result.stderr.strip()[:100]
                errors.append(f"docker rm -f failed: {stderr}")
                # Still count partial success
                removed += max(0, len(batch) - stderr.count("Error"))

        except subprocess.TimeoutExpired:
            errors.append(f"docker rm -f timed out for batch starting {batch[0][:12]}")
        except Exception as e:
            errors.append(f"docker rm -f error: {type(e).__name__}")

    return removed, errors


def _list_project_networks(project: str) -> list[str]:
    """List networks belonging to a compose project using label filter.

    Args:
        project: Compose project name

    Returns:
        List of network names
    """
    cmd = [
        "docker", "network", "ls",
        "--filter", f"label=com.docker.compose.project={project}",
        "--format", "{{.Name}}",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            shell=False,
            timeout=10.0,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []

        return [name.strip() for name in result.stdout.strip().split("\n") if name.strip()]

    except (subprocess.TimeoutExpired, Exception) as e:
        logger.debug(f"Failed to list networks for project {project}: {type(e).__name__}")
        return []


def _rm_networks(network_names: list[str]) -> tuple[int, int, list[str]]:
    """Remove networks by name.

    SECURITY: Only operates on provided network names with shell=False.

    Args:
        network_names: List of network names to remove

    Returns:
        Tuple of (removed_count, remaining_count, error_messages)
    """
    if not network_names:
        return 0, 0, []

    removed = 0
    errors = []

    for net_name in network_names:
        # Defense-in-depth: skip non-octolab networks
        if not net_name.startswith("octolab_"):
            logger.debug(f"Skipping non-octolab network: {net_name}")
            continue

        cmd = ["docker", "network", "rm", net_name]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=False,
                timeout=_TIMEOUT_NETWORK_RM,
            )
            if result.returncode == 0:
                removed += 1
            else:
                stderr = result.stderr.strip().lower()
                if "not found" in stderr or "no such network" in stderr:
                    # Already gone, count as success
                    removed += 1
                elif "has active endpoints" in stderr:
                    errors.append(f"{net_name}: has active endpoints")
                else:
                    errors.append(f"{net_name}: {result.stderr.strip()[:50]}")

        except subprocess.TimeoutExpired:
            errors.append(f"{net_name}: timeout")
        except Exception as e:
            errors.append(f"{net_name}: {type(e).__name__}")

    remaining = len(network_names) - removed
    return removed, remaining, errors


class ComposeLabRuntime(LabRuntime):
    """Provision labs by invoking docker compose with per-lab project names."""

    def __init__(
        self,
        compose_path: Path,
        project_prefix: str = "octolab_",
    ) -> None:
        self.compose_path = compose_path.resolve()
        self.compose_dir = str(self.compose_path.parent)  # Directory for --project-directory and cwd
        if not self.compose_path.exists():
            raise RuntimeError(f"Compose file not found: {self.compose_path}")
        self.project_prefix = project_prefix

    def _project_name(self, lab: Lab) -> str:
        """Generate normalized project name from server-owned lab ID."""
        raw_name = f"{self.project_prefix}{lab.id}"
        return _normalize_project_name(raw_name)

    def _is_pool_exhausted_error(self, error_msg: str) -> bool:
        """Check if an error message indicates Docker subnet pool exhaustion.

        Args:
            error_msg: Error message from docker command

        Returns:
            True if error indicates pool exhaustion
        """
        error_lower = error_msg.lower()
        return any(pattern in error_lower for pattern in POOL_EXHAUSTED_PATTERNS)

    async def _run_compose(
        self,
        args: Sequence[str],
        env: dict[str, str] | None = None,
        suppress_errors: bool = False,
        timeout: float = 120.0,
        secrets_for_redaction: list[str] | None = None,
    ) -> tuple[str, str]:
        """Run docker compose command with deterministic paths and captured output.

        DETERMINISTIC EXECUTION:
        - Uses --project-directory to set compose context
        - Sets cwd to compose_dir so relative paths resolve correctly

        Args:
            args: Compose subcommand and arguments
            env: Environment variables for subprocess (secrets must not be logged)
            suppress_errors: If True, log and swallow CalledProcessError
            timeout: Command timeout in seconds (default 120s)
            secrets_for_redaction: List of secret values to redact from output

        Returns:
            Tuple of (sanitized_stdout, sanitized_stderr)

        Raises:
            ComposeCommandError: If compose command fails (with sanitized output)
            subprocess.TimeoutExpired: If command times out
        """
        secrets = secrets_for_redaction or []

        # Build command with --project-directory for deterministic path resolution
        cmd = [
            "docker", "compose",
            "--project-directory", self.compose_dir,
            "-f", str(self.compose_path),
            *args,
        ]

        # SECURITY: Log command without env (may contain VNC_PASSWORD)
        # Only log whether VNC_PASSWORD is present, never its value
        vnc_password_present = bool(env and env.get("VNC_PASSWORD"))
        logger.debug(
            f"Running compose command: {redact_argv(cmd)}, "
            f"cwd={self.compose_dir}, vnc_password_present={vnc_password_present}"
        )

        def _run() -> subprocess.CompletedProcess:
            return subprocess.run(
                cmd,
                env=env,
                check=True,
                shell=False,
                timeout=timeout,
                capture_output=True,
                text=True,
                cwd=self.compose_dir,  # DETERMINISTIC: Run from compose directory
            )

        try:
            result = await asyncio.to_thread(_run)
            # Sanitize output even on success
            sanitized_stdout = sanitize_output(result.stdout, secrets)
            sanitized_stderr = sanitize_output(result.stderr, secrets)
            return sanitized_stdout, sanitized_stderr

        except subprocess.CalledProcessError as exc:
            # Sanitize output before any logging or exception propagation
            sanitized_stdout = sanitize_output(exc.stdout, secrets)
            sanitized_stderr = sanitize_output(exc.stderr, secrets)

            if suppress_errors:
                logger.info(
                    f"docker compose command failed but was suppressed "
                    f"(exit_code={exc.returncode}, vnc_password_present={vnc_password_present})"
                )
                return sanitized_stdout, sanitized_stderr

            # Log sanitized error details
            stderr_excerpt = sanitized_stderr[:500] if sanitized_stderr else "(empty)"
            logger.error(
                f"docker compose failed (exit_code={exc.returncode}): {stderr_excerpt}"
            )

            # Raise ComposeCommandError with sanitized diagnostics
            raise ComposeCommandError(
                f"docker compose failed (exit_code={exc.returncode})",
                cmd=cmd,
                cwd=self.compose_dir,
                exit_code=exc.returncode,
                stdout=sanitized_stdout,
                stderr=sanitized_stderr,
            ) from exc

        except subprocess.TimeoutExpired:
            logger.error(
                f"docker compose timed out after {timeout}s, "
                f"vnc_password_present={vnc_password_present}"
            )
            raise

    async def _run_compose_build_with_cache_bust(
        self,
        project: str,
        env: dict[str, str],
    ) -> None:
        """Run docker compose build with CMDLOG_BUST arg for cache invalidation.

        This forces rebuild of cmdlog layers without rebuilding cached apt layers.
        Only called when dev_force_cmdlog_rebuild is enabled (server-side setting).

        Args:
            project: Compose project name
            env: Environment variables for subprocess

        Raises:
            subprocess.CalledProcessError: If build fails
            subprocess.TimeoutExpired: If build exceeds timeout
        """
        # Generate server-side cache bust value (unix timestamp)
        cache_bust_value = str(int(time.time()))

        cmd = [
            "docker", "compose",
            "--project-directory", self.compose_dir,
            "-f", str(self.compose_path),
            "-p", project,
            "build",
            "--build-arg", f"CMDLOG_BUST={cache_bust_value}",
        ]

        def _build() -> None:
            subprocess.run(
                cmd,
                env=env,
                check=True,
                shell=False,
                timeout=_TIMEOUT_COMPOSE_BUILD,
                capture_output=True,  # Don't spam logs with build output
                cwd=self.compose_dir,  # DETERMINISTIC: Run from compose directory
            )

        logger.info(f"Building with CMDLOG_BUST={cache_bust_value} for project {project}")
        await asyncio.to_thread(_build)

    def _is_localhost(self, host: str) -> bool:
        """Check if host is a localhost address."""
        return host in ("127.0.0.1", "localhost", "::1")

    def _collect_compose_diagnostics(
        self,
        project: str,
        secrets: list[str] | None = None,
    ) -> dict[str, str]:
        """Collect docker compose diagnostic information for failed labs.

        Runs compose ps, logs, and config to gather diagnostic info.
        All output is sanitized (secrets redacted, truncated).

        Args:
            project: Compose project name
            secrets: List of secret values to redact from output

        Returns:
            Dict with keys: compose_ps, compose_logs, compose_config
            Values are sanitized strings (may include error info if command failed)
        """
        secrets = secrets or []
        diagnostics: dict[str, str] = {}

        # Commands to run for diagnostics
        diagnostic_commands = {
            "compose_ps": ["-p", project, "ps", "-a"],
            "compose_logs": ["-p", project, "logs", "--no-color", "--tail=200"],
            "compose_config": ["-p", project, "config"],
        }

        for diag_name, args in diagnostic_commands.items():
            cmd = [
                "docker", "compose",
                "--project-directory", self.compose_dir,
                "-f", str(self.compose_path),
                *args,
            ]

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    shell=False,
                    timeout=30.0,
                    cwd=self.compose_dir,
                )
                if result.returncode == 0:
                    diagnostics[diag_name] = sanitize_output(result.stdout, secrets)
                else:
                    # Include stderr on failure but note the error
                    stderr = sanitize_output(result.stderr, secrets)
                    diagnostics[diag_name] = f"(exit_code={result.returncode}) {stderr}"
            except subprocess.TimeoutExpired:
                diagnostics[diag_name] = "(timed out)"
            except Exception as e:
                diagnostics[diag_name] = f"(error: {type(e).__name__})"

        # Add network count diagnostics (numeric only, safe for logging)
        try:
            net_counts = get_network_counts(timeout=5.0)
            diagnostics["network_total_count"] = str(net_counts.total_count)
            diagnostics["network_octolab_count"] = str(net_counts.octolab_count)
            if net_counts.hint:
                diagnostics["network_hint"] = net_counts.hint
        except Exception:
            diagnostics["network_counts"] = "(error)"

        return diagnostics

    async def _cleanup_project(
        self,
        project: str,
        secrets: list[str] | None = None,
    ) -> dict[str, str]:
        """Best-effort cleanup of a compose project on provisioning failure.

        This performs scoped cleanup without --volumes to preserve evidence.
        Used when provisioning fails to ensure resources don't leak.

        SECURITY:
        - Only cleans up the specific project (server-derived name)
        - No --volumes flag (preserves evidence for debugging)
        - No broad prune commands
        - All output is sanitized

        Args:
            project: Compose project name (server-derived, never from client)
            secrets: List of secrets to redact from output

        Returns:
            Dict with cleanup command results (sanitized)
        """
        secrets = secrets or []
        cleanup_results: dict[str, str] = {}

        # Run docker compose down --remove-orphans (no --volumes)
        try:
            stdout, stderr = await self._run_compose(
                ["-p", project, "down", "--remove-orphans"],
                env=os.environ.copy(),
                suppress_errors=True,  # Best-effort, don't raise
                timeout=_TIMEOUT_COMPOSE_DOWN,
                secrets_for_redaction=secrets,
            )
            cleanup_results["compose_down"] = f"stdout={stdout[:200]}... stderr={stderr[:200]}..."
        except Exception as e:
            cleanup_results["compose_down"] = f"(error: {type(e).__name__})"

        # Label-based network cleanup (most reliable)
        try:
            label_stats = await asyncio.to_thread(
                self._cleanup_project_networks_by_label,
                project,
            )
            cleanup_results["label_cleanup_found"] = str(label_stats.get("networks_found", 0))
            cleanup_results["label_cleanup_removed"] = str(label_stats.get("networks_removed", 0))
            if label_stats.get("errors"):
                cleanup_results["label_cleanup_errors"] = label_stats["errors"][:200]
        except Exception as e:
            cleanup_results["label_cleanup"] = f"(error: {type(e).__name__})"

        # Fallback: targeted network removal for expected networks
        # These are deterministically named from the project
        lab_net = f"{project}_lab_net"
        egress_net = f"{project}_egress_net"

        for net_name in [lab_net, egress_net]:
            try:
                await asyncio.to_thread(
                    self._remove_network_with_retry,
                    net_name,
                    project,
                )
                cleanup_results[f"network_rm_{net_name}"] = "ok"
            except NetworkCleanupBlockedError as e:
                # Log but don't fail - cleanup is best-effort
                cleanup_results[f"network_rm_{net_name}"] = f"blocked: {','.join(e.blocking_containers)}"
            except Exception as e:
                cleanup_results[f"network_rm_{net_name}"] = f"(error: {type(e).__name__})"

        return cleanup_results

    def _cleanup_project_networks_by_label(
        self,
        project: str,
    ) -> dict[str, int | str]:
        """Remove all networks belonging to a Compose project using label-based discovery.

        Uses com.docker.compose.project label to find networks created by the project.
        Only removes networks with 0 attached containers (detached).
        Defense-in-depth: additionally requires network name to start with "octolab_".

        SECURITY:
        - project is derived from server-owned lab.id, never client input
        - Only removes networks matching the label AND starting with octolab_
        - Never runs broad prune commands
        - Ignores failures (best-effort cleanup)

        Args:
            project: Compose project name (server-derived)

        Returns:
            Dict with cleanup stats:
            - networks_found: int
            - networks_removed: int
            - networks_skipped_attached: int
            - errors: str (truncated error summary)
        """
        stats: dict[str, int | str] = {
            "networks_found": 0,
            "networks_removed": 0,
            "networks_skipped_attached": 0,
            "errors": "",
        }
        errors: list[str] = []

        # Discover networks by Compose project label
        networks = list_networks_by_compose_project(project)
        stats["networks_found"] = len(networks)

        if not networks:
            return stats

        for net_name in networks:
            # Defense-in-depth: skip if doesn't start with octolab_
            if not net_name.startswith("octolab_"):
                logger.debug(f"Skipping non-octolab network {net_name} during cleanup")
                continue

            # Check if network has attached containers
            container_count = get_network_container_count(net_name)

            if container_count == 0:
                # Safe to remove - no containers attached
                try:
                    cmd = ["docker", "network", "rm", net_name]
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=_TIMEOUT_NETWORK_RM,
                        shell=False,
                    )
                    if result.returncode == 0:
                        stats["networks_removed"] = int(stats["networks_removed"]) + 1
                        logger.debug(f"Removed network {net_name} (label-based cleanup)")
                    else:
                        # Check for "not found" (already gone - count as success)
                        stderr_lower = result.stderr.lower()
                        if "not found" in stderr_lower or "no such network" in stderr_lower:
                            stats["networks_removed"] = int(stats["networks_removed"]) + 1
                        else:
                            errors.append(f"{net_name}: {result.stderr.strip()[:50]}")
                except subprocess.TimeoutExpired:
                    errors.append(f"{net_name}: timeout")
                except Exception as e:
                    errors.append(f"{net_name}: {type(e).__name__}")
            elif container_count > 0:
                # Has containers - skip and log
                stats["networks_skipped_attached"] = int(stats["networks_skipped_attached"]) + 1
                logger.debug(
                    f"Network {net_name} has {container_count} containers, "
                    f"skipping removal (will retry after compose down)"
                )
            # container_count == -1 means error inspecting, skip silently

        # Truncate errors for diagnostics
        if errors:
            stats["errors"] = "; ".join(errors)[:500]

        return stats

    def _is_project_owned_container(self, container_name: str, project_name: str) -> bool:
        """Check if container belongs to this compose project.

        Compose v2 naming: <project>-<service>-<replica> (hyphens).
        Our project names use underscores: octolab_<uuid>.
        """
        # Compose v2 converts underscores to hyphens
        normalized_prefix = project_name.replace("_", "-")
        return container_name.startswith(f"{normalized_prefix}-")

    def _compose_rm_sfv(self, project: str) -> None:
        """Run docker compose rm -sfv to forcefully remove project containers.

        Args:
            project: Compose project name

        Note: This is a sync function, run via asyncio.to_thread if needed.
        """
        cmd = [
            "docker", "compose",
            "-f", str(self.compose_path),
            "-p", project,
            "rm", "-sfv",
        ]

        try:
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_COMPOSE_RM,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            logger.debug(f"compose rm -sfv timed out for project {project}")
        except Exception as e:
            logger.debug(f"compose rm -sfv failed for project {project}: {type(e).__name__}")

    def _remove_network_with_retry(self, net_name: str, project: str) -> bool:
        """Remove a lab network with bounded retry for GC race handling.

        Returns True if removed or already gone, False if gave up.
        May raise NetworkCleanupBlockedError when blocked by unknown containers.

        Algorithm:
        1. Attempt docker network rm
        2. If NOT_FOUND or OK: return True (success)
        3. If IN_USE:
           - Inspect containers
           - If project-owned containers: compose rm -sfv, then retry
           - If allowlisted containers: force-disconnect, then retry
           - If unknown containers: raise NetworkCleanupBlockedError
           - If empty containers (GC race): sleep and retry
        4. After max retries: log WARNING once and return False

        Args:
            net_name: Network name to remove
            project: Compose project name

        Returns:
            True if network removed or already gone, False if gave up

        Raises:
            NetworkCleanupBlockedError: If blocked by unknown containers
        """
        from app.services.docker_net import (
            remove_network,
            inspect_network_containers,
            disconnect_container,
            NetworkRemoveResult,
        )

        max_retries = settings.net_rm_max_retries
        backoff_sec = settings.net_rm_backoff_ms / 1000.0
        allowlist_set = set(settings.control_plane_containers)

        # Handle edge case: max_retries = 0 means try at least once
        effective_max = max(max_retries, 1)

        for attempt in range(1, effective_max + 1):
            result = remove_network(net_name, timeout=_TIMEOUT_NETWORK_RM)

            # Success cases
            if result in (NetworkRemoveResult.OK, NetworkRemoveResult.NOT_FOUND):
                return True

            if result == NetworkRemoveResult.IN_USE:
                # Inspect what containers are attached
                containers = inspect_network_containers(net_name, timeout=_TIMEOUT_NETWORK_INSPECT)

                if containers:
                    # Extract container names from the nested dict
                    attached_names = sorted([
                        meta.get("Name", "")
                        for meta in containers.values()
                        if isinstance(meta, dict) and meta.get("Name")
                    ])

                    if attached_names:
                        # Partition containers
                        project_owned = [
                            c for c in attached_names
                            if self._is_project_owned_container(c, project)
                        ]
                        allowlisted = [
                            c for c in attached_names
                            if c in allowlist_set and c not in project_owned
                        ]
                        unknown = [
                            c for c in attached_names
                            if c not in project_owned and c not in allowlist_set
                        ]

                        # Handle project-owned containers first
                        if project_owned:
                            logger.debug(f"Removing project containers for {project}: {project_owned}")
                            self._compose_rm_sfv(project)
                            continue  # Retry after compose rm

                        # Handle allowlisted containers
                        if allowlisted and not unknown:
                            for container in allowlisted:
                                disconnect_container(
                                    net_name,
                                    container,
                                    force=True,
                                    timeout=_TIMEOUT_NETWORK_DISCONNECT,
                                )
                            continue  # Retry after disconnect

                        # Unknown containers block cleanup
                        if unknown:
                            raise NetworkCleanupBlockedError(
                                message=(
                                    f"Cannot remove {net_name}: blocked by containers: {', '.join(unknown)}. "
                                    f"Manual cleanup: docker network disconnect {net_name} <container> "
                                    f"(or add to OCTOLAB_CONTROL_PLANE_CONTAINERS if safe)."
                                ),
                                network_name=net_name,
                                blocking_containers=unknown,
                            )

                # Empty containers but IN_USE => Docker endpoint GC race
                # Wait and retry (except on last attempt)
                if attempt < effective_max:
                    time.sleep(backoff_sec)
                    continue

            # ERROR or max retries exhausted
            break

        # Gave up
        logger.warning(f"Network {net_name} removal gave up after {attempt} attempt(s)")
        return False

    async def create_lab(
        self,
        lab: Lab,
        recipe: Recipe,
        db_session: AsyncSession | None = None,
        vnc_password: str | None = None,
    ) -> None:  # noqa: ARG002
        """
        Create lab with dynamic port allocation for noVNC.

        Args:
            lab: Lab model instance
            recipe: Recipe model instance (unused for compose)
            db_session: Async database session for port allocation
            vnc_password: Per-lab VNC password (required in GUAC mode)

        Raises:
            RuntimeError: If port allocation fails or compose provisioning fails
            NetworkPoolExhaustedError: If Docker has no available subnets
            NetworkCleanupBlockedError: If stale networks can't be cleaned
        """
        if not db_session:
            raise RuntimeError("Database session required for port allocation")

        # SECURITY: Enforce localhost-only guard for passwordless VNC
        # Passwordless VNC (vnc_auth_mode="none") is ONLY allowed when binding to localhost
        vnc_auth_mode = settings.vnc_auth_mode
        if vnc_auth_mode == "none" and not self._is_localhost(settings.compose_bind_host):
            logger.error(
                f"SECURITY: Refusing to spawn lab {lab.id} with passwordless VNC on non-localhost bind "
                f"(compose_bind_host={settings.compose_bind_host})"
            )
            raise RuntimeError(
                "Passwordless VNC (vnc_auth_mode=none) is only allowed when binding to localhost. "
                "Set VNC_AUTH_MODE=password or COMPOSE_BIND_HOST=127.0.0.1"
            )

        # Preflight: Clean up stale empty lab networks to recover address pool space
        # This is strictly scoped (only empty per-lab networks) and never raises
        cleanup_result = await preflight_network_cleanup()
        if cleanup_result.removed_count > 0:
            logger.info(
                f"Preflight cleanup freed {cleanup_result.removed_count} "
                f"empty lab network(s) before creating lab {lab.id}"
            )

        # Allocate a unique port for noVNC access (with tenant isolation)
        novnc_port = await allocate_novnc_port(db_session, lab_id=lab.id, owner_id=lab.owner_id)

        # Prepare environment with port information
        env = os.environ.copy()
        env["LAB_ID"] = str(lab.id)
        env["NOVNC_HOST_PORT"] = str(novnc_port)
        env["COMPOSE_BIND_HOST"] = settings.compose_bind_host
        env["OCTOBOX_VNC_AUTH"] = vnc_auth_mode  # Pass VNC auth mode to container

        # GUAC mode: when guac_enabled, VNC binds to 0.0.0.0 for guacd access
        # This enables guacd to connect to octobox:5900 via lab_net
        guac_enabled = settings.guac_enabled
        env["GUAC_ENABLED"] = "true" if guac_enabled else "false"

        # SECURITY: Always require VNC password for provisioned labs
        # The compose file uses ${VNC_PASSWORD?err} to fail fast if not provided
        if not vnc_password:
            logger.error(
                f"SECURITY: VNC password not provided for lab {lab.id} "
                f"(vnc_password_present=False)"
            )
            raise RuntimeError(
                "VNC password is required for lab provisioning. "
                "Ensure lab_service generates and passes vnc_password to create_lab()."
            )
        # SECURITY: Never log the password value, only log presence
        env["VNC_PASSWORD"] = vnc_password
        logger.debug(f"VNC password injected for lab {lab.id} (vnc_password_present=True)")

        logger.info(
            f"Creating lab {lab.id} with VNC auth mode: {vnc_auth_mode}, "
            f"GUAC mode: {guac_enabled}, vnc_password_present=True"
        )

        project = self._project_name(lab)

        # Dev-only: Force cmdlog rebuild when enabled (server-side setting)
        # This ensures cmdlog script changes are picked up without manual cache busting
        if settings.dev_force_cmdlog_rebuild:
            try:
                await self._run_compose_build_with_cache_bust(project, env)
            except subprocess.TimeoutExpired:
                logger.warning(
                    f"Cmdlog cache-bust build timed out for lab {lab.id}, proceeding with cached image"
                )
            except subprocess.CalledProcessError as e:
                logger.warning(
                    f"Cmdlog cache-bust build failed for lab {lab.id}: {type(e).__name__}, proceeding with cached image"
                )

        # SECURITY: Build secrets list for redaction (never log these values)
        secrets_for_redaction = [vnc_password] if vnc_password else []

        # Attempt to start the compose stack with allocated port
        max_port_retries = 5
        for attempt in range(max_port_retries):
            try:
                await self._run_compose(
                    ["-p", project, "up", "-d"],
                    env=env,
                    secrets_for_redaction=secrets_for_redaction,
                )
                logger.info(f"Lab {lab.id} started successfully with noVNC port {novnc_port}")
                return  # Success

            except ComposeCommandError as e:
                # ComposeCommandError has sanitized stdout/stderr attached
                error_msg = e.stderr or str(e)

                # Check for Docker network pool exhaustion
                if self._is_pool_exhausted_error(error_msg):
                    # Collect network counts for diagnostics
                    net_counts = get_network_counts(timeout=5.0)
                    logger.error(
                        f"Docker network pool exhausted while creating lab {lab.id}. "
                        f"Preflight cleanup freed {cleanup_result.removed_count} network(s) "
                        f"but pool is still exhausted. "
                        f"Network counts: total={net_counts.total_count}, octolab={net_counts.octolab_count}"
                    )
                    if net_counts.hint:
                        logger.error(f"Pool exhaustion hint: {net_counts.hint}")

                    # Clean up port reservation before raising
                    try:
                        await release_novnc_port(db_session, lab_id=lab.id)
                    except Exception:
                        pass

                    raise NetworkPoolExhaustedError(
                        f"Docker has no available subnets for new networks. "
                        f"octolab_networks={net_counts.octolab_count}, total_networks={net_counts.total_count}. "
                        f"Wait for labs to finish or see docs/compose-runtime-ops.md",
                        cleaned_count=cleanup_result.removed_count,
                        blocked_networks=[],
                    )

                error_msg_lower = error_msg.lower()

                # If the port is already allocated (port collision after DB reservation),
                # release the current port and try to allocate a new one
                if "port is already allocated" in error_msg_lower or "address already in use" in error_msg_lower:
                    logger.warning(
                        f"Port {novnc_port} already in use (collision after DB reservation) for lab {lab.id}, "
                        f"attempt {attempt + 1}/{max_port_retries}. Reallocating..."
                    )

                    # Release the currently allocated port
                    await release_novnc_port(db_session, lab_id=lab.id)

                    # Allocate a new port for the next attempt (with tenant isolation)
                    novnc_port = await allocate_novnc_port(db_session, lab_id=lab.id, owner_id=lab.owner_id)

                    # Update environment with new port
                    env["NOVNC_HOST_PORT"] = str(novnc_port)

                    continue  # Retry with new port
                else:
                    # For any other error, collect diagnostics and re-raise
                    try:
                        # Collect diagnostic info before cleanup
                        diagnostics = await asyncio.to_thread(
                            self._collect_compose_diagnostics,
                            project,
                            secrets_for_redaction,
                        )
                        logger.debug(
                            f"Compose diagnostics for failed lab {lab.id}:\n"
                            f"  compose_ps: {diagnostics.get('compose_ps', '(none)')[:500]}\n"
                            f"  compose_config: {diagnostics.get('compose_config', '(none)')[:500]}"
                        )
                    except Exception as diag_error:
                        logger.debug(f"Failed to collect diagnostics: {type(diag_error).__name__}")

                    # Try to clean up with scoped project cleanup
                    try:
                        cleanup_results = await self._cleanup_project(
                            project,
                            secrets=secrets_for_redaction,
                        )
                        logger.debug(f"Cleanup results for failed lab {lab.id}: {cleanup_results}")
                        await release_novnc_port(db_session, lab_id=lab.id)
                    except Exception as cleanup_error:
                        logger.error(f"Failed to cleanup after provisioning failure: {type(cleanup_error).__name__}")

                    # Re-raise with sanitized error message including stderr excerpt
                    stderr_excerpt = (e.stderr[:500] + "...") if e.stderr and len(e.stderr) > 500 else (e.stderr or "")
                    raise RuntimeError(
                        f"Docker compose failed (exit_code={e.exit_code}). stderr: {stderr_excerpt}"
                    ) from e

            except subprocess.TimeoutExpired:
                # Timeout is a separate case - no stderr available
                try:
                    await self._cleanup_project(project, secrets=secrets_for_redaction)
                    await release_novnc_port(db_session, lab_id=lab.id)
                except Exception:
                    pass
                raise RuntimeError("Docker compose timed out")

            except Exception as e:
                # Catch-all for unexpected errors
                error_msg = str(e)
                error_msg_lower = error_msg.lower()

                # Check for port collision even in unexpected error types
                if "port is already allocated" in error_msg_lower or "address already in use" in error_msg_lower:
                    logger.warning(
                        f"Port {novnc_port} already in use for lab {lab.id}, "
                        f"attempt {attempt + 1}/{max_port_retries}. Reallocating..."
                    )
                    await release_novnc_port(db_session, lab_id=lab.id)
                    novnc_port = await allocate_novnc_port(db_session, lab_id=lab.id, owner_id=lab.owner_id)
                    env["NOVNC_HOST_PORT"] = str(novnc_port)
                    continue

                # For any other unexpected error, cleanup and re-raise
                try:
                    await self._cleanup_project(project, secrets=secrets_for_redaction)
                    await release_novnc_port(db_session, lab_id=lab.id)
                except Exception:
                    pass

                logger.error(f"Unexpected error during lab {lab.id} provisioning: {type(e).__name__}")
                raise RuntimeError(f"Docker compose failed: {type(e).__name__}") from e

        # If we exhausted retries due to port conflicts
        raise RuntimeError(
            f"Unable to start lab {lab.id} after {max_port_retries} attempts due to persistent port conflicts"
        )

    async def destroy_lab(self, lab: Lab) -> TeardownResult:
        """
        Destroy lab resources with VERIFIED cleanup and truthful reporting.

        Teardown sequence with verification:
        1. Validate project name (security: only operate on octolab_<uuid>)
        2. docker compose down --remove-orphans (stops containers, removes networks)
        3. VERIFY: Check if containers remain for this project
        4. FALLBACK: If containers remain, force-remove them with docker rm -f
        5. VERIFY: Re-check containers after fallback
        6. Remove networks (if any remain after compose down)
        7. VERIFY: Check if networks remain
        8. Release noVNC port reservation
        9. Return truthful TeardownResult

        SECURITY:
        - Only operates on projects matching octolab_<uuid> pattern
        - Uses label-based filtering for container/network discovery
        - Never runs docker prune or broad cleanup commands
        - All subprocess calls use shell=False with explicit args
        - Logs only project name, lab_id, and counts (no container details beyond 3)

        Args:
            lab: Lab model instance to destroy

        Returns:
            TeardownResult with truthful accounting of what was cleaned up
        """
        project = self._project_name(lab)
        result = TeardownResult(project)

        # SECURITY: Validate project name before any operations
        if not _is_lab_project(project):
            result.errors.append(f"Invalid project name: {project[:50]}")
            logger.error(f"Refusing to teardown invalid project name for lab {lab.id}")
            return result

        # Step 1: Run docker compose down
        try:
            stdout, stderr = await self._run_compose(
                ["-p", project, "down", "--remove-orphans"],
                env=os.environ.copy(),
                suppress_errors=True,
                timeout=_TIMEOUT_COMPOSE_DOWN,
            )
            result.compose_down_ok = True
        except ComposeCommandError as e:
            result.errors.append(f"compose down failed: exit_code={e.exit_code}")
            logger.debug(f"compose down for lab {lab.id} exited with rc={e.exit_code}")
        except Exception as e:
            result.errors.append(f"compose down error: {type(e).__name__}")
            logger.debug(f"compose down for lab {lab.id} failed: {type(e).__name__}")

        # Step 2: VERIFY containers after compose down
        containers = await asyncio.to_thread(_list_project_containers, project, True)
        result.containers_before = len(containers)

        # Step 3: FALLBACK - force-remove remaining containers
        if containers:
            container_ids = [c["id"] for c in containers]
            # Log up to 3 container names for debugging
            container_names = [c["name"] for c in containers[:3]]
            logger.info(
                f"Lab {lab.id} has {len(containers)} remaining container(s) after compose down. "
                f"Force-removing... (first 3: {container_names})"
            )

            removed, rm_errors = await asyncio.to_thread(_rm_containers_force, container_ids)
            result.containers_removed_force = removed
            result.errors.extend(rm_errors)

        # Step 4: VERIFY containers after fallback
        containers_after = await asyncio.to_thread(_list_project_containers, project, True)
        result.containers_remaining = len(containers_after)

        if result.containers_remaining > 0:
            container_names = [c["name"] for c in containers_after[:3]]
            logger.warning(
                f"Lab {lab.id} still has {result.containers_remaining} container(s) after force-remove! "
                f"(first 3: {container_names})"
            )

        # Step 5: Remove networks with retry logic for GC race handling
        # This handles the Docker endpoint cleanup lag (~200-800ms after container removal)
        net_result: NetworkRemovalResult = await asyncio.to_thread(
            remove_compose_project_networks,
            project,
            str(lab.id),
            deadline_secs=8.0,
        )
        result.networks_before = net_result.networks_found
        result.networks_removed = net_result.networks_removed
        result.networks_remaining = net_result.networks_remaining
        result.errors.extend(net_result.last_errors)

        # Log any skipped networks (accurately reports what remains)
        if net_result.networks_skipped:
            for skipped in net_result.networks_skipped:
                if skipped.reason == "in_use" and skipped.containers:
                    result.errors.append(
                        f"network {skipped.name}: blocked by {','.join(skipped.containers[:3])}"
                    )
                elif skipped.reason != "name_not_allowed":
                    result.errors.append(f"network {skipped.name}: {skipped.reason}")

        # Log truthful summary
        logger.info(
            f"Teardown verified for lab {lab.id}: success={result.success}, "
            f"containers_remaining={result.containers_remaining}, "
            f"networks_remaining={result.networks_remaining}, "
            f"force_removed={result.containers_removed_force}"
        )

        # Step 7: Port cleanup (best-effort, non-blocking)
        try:
            from app.db import AsyncSessionLocal

            async with AsyncSessionLocal() as session:
                released = await release_novnc_port(session, lab_id=lab.id)
                if released:
                    logger.debug(f"Released noVNC port reservation for lab {lab.id}")
        except Exception as e:
            result.errors.append(f"port release: {type(e).__name__}")
            logger.warning(f"Failed to release noVNC port for lab {lab.id}: {type(e).__name__}")

        return result

    async def wait_for_healthy(
        self,
        lab: Lab,
        timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 2.0,
    ) -> bool:
        """
        Wait for the octobox container to become healthy.

        Uses Docker inspect to monitor healthcheck transitions and surfaces the
        underlying healthcheck command plus recent log output when failures occur.
        Returns True when healthy, raises TimeoutError if not healthy within timeout.

        Args:
            lab: Lab model instance
            timeout_seconds: Maximum time to wait for healthy status
            poll_interval_seconds: Delay between health checks

        Returns:
            True if container is healthy

        Raises:
            TimeoutError: If container doesn't become healthy within timeout
            RuntimeError: If container is unhealthy (failed healthcheck)
        """
        import time

        project = self._project_name(lab)
        container_name = f"{project}-octobox-1"  # Compose v2 naming convention

        start_time = time.monotonic()
        deadline = start_time + timeout_seconds
        last_status: str | None = None
        last_inspect: dict | None = None
        initial_logged = False

        while time.monotonic() < deadline:
            inspect_data = await self._inspect_container_health(container_name)
            if inspect_data:
                last_inspect = inspect_data

            health_section = (inspect_data or {}).get("State", {}).get("Health") or {}
            status = health_section.get("Status")
            has_healthcheck = bool((inspect_data or {}).get("Config", {}).get("Healthcheck"))

            if not initial_logged:
                healthcheck_state = "yes" if has_healthcheck else ("no" if inspect_data else "unknown")
                logger.debug(
                    f"Waiting for {container_name} health (healthcheck={healthcheck_state})"
                )
                initial_logged = True

            if status and status != last_status:
                logger.debug(f"{container_name} health status -> {status}")
                last_status = status

            if status == "healthy":
                elapsed = time.monotonic() - start_time
                logger.info(
                    f"Container {container_name} is healthy (elapsed {elapsed:.1f}s)"
                )
                return True

            if status == "unhealthy":
                elapsed = time.monotonic() - start_time
                details = self._format_health_details(container_name, inspect_data or last_inspect)
                raise RuntimeError(
                    f"Container {container_name} is unhealthy after {elapsed:.1f}s ({details})"
                )

            await asyncio.sleep(poll_interval_seconds)

        elapsed = time.monotonic() - start_time
        latest = await self._inspect_container_health(container_name)
        details = self._format_health_details(container_name, latest or last_inspect)
        raise TimeoutError(
            f"Container {container_name} not healthy within {timeout_seconds}s (elapsed {elapsed:.1f}s; {details})"
        )

    async def _inspect_container_health(self, container_name: str) -> dict | None:
        """Return docker inspect data for the container (limited to health info)."""
        cmd = ["docker", "inspect", container_name]

        def _inspect() -> dict | None:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=False,
                timeout=5.0,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                return None
            if not payload:
                return None
            first = payload[0]
            return first if isinstance(first, dict) else None

        try:
            return await asyncio.to_thread(_inspect)
        except subprocess.TimeoutExpired:
            return None
        except Exception as exc:
            logger.debug(
                f"Failed to inspect container health for {container_name}: {type(exc).__name__}"
            )
            return None

    def _format_health_details(self, container_name: str, inspect_data: dict | None) -> str:
        """Render healthcheck command and last few log lines for diagnostics."""
        if not inspect_data:
            return "healthcheck=unknown; recent_logs=[]"

        config = inspect_data.get("Config", {}) or {}
        healthcheck_cfg = config.get("Healthcheck") or {}
        test_cmd = healthcheck_cfg.get("Test")
        if isinstance(test_cmd, list):
            cmd_str = " ".join(str(part) for part in test_cmd)
        elif test_cmd is None:
            cmd_str = "None"
        else:
            cmd_str = str(test_cmd)
        cmd_str = truncate_text(redact_text(cmd_str), 300)

        health_section = (inspect_data.get("State", {}) or {}).get("Health") or {}
        logs = health_section.get("Log") or []
        tail = logs[-3:]
        formatted_logs: list[str] = []
        for entry in tail:
            timestamp = ""
            output = ""
            if isinstance(entry, dict):
                timestamp = entry.get("End") or entry.get("Start") or ""
                output = entry.get("Output") or ""
            else:
                output = str(entry)
            output = output.replace("\n", " ").strip()
            output = truncate_text(redact_text(output), 300)
            if timestamp:
                formatted_logs.append(f"{timestamp}: {output}")
            else:
                formatted_logs.append(output)

        logs_repr = "[" + "; ".join(formatted_logs) + "]" if formatted_logs else "[]"
        return f"healthcheck_cmd={cmd_str}; recent_logs={logs_repr}"

    async def resources_exist_for_lab(self, lab: Lab) -> bool:
        """
        Check if Docker Compose resources exist for a lab.

        Uses docker ps -a with name filter to detect containers matching the lab project.
        Short timeout (3s) to prevent blocking during reconciliation.

        Args:
            lab: Lab model instance

        Returns:
            True if any containers exist for this lab's project, False otherwise
        """
        project = self._project_name(lab)

        # Use docker ps -a to check for any containers (running or stopped)
        # Filter by name prefix matching the project name
        cmd = [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"name={project}",
            "--format",
            "{{.ID}}",
        ]

        def _check_containers() -> str:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=False,
                timeout=3.0,
            )
            return result.stdout.strip()

        try:
            container_ids = await asyncio.to_thread(_check_containers)
            exists = bool(container_ids)

            if exists:
                logger.debug(f"Resources exist for lab {lab.id}: found containers")
            else:
                logger.debug(f"No resources found for lab {lab.id}")

            return exists

        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout checking resources for lab {lab.id}; assuming exist")
            return True  # Conservative: assume exist on timeout
        except Exception as e:
            logger.warning(f"Error checking resources for lab {lab.id}: {type(e).__name__}; assuming exist")
            return True  # Conservative: assume exist on error

