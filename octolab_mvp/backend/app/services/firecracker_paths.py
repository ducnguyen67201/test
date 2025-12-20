"""Safe path handling for Firecracker microVM state directories.

SECURITY:
- All paths are derived from server-owned lab_id, never client input.
- Path traversal attacks are prevented by containment validation.
- Realpath resolution catches symlink attacks.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import UUID

from app.config import settings


class PathContainmentError(Exception):
    """Raised when a path escapes its allowed directory."""

    pass


class InvalidLabIdError(Exception):
    """Raised when a lab ID is invalid or malformed."""

    pass


# Valid lab ID pattern (UUID format)
LAB_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def validate_lab_id(lab_id: UUID | str) -> str:
    """Validate and normalize a lab ID.

    Args:
        lab_id: UUID or string lab ID

    Returns:
        Normalized lowercase string lab ID

    Raises:
        InvalidLabIdError: If lab ID is invalid or malformed

    SECURITY: This prevents path traversal via malformed lab IDs.
    """
    lab_id_str = str(lab_id).lower().strip()

    if not LAB_ID_PATTERN.match(lab_id_str):
        raise InvalidLabIdError(
            f"Invalid lab ID format: expected UUID, got invalid pattern"
        )

    return lab_id_str


def get_state_dir() -> Path:
    """Get the microVM state directory root.

    Returns:
        Path to state directory

    SECURITY: This is a server-configured directory.
    """
    return Path(settings.microvm_state_dir)


def lab_state_dir(lab_id: UUID | str) -> Path:
    """Get the state directory for a specific lab.

    Args:
        lab_id: Server-owned lab ID (UUID)

    Returns:
        Path to lab's state directory

    Raises:
        InvalidLabIdError: If lab ID is invalid
        PathContainmentError: If resulting path escapes state directory

    SECURITY: Enforces:
    1. Lab ID format validation (prevents injection)
    2. Deterministic naming (no client input)
    3. Containment check (prevents traversal)
    """
    # Validate and normalize lab ID
    safe_lab_id = validate_lab_id(lab_id)

    # Get state root and resolve it
    state_root = get_state_dir().resolve()

    # Build lab directory path
    lab_dir = state_root / f"lab_{safe_lab_id}"

    # Resolve the lab directory (catches symlink attacks)
    # Note: For non-existent paths, we check the parent
    if lab_dir.exists():
        resolved_lab_dir = lab_dir.resolve()
    else:
        # For new directories, ensure parent is resolvable
        resolved_lab_dir = lab_dir.parent.resolve() / lab_dir.name

    # Containment check: lab dir must be under state root
    try:
        resolved_lab_dir.relative_to(state_root)
    except ValueError:
        raise PathContainmentError(
            f"Lab state directory escapes containment: lab_id ends in ...{safe_lab_id[-6:]}"
        )

    return resolved_lab_dir


def lab_socket_path(lab_id: UUID | str) -> Path:
    """Get the Firecracker API socket path for a lab.

    Args:
        lab_id: Server-owned lab ID

    Returns:
        Path to the API socket

    Raises:
        InvalidLabIdError: If lab ID is invalid
        PathContainmentError: If path escapes containment
    """
    return lab_state_dir(lab_id) / "firecracker.sock"


def lab_rootfs_path(lab_id: UUID | str) -> Path:
    """Get the per-lab rootfs path (copy or overlay).

    Args:
        lab_id: Server-owned lab ID

    Returns:
        Path to lab's rootfs image

    Raises:
        InvalidLabIdError: If lab ID is invalid
        PathContainmentError: If path escapes containment
    """
    return lab_state_dir(lab_id) / "rootfs.ext4"


def lab_log_path(lab_id: UUID | str) -> Path:
    """Get the Firecracker log path for a lab.

    Args:
        lab_id: Server-owned lab ID

    Returns:
        Path to log file

    Raises:
        InvalidLabIdError: If lab ID is invalid
        PathContainmentError: If path escapes containment
    """
    return lab_state_dir(lab_id) / "firecracker.log"


def lab_metrics_path(lab_id: UUID | str) -> Path:
    """Get the Firecracker metrics path for a lab.

    Args:
        lab_id: Server-owned lab ID

    Returns:
        Path to metrics file

    Raises:
        InvalidLabIdError: If lab ID is invalid
        PathContainmentError: If path escapes containment
    """
    return lab_state_dir(lab_id) / "firecracker.metrics"


def lab_token_path(lab_id: UUID | str) -> Path:
    """Get the path to store the per-lab auth token.

    Args:
        lab_id: Server-owned lab ID

    Returns:
        Path to token file (should be chmod 0600)

    Raises:
        InvalidLabIdError: If lab ID is invalid
        PathContainmentError: If path escapes containment

    SECURITY: Token file must have restrictive permissions (0600).
    """
    return lab_state_dir(lab_id) / ".token"


def lab_pid_path(lab_id: UUID | str) -> Path:
    """Get the path to store the Firecracker process ID.

    Args:
        lab_id: Server-owned lab ID

    Returns:
        Path to PID file

    Raises:
        InvalidLabIdError: If lab ID is invalid
        PathContainmentError: If path escapes containment
    """
    return lab_state_dir(lab_id) / "firecracker.pid"


def ensure_lab_state_dir(lab_id: UUID | str) -> Path:
    """Create the lab state directory if it doesn't exist.

    Args:
        lab_id: Server-owned lab ID

    Returns:
        Path to created/existing lab state directory

    Raises:
        InvalidLabIdError: If lab ID is invalid
        PathContainmentError: If path escapes containment
        OSError: If directory creation fails
    """
    lab_dir = lab_state_dir(lab_id)

    # Ensure parent state directory exists
    state_root = get_state_dir()
    state_root.mkdir(parents=True, exist_ok=True)

    # Create lab directory with restrictive permissions
    lab_dir.mkdir(mode=0o700, exist_ok=True)

    return lab_dir


def cleanup_lab_state_dir(lab_id: UUID | str) -> bool:
    """Remove the lab state directory and all contents.

    Args:
        lab_id: Server-owned lab ID

    Returns:
        True if directory was removed, False if it didn't exist

    Raises:
        InvalidLabIdError: If lab ID is invalid
        PathContainmentError: If path escapes containment
        OSError: If removal fails
    """
    import shutil

    lab_dir = lab_state_dir(lab_id)

    if not lab_dir.exists():
        return False

    # Final containment check before deletion
    state_root = get_state_dir().resolve()
    try:
        lab_dir.resolve().relative_to(state_root)
    except ValueError:
        raise PathContainmentError(
            f"Refusing to delete directory outside containment"
        )

    shutil.rmtree(lab_dir)
    return True


def redact_path(path: Path | str) -> str:
    """Redact a path for safe logging.

    Shows only the basename and whether it exists, never the full path.

    Args:
        path: Path to redact

    Returns:
        Redacted path string safe for logging
    """
    p = Path(path) if isinstance(path, str) else path

    try:
        exists = p.exists()
    except OSError:
        exists = False

    basename = p.name if p.name else "(root)"
    status = "exists" if exists else "missing"

    return f".../{basename} ({status})"
