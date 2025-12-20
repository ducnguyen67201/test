"""Safe tar archive extraction with security hardening.

This module provides secure extraction of tar archives that may come from
untrusted sources (containers, user uploads).

THREAT MODEL:
- Tar-slip attacks: Archives with paths like "../../../etc/passwd" that
  escape the destination directory through path traversal
- Permission poisoning: Files with restrictive permissions (0o000) that
  prevent later cleanup, or setuid/setgid bits
- Ownership poisoning: Files owned by root/other UIDs that can't be deleted
  by the extracting user
- Symlink attacks: Symlinks pointing outside dest_dir, potentially to
  sensitive system files
- Hardlink attacks: Hardlinks to files outside the archive
- Device files: Character/block devices, FIFOs that could have security
  implications
- Resource exhaustion: Huge archives or individual files causing disk DoS

SECURITY INVARIANTS:
- NEVER follow or extract symlinks, hardlinks, or device files
- NEVER preserve uid/gid from archive (always use current user)
- NEVER preserve permissions from archive (use 0o700 for dirs, 0o600 for files)
- ALWAYS validate paths are within dest_dir after normalization
- ALWAYS enforce size limits (total archive size, individual file size)
- NEVER use unbounded memory (chunk-based extraction)
"""

from __future__ import annotations

import logging
import os
import tarfile
from pathlib import Path
from typing import BinaryIO

from app.utils.fs import is_safe_relative_path, safe_mkdir

logger = logging.getLogger(__name__)

# Size limits for extraction
DEFAULT_MAX_TOTAL_BYTES = 250 * 1024 * 1024  # 250 MB
DEFAULT_MAX_MEMBER_BYTES = 50 * 1024 * 1024  # 50 MB
COPY_CHUNK_SIZE = 1024 * 1024  # 1 MB chunks for file copying


class UnsafeArchiveError(Exception):
    """Raised when an archive contains unsafe content."""


class ArchiveSizeLimitError(Exception):
    """Raised when archive exceeds size limits."""


def _validate_member(
    member: tarfile.TarInfo,
    dest_dir: Path,
) -> None:
    """
    Validate a tar member for safety.

    Raises UnsafeArchiveError if member is:
    - A symlink, hardlink, device, or FIFO
    - Has path traversal (../, absolute path, drive letters)
    - Resolves outside dest_dir

    Args:
        member: Tar member to validate
        dest_dir: Destination directory (resolved, absolute)

    Raises:
        UnsafeArchiveError: If member is unsafe
    """
    # Reject links and special files
    if member.issym():
        raise UnsafeArchiveError(
            f"Archive contains symlink (blocked): {member.name}"
        )

    if member.islnk():
        raise UnsafeArchiveError(
            f"Archive contains hardlink (blocked): {member.name}"
        )

    if member.isdev():
        raise UnsafeArchiveError(
            f"Archive contains device file (blocked): {member.name}"
        )

    if member.isfifo():
        raise UnsafeArchiveError(
            f"Archive contains FIFO (blocked): {member.name}"
        )

    if member.ischr():
        raise UnsafeArchiveError(
            f"Archive contains character device (blocked): {member.name}"
        )

    if member.isblk():
        raise UnsafeArchiveError(
            f"Archive contains block device (blocked): {member.name}"
        )

    # Validate path safety (no traversal, no absolute)
    if not is_safe_relative_path(member.name):
        raise UnsafeArchiveError(
            f"Archive contains unsafe path (blocked): {member.name}"
        )

    # Double-check: resolve final path and ensure it's under dest_dir
    # This catches edge cases the simple check might miss
    target_path = (dest_dir / member.name).resolve()
    try:
        target_path.relative_to(dest_dir)
    except ValueError:
        raise UnsafeArchiveError(
            f"Archive member escapes destination (blocked): {member.name}"
        )


def _extract_member_safe(
    tf: tarfile.TarFile,
    member: tarfile.TarInfo,
    dest_dir: Path,
    max_member_bytes: int,
    running_total: int,
    max_total_bytes: int,
) -> int:
    """
    Extract a single tar member safely.

    - Creates directories with 0o700
    - Creates files with 0o600
    - Uses chunk-based copying (no unbounded memory)
    - Enforces size limits

    Args:
        tf: Open TarFile
        member: Member to extract
        dest_dir: Destination directory
        max_member_bytes: Max size for this member
        running_total: Current total extracted bytes
        max_total_bytes: Max total bytes allowed

    Returns:
        Number of bytes extracted

    Raises:
        ArchiveSizeLimitError: If size limits exceeded
    """
    target_path = dest_dir / member.name

    if member.isdir():
        safe_mkdir(target_path, mode=0o700)
        return 0

    if member.isfile():
        # Check member size against limit
        if member.size > max_member_bytes:
            raise ArchiveSizeLimitError(
                f"Member '{member.name}' exceeds size limit "
                f"({member.size} > {max_member_bytes} bytes)"
            )

        # Check if adding this would exceed total
        if running_total + member.size > max_total_bytes:
            raise ArchiveSizeLimitError(
                f"Total extraction would exceed limit "
                f"({running_total + member.size} > {max_total_bytes} bytes)"
            )

        # Ensure parent directory exists
        target_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(target_path.parent, 0o700)

        # Extract file in chunks
        extracted_bytes = 0
        src_file: BinaryIO | None = tf.extractfile(member)

        if src_file is None:
            # Not a regular file (shouldn't happen after validation)
            return 0

        try:
            with open(target_path, "wb") as dst:
                while True:
                    chunk = src_file.read(COPY_CHUNK_SIZE)
                    if not chunk:
                        break

                    extracted_bytes += len(chunk)

                    # Double-check size limit during streaming
                    if extracted_bytes > max_member_bytes:
                        raise ArchiveSizeLimitError(
                            f"Member '{member.name}' exceeds size limit during extraction"
                        )

                    if running_total + extracted_bytes > max_total_bytes:
                        raise ArchiveSizeLimitError(
                            f"Total extraction exceeds limit during streaming"
                        )

                    dst.write(chunk)

            # Set secure permissions (overwrite any archive permissions)
            os.chmod(target_path, 0o600)

        finally:
            src_file.close()

        return extracted_bytes

    # Other types (shouldn't reach here after validation)
    return 0


def safe_extract_tarfile_from_path(
    tar_path: Path,
    dest_dir: Path,
    *,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
) -> list[str]:
    """
    Safely extract a tar archive to a directory.

    Opens the tar file and extracts all members with security checks:
    - Validates each member (no links, devices, traversal)
    - Enforces size limits
    - Uses secure permissions (0o700 dirs, 0o600 files)
    - Ignores uid/gid from archive

    Args:
        tar_path: Path to tar file (can be .tar, .tar.gz, .tgz)
        dest_dir: Destination directory (must exist)
        max_total_bytes: Maximum total extracted size (default 250MB)
        max_member_bytes: Maximum single file size (default 50MB)

    Returns:
        List of extracted file paths (relative to dest_dir)

    Raises:
        UnsafeArchiveError: If archive contains unsafe content
        ArchiveSizeLimitError: If size limits exceeded
        FileNotFoundError: If tar_path doesn't exist
        tarfile.TarError: If tar is corrupt or invalid
    """
    dest_dir = dest_dir.resolve()

    if not dest_dir.exists():
        raise FileNotFoundError(f"Destination directory does not exist: {dest_dir}")

    extracted_files: list[str] = []
    total_extracted = 0

    # Detect compression automatically
    with tarfile.open(tar_path, "r:*") as tf:
        for member in tf:
            # Validate member safety
            _validate_member(member, dest_dir)

            # Extract safely
            bytes_extracted = _extract_member_safe(
                tf,
                member,
                dest_dir,
                max_member_bytes,
                total_extracted,
                max_total_bytes,
            )

            total_extracted += bytes_extracted

            if member.isfile():
                extracted_files.append(member.name)

    logger.debug(
        f"Safely extracted {len(extracted_files)} files, "
        f"{total_extracted} bytes from {tar_path.name}"
    )

    return extracted_files


def safe_extract_tarfile_from_fileobj(
    fileobj: BinaryIO,
    dest_dir: Path,
    *,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
    mode: str = "r:*",
) -> list[str]:
    """
    Safely extract a tar archive from a file-like object.

    Same security guarantees as safe_extract_tarfile_from_path but works
    with file objects (e.g., from Docker SDK get_archive).

    Args:
        fileobj: File-like object containing tar data
        dest_dir: Destination directory (must exist)
        max_total_bytes: Maximum total extracted size (default 250MB)
        max_member_bytes: Maximum single file size (default 50MB)
        mode: Tar open mode (default "r:*" for auto-detect compression)

    Returns:
        List of extracted file paths (relative to dest_dir)

    Raises:
        UnsafeArchiveError: If archive contains unsafe content
        ArchiveSizeLimitError: If size limits exceeded
    """
    dest_dir = dest_dir.resolve()

    if not dest_dir.exists():
        raise FileNotFoundError(f"Destination directory does not exist: {dest_dir}")

    extracted_files: list[str] = []
    total_extracted = 0

    with tarfile.open(fileobj=fileobj, mode=mode) as tf:
        for member in tf:
            # Validate member safety
            _validate_member(member, dest_dir)

            # Extract safely
            bytes_extracted = _extract_member_safe(
                tf,
                member,
                dest_dir,
                max_member_bytes,
                total_extracted,
                max_total_bytes,
            )

            total_extracted += bytes_extracted

            if member.isfile():
                extracted_files.append(member.name)

    return extracted_files


def spool_docker_archive(
    stream,
    tmpdir: Path,
    max_bytes: int = 256 * 1024 * 1024,
) -> Path:
    """
    Spool a Docker get_archive stream to disk with size limit.

    Docker SDK's get_archive returns (Generator[bytes], stat_dict).
    This function writes the stream to a temp file with strict size cap.

    Args:
        stream: Generator of bytes chunks from Docker get_archive
        tmpdir: Temp directory to write spool file
        max_bytes: Maximum allowed archive size (default 256MB)

    Returns:
        Path to spooled tar file

    Raises:
        ValueError: If archive exceeds size limit (partial file deleted)
    """
    spool_path = tmpdir / "raw_archive.tar"
    total = 0

    try:
        with open(spool_path, "wb") as f:
            for chunk in stream:
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"Archive exceeds {max_bytes} byte limit")
                f.write(chunk)
    except ValueError:
        # Clean up partial file
        try:
            spool_path.unlink()
        except FileNotFoundError:
            pass
        raise

    return spool_path
