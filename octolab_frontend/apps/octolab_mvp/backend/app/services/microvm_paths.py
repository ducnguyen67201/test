"""Safe path handling utilities for microVM operations.

SECURITY:
- All paths are validated to stay within allowed base directories
- Path traversal attacks (../) are explicitly rejected
- Symlink attacks are caught via resolve()
- No client-provided paths are trusted

This module provides low-level path utilities that work without
importing app.config (safe for use in setup scripts).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, Union


# =============================================================================
# WSL Detection & Jailer Policy
# =============================================================================


def is_wsl() -> bool:
    """Detect if running under WSL.

    Checks multiple indicators:
    - /proc/sys/fs/binfmt_misc/WSLInterop file
    - "microsoft" in /proc/version
    - WSL_INTEROP or WSL_DISTRO_NAME env vars

    Returns:
        True if running under WSL, False otherwise
    """
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

    # Check for WSL env vars
    if os.environ.get("WSL_INTEROP") or os.environ.get("WSL_DISTRO_NAME"):
        return True

    return False


def resolve_use_jailer(
    setting_value: Optional[bool],
    jailer_bin: str = "/usr/local/bin/jailer",
) -> bool:
    """Resolve whether to use jailer based on setting and environment.

    Policy:
    - If setting_value is explicitly True/False, use that
    - If None (auto-detect):
      - On WSL: always False (jailer doesn't work on WSL)
      - On native Linux: True if jailer binary exists and is executable

    Args:
        setting_value: Value of OCTOLAB_MICROVM_USE_JAILER setting (None = auto)
        jailer_bin: Path to jailer binary to check

    Returns:
        True if jailer should be used, False otherwise

    SECURITY: Production deployments should set this to True explicitly.
    WSL cannot run jailer due to missing kernel features.
    """
    # Explicit setting takes precedence
    if setting_value is not None:
        return setting_value

    # Auto-detect mode
    if is_wsl():
        # WSL cannot run jailer - kernel features not available
        return False

    # Native Linux - use jailer if binary exists and is executable
    jailer_path = Path(jailer_bin)
    if jailer_path.exists() and os.access(jailer_path, os.X_OK):
        return True

    return False


class PathContainmentError(Exception):
    """Raised when a path escapes its allowed directory."""

    pass


class PathTraversalError(Exception):
    """Raised when path contains traversal attempts like '..'."""

    pass


# Pattern to detect path traversal attempts
# Matches: "..", "../", "..\", or parts starting with ".."
PATH_TRAVERSAL_PATTERN = re.compile(r"(^|[\\/])\.\.($|[\\/])")


def _contains_traversal(parts: tuple[str, ...]) -> bool:
    """Check if any path parts contain traversal attempts.

    Args:
        parts: Tuple of path component strings

    Returns:
        True if any part is ".." or contains traversal

    SECURITY: Belt-and-suspenders check for path injection.
    """
    for part in parts:
        # Reject ".." as a component
        if part == "..":
            return True
        # Reject embedded traversal like "foo/../bar" passed as single part
        if PATH_TRAVERSAL_PATTERN.search(part):
            return True
        # Reject absolute paths passed as parts
        if os.path.isabs(part):
            return True
    return False


def resolve_under_base(base: Union[str, Path], *parts: str) -> Path:
    """Safely resolve a path under a base directory.

    This function ensures the resulting path:
    1. Has no '..' traversal in any component (explicit check)
    2. Resolves to a path within base_dir (containment check)
    3. Cannot escape via symlinks (resolve() catches this)

    Args:
        base: The base directory (must be absolute or resolvable)
        *parts: Path components to join under base

    Returns:
        Resolved Path that is guaranteed to be under base

    Raises:
        PathTraversalError: If any part contains '..' traversal
        PathContainmentError: If resulting path escapes base
        ValueError: If base is not a directory or doesn't exist

    Example:
        >>> resolve_under_base("/var/lib/octolab", "smoke_12345", "rootfs.ext4")
        PosixPath('/var/lib/octolab/smoke_12345/rootfs.ext4')

        >>> resolve_under_base("/var/lib/octolab", "..", "etc", "passwd")
        PathTraversalError: Path component contains '..' traversal

    SECURITY:
    - Always use this function when constructing paths from any variable input
    - Never trust lab_id, user_id, or any other identifier in paths without validation
    """
    # Check for traversal attempts in parts
    if _contains_traversal(parts):
        # SECURITY: Don't reveal what parts were rejected
        raise PathTraversalError("Path component contains '..' traversal")

    # Resolve base directory
    base_path = Path(base).resolve()

    # Build candidate path
    # We don't resolve yet to preserve path structure for validation
    candidate = base_path
    for part in parts:
        if not part:
            continue
        candidate = candidate / part

    # Resolve the candidate to catch symlink attacks
    # For non-existent paths, resolve the deepest existing parent
    try:
        if candidate.exists():
            resolved = candidate.resolve()
        else:
            # Find deepest existing ancestor and resolve from there
            existing = candidate
            remaining_parts: list[str] = []
            while not existing.exists() and existing != existing.parent:
                remaining_parts.insert(0, existing.name)
                existing = existing.parent

            resolved_parent = existing.resolve()
            resolved = resolved_parent
            for part in remaining_parts:
                resolved = resolved / part
    except OSError as e:
        raise PathContainmentError(f"Path resolution failed: {type(e).__name__}")

    # Containment check: resolved must be under base_path
    try:
        resolved.relative_to(base_path)
    except ValueError:
        raise PathContainmentError("Path escapes base directory containment")

    return resolved


def redact_path(
    path: Union[str, Path],
    base_placeholder: str = "<STATE_DIR>",
    base_dir: Union[str, Path, None] = None,
) -> str:
    """Redact a path for safe logging/display.

    Replaces absolute path prefix with placeholder, showing only
    the relative portion under the base directory.

    Args:
        path: Path to redact
        base_placeholder: Placeholder for base directory (e.g., "<STATE_DIR>")
        base_dir: Base directory to strip (if None, shows only basename)

    Returns:
        Redacted path string safe for logging

    Example:
        >>> redact_path("/var/lib/octolab/microvm/smoke_123", "<STATE_DIR>",
        ...             "/var/lib/octolab/microvm")
        '<STATE_DIR>/smoke_123'

        >>> redact_path("/var/lib/octolab/microvm/smoke_123/rootfs.ext4")
        '.../rootfs.ext4'

    SECURITY:
    - Never expose full absolute paths in logs/API responses
    - Always use this before logging or returning path info
    """
    p = Path(path) if isinstance(path, str) else path

    if base_dir is not None:
        base_path = Path(base_dir).resolve()
        try:
            if p.is_absolute():
                resolved_p = p.resolve() if p.exists() else p
            else:
                resolved_p = p
            rel = resolved_p.relative_to(base_path)
            return f"{base_placeholder}/{rel}"
        except ValueError:
            # Path not under base_dir, show basename only
            pass

    # Fallback: show only basename
    return f".../{p.name}" if p.name else "(path)"


def redact_secret_patterns(text: str) -> str:
    """Redact common secret patterns from text.

    This catches secrets that may have leaked into stderr/logs:
    - PostgreSQL connection strings
    - SECRET_KEY values
    - GUAC passwords
    - Generic tokens

    Args:
        text: Text to redact

    Returns:
        Text with secrets replaced by <REDACTED>

    SECURITY:
    - Call this on all stderr/stdout before logging or returning
    - Add patterns as new secret types are discovered
    """
    # PostgreSQL connection strings (asyncpg and psycopg)
    text = re.sub(
        r"postgresql(\+[a-z]+)?://[^@]+@[^\s]+",
        "postgresql://<REDACTED>",
        text,
        flags=re.IGNORECASE,
    )

    # Generic key=value secrets
    secret_keys = [
        "SECRET_KEY",
        "GUAC_ADMIN_PASSWORD",
        "GUAC_ENC_KEY",
        "DATABASE_URL",
        "INTERNAL_TOKEN",
        "EVIDENCE_HMAC_SECRET",
    ]
    for key in secret_keys:
        # Match KEY=value (stop at whitespace or newline)
        text = re.sub(
            rf"{key}=\S+",
            f"{key}=<REDACTED>",
            text,
            flags=re.IGNORECASE,
        )

    # Token-like patterns (32+ hex chars)
    text = re.sub(r"[0-9a-fA-F]{32,}", "<REDACTED_TOKEN>", text)

    return text


def safe_tail(content: str, max_lines: int = 50, max_chars: int = 4000) -> str:
    """Get the tail of content with size limits.

    Args:
        content: Text content to tail
        max_lines: Maximum number of lines to return
        max_chars: Maximum total characters

    Returns:
        Truncated and redacted tail of content

    SECURITY:
    - Prevents DoS via large log files
    - Applies secret redaction
    """
    # Take last N characters first (fast)
    if len(content) > max_chars:
        content = content[-max_chars:]

    # Split to lines and take tail
    lines = content.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]

    result = "\n".join(lines)

    # Redact secrets
    result = redact_secret_patterns(result)

    return result


# =============================================================================
# Config Excerpt Generation
# =============================================================================


def safe_config_excerpt(config: dict, max_depth: int = 2) -> dict:
    """Create a safe excerpt of Firecracker config for logging.

    Redacts all paths and sensitive values, keeping only structural info.

    Args:
        config: Firecracker config dict
        max_depth: Maximum recursion depth

    Returns:
        Redacted config dict safe for logging

    SECURITY:
    - Replaces all path values with redacted versions
    - Never exposes full filesystem structure
    """
    if max_depth <= 0:
        return {"...": "(truncated)"}

    result = {}
    for key, value in config.items():
        if isinstance(value, dict):
            result[key] = safe_config_excerpt(value, max_depth - 1)
        elif isinstance(value, list):
            # Handle lists (like drives array)
            result[key] = [
                safe_config_excerpt(item, max_depth - 1)
                if isinstance(item, dict)
                else _redact_value(key, item)
                for item in value[:5]  # Cap list length
            ]
        else:
            result[key] = _redact_value(key, value)

    return result


def _redact_value(key: str, value) -> str:
    """Redact a single config value based on key name."""
    # Keys that contain paths
    path_keys = {
        "path_on_host",
        "kernel_image_path",
        "log_path",
        "metrics_path",
        "uds_path",
    }

    if key in path_keys and isinstance(value, str):
        return f".../{Path(value).name}"

    # Keys that contain secrets (shouldn't be in config but just in case)
    secret_keys = {"token", "password", "secret"}
    if any(s in key.lower() for s in secret_keys):
        return "<REDACTED>"

    # Pass through safe values
    if isinstance(value, (int, float, bool)):
        return value

    if isinstance(value, str):
        # Truncate long strings
        if len(value) > 100:
            return value[:100] + "..."
        return value

    return str(type(value).__name__)
