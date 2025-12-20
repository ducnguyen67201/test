"""Filesystem utilities with security hardening.

This module provides hardened filesystem operations for cleaning up temp
directories that may contain container-produced files with restrictive
permissions or unusual ownership.

Threat model:
- Container processes may create files owned by root or other UIDs
- Files may have permissions that prevent deletion (0o000, 0o500 dirs)
- Directories may contain symlinks pointing outside the tree
- Best-effort cleanup is preferred over failure

SECURITY:
- Only log basenames, never full paths or file contents
- Never follow symlinks during deletion
- Retry with chmod on PermissionError, but only once
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _on_rm_error_handler(
    func: Callable[..., Any],
    path: str | Path,
    exc_info: Any,
) -> None:
    """
    Error handler for shutil.rmtree (Python < 3.12 style).

    On PermissionError, attempts to chmod the file/dir and retry once.
    Ignores FileNotFoundError (already deleted).
    Logs only at DEBUG level to reduce spam (summary logged by caller).

    Args:
        func: The function that raised the exception
        path: The path being processed
        exc_info: Exception info tuple (type, value, traceback)
    """
    path_obj = Path(path)
    exc_type, exc_value, _ = exc_info

    # Ignore FileNotFoundError - file already gone
    if exc_type is FileNotFoundError:
        return

    # On PermissionError, try to fix permissions and retry once
    if exc_type is PermissionError:
        try:
            # If it's a directory, make it writable/executable
            # If it's a file, make it writable
            current_mode = path_obj.stat().st_mode
            if stat.S_ISDIR(current_mode):
                os.chmod(path, stat.S_IRWXU)  # 0o700
            else:
                os.chmod(path, stat.S_IWUSR | stat.S_IRUSR)  # 0o600

            # Retry the original operation
            func(path)
            return
        except (OSError, PermissionError):
            pass  # Give up, will be logged below

    # Log failure at DEBUG level (reduce spam - caller logs summary)
    logger.debug(
        f"rmtree_hardened: failed to remove '{path_obj.name}' "
        f"({exc_type.__name__})"
    )


def _on_rm_error_handler_py312(
    func: Callable[..., Any],
    path: str | Path,
    exc: BaseException,
) -> None:
    """
    Error handler for shutil.rmtree (Python >= 3.12 style).

    Python 3.12+ uses onexc= instead of onerror=, and passes the
    exception directly instead of exc_info tuple.
    Logs only at DEBUG level to reduce spam (summary logged by caller).

    Args:
        func: The function that raised the exception
        path: The path being processed
        exc: The exception that was raised
    """
    path_obj = Path(path)

    # Ignore FileNotFoundError - file already gone
    if isinstance(exc, FileNotFoundError):
        return

    # On PermissionError, try to fix permissions and retry once
    if isinstance(exc, PermissionError):
        try:
            current_mode = path_obj.stat().st_mode
            if stat.S_ISDIR(current_mode):
                os.chmod(path, stat.S_IRWXU)  # 0o700
            else:
                os.chmod(path, stat.S_IWUSR | stat.S_IRUSR)  # 0o600

            # Retry the original operation
            func(path)
            return
        except (OSError, PermissionError):
            pass  # Give up, will be logged below

    # Log failure at DEBUG level (reduce spam - caller logs summary)
    logger.debug(
        f"rmtree_hardened: failed to remove '{path_obj.name}' "
        f"({type(exc).__name__})"
    )


def rmtree_hardened(path: str | Path) -> None:
    """
    Remove a directory tree with hardening for container-produced files.

    Handles common issues with temp directories containing evidence:
    - Files owned by root or other UIDs
    - Directories with restrictive permissions (0o500, 0o000)
    - Race conditions (files already deleted)

    On permission errors, attempts chmod and single retry.
    Logs only basenames on failure (no path disclosure).

    This function NEVER follows symlinks - uses os.walk with followlinks=False.

    Args:
        path: Directory to remove

    Note:
        This is best-effort. If deletion fails after retry, the error is
        logged but not raised. Callers should not depend on deletion
        succeeding.
    """
    path_obj = Path(path)

    if not path_obj.exists():
        return

    # Python version determines which error handler signature to use
    py_version = sys.version_info[:2]

    try:
        if py_version >= (3, 12):
            # Python 3.12+: use onexc= parameter
            shutil.rmtree(path_obj, onexc=_on_rm_error_handler_py312)
        else:
            # Python < 3.12: use onerror= parameter
            shutil.rmtree(path_obj, onerror=_on_rm_error_handler)
    except Exception as e:
        # Last-resort catch: log and continue
        logger.warning(
            f"rmtree_hardened: unexpected error removing '{path_obj.name}': "
            f"{type(e).__name__}"
        )


def safe_mkdir(path: Path, mode: int = 0o700) -> None:
    """
    Create directory with explicit secure permissions.

    Args:
        path: Directory path to create
        mode: Permissions mode (default: 0o700, owner-only access)
    """
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, mode)


def is_safe_relative_path(path: str | Path) -> bool:
    """
    Check if a path is safe for extraction (no traversal, no absolute).

    Rejects:
    - Absolute paths
    - Paths containing '..'
    - Paths starting with /
    - Paths containing drive letters (Windows)

    Args:
        path: Path to validate

    Returns:
        True if path is safe, False otherwise
    """
    path_str = str(path)

    # Reject absolute paths
    if os.path.isabs(path_str):
        return False

    # Reject Windows drive letters
    if len(path_str) >= 2 and path_str[1] == ":":
        return False

    # Normalize and check for traversal
    normalized = os.path.normpath(path_str)

    # After normalization, check for leading .. or absolute path
    if normalized.startswith("..") or normalized.startswith(os.sep):
        return False

    # Check each component for ..
    parts = Path(normalized).parts
    if ".." in parts:
        return False

    return True


class EvidenceTreeError(Exception):
    """Raised when evidence tree contains unsafe content (e.g., symlinks)."""


def normalize_evidence_tree(root: Path, *, lab_id: str = "") -> None:
    """
    Normalize permissions on a staged evidence tree.

    This is a defense-in-depth measure to ensure files extracted from
    Docker volumes/containers are readable by the backend process.

    Container files may have:
    - Root ownership (uid=0)
    - Restrictive permissions (0o000, 0o200, etc.)
    - Unexpected symlinks

    This function:
    - Walks the tree WITHOUT following symlinks
    - Raises EvidenceTreeError if symlinks are found
    - Best-effort chmod dirs to 0o700, files to 0o600
    - Ignores PermissionError on chmod (may be owned by root)

    SECURITY:
    - Never follows symlinks
    - Raises on symlinks (do not silently skip)
    - Logs only basenames, never full paths
    - Uses lab_id in logs if provided

    Args:
        root: Root directory of evidence tree
        lab_id: Optional lab ID for logging (no secrets)

    Raises:
        EvidenceTreeError: If tree contains symlinks
    """
    root = root.resolve()

    if not root.exists():
        return

    lab_suffix = f" for lab {lab_id}" if lab_id else ""

    # Walk tree without following symlinks
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current_dir = Path(dirpath)

        # Check and chmod the current directory
        try:
            os.chmod(current_dir, 0o700)
        except PermissionError:
            # Best-effort: can't chmod, may be owned by root
            logger.debug(
                f"normalize_evidence_tree: cannot chmod directory '{current_dir.name}'{lab_suffix}"
            )

        # Check each file
        for filename in filenames:
            file_path = current_dir / filename

            # SECURITY: Reject symlinks immediately
            if file_path.is_symlink():
                raise EvidenceTreeError(
                    f"Evidence tree contains symlink: {filename}{lab_suffix}"
                )

            # Best-effort chmod to 0o600
            if file_path.is_file():
                try:
                    os.chmod(file_path, 0o600)
                except PermissionError:
                    # Best-effort: can't chmod, may be owned by root
                    logger.debug(
                        f"normalize_evidence_tree: cannot chmod file '{filename}'{lab_suffix}"
                    )

        # Check subdirectories for symlinks
        for dirname in dirnames:
            dir_path = current_dir / dirname

            # SECURITY: Reject symlinks immediately
            if dir_path.is_symlink():
                raise EvidenceTreeError(
                    f"Evidence tree contains symlink directory: {dirname}{lab_suffix}"
                )


def copy_file_to_zip_streaming(
    zf,
    src_path: Path,
    arcname: str,
    *,
    chunk_size: int = 1024 * 1024,
) -> None:
    """
    Copy a file into a ZipFile using streaming (no full file in RAM).

    This avoids zipfile.ZipFile.write() which may fail on files with
    restrictive permissions or unusual ownership, and avoids loading
    large files entirely into memory.

    SECURITY:
    - Validates src_path is a regular file (not symlink)
    - Uses explicit open/read to control file access
    - Streams in chunks to avoid memory exhaustion

    Args:
        zf: Open ZipFile in write mode
        src_path: Source file path
        arcname: Archive name (path within zip)
        chunk_size: Read/write chunk size (default 1MB)

    Raises:
        ValueError: If src_path is a symlink
        PermissionError: If src_path cannot be read
    """
    # SECURITY: Reject symlinks
    if src_path.is_symlink():
        raise ValueError(f"Cannot add symlink to zip: {src_path.name}")

    if not src_path.is_file():
        raise ValueError(f"Cannot add non-file to zip: {src_path.name}")

    # Use POSIX-style paths in zip for cross-platform compatibility
    arcname_posix = arcname.replace(os.sep, "/")

    # Open explicitly and stream into zip
    with zf.open(arcname_posix, "w") as dest:
        with open(src_path, "rb") as src:
            shutil.copyfileobj(src, dest, length=chunk_size)
