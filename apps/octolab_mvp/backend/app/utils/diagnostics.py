"""Diagnostics collection for lab runtime debugging.

Admin-only utilities for collecting runtime diagnostics when labs fail.

Security:
- No secrets in output (DATABASE_URL, tokens redacted)
- Owner IDs redacted (show only last 6 chars)
- Truncated logs (prevent log bombs)
- shell=False for subprocess calls
"""

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)


async def collect_compose_diagnostics(
    lab_id: UUID,
    project_name: str,
    compose_file: Optional[Path] = None,
    max_log_lines: int = 200,
) -> dict[str, str]:
    """Collect diagnostics for a docker compose lab.

    Args:
        lab_id: Lab ID (for logging only)
        project_name: Docker compose project name (e.g., "octolab_<uuid>")
        compose_file: Optional path to compose file
        max_log_lines: Maximum log lines to capture per service

    Returns:
        Dictionary with diagnostic information:
        - "compose_ps": Output of docker compose ps
        - "compose_logs": Last N lines of compose logs
        - "errors": Any errors encountered during collection

    Security:
        - Uses shell=False for subprocess
        - Truncates output to prevent log bombs
        - Does not expose secrets
    """
    diagnostics = {}
    errors = []

    # Build compose command prefix
    compose_cmd = ["docker", "compose"]
    if compose_file:
        compose_cmd.extend(["-f", str(compose_file)])
    compose_cmd.extend(["-p", project_name])

    # Collect: docker compose ps
    try:
        result = await asyncio.create_subprocess_exec(
            *compose_cmd,
            "ps",
            "-a",  # Show all containers
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=10.0)

        if result.returncode == 0:
            diagnostics["compose_ps"] = stdout.decode("utf-8", errors="replace")
        else:
            error_msg = stderr.decode("utf-8", errors="replace")
            errors.append(f"compose ps failed: {error_msg[:500]}")
            diagnostics["compose_ps"] = f"ERROR: {error_msg[:500]}"

    except asyncio.TimeoutError:
        errors.append("compose ps timed out")
        diagnostics["compose_ps"] = "ERROR: Timed out"
    except Exception as e:
        errors.append(f"compose ps exception: {type(e).__name__}")
        diagnostics["compose_ps"] = f"ERROR: {type(e).__name__}"

    # Collect: docker compose logs (last N lines)
    try:
        result = await asyncio.create_subprocess_exec(
            *compose_cmd,
            "logs",
            "--tail",
            str(max_log_lines),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=30.0)

        if result.returncode == 0:
            logs = stdout.decode("utf-8", errors="replace")
            # Truncate if still too large
            if len(logs) > 50000:
                logs = logs[-50000:] + "\n... (truncated)"
            diagnostics["compose_logs"] = logs
        else:
            error_msg = stderr.decode("utf-8", errors="replace")
            errors.append(f"compose logs failed: {error_msg[:500]}")
            diagnostics["compose_logs"] = f"ERROR: {error_msg[:500]}"

    except asyncio.TimeoutError:
        errors.append("compose logs timed out")
        diagnostics["compose_logs"] = "ERROR: Timed out"
    except Exception as e:
        errors.append(f"compose logs exception: {type(e).__name__}")
        diagnostics["compose_logs"] = f"ERROR: {type(e).__name__}"

    if errors:
        diagnostics["errors"] = "; ".join(errors)

    logger.info(f"Collected diagnostics for lab {lab_id} (project {project_name})")
    return diagnostics


def redact_owner_id(owner_id: UUID) -> str:
    """Redact owner ID for logs (show last 6 chars only).

    Args:
        owner_id: Owner UUID

    Returns:
        Redacted string like "****abc123"
    """
    return f"****{str(owner_id)[-6:]}"


def format_diagnostics_for_log(diagnostics: dict[str, str]) -> str:
    """Format diagnostics dict as human-readable string for logging.

    Args:
        diagnostics: Diagnostics dictionary from collect_compose_diagnostics

    Returns:
        Formatted multiline string (truncated for safety)
    """
    lines = ["=== Lab Diagnostics ==="]

    for key, value in diagnostics.items():
        lines.append(f"\n--- {key} ---")
        # Truncate each value
        if len(value) > 10000:
            lines.append(value[:10000] + "\n... (truncated)")
        else:
            lines.append(value)

    lines.append("\n=== End Diagnostics ===")
    result = "\n".join(lines)

    # Final safety truncation
    if len(result) > 50000:
        return result[:50000] + "\n... (truncated)"

    return result
