"""Authoritative evidence sealing and verification service.

This module provides tamper-evident sealing of authoritative evidence:
- Generates manifest with SHA256 hashes of all evidence files
- Signs manifest with HMAC-SHA256 using backend-held secret
- Verifies seal before serving as "authoritative"

SECURITY INVARIANTS:
- OctoBox NEVER has access to authoritative evidence volume (enforced by compose)
- Only gateway and backend can write to auth volume
- HMAC secret is backend-only, never exposed to containers
- Lab IDs are always server-owned (never from client)
- Never preserve container uid/gid/mode when extracting
- Never follow symlinks when building ZIP bundles
- Use hardened rmtree for temp directory cleanup
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import io
import json
import logging
import os
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import settings
from app.models.lab import Lab, EvidenceSealStatus
from app.utils.fs import (
    copy_file_to_zip_streaming,
    normalize_evidence_tree,
    rmtree_hardened,
    safe_mkdir,
    EvidenceTreeError,
)
from app.utils.safe_extract import (
    UnsafeArchiveError,
    safe_extract_tarfile_from_path,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Timeout for docker operations
DOCKER_TIMEOUT = 30


class EvidenceSealError(Exception):
    """Raised when evidence sealing fails."""


class EvidenceVerificationError(Exception):
    """Raised when evidence verification fails."""


class EvidenceNotSealedError(Exception):
    """Raised when trying to access unsealed evidence."""


def _get_hmac_secret() -> bytes:
    """
    Get the HMAC secret for signing evidence.

    SECURITY: This secret is backend-only and MUST never be logged or exposed.

    Returns:
        HMAC secret bytes

    Raises:
        EvidenceSealError: If secret is not configured
    """
    secret = settings.evidence_hmac_secret
    if not secret:
        # In development, use a placeholder but warn
        if settings.log_level.upper() == "DEBUG":
            logger.warning("EVIDENCE_HMAC_SECRET not set - using insecure placeholder for dev")
            return b"dev-only-insecure-placeholder"
        raise EvidenceSealError(
            "EVIDENCE_HMAC_SECRET not configured - required for production"
        )
    # SECURITY: SecretStr requires .get_secret_value() to access the value
    return secret.get_secret_value().encode("utf-8")


def _canonical_json(obj: dict) -> bytes:
    """
    Generate canonical JSON bytes for deterministic hashing.

    Uses sorted keys and no extra whitespace for reproducibility.

    Args:
        obj: Dictionary to serialize

    Returns:
        Canonical JSON bytes (UTF-8 encoded)
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _compute_hmac(secret: bytes, data: bytes) -> str:
    """
    Compute HMAC-SHA256 signature and return as base64.

    Args:
        secret: HMAC secret bytes
        data: Data to sign

    Returns:
        Base64-encoded signature string
    """
    sig = hmac.new(secret, data, hashlib.sha256).digest()
    return base64.b64encode(sig).decode("ascii")


def _verify_hmac(secret: bytes, data: bytes, signature: str) -> bool:
    """
    Verify HMAC-SHA256 signature.

    Args:
        secret: HMAC secret bytes
        data: Original data
        signature: Base64-encoded signature to verify

    Returns:
        True if signature is valid, False otherwise
    """
    try:
        expected = hmac.new(secret, data, hashlib.sha256).digest()
        provided = base64.b64decode(signature)
        return hmac.compare_digest(expected, provided)
    except Exception:
        return False


def _compute_file_hash(file_path: Path) -> str:
    """
    Compute SHA256 hash of a file.

    Args:
        file_path: Path to file

    Returns:
        Hex-encoded SHA256 hash
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def get_evidence_volume_names(lab: Lab) -> tuple[str, str]:
    """
    Get deterministic volume names for a lab.

    Volume names are derived from lab.id only (server-owned).
    NEVER use client-supplied identifiers.

    Args:
        lab: Lab model instance

    Returns:
        Tuple of (auth_volume_name, user_volume_name)
    """
    project_name = f"octolab_{lab.id}"
    auth_vol = f"{project_name}_evidence_auth"
    user_vol = f"{project_name}_evidence_user"
    return auth_vol, user_vol


async def export_compose_logs_to_auth_volume(
    lab: Lab,
    compose_path: Path | None = None,
) -> bool:
    """
    Export docker compose logs to authoritative evidence volume.

    Runs `docker compose logs` and writes output to auth volume via helper container.
    This is authoritative evidence that OctoBox cannot modify.

    Args:
        lab: Lab model instance
        compose_path: Path to compose file (optional)

    Returns:
        True if logs were exported successfully, False otherwise
    """
    project_name = f"octolab_{lab.id}"
    auth_vol, _ = get_evidence_volume_names(lab)

    # Build docker compose logs command
    compose_args = ["docker", "compose", "-p", project_name]
    if compose_path:
        compose_args.extend(["-f", str(compose_path)])
    compose_args.extend(["logs", "--no-color", "--timestamps"])

    def _export_logs() -> bool:
        try:
            # Get logs from compose
            result = subprocess.run(
                compose_args,
                capture_output=True,
                text=True,
                timeout=settings.evidence_export_timeout_seconds,
                shell=False,
            )
            logs_content = result.stdout or ""
            if result.stderr:
                logs_content += f"\n--- STDERR ---\n{result.stderr}"

            if not logs_content.strip():
                logger.warning(f"No compose logs available for lab {lab.id}")
                return False

            # Create temp file with logs
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".log",
                delete=False,
            ) as tmp:
                tmp.write(logs_content)
                tmp_path = tmp.name

            try:
                # Write to auth volume via helper container
                # shell=False, explicit args
                write_cmd = [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{auth_vol}:/evidence/auth",
                    "-v",
                    f"{tmp_path}:/input.log:ro",
                    "alpine",
                    "sh",
                    "-c",
                    "mkdir -p /evidence/auth/logs && cp /input.log /evidence/auth/logs/compose.log",
                ]
                subprocess.run(
                    write_cmd,
                    check=True,
                    capture_output=True,
                    timeout=DOCKER_TIMEOUT,
                    shell=False,
                )
                return True
            finally:
                os.unlink(tmp_path)

        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout exporting logs for lab {lab.id}")
            return False
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to export logs for lab {lab.id}: {type(e).__name__}")
            return False
        except Exception as e:
            logger.warning(f"Error exporting logs for lab {lab.id}: {type(e).__name__}")
            return False

    return await asyncio.to_thread(_export_logs)


async def _extract_auth_volume_to_dir(
    volume_name: str,
    dest_dir: Path,
) -> list[str]:
    """
    Extract authoritative evidence volume to local directory.

    Uses tar streaming: container creates tar to stdout, host extracts with
    correct ownership. This avoids root-owned files on the host.

    SECURITY:
    - Container runs as root to read volume files (may have various perms)
    - Tar is streamed to host and extracted with safe_extract (host user ownership)
    - Does NOT preserve uid/gid from container (extracts as current user)
    - Sets secure permissions: directories 0o700, files 0o600
    - Does not follow symlinks (rejects them during extraction)

    Args:
        volume_name: Docker volume name
        dest_dir: Local destination directory

    Returns:
        List of relative file paths extracted
    """
    target_dir = dest_dir / "auth"
    safe_mkdir(target_dir, mode=0o700)

    # Create tar from volume contents and stream to stdout
    # Container runs as root to read any files in the volume
    # We extract on host side with correct user ownership
    # BUG FIX: Previous implementation used bidirectional bind mount which
    # created root-owned files on host. Now we use tar streaming.
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{volume_name}:/src:ro",
        "alpine",
        "sh",
        "-c",
        # Create tar of regular files only (no symlinks, devices)
        "cd /src && find . -type f -print0 | tar -cf - --null -T - 2>/dev/null || true",
    ]

    def _stream_tar() -> bytes | None:
        """Run docker and capture tar stream."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=DOCKER_TIMEOUT * 2,  # Longer timeout for tar
                shell=False,
            )
            # Return stdout (tar data) even if returncode is non-zero
            return result.stdout if result.stdout else None
        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout extracting auth volume {volume_name}")
            return None
        except Exception as e:
            logger.warning(f"Error extracting auth volume {volume_name}: {type(e).__name__}")
            return None

    tar_data = await asyncio.to_thread(_stream_tar)

    if not tar_data:
        # Empty volume or error - return empty list
        return []

    # Spool tar to disk
    spool_path = dest_dir / "auth_raw.tar"
    try:
        spool_path.write_bytes(tar_data)

        # Extract using safe_extract (ignores tar uid/gid, sets 0o600/0o700)
        try:
            extracted = safe_extract_tarfile_from_path(
                spool_path,
                target_dir,
                max_total_bytes=500 * 1024 * 1024,  # 500MB
                max_member_bytes=200 * 1024 * 1024,  # 200MB per file
            )
        except UnsafeArchiveError as e:
            logger.warning(f"Unsafe content in auth volume {volume_name}: {e}")
            return []
        except Exception as e:
            logger.warning(f"Error extracting tar from auth volume {volume_name}: {type(e).__name__}")
            return []
    finally:
        # Clean up spool file
        try:
            spool_path.unlink()
        except FileNotFoundError:
            pass

    # Return paths relative to dest_dir (include "auth/" prefix)
    return [f"auth/{f}" for f in extracted]


async def seal_auth_evidence(
    lab: Lab,
    session: "AsyncSession",
) -> bool:
    """
    Seal authoritative evidence with HMAC signature.

    Creates manifest.json with file hashes and manifest.sig with HMAC signature.
    Updates lab model with seal status.

    Args:
        lab: Lab model instance
        session: Database session for updating lab

    Returns:
        True if sealed successfully, False otherwise
    """
    auth_vol, _ = get_evidence_volume_names(lab)

    try:
        secret = _get_hmac_secret()
    except EvidenceSealError as e:
        logger.error(f"Cannot seal evidence for lab {lab.id}: {e}")
        lab.evidence_seal_status = EvidenceSealStatus.FAILED.value
        await session.commit()
        return False

    # Create temp directory for extraction
    temp_dir = Path(tempfile.mkdtemp(prefix="octolab-evidence-"))

    try:
        safe_mkdir(temp_dir, mode=0o700)

        # Extract auth volume contents
        files = await _extract_auth_volume_to_dir(auth_vol, temp_dir)

        if not files:
            logger.warning(f"No authoritative evidence files for lab {lab.id}")
            lab.evidence_seal_status = EvidenceSealStatus.FAILED.value
            await session.commit()
            return False

        # Compute hashes for all files (skip symlinks)
        file_hashes = {}
        for rel_path in sorted(files):
            full_path = temp_dir / rel_path
            if full_path.is_symlink():
                continue
            if full_path.is_file() and not rel_path.endswith(("manifest.json", "manifest.sig")):
                file_hashes[rel_path] = _compute_file_hash(full_path)

        # Create manifest
        manifest = {
            "lab_id": str(lab.id),
            "sealed_at": datetime.now(timezone.utc).isoformat(),
            "evidence_version": "4.0",
            "seal_version": 1,
            "files": file_hashes,
        }

        # Compute canonical form and signature
        canonical_bytes = _canonical_json(manifest)
        signature = _compute_hmac(secret, canonical_bytes)
        manifest_sha256 = hashlib.sha256(canonical_bytes).hexdigest()

        # Write manifest and signature to temp files
        manifest_path = temp_dir / "manifest.json"
        sig_path = temp_dir / "manifest.sig"
        manifest_path.write_text(json.dumps(manifest, indent=2))
        os.chmod(manifest_path, 0o600)
        sig_path.write_text(signature)
        os.chmod(sig_path, 0o600)

        # Copy manifest and sig to auth volume via helper container
        def _write_seal_files() -> None:
            cmd = [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{auth_vol}:/evidence/auth",
                "-v",
                f"{manifest_path}:/manifest.json:ro",
                "-v",
                f"{sig_path}:/manifest.sig:ro",
                "alpine",
                "sh",
                "-c",
                "cp /manifest.json /evidence/auth/manifest.json && cp /manifest.sig /evidence/auth/manifest.sig",
            ]
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                timeout=DOCKER_TIMEOUT,
                shell=False,
            )

        await asyncio.to_thread(_write_seal_files)

        # Update lab model
        lab.evidence_seal_status = EvidenceSealStatus.SEALED.value
        lab.evidence_sealed_at = datetime.now(timezone.utc)
        lab.evidence_manifest_sha256 = manifest_sha256
        lab.evidence_auth_volume = auth_vol
        await session.commit()

        logger.info(f"Sealed evidence for lab {lab.id} with {len(file_hashes)} files")
        return True

    except Exception as e:
        logger.error(f"Failed to seal evidence for lab {lab.id}: {type(e).__name__}")
        lab.evidence_seal_status = EvidenceSealStatus.FAILED.value
        await session.commit()
        return False
    finally:
        # Cleanup temp directory using hardened rmtree
        rmtree_hardened(temp_dir)


async def verify_auth_evidence(lab: Lab) -> tuple[bool, str]:
    """
    Verify authoritative evidence seal.

    Reads manifest and signature from auth volume, verifies HMAC,
    and checks that all listed files exist with correct hashes.

    Args:
        lab: Lab model instance

    Returns:
        Tuple of (is_valid, reason)
    """
    auth_vol, _ = get_evidence_volume_names(lab)

    try:
        secret = _get_hmac_secret()
    except EvidenceSealError as e:
        return False, f"HMAC secret not configured: {e}"

    # Create temp directory for verification
    temp_dir = Path(tempfile.mkdtemp(prefix="octolab-evidence-"))

    try:
        safe_mkdir(temp_dir, mode=0o700)

        # Extract auth volume
        await _extract_auth_volume_to_dir(auth_vol, temp_dir)

        auth_dir = temp_dir / "auth"
        manifest_path = auth_dir / "manifest.json"
        sig_path = auth_dir / "manifest.sig"

        if not manifest_path.exists():
            return False, "manifest.json not found"

        if not sig_path.exists():
            return False, "manifest.sig not found"

        # Read and parse manifest
        manifest_text = manifest_path.read_text()
        try:
            manifest = json.loads(manifest_text)
        except json.JSONDecodeError:
            return False, "manifest.json is not valid JSON"

        # Verify signature
        # Re-canonicalize for verification (don't use stored text directly)
        canonical_bytes = _canonical_json(manifest)
        signature = sig_path.read_text().strip()

        if not _verify_hmac(secret, canonical_bytes, signature):
            return False, "HMAC signature verification failed"

        # Verify all files exist and match hashes
        file_hashes = manifest.get("files", {})
        for rel_path, expected_hash in file_hashes.items():
            full_path = temp_dir / rel_path
            if not full_path.exists():
                return False, f"File missing: {rel_path}"

            # Skip symlinks
            if full_path.is_symlink():
                return False, f"Unexpected symlink: {rel_path}"

            actual_hash = _compute_file_hash(full_path)
            if actual_hash != expected_hash:
                return False, f"Hash mismatch for {rel_path}"

        return True, "Verification successful"

    except Exception as e:
        return False, f"Verification error: {type(e).__name__}"
    finally:
        # Cleanup using hardened rmtree
        rmtree_hardened(temp_dir)


async def _extract_user_volume_to_dir(
    volume_name: str,
    dest_dir: Path,
) -> list[str]:
    """
    Extract user evidence volume to local directory.

    Uses tar streaming: container creates tar to stdout, host extracts with
    correct ownership. This avoids root-owned files on the host.

    SECURITY:
    - Container runs as root to read volume files (may have various perms)
    - Tar is streamed to host and extracted with safe_extract (host user ownership)
    - Does NOT preserve uid/gid from container (extracts as current user)
    - Sets secure permissions: directories 0o700, files 0o600
    - Does not follow symlinks (rejects them during extraction)

    Args:
        volume_name: Docker volume name
        dest_dir: Local destination directory

    Returns:
        List of relative file paths extracted
    """
    target_dir = dest_dir / "untrusted"
    safe_mkdir(target_dir, mode=0o700)

    # Create tar from volume contents and stream to stdout
    # Container runs as root to read any files in the volume
    # We extract on host side with correct user ownership
    # BUG FIX: Previous implementation used bidirectional bind mount which
    # created root-owned files on host. Now we use tar streaming.
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{volume_name}:/src:ro",
        "alpine",
        "sh",
        "-c",
        # Create tar of regular files only (no symlinks, devices)
        "cd /src && find . -type f -print0 | tar -cf - --null -T - 2>/dev/null || true",
    ]

    def _stream_tar() -> bytes | None:
        """Run docker and capture tar stream."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=DOCKER_TIMEOUT * 2,  # Longer timeout for tar
                shell=False,
            )
            # Return stdout (tar data) even if returncode is non-zero
            return result.stdout if result.stdout else None
        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout extracting user volume {volume_name}")
            return None
        except Exception as e:
            logger.warning(f"Error extracting user volume {volume_name}: {type(e).__name__}")
            return None

    tar_data = await asyncio.to_thread(_stream_tar)

    if not tar_data:
        # Empty volume or error - return empty list
        return []

    # Spool tar to disk
    spool_path = dest_dir / "untrusted_raw.tar"
    try:
        spool_path.write_bytes(tar_data)

        # Extract using safe_extract (ignores tar uid/gid, sets 0o600/0o700)
        try:
            extracted = safe_extract_tarfile_from_path(
                spool_path,
                target_dir,
                max_total_bytes=500 * 1024 * 1024,  # 500MB
                max_member_bytes=200 * 1024 * 1024,  # 200MB per file
            )
        except UnsafeArchiveError as e:
            logger.warning(f"Unsafe content in user volume {volume_name}: {e}")
            return []
        except Exception as e:
            logger.warning(f"Error extracting tar from user volume {volume_name}: {type(e).__name__}")
            return []
    finally:
        # Clean up spool file
        try:
            spool_path.unlink()
        except FileNotFoundError:
            pass

    # Return paths relative to dest_dir (include "untrusted/" prefix)
    return [f"untrusted/{f}" for f in extracted]


async def build_verified_evidence_bundle(
    lab: Lab,
    include_untrusted: bool = True,
) -> bytes:
    """
    Build verified evidence bundle ZIP.

    Only builds bundle if evidence is sealed and verification passes.

    SECURITY:
    - Does NOT follow symlinks when building ZIP
    - Uses hardened rmtree for temp directory cleanup
    - Only includes regular files

    Args:
        lab: Lab model instance
        include_untrusted: Whether to include user evidence under untrusted/ folder

    Returns:
        ZIP file contents as bytes

    Raises:
        EvidenceNotSealedError: If evidence is not sealed
        EvidenceVerificationError: If seal verification fails
    """
    # Check seal status
    if lab.evidence_seal_status != EvidenceSealStatus.SEALED.value:
        raise EvidenceNotSealedError(
            f"Evidence not sealed for lab {lab.id} (status: {lab.evidence_seal_status})"
        )

    # Verify seal
    is_valid, reason = await verify_auth_evidence(lab)
    if not is_valid:
        raise EvidenceVerificationError(f"Verification failed: {reason}")

    auth_vol, user_vol = get_evidence_volume_names(lab)

    # Create temp directory for bundle
    temp_dir = Path(tempfile.mkdtemp(prefix="octolab-evidence-"))

    try:
        safe_mkdir(temp_dir, mode=0o700)

        # Extract auth volume (authoritative evidence)
        auth_files = await _extract_auth_volume_to_dir(auth_vol, temp_dir)

        # Optionally extract user volume (untrusted evidence)
        user_files = []
        if include_untrusted:
            user_files = await _extract_user_volume_to_dir(user_vol, temp_dir)

        all_files = auth_files + user_files

        if not all_files:
            raise EvidenceVerificationError(f"No evidence files found for lab {lab.id}")

        # DEFENSE-IN-DEPTH: Normalize permissions on staged tree
        # This handles container files with restrictive perms (should not happen with
        # tar streaming, but provides extra safety)
        try:
            normalize_evidence_tree(temp_dir, lab_id=str(lab.id))
        except EvidenceTreeError as e:
            logger.error(f"Evidence tree error for lab {lab.id}: {e}")
            raise EvidenceVerificationError(
                f"Evidence contains unsafe content for lab {lab.id}"
            ) from e

        # Build ZIP using streaming copy
        # SECURITY: Do NOT follow symlinks
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel_path in all_files:
                full_path = temp_dir / rel_path
                # SECURITY: Skip symlinks, only include regular files
                if full_path.is_symlink():
                    logger.warning(f"Skipping symlink in verified bundle: {Path(rel_path).name}")
                    continue
                if full_path.exists() and full_path.is_file():
                    try:
                        copy_file_to_zip_streaming(zf, full_path, rel_path)
                    except PermissionError:
                        logger.error(f"Permission denied reading '{Path(rel_path).name}' for lab {lab.id}")
                        raise

        logger.info(
            f"Built verified evidence bundle for lab {lab.id}: "
            f"{len(auth_files)} auth files, {len(user_files)} user files"
        )

        return zip_buffer.getvalue()

    finally:
        # Cleanup temp directory using hardened rmtree
        rmtree_hardened(temp_dir)


async def build_verified_evidence_bundle_file(
    lab: Lab,
    include_untrusted: bool = True,
) -> tuple[Path, Path]:
    """
    Build verified evidence bundle ZIP file (Pattern B).

    Same as build_verified_evidence_bundle but writes to disk and returns file path.
    Caller is responsible for cleanup via BackgroundTask.

    SECURITY:
    - Does NOT follow symlinks when building ZIP
    - Returns (zip_path, tmpdir) - caller MUST use rmtree_hardened(tmpdir) for cleanup
    - Only includes regular files

    Args:
        lab: Lab model instance
        include_untrusted: Whether to include user evidence under untrusted/ folder

    Returns:
        Tuple of (zip_path, tmpdir) - caller must cleanup tmpdir

    Raises:
        EvidenceNotSealedError: If evidence is not sealed
        EvidenceVerificationError: If seal verification fails
    """
    # Check seal status
    if lab.evidence_seal_status != EvidenceSealStatus.SEALED.value:
        raise EvidenceNotSealedError(
            f"Evidence not sealed for lab {lab.id} (status: {lab.evidence_seal_status})"
        )

    # Verify seal
    is_valid, reason = await verify_auth_evidence(lab)
    if not is_valid:
        raise EvidenceVerificationError(f"Verification failed: {reason}")

    auth_vol, user_vol = get_evidence_volume_names(lab)

    # Create temp directory for bundle
    # CALLER is responsible for cleanup via BackgroundTask
    temp_dir = Path(tempfile.mkdtemp(prefix="octolab-evidence-"))
    safe_mkdir(temp_dir, mode=0o700)

    try:
        # Extract auth volume (authoritative evidence)
        auth_files = await _extract_auth_volume_to_dir(auth_vol, temp_dir)

        # Optionally extract user volume (untrusted evidence)
        user_files = []
        if include_untrusted:
            user_files = await _extract_user_volume_to_dir(user_vol, temp_dir)

        all_files = auth_files + user_files

        if not all_files:
            rmtree_hardened(temp_dir)
            raise EvidenceVerificationError(f"No evidence files found for lab {lab.id}")

        # DEFENSE-IN-DEPTH: Normalize permissions on staged tree
        try:
            normalize_evidence_tree(temp_dir, lab_id=str(lab.id))
        except EvidenceTreeError as e:
            logger.error(f"Evidence tree error for lab {lab.id}: {e}")
            rmtree_hardened(temp_dir)
            raise EvidenceVerificationError(
                f"Evidence contains unsafe content for lab {lab.id}"
            ) from e

        # Build ZIP to disk (not memory) for FileResponse
        # SECURITY: Do NOT follow symlinks
        zip_path = temp_dir / f"verified-evidence-{lab.id}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel_path in all_files:
                full_path = temp_dir / rel_path
                # SECURITY: Skip symlinks, only include regular files
                if full_path.is_symlink():
                    logger.warning(f"Skipping symlink in verified bundle: {Path(rel_path).name}")
                    continue
                if full_path.exists() and full_path.is_file():
                    try:
                        copy_file_to_zip_streaming(zf, full_path, rel_path)
                    except PermissionError:
                        logger.error(f"Permission denied reading '{Path(rel_path).name}' for lab {lab.id}")
                        raise

        os.chmod(zip_path, 0o600)

        logger.info(
            f"Built verified evidence bundle file for lab {lab.id}: "
            f"{len(auth_files)} auth files, {len(user_files)} user files"
        )

        return zip_path, temp_dir

    except (EvidenceNotSealedError, EvidenceVerificationError):
        raise
    except Exception:
        # Cleanup on unexpected error
        rmtree_hardened(temp_dir)
        raise
