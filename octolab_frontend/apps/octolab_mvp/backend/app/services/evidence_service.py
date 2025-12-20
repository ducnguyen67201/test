"""Helpers for building structured evidence archives.

EVIDENCE BUNDLING FLOW:
1. Extract evidence from Docker volumes to a temp directory
2. Build manifest with file hashes
3. Create ZIP bundle from extracted files
4. Return ZIP for streaming/download
5. Clean up temp directory (using hardened rmtree)

SECURITY:
- Container files may have restrictive permissions or root ownership
- Never preserve container uid/gid/mode when extracting
- Never follow symlinks when creating ZIP bundles
- Use hardened rmtree for cleanup (handles permission issues)
- Temp directories cleaned up via BackgroundTask or finally block
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import posixpath
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lab import Lab
from app.runtime import get_runtime
from app.runtime.k8s_runtime import K8sLabRuntime
from app.utils.fs import (
    EvidenceTreeError,
    copy_file_to_zip_streaming,
    normalize_evidence_tree,
    rmtree_hardened,
    safe_mkdir,
)

logger = logging.getLogger(__name__)

# Timeout for docker commands (seconds)
DOCKER_TIMEOUT = 30


class EvidenceNotFoundError(Exception):
    """Raised when evidence for a lab cannot be located."""


class PathTraversalError(Exception):
    """Raised when a path traversal attempt is detected."""


# =============================================================================
# Path Normalization and Safety Helpers
# =============================================================================


def _norm_rel(rel: str) -> str:
    """Normalize a relative path to POSIX format with safety checks.

    SECURITY: Prevents path traversal attacks by rejecting dangerous patterns.

    Args:
        rel: Relative path string (may contain backslashes or redundant segments)

    Returns:
        Normalized POSIX-style relative path

    Raises:
        PathTraversalError: If path contains traversal patterns or is absolute
    """
    # Convert Windows-style backslashes to forward slashes
    rel = rel.replace("\\", "/")

    # Normalize (removes redundant separators, resolves . and ..)
    rel = posixpath.normpath(rel)

    # Strip leading './' if present
    if rel.startswith("./"):
        rel = rel[2:]

    # Reject absolute paths
    if rel.startswith("/"):
        raise PathTraversalError(f"Absolute path not allowed: {rel}")

    # Reject if normpath couldn't eliminate parent traversal
    # (e.g., "../foo" or "foo/../../../etc/passwd")
    if rel.startswith("..") or "/../" in rel or rel.endswith("/.."):
        raise PathTraversalError(f"Path traversal detected: {rel}")

    # Reject just ".." (edge case)
    if rel == "..":
        raise PathTraversalError(f"Path traversal detected: {rel}")

    return rel


def _safe_resolve(evidence_root: Path, rel: str) -> Path | None:
    """Safely resolve a relative path within evidence_root.

    SECURITY: Prevents zip-slip and path traversal by verifying the resolved
    path stays within the evidence_root boundary.

    Args:
        evidence_root: Root path for evidence files (must be absolute)
        rel: Relative path to resolve (already normalized via _norm_rel)

    Returns:
        Resolved absolute Path if safe and exists as a regular file, None otherwise
    """
    try:
        # Normalize the relative path first
        rel = _norm_rel(rel)
    except PathTraversalError:
        return None

    # Resolve evidence_root to canonical absolute path
    evidence_root_resolved = evidence_root.resolve()

    # Build candidate path (without resolving symlinks yet)
    candidate_path = evidence_root_resolved / rel

    # SECURITY: Check if the candidate path is a symlink BEFORE resolving
    # This ensures we reject symlinks regardless of what they point to
    if candidate_path.is_symlink():
        return None

    # Now resolve to canonical form
    abs_path = candidate_path.resolve()

    # SECURITY: Verify resolved path is under evidence_root (prefix check)
    # This catches symlink escapes and any remaining traversal attempts
    try:
        abs_path.relative_to(evidence_root_resolved)
    except ValueError:
        # Path is outside evidence_root - security violation
        return None

    # Only return if it's a regular file (not directory, etc.)
    if not abs_path.is_file():
        return None

    return abs_path


# =============================================================================
# Evidence Bundle Preview (Discovery Phase)
# =============================================================================


def preview_bundle(
    lab_id: UUID,
    evidence_root: Path,
    debug: bool = False,
    max_debug_hints: int = 10,
) -> dict:
    """Discover files in evidence tree and return preview of what would be bundled.

    This is the discovery phase before building a ZIP. It walks the expected
    evidence structure and validates each file using _safe_resolve.

    SECURITY:
    - Only includes files that pass _safe_resolve (no traversal, no symlinks)
    - Returns skipped files with reasons for debugging (bounded by max_debug_hints)
    - Does not read file contents, only metadata

    Expected directory structure:
    - evidence_root/evidence/tlog/<lab_id>/*.jsonl, *.tsv (terminal logs)
    - evidence_root/evidence/commands.log (legacy)
    - evidence_root/pcap/*.pcap, *.pcapng (network captures)
    - evidence_root/recordings/<lab_id>/* (guac recordings)

    Args:
        lab_id: Lab UUID for per-lab paths
        evidence_root: Root path of evidence tree (e.g., tmpdir after extraction)
        debug: If True, include detailed debug_hints for skipped files
        max_debug_hints: Maximum number of debug hints to include (default 10)

    Returns:
        {
            "found": [{"arcname": str, "abs_path": str, "bytes": int}, ...],
            "skipped": [{"rel": str, "reason": str}, ...],  # Only if debug=True
            "total_bytes": int,
            "arcnames": [str, ...],  # Just the archive names for quick reference
            "artifact_counts": {
                "terminal_logs": int,
                "pcap": int,
                "guac_recordings": int,
            }
        }
    """
    lab_id_str = str(lab_id)
    found: list[dict] = []
    skipped: list[dict] = []
    total_bytes = 0

    # Expected paths to scan
    scan_paths = [
        # Terminal logs - tlog directory
        (f"evidence/tlog/{lab_id_str}", [".jsonl", ".tsv"]),
        # Terminal logs - legacy commands.log
        ("evidence", ["commands.log", "commands.time"]),
        # Auth evidence
        ("evidence/auth", None),  # All files
        # PCAP directory
        ("pcap", [".pcap", ".pcapng"]),
        # Guacamole recordings
        (f"recordings/{lab_id_str}", None),  # All files
    ]

    evidence_root_resolved = evidence_root.resolve()

    for rel_dir, extensions in scan_paths:
        dir_path = evidence_root_resolved / rel_dir

        if not dir_path.exists() or not dir_path.is_dir():
            continue

        # Walk the directory
        try:
            for file_path in dir_path.rglob("*"):
                if not file_path.is_file():
                    continue

                # Build relative path from evidence_root
                try:
                    rel_from_root = str(file_path.relative_to(evidence_root_resolved))
                except ValueError:
                    # Outside evidence_root - skip silently
                    if debug and len(skipped) < max_debug_hints:
                        skipped.append({
                            "rel": str(file_path)[-100:],  # Truncate for safety
                            "reason": "outside_evidence_root",
                        })
                    continue

                # Apply extension filter if specified
                if extensions is not None:
                    if not any(file_path.name.endswith(ext) for ext in extensions):
                        continue

                # Validate with _safe_resolve
                safe_path = _safe_resolve(evidence_root, rel_from_root)

                if safe_path is None:
                    if debug and len(skipped) < max_debug_hints:
                        # Determine reason
                        reason = "unknown"
                        if file_path.is_symlink():
                            reason = "symlink"
                        elif not file_path.exists():
                            reason = "not_exists"
                        else:
                            try:
                                _norm_rel(rel_from_root)
                            except PathTraversalError:
                                reason = "path_traversal"
                        skipped.append({
                            "rel": rel_from_root[:200],  # Truncate for safety
                            "reason": reason,
                        })
                    continue

                # File is safe - add to found list
                try:
                    file_size = safe_path.stat().st_size
                except OSError:
                    file_size = 0

                # Normalize arcname (relative path in ZIP)
                arcname = _norm_rel(rel_from_root)

                found.append({
                    "arcname": arcname,
                    "abs_path": str(safe_path),
                    "bytes": file_size,
                })
                total_bytes += file_size

        except PermissionError:
            if debug and len(skipped) < max_debug_hints:
                skipped.append({
                    "rel": rel_dir,
                    "reason": "permission_denied",
                })
            continue

    # Sort found files for deterministic output
    found.sort(key=lambda x: x["arcname"])

    # Count artifacts by type
    terminal_count = sum(1 for f in found if "tlog" in f["arcname"] or f["arcname"].endswith(("commands.log", "commands.time")))
    pcap_count = sum(1 for f in found if f["arcname"].endswith((".pcap", ".pcapng")))
    guac_count = sum(1 for f in found if "recordings" in f["arcname"])

    result = {
        "found": found,
        "total_bytes": total_bytes,
        "arcnames": [f["arcname"] for f in found],
        "artifact_counts": {
            "terminal_logs": terminal_count,
            "pcap": pcap_count,
            "guac_recordings": guac_count,
        },
    }

    if debug:
        result["skipped"] = skipped

    return result


# =============================================================================
# Evidence State Computation (Lifecycle Management)
# =============================================================================


@dataclass
class EvidenceInspectResult:
    """Result of evidence inspection for admin visibility.

    SECURITY:
    - found_rel: Relative paths only (no absolute paths)
    - missing_rel: Relative paths with reasons (no host details)
    - Bounded: max 20 entries per list
    """

    state: str  # EvidenceState value
    found_rel: list[dict]  # [{"rel": str, "bytes": int|None}]
    missing_rel: list[dict]  # [{"rel": str, "reason": str}]
    total_bytes: int
    artifact_counts: dict


# Maximum entries in admin inspect results (bounded for security)
MAX_INSPECT_ENTRIES = 20

# Key artifacts that determine evidence state
# Terminal logs are required for "ready" state
KEY_ARTIFACT_TERMINAL = "terminal_logs"
KEY_ARTIFACT_PCAP = "pcap"


def compute_evidence_state(
    lab_id: UUID,
    evidence_root: Path,
) -> tuple[str, EvidenceInspectResult]:
    """Compute evidence state from discovered files.

    Uses preview_bundle to discover files, then classifies:
    - ready: Both terminal logs AND pcap present
    - partial: At least one key artifact present
    - unavailable: No key artifacts found

    SECURITY:
    - Returns only relative paths (no absolute paths)
    - Bounded output (max 20 entries per list)
    - No shell commands, no symlink following

    Args:
        lab_id: Lab UUID
        evidence_root: Root path of evidence tree

    Returns:
        Tuple of (state_value, EvidenceInspectResult)
        state_value is one of: "ready", "partial", "unavailable"
    """
    from app.models.lab import EvidenceState

    # Run discovery
    preview = preview_bundle(lab_id, evidence_root, debug=True, max_debug_hints=MAX_INSPECT_ENTRIES)

    # Build found_rel (relative paths only, bounded)
    found_rel: list[dict] = []
    for item in preview["found"][:MAX_INSPECT_ENTRIES]:
        found_rel.append({
            "rel": item["arcname"],  # arcname is already relative
            "bytes": item.get("bytes"),
        })

    # Build missing_rel from expected artifacts that weren't found
    missing_rel: list[dict] = []
    lab_id_str = str(lab_id)

    # Check expected key artifacts
    arcnames = set(preview["arcnames"])

    # Terminal logs: check for tlog files or legacy commands.log
    has_terminal = preview["artifact_counts"]["terminal_logs"] > 0

    # PCAP: check for pcap files
    has_pcap = preview["artifact_counts"]["pcap"] > 0

    # Build missing list with reasons
    if not has_terminal:
        missing_rel.append({
            "rel": f"evidence/tlog/{lab_id_str}/*.jsonl",
            "reason": "No terminal log files found (tlog or commands.log)",
        })

    if not has_pcap:
        missing_rel.append({
            "rel": "pcap/*.pcap",
            "reason": "No network capture files found",
        })

    # Add skipped files from preview (already bounded)
    for item in preview.get("skipped", [])[:MAX_INSPECT_ENTRIES - len(missing_rel)]:
        if len(missing_rel) >= MAX_INSPECT_ENTRIES:
            break
        missing_rel.append({
            "rel": item["rel"],
            "reason": item.get("reason", "skipped"),
        })

    # Determine state based on key artifacts
    if has_terminal and has_pcap:
        state = EvidenceState.READY.value
    elif has_terminal or has_pcap:
        state = EvidenceState.PARTIAL.value
    else:
        state = EvidenceState.UNAVAILABLE.value

    inspect_result = EvidenceInspectResult(
        state=state,
        found_rel=found_rel,
        missing_rel=missing_rel,
        total_bytes=preview["total_bytes"],
        artifact_counts=preview["artifact_counts"],
    )

    return state, inspect_result


async def finalize_evidence_state(
    lab: "Lab",
    db_session: "AsyncSession",
    *,
    commit: bool = True,
) -> str:
    """Finalize evidence state for a lab after teardown.

    Extracts evidence from Docker volumes, computes state, and updates the Lab row.
    This is idempotent - safe to call multiple times.

    IMPORTANT: Called during teardown; must not block or raise on errors.
    On failure, sets evidence_state to unavailable and logs error.

    Args:
        lab: Lab model instance
        db_session: Async database session
        commit: If True (default), commit the session after update.
                If False, only flush (caller is responsible for commit).
                Use commit=False when called from GET handlers to avoid
                MissingGreenlet issues during Pydantic serialization.

    Returns:
        The computed evidence state value
    """
    from app.models.lab import EvidenceState

    now = datetime.now(timezone.utc)
    lab_id = lab.id

    try:
        # Extract volumes to temp directory
        project_name = f"octolab_{lab_id}"
        evidence_user_vol = f"{project_name}_evidence_user"
        evidence_auth_vol = f"{project_name}_evidence_auth"
        pcap_vol = f"{project_name}_lab_pcap"

        temp_dir = Path(tempfile.mkdtemp(prefix="octolab-finalize-"))

        try:
            safe_mkdir(temp_dir, mode=0o700)

            # Extract volumes (best-effort)
            await _extract_volume_to_dir(evidence_user_vol, temp_dir, "evidence")
            await _extract_volume_to_dir(evidence_auth_vol, temp_dir, "evidence/auth")
            await _extract_volume_to_dir(pcap_vol, temp_dir, "pcap")

            # Compute state
            state, _inspect = compute_evidence_state(lab_id, temp_dir)

            # Update lab
            lab.evidence_state = state
            lab.evidence_finalized_at = now

            # Flush or commit based on context
            if commit:
                await db_session.commit()
            else:
                await db_session.flush()

            logger.info(f"Finalized evidence state for lab {lab_id}: {state}")
            return state

        finally:
            rmtree_hardened(temp_dir)

    except Exception as e:
        # On any error, mark as unavailable (don't block teardown)
        logger.warning(
            f"Failed to finalize evidence for lab {lab_id}: {type(e).__name__}. "
            "Setting state to unavailable."
        )
        lab.evidence_state = EvidenceState.UNAVAILABLE.value
        lab.evidence_finalized_at = now
        try:
            if commit:
                await db_session.commit()
            else:
                await db_session.flush()
        except Exception:
            pass  # Best-effort
        return EvidenceState.UNAVAILABLE.value


def build_evidence_zip(
    lab_id: UUID,
    evidence_root: Path,
    out_path: Path,
    debug: bool = False,
) -> dict:
    """Build evidence ZIP using discovery-based approach.

    FLOW:
    1. Call preview_bundle() to discover files
    2. Create ZIP, adding only discovered files
    3. Generate manifest from ACTUAL ZIP contents (truthful)
    4. Return summary dict

    SECURITY:
    - Uses _safe_resolve via preview_bundle (no traversal, no symlinks)
    - Manifest reflects ONLY what is in the ZIP
    - Uses streaming copy for memory efficiency
    - No shell commands

    Args:
        lab_id: Lab UUID
        evidence_root: Root of extracted evidence tree
        out_path: Path to write ZIP file
        debug: Include debug info in result

    Returns:
        {
            "lab_id": str,
            "zip_path": str,
            "files_included": [str, ...],
            "total_bytes": int,
            "artifact_counts": {...},
            "manifest": {...},  # The actual manifest written to ZIP
            "debug": {...} if debug else None
        }
    """
    lab_id_str = str(lab_id)

    # Phase 1: Discover files using preview_bundle
    preview = preview_bundle(lab_id, evidence_root, debug=debug)

    # Phase 2: Build ZIP with discovered files
    files_actually_added: list[str] = []
    bytes_by_file: dict[str, int] = {}

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_info in preview["found"]:
            arcname = file_info["arcname"]
            abs_path = Path(file_info["abs_path"])

            # Double-check file exists and is regular (defense-in-depth)
            if not abs_path.exists() or not abs_path.is_file() or abs_path.is_symlink():
                continue

            try:
                copy_file_to_zip_streaming(zf, abs_path, arcname)
                files_actually_added.append(arcname)
                bytes_by_file[arcname] = file_info["bytes"]
            except (PermissionError, OSError) as e:
                logger.warning(
                    f"Failed to add {Path(arcname).name} to ZIP for lab {lab_id}: {type(e).__name__}"
                )
                continue

        # Phase 3: Build manifest from ACTUAL ZIP contents
        from app.schemas.lab import ArtifactStatus

        terminal_files = [f for f in files_actually_added if "tlog" in f or f.endswith(("commands.log", "commands.time"))]
        pcap_files = [f for f in files_actually_added if f.endswith((".pcap", ".pcapng"))]
        guac_files = [f for f in files_actually_added if "recordings" in f]
        auth_files = [f for f in files_actually_added if "auth" in f]

        terminal_bytes = sum(bytes_by_file.get(f, 0) for f in terminal_files)
        pcap_bytes = sum(bytes_by_file.get(f, 0) for f in pcap_files)
        guac_bytes = sum(bytes_by_file.get(f, 0) for f in guac_files)

        # Build artifact status from ACTUAL contents
        if terminal_files:
            terminal_status = ArtifactStatus(
                present=True,
                files=sorted(terminal_files),
                bytes=terminal_bytes,
            )
        else:
            terminal_status = ArtifactStatus(
                present=False,
                reason="No terminal logs found in evidence",
            )

        if pcap_files:
            pcap_status = ArtifactStatus(
                present=True,
                files=sorted(pcap_files),
                bytes=pcap_bytes,
            )
        else:
            pcap_status = ArtifactStatus(
                present=False,
                reason="No network capture found",
            )

        if guac_files:
            guac_status = ArtifactStatus(
                present=True,
                files=sorted(guac_files),
                bytes=guac_bytes,
            )
        else:
            guac_status = ArtifactStatus(
                present=False,
                reason="Guacamole recording not enabled or not found",
            )

        manifest = {
            "lab_id": lab_id_str,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "bundle_version": 3,  # New version with discovery-based bundling
            "evidence_version": "3.1",
            "artifacts": {
                "terminal_logs": terminal_status.model_dump(),
                "pcap": pcap_status.model_dump(),
                "guac_recordings": guac_status.model_dump(),
            },
            # TRUTH: included_files is exactly what's in the ZIP
            "included_files": sorted(files_actually_added),
            # Legacy compat
            "tlog_enabled": terminal_status.present,
            "pcap_included": pcap_status.present,
            "pcap_missing": not pcap_status.present,
        }

        # Write manifest LAST
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    # Set secure permissions on output file
    os.chmod(out_path, 0o600)

    # Build result
    total_bytes = sum(bytes_by_file.values())
    result = {
        "lab_id": lab_id_str,
        "zip_path": str(out_path),
        "files_included": sorted(files_actually_added),
        "total_bytes": total_bytes,
        "artifact_counts": {
            "terminal_logs": len(terminal_files),
            "pcap": len(pcap_files),
            "guac_recordings": len(guac_files),
        },
        "manifest": manifest,
    }

    if debug:
        result["debug"] = {
            "preview_found_count": len(preview["found"]),
            "preview_skipped": preview.get("skipped", []),
            "evidence_root": str(evidence_root),
        }

    logger.info(
        f"Built evidence ZIP for lab {lab_id}: {len(files_actually_added)} files, "
        f"{total_bytes} bytes, terminal={terminal_status.present}, pcap={pcap_status.present}"
    )

    return result


async def async_preview_bundle(lab: Lab, debug: bool = False) -> dict:
    """Async wrapper for preview_bundle that extracts Docker volumes first.

    FLOW:
    1. Extract evidence volumes to temp directory
    2. Call preview_bundle on extracted files
    3. Cleanup temp directory
    4. Return preview result

    SECURITY:
    - Admin-only endpoint (checked in route handler)
    - Uses rmtree_hardened for cleanup
    - Temp directory has 0o700 permissions

    Args:
        lab: Lab model instance
        debug: Include debug hints for skipped files

    Returns:
        preview_bundle() result with extraction notes added
    """
    project_name = f"octolab_{lab.id}"
    # Volume names match compose file: evidence_user, evidence_auth, lab_pcap
    evidence_user_vol = f"{project_name}_evidence_user"
    evidence_auth_vol = f"{project_name}_evidence_auth"
    pcap_vol = f"{project_name}_lab_pcap"
    lab_id = lab.id

    # Create temp directory for extraction
    temp_dir = Path(tempfile.mkdtemp(prefix="octolab-preview-"))
    notes: list[str] = []

    try:
        safe_mkdir(temp_dir, mode=0o700)

        # Extract user evidence volume
        user_files = await _extract_volume_to_dir(evidence_user_vol, temp_dir, "evidence")
        if not user_files:
            notes.append("User evidence volume extraction returned no files")

        # Extract auth evidence volume
        auth_files = await _extract_volume_to_dir(evidence_auth_vol, temp_dir, "evidence/auth")
        if not auth_files:
            notes.append("Auth evidence volume extraction returned no files")

        # Extract pcap volume
        pcap_files = await _extract_volume_to_dir(pcap_vol, temp_dir, "pcap")
        if not pcap_files:
            notes.append("PCAP volume extraction returned no files")

        # Run preview_bundle on extracted files
        preview = preview_bundle(lab_id, temp_dir, debug=debug)

        # Add extraction metadata
        preview["extraction_notes"] = notes
        preview["evidence_root_was"] = str(temp_dir)
        preview["volumes_extracted"] = {
            "evidence_user": len(user_files),
            "evidence_auth": len(auth_files),
            "pcap": len(pcap_files),
        }

        return preview

    finally:
        # Cleanup temp directory
        rmtree_hardened(temp_dir)


# =============================================================================
# Evidence Status Resolver (Single Source of Truth)
# =============================================================================


def _safe_stat_path(path: Path) -> tuple[bool, int, str | None]:
    """Safely stat a path and return (exists, size_bytes, error_reason).

    Side-effect free: only reads metadata.

    Args:
        path: Path to stat

    Returns:
        (exists, size_bytes, error_reason) tuple
        - exists: True if path exists and is readable
        - size_bytes: Total size if readable, 0 otherwise
        - error_reason: None if readable, error description otherwise
    """
    try:
        if not path.exists():
            return False, 0, "Path does not exist"
        if path.is_dir():
            # Sum size of all files in directory
            total = 0
            for f in path.rglob("*"):
                if f.is_file():
                    try:
                        total += f.stat().st_size
                    except PermissionError:
                        return False, 0, "Permission denied"
            return True, total, None
        else:
            # Single file
            size = path.stat().st_size
            # Try to open to verify readability
            with open(path, "rb") as f:
                f.read(1)  # Read 1 byte to verify
            return True, size, None
    except PermissionError:
        return False, 0, "Permission denied"
    except Exception as e:
        return False, 0, f"Read error: {type(e).__name__}"


def _list_files_safe(path: Path, extensions: list[str] | None = None) -> list[str]:
    """Safely list files in a directory with optional extension filter.

    Args:
        path: Directory path
        extensions: Optional list of extensions to filter (e.g., ['.jsonl', '.log'])

    Returns:
        List of relative file paths from the directory
    """
    if not path.exists() or not path.is_dir():
        return []

    files = []
    try:
        for f in path.rglob("*"):
            if f.is_file():
                try:
                    # Verify readability
                    with open(f, "rb") as fh:
                        fh.read(1)
                    rel = str(f.relative_to(path))
                    if extensions is None or any(rel.endswith(ext) for ext in extensions):
                        files.append(rel)
                except PermissionError:
                    continue
                except Exception:
                    continue
    except PermissionError:
        return []
    return sorted(files)


def compute_evidence_status(
    evidence_root: Path,
    lab_id: str,
) -> dict:
    """Compute evidence artifact status from an extracted evidence tree.

    This is the single source of truth for artifact presence.
    Pure function: no side effects, only reads filesystem.

    Expected directory structure (compose runtime):
    - evidence_root/evidence/tlog/<lab_id>/*.jsonl  (tlog session files)
    - evidence_root/evidence/commands.log          (legacy script output)
    - evidence_root/pcap/*.pcap, *.pcapng          (network captures)
    - evidence_root/recordings/<lab_id>/*          (guac recordings, if enabled)

    Args:
        evidence_root: Root path of extracted evidence tree (e.g., tmpdir)
        lab_id: Lab ID string for per-lab paths

    Returns:
        Dict with artifact statuses (matches EvidenceArtifacts schema)
    """
    from app.schemas.lab import ArtifactStatus

    # Terminal logs: check tlog/<lab_id> for commands.tsv and .jsonl files
    # Also check legacy commands.log
    tlog_dir = evidence_root / "evidence" / "tlog" / lab_id
    legacy_log = evidence_root / "evidence" / "commands.log"

    terminal_files = []
    terminal_bytes = 0
    terminal_reason = None
    has_tlog_jsonl = False  # Track if actual tlog session files exist

    # Check tlog directory for both .tsv (PROMPT_COMMAND hook) and .jsonl (tlog structured)
    if tlog_dir.exists():
        # Include commands.tsv (from octolab-cmdlog PROMPT_COMMAND hook)
        # Include .jsonl files (from tlog structured sessions)
        tlog_files = _list_files_safe(tlog_dir, extensions=[".jsonl", ".tsv"])
        if tlog_files:
            terminal_files.extend([f"evidence/tlog/{lab_id}/{f}" for f in tlog_files])
            # Check specifically for .jsonl files (tlog format)
            has_tlog_jsonl = any(f.endswith(".jsonl") for f in tlog_files)
            exists, size, reason = _safe_stat_path(tlog_dir)
            if exists:
                terminal_bytes += size
            else:
                terminal_reason = reason

    # Check legacy commands.log
    if legacy_log.exists():
        exists, size, reason = _safe_stat_path(legacy_log)
        if exists:
            terminal_files.append("evidence/commands.log")
            terminal_bytes += size
        else:
            terminal_reason = reason

    if terminal_files:
        terminal_status = ArtifactStatus(
            present=True,
            files=terminal_files,
            bytes=terminal_bytes,
        )
    else:
        terminal_status = ArtifactStatus(
            present=False,
            reason=terminal_reason or "No terminal logs found",
        )

    # PCAP: check pcap/ directory
    pcap_dir = evidence_root / "pcap"
    pcap_files = _list_files_safe(pcap_dir, extensions=[".pcap", ".pcapng"])
    if pcap_files:
        _, pcap_bytes, pcap_reason = _safe_stat_path(pcap_dir)
        pcap_status = ArtifactStatus(
            present=True,
            files=[f"pcap/{f}" for f in pcap_files],
            bytes=pcap_bytes,
        )
    else:
        pcap_status = ArtifactStatus(
            present=False,
            reason="No network capture found",
        )

    # Guacamole recordings: check recordings/<lab_id>/ (optional)
    recordings_dir = evidence_root / "recordings" / lab_id
    recording_files = _list_files_safe(recordings_dir)
    if recording_files:
        _, rec_bytes, _ = _safe_stat_path(recordings_dir)
        guac_status = ArtifactStatus(
            present=True,
            files=[f"recordings/{lab_id}/{f}" for f in recording_files],
            bytes=rec_bytes,
        )
    else:
        guac_status = ArtifactStatus(
            present=False,
            reason="Guacamole recording not enabled or no recordings found",
        )

    return {
        "terminal_logs": terminal_status,
        "pcap": pcap_status,
        "guac_recordings": guac_status,
        # Separate flag for tlog .jsonl files specifically (not .tsv or legacy)
        "has_tlog_jsonl": has_tlog_jsonl,
    }


async def build_evidence_status(lab: Lab) -> dict:
    """Build evidence status for a lab by extracting and inspecting artifacts.

    This is the async wrapper that:
    1. Creates temp directory
    2. Extracts evidence volumes
    3. Computes status using compute_evidence_status
    4. Cleans up temp directory

    Does NOT create a ZIP - only inspects and returns status.

    Args:
        lab: Lab model instance

    Returns:
        Dict with:
        - lab_id: UUID
        - generated_at: datetime
        - artifacts: {terminal_logs, pcap, guac_recordings}
        - notes: list[str]
    """
    from app.schemas.lab import EvidenceArtifacts, EvidenceStatusResponse

    project_name = f"octolab_{lab.id}"
    # Volume names match compose file: evidence_user, evidence_auth, lab_pcap
    evidence_user_vol = f"{project_name}_evidence_user"
    evidence_auth_vol = f"{project_name}_evidence_auth"
    pcap_vol = f"{project_name}_lab_pcap"
    lab_id_str = str(lab.id)

    # Create temp directory for extraction
    temp_dir = Path(tempfile.mkdtemp(prefix="octolab-status-"))
    notes: list[str] = []

    try:
        safe_mkdir(temp_dir, mode=0o700)

        # Extract user evidence volume (contains tlog/<lab_id>/commands.tsv, etc.)
        user_files = await _extract_volume_to_dir(evidence_user_vol, temp_dir, "evidence")
        if not user_files:
            notes.append("User evidence volume extraction returned no files")

        # Extract auth evidence volume (contains gateway-written logs)
        auth_files = await _extract_volume_to_dir(evidence_auth_vol, temp_dir, "evidence/auth")
        if not auth_files:
            notes.append("Auth evidence volume extraction returned no files")

        # Extract pcap volume
        pcap_files = await _extract_volume_to_dir(pcap_vol, temp_dir, "pcap")
        if not pcap_files:
            notes.append("PCAP volume extraction returned no files")

        # Note: guac recordings would come from a separate volume if enabled
        # For now, we don't have a guac recordings volume, so it will always be empty

        # Compute status using the resolver
        artifacts = compute_evidence_status(temp_dir, lab_id_str)

        return {
            "lab_id": lab.id,
            "generated_at": datetime.now(timezone.utc),
            "artifacts": EvidenceArtifacts(**artifacts),
            "notes": notes,
        }

    finally:
        # Always cleanup temp directory
        rmtree_hardened(temp_dir)


async def _build_lab_evidence_tar_k8s(lab: Lab) -> bytes:
    """
    Build evidence tar.gz for k8s labs using kubectl exec.

    Streams tar output directly from pod without temp files.
    """
    runtime = get_runtime()
    if not isinstance(runtime, K8sLabRuntime):
        raise ValueError("Runtime is not K8sLabRuntime")

    ns_name = runtime.ns_name(lab)
    deployment_name = runtime._resource_name(lab)

    # Find pod by label selector
    label_selector = f"app.octolab.io/lab-id={lab.id}"
    cmd = runtime._kubectl_base_args(ns_name) + [
        "get",
        "pod",
        "-l",
        label_selector,
        "-o",
        "jsonpath={.items[0].metadata.name}",
    ]

    def _get_pod_name() -> str:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        pod_name = result.stdout.strip()
        if not pod_name:
            raise EvidenceNotFoundError(f"No pod found for lab {lab.id} in namespace {ns_name}")
        return pod_name

    pod_name = await asyncio.to_thread(_get_pod_name)

    # Stream tar from pod's /evidence directory
    tar_cmd = runtime._kubectl_base_args(ns_name) + [
        "exec",
        pod_name,
        "-c",
        "octobox-beta",
        "--",
        "tar",
        "-cz",
        "-C",
        "/evidence",
        ".",
    ]

    def _stream_tar() -> bytes:
        proc = subprocess.Popen(
            tar_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = proc.communicate(timeout=60)
        if proc.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            logger.error("kubectl exec failed for lab %s: %s", lab.id, error_msg)
            raise EvidenceNotFoundError(
                f"Failed to stream evidence from pod {pod_name}: {error_msg}"
            )
        return stdout

    tar_bytes = await asyncio.to_thread(_stream_tar)
    logger.info("Streamed evidence tar.gz from pod %s for lab %s", pod_name, lab.id)
    return tar_bytes


async def build_lab_network_evidence_tar(lab: Lab) -> bytes:
    """
    Build a tar.gz archive of structured evidence logs for the given lab.

    Detects runtime type and routes to appropriate implementation:
    - k8s: Uses kubectl exec to stream tar from pod
    - compose: Uses Docker volume mounts (existing behavior)
    """
    runtime = get_runtime()

    # Route to k8s implementation if using k8s runtime
    if isinstance(runtime, K8sLabRuntime):
        return await _build_lab_evidence_tar_k8s(lab)

    # Compose runtime: existing Docker volume-based implementation
    project_name = f"octolab_{lab.id}"
    # Volume name matches compose file: evidence_user (not lab_evidence)
    volume_name = f"{project_name}_evidence_user"

    # Compute SHA256 checksums for commands.log and commands.time if they exist
    # We'll do this in helper containers that have access to the volume
    commands_log_sha256 = None
    commands_timing_sha256 = None

    # Check if commands.log exists and compute its checksum
    check_log_cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{volume_name}:/evidence:ro",
        "alpine",
        "sh",
        "-c",
        "if [ -f /evidence/commands.log ]; then sha256sum /evidence/commands.log | cut -d' ' -f1; fi",
    ]

    try:
        check_result = await asyncio.to_thread(
            subprocess.run,
            check_log_cmd,
            check=False,  # Don't fail if file doesn't exist
            capture_output=True,
            text=True,
        )
        if check_result.returncode == 0 and check_result.stdout.strip():
            commands_log_sha256 = check_result.stdout.strip()
    except Exception as e:
        logger.warning("Failed to compute commands.log checksum: %s", e)

    # Check if commands.time exists and compute its checksum
    check_time_cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{volume_name}:/evidence:ro",
        "alpine",
        "sh",
        "-c",
        "if [ -f /evidence/commands.time ]; then sha256sum /evidence/commands.time | cut -d' ' -f1; fi",
    ]

    try:
        check_result = await asyncio.to_thread(
            subprocess.run,
            check_time_cmd,
            check=False,  # Don't fail if file doesn't exist
            capture_output=True,
            text=True,
        )
        if check_result.returncode == 0 and check_result.stdout.strip():
            commands_timing_sha256 = check_result.stdout.strip()
    except Exception as e:
        logger.warning("Failed to compute commands.time checksum: %s", e)

    # Generate metadata JSON
    metadata = {
        "lab_id": str(lab.id),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_version": "2.0",
        "commands_log_format": "script-tty",
    }

    # Add command log metadata if available
    if commands_log_sha256:
        metadata["commands_log_path"] = "commands.log"
        metadata["commands_log_sha256"] = commands_log_sha256

    # Add timing file metadata if available
    if commands_timing_sha256:
        metadata["commands_timing_path"] = "commands.time"
        metadata["commands_timing_sha256"] = commands_timing_sha256

    metadata_json = json.dumps(metadata, indent=2)

    # Create tarball with evidence directory contents and metadata
    # Use base64 encoding to safely pass JSON through shell command
    metadata_b64 = base64.b64encode(metadata_json.encode()).decode()

    # BusyBox tar doesn't support --transform, so we copy metadata into evidence dir first
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{volume_name}:/evidence:rw",
        "alpine",
        "sh",
        "-c",
        f"echo '{metadata_b64}' | base64 -d > /evidence/metadata.json && tar -C /evidence -czf - .",
    ]

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover - CLI failure
        raise EvidenceNotFoundError(
            f"Unable to collect evidence for lab {lab.id}"
        ) from exc

    return result.stdout


async def purge_lab_evidence(lab: Lab) -> None:
    """
    Remove the per-lab evidence volumes (evidence_user, evidence_auth, lab_pcap).

    Intended for background retention jobs rather than HTTP handlers.
    """

    project_name = f"octolab_{lab.id}"
    # Volume names match compose file: evidence_user, evidence_auth, lab_pcap
    volumes_to_remove = [
        f"{project_name}_evidence_user",
        f"{project_name}_evidence_auth",
        f"{project_name}_lab_pcap",
    ]

    for volume_name in volumes_to_remove:
        cmd = ["docker", "volume", "rm", volume_name]
        try:
            await asyncio.to_thread(
                subprocess.run,
                cmd,
                check=True,
                capture_output=True,
            )
            logger.info("Removed evidence volume %s for lab %s", volume_name, lab.id)
        except subprocess.CalledProcessError:
            logger.info(
                "Evidence volume %s already absent for lab %s",
                volume_name,
                lab.id,
            )

    lab.evidence_deleted_at = datetime.now(timezone.utc)


async def _extract_volume_to_dir(
    volume_name: str,
    dest_dir: Path,
    subfolder: str,
) -> list[str]:
    """
    Extract contents of a Docker volume to a local directory.

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
        subfolder: Subfolder name within dest_dir to place files

    Returns:
        List of relative file paths extracted
    """
    from app.utils.safe_extract import (
        UnsafeArchiveError,
        safe_extract_tarfile_from_path,
        spool_docker_archive,
    )

    target_dir = dest_dir / subfolder
    safe_mkdir(target_dir, mode=0o700)

    # Create tar from volume contents and stream to stdout
    # Container runs as UID 1000:1000 (pentester) to read OctoBox evidence files
    # SECURITY: With --cap-drop ALL, even root can't bypass 0700 permissions
    # Running as 1000:1000 (file owner) allows reading tlog/<lab_id>/commands.tsv
    # We extract on host side with correct user ownership
    # SECURITY: Hardened container with minimal privileges
    cmd = [
        "docker",
        "run",
        "--rm",
        "--network", "none",  # No network access needed
        "--cap-drop", "ALL",  # Drop all capabilities
        "--security-opt", "no-new-privileges",  # Prevent privilege escalation
        "--user", "1000:1000",  # Run as pentester UID to read 0700 dirs
        "--pids-limit", "64",  # Limit processes (defense-in-depth)
        "--memory", "128m",  # Memory limit (prevents OOM attacks)
        "-v",
        f"{volume_name}:/src:ro",  # Read-only mount
        "alpine:3.20",  # Pinned version for reproducibility
        "sh",
        "-c",
        # Create tar of regular files only (no symlinks, devices)
        # Note: BusyBox tar doesn't support --null -T -, use tar with find output
        "cd /src && tar -cf - $(find . -type f 2>/dev/null) 2>/dev/null || true",
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
            # (e.g., empty volume returns empty tar)
            return result.stdout if result.stdout else None
        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout extracting volume {volume_name}")
            return None
        except Exception as e:
            logger.warning(f"Error extracting volume {volume_name}: {type(e).__name__}")
            return None

    tar_data = await asyncio.to_thread(_stream_tar)

    if not tar_data:
        # Empty volume or error - return empty list
        return []

    # Spool tar to disk (avoids memory issues with large pcaps)
    spool_path = dest_dir / f"{subfolder}_raw.tar"
    try:
        spool_path.write_bytes(tar_data)

        # Extract using safe_extract (ignores tar uid/gid, sets 0o600/0o700)
        try:
            extracted = safe_extract_tarfile_from_path(
                spool_path,
                target_dir,
                max_total_bytes=500 * 1024 * 1024,  # 500MB for pcaps
                max_member_bytes=200 * 1024 * 1024,  # 200MB per file
            )
        except UnsafeArchiveError as e:
            logger.warning(f"Unsafe content in volume {volume_name}: {e}")
            return []
        except Exception as e:
            logger.warning(f"Error extracting tar from {volume_name}: {type(e).__name__}")
            return []

    finally:
        # Clean up spool file
        try:
            spool_path.unlink()
        except FileNotFoundError:
            pass

    # Return paths relative to dest_dir (include subfolder prefix)
    return [f"{subfolder}/{f}" for f in extracted]


async def build_evidence_bundle_zip(lab: Lab) -> bytes:
    """
    Build a ZIP bundle of all evidence for a lab.

    Includes:
    - evidence/tlog/<lab_id>/session.jsonl (structured tlog output)
    - evidence/commands.log, evidence/commands.time (legacy script output)
    - pcap/*.pcap (network captures, if present)
    - manifest.json (metadata about the bundle)

    SECURITY:
    - Does NOT follow symlinks when building ZIP
    - Uses hardened cleanup for temp directory
    - Only includes regular files
    - Normalizes permissions before zipping (defense-in-depth)
    - Uses streaming copy to avoid loading large files into RAM

    Args:
        lab: Lab model instance

    Returns:
        ZIP file contents as bytes

    Raises:
        EvidenceNotFoundError: If no evidence files could be collected
    """
    project_name = f"octolab_{lab.id}"
    # Volume names match compose file: evidence_user, evidence_auth, lab_pcap
    evidence_user_vol = f"{project_name}_evidence_user"
    evidence_auth_vol = f"{project_name}_evidence_auth"
    pcap_vol = f"{project_name}_lab_pcap"
    lab_id_str = str(lab.id)

    # Create temp directory for extraction (will be cleaned up after)
    temp_dir = Path(tempfile.mkdtemp(prefix="octolab-evidence-"))

    try:
        safe_mkdir(temp_dir, mode=0o700)

        # Extract user evidence volume (contains tlog/<lab_id>/commands.tsv, etc.)
        evidence_files = await _extract_volume_to_dir(evidence_user_vol, temp_dir, "evidence")

        # Extract auth evidence volume (gateway-written authoritative evidence)
        auth_files = await _extract_volume_to_dir(evidence_auth_vol, temp_dir, "evidence/auth")

        # Extract pcap volume (graceful if missing)
        # pcap may not exist for all labs - that's OK
        pcap_files = await _extract_volume_to_dir(pcap_vol, temp_dir, "pcap")

        all_files = evidence_files + auth_files + pcap_files

        # Require at least evidence files (pcap is optional)
        if not evidence_files and not auth_files:
            raise EvidenceNotFoundError(f"No evidence files found for lab {lab.id}")

        # DEFENSE-IN-DEPTH: Normalize permissions on staged tree
        # This handles container files with restrictive perms (root-owned, 0o000, etc.)
        try:
            normalize_evidence_tree(temp_dir, lab_id=lab_id_str)
        except EvidenceTreeError as e:
            # Symlink detected - this is a security issue
            logger.error(f"Evidence tree error for lab {lab.id}: {e}")
            raise EvidenceNotFoundError(
                f"Evidence contains unsafe content for lab {lab.id}"
            ) from e

        # Build ZIP in memory using streaming copy
        # CRITICAL: Track what ACTUALLY gets added to the ZIP
        # Manifest must reflect reality, not what was "supposed to" be included
        # SECURITY: Do NOT follow symlinks, use explicit open/copy
        zip_buffer = io.BytesIO()
        files_actually_added: list[str] = []
        bytes_by_file: dict[str, int] = {}

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add all extracted files using streaming (handles large pcaps)
            # Track what actually gets added for truthful manifest
            for rel_path in all_files:
                full_path = temp_dir / rel_path
                # SECURITY: Skip symlinks, only include regular files
                if full_path.is_symlink():
                    logger.warning(
                        f"Skipping symlink in evidence: {Path(rel_path).name} for lab {lab.id}"
                    )
                    continue
                if full_path.exists() and full_path.is_file():
                    try:
                        copy_file_to_zip_streaming(zf, full_path, rel_path)
                        files_actually_added.append(rel_path)
                        bytes_by_file[rel_path] = full_path.stat().st_size
                    except PermissionError:
                        # Log only basename for security; don't include in manifest
                        logger.warning(
                            f"Permission denied reading '{Path(rel_path).name}' for lab {lab.id}"
                        )
                        continue  # Don't raise - continue with other files

            # NOW compute artifact status based on what was ACTUALLY added
            # This ensures manifest cannot lie about ZIP contents
            terminal_files = [f for f in files_actually_added if "tlog" in f or f.endswith("commands.log")]
            pcap_files = [f for f in files_actually_added if f.endswith((".pcap", ".pcapng"))]
            auth_files = [f for f in files_actually_added if "auth" in f]

            terminal_bytes = sum(bytes_by_file.get(f, 0) for f in terminal_files)
            pcap_bytes = sum(bytes_by_file.get(f, 0) for f in pcap_files)

            # Build artifacts from ACTUAL ZIP contents
            from app.schemas.lab import ArtifactStatus

            if terminal_files:
                terminal_status = ArtifactStatus(
                    present=True,
                    files=sorted(terminal_files),
                    bytes=terminal_bytes,
                )
            else:
                terminal_status = ArtifactStatus(
                    present=False,
                    reason="No terminal logs found in extracted evidence",
                )

            if pcap_files:
                pcap_status = ArtifactStatus(
                    present=True,
                    files=sorted(pcap_files),
                    bytes=pcap_bytes,
                )
            else:
                pcap_status = ArtifactStatus(
                    present=False,
                    reason="No network capture found",
                )

            # Guac recordings - check if any were added
            guac_files = [f for f in files_actually_added if "recordings" in f]
            if guac_files:
                guac_status = ArtifactStatus(
                    present=True,
                    files=sorted(guac_files),
                    bytes=sum(bytes_by_file.get(f, 0) for f in guac_files),
                )
            else:
                guac_status = ArtifactStatus(
                    present=False,
                    reason="Guacamole recording not enabled or no recordings found",
                )

            # Generate manifest from ACTUAL ZIP contents
            # CRITICAL: tlog_enabled must be true if terminal_logs.present is true
            manifest = {
                "lab_id": lab_id_str,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "bundle_version": 2,
                "evidence_version": "3.0",
                "artifacts": {
                    "terminal_logs": terminal_status.model_dump(),
                    "pcap": pcap_status.model_dump(),
                    "guac_recordings": guac_status.model_dump(),
                },
                # TRUTH: included_files is exactly what's in the ZIP
                "included_files": sorted(files_actually_added),
                # tlog_enabled = true if ANY terminal logs present (consistent with terminal_logs.present)
                "tlog_enabled": terminal_status.present,
                "pcap_included": pcap_status.present,
                "pcap_missing": not pcap_status.present,
            }

            # Write manifest LAST after all files are added
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        logger.info(
            f"Built evidence bundle for lab {lab.id}: {len(files_actually_added)} files, "
            f"tlog={manifest['tlog_enabled']}, pcap={manifest['pcap_included']}"
        )

        return zip_buffer.getvalue()

    finally:
        # Cleanup temp directory using hardened rmtree
        rmtree_hardened(temp_dir)


async def build_evidence_bundle_zip_file(lab: Lab) -> tuple[Path, Path]:
    """
    Build a ZIP bundle of all evidence for a lab (Pattern B).

    Same as build_evidence_bundle_zip but writes to disk and returns file path.
    Caller is responsible for cleanup via BackgroundTask.

    IMPORTANT: This function ALWAYS returns a valid ZIP with at minimum manifest.json.
    Missing artifacts are described in the manifest but do NOT cause 404.

    SECURITY:
    - Does NOT follow symlinks when building ZIP
    - Returns (zip_path, tmpdir) - caller MUST use rmtree_hardened(tmpdir) for cleanup
    - Only includes regular files
    - Normalizes permissions before zipping (defense-in-depth)
    - Uses streaming copy to avoid loading large files into RAM

    Args:
        lab: Lab model instance

    Returns:
        Tuple of (zip_path, tmpdir) - caller must cleanup tmpdir
        Never raises EvidenceNotFoundError - always returns valid ZIP with manifest
    """
    project_name = f"octolab_{lab.id}"
    # Volume names match compose file: evidence_user, evidence_auth, lab_pcap
    evidence_user_vol = f"{project_name}_evidence_user"
    evidence_auth_vol = f"{project_name}_evidence_auth"
    pcap_vol = f"{project_name}_lab_pcap"
    lab_id_str = str(lab.id)

    # Create temp directory for extraction
    # CALLER is responsible for cleanup via BackgroundTask
    temp_dir = Path(tempfile.mkdtemp(prefix="octolab-evidence-"))
    safe_mkdir(temp_dir, mode=0o700)

    try:
        # Extract user evidence volume (contains tlog/<lab_id>/commands.tsv, etc.)
        evidence_files = await _extract_volume_to_dir(evidence_user_vol, temp_dir, "evidence")

        # Extract auth evidence volume (gateway-written authoritative evidence)
        auth_files = await _extract_volume_to_dir(evidence_auth_vol, temp_dir, "evidence/auth")

        # Extract pcap volume (graceful if missing)
        # pcap may not exist for all labs - that's OK
        pcap_files = await _extract_volume_to_dir(pcap_vol, temp_dir, "pcap")

        all_files = evidence_files + auth_files + pcap_files

        # DEFENSE-IN-DEPTH: Normalize permissions on staged tree if we have files
        # This handles container files with restrictive perms (root-owned, 0o000, etc.)
        if all_files:
            try:
                normalize_evidence_tree(temp_dir, lab_id=lab_id_str)
            except EvidenceTreeError as e:
                # Symlink detected - this is a security issue
                # Don't fail entirely - just skip unsafe files
                logger.warning(f"Evidence tree warning for lab {lab.id}: {e}")

        # Build ZIP to disk (not memory) for FileResponse
        # CRITICAL: Track what ACTUALLY gets added to the ZIP
        # Manifest must reflect reality, not what was "supposed to" be included
        # SECURITY: Use streaming copy, do NOT follow symlinks
        zip_path = temp_dir / f"evidence-{lab.id}.zip"
        files_actually_added: list[str] = []
        bytes_by_file: dict[str, int] = {}

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add all extracted files using streaming (handles large pcaps)
            # Track what actually gets added for truthful manifest
            for rel_path in all_files:
                full_path = temp_dir / rel_path
                # SECURITY: Skip symlinks, only include regular files
                if full_path.is_symlink():
                    logger.warning(
                        f"Skipping symlink in evidence: {Path(rel_path).name} for lab {lab.id}"
                    )
                    continue
                if full_path.exists() and full_path.is_file():
                    try:
                        copy_file_to_zip_streaming(zf, full_path, rel_path)
                        files_actually_added.append(rel_path)
                        bytes_by_file[rel_path] = full_path.stat().st_size
                    except PermissionError:
                        # Log only basename for security; don't include in manifest
                        logger.warning(
                            f"Permission denied reading '{Path(rel_path).name}' for lab {lab.id}"
                        )
                        continue  # Don't raise - continue with other files

            # NOW compute artifact status based on what was ACTUALLY added
            # This ensures manifest cannot lie about ZIP contents
            terminal_files = [f for f in files_actually_added if "tlog" in f or f.endswith("commands.log")]
            pcap_file_list = [f for f in files_actually_added if f.endswith((".pcap", ".pcapng"))]
            auth_file_list = [f for f in files_actually_added if "auth" in f]
            guac_file_list = [f for f in files_actually_added if "recordings" in f]

            terminal_bytes = sum(bytes_by_file.get(f, 0) for f in terminal_files)
            pcap_bytes = sum(bytes_by_file.get(f, 0) for f in pcap_file_list)

            # Build artifacts from ACTUAL ZIP contents
            from app.schemas.lab import ArtifactStatus

            if terminal_files:
                terminal_status = ArtifactStatus(
                    present=True,
                    files=sorted(terminal_files),
                    bytes=terminal_bytes,
                )
            else:
                terminal_status = ArtifactStatus(
                    present=False,
                    reason="No terminal logs found in extracted evidence",
                )

            if pcap_file_list:
                pcap_status = ArtifactStatus(
                    present=True,
                    files=sorted(pcap_file_list),
                    bytes=pcap_bytes,
                )
            else:
                pcap_status = ArtifactStatus(
                    present=False,
                    reason="No network capture found",
                )

            if guac_file_list:
                guac_status = ArtifactStatus(
                    present=True,
                    files=sorted(guac_file_list),
                    bytes=sum(bytes_by_file.get(f, 0) for f in guac_file_list),
                )
            else:
                guac_status = ArtifactStatus(
                    present=False,
                    reason="Guacamole recording not enabled or no recordings found",
                )

            # Build structured artifacts from ACTUAL ZIP contents
            artifacts = {
                "terminal_logs": terminal_status.model_dump(),
                "pcap": pcap_status.model_dump(),
                "guac_recordings": guac_status.model_dump(),
                # Legacy field for backwards compatibility
                "screenshots": {
                    "present": False,
                    "reason": "Screenshot capture not enabled",
                },
            }

            # Generate manifest from ACTUAL ZIP contents
            # CRITICAL: tlog_enabled must be true if terminal_logs.present is true
            manifest = {
                "lab_id": lab_id_str,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "bundle_version": 2,
                "evidence_version": "3.0",
                "artifacts": artifacts,
                # TRUTH: included_files is exactly what's in the ZIP
                "included_files": sorted(files_actually_added),
                # tlog_enabled = true if ANY terminal logs present (consistent with terminal_logs.present)
                "tlog_enabled": terminal_status.present,
                "pcap_included": pcap_status.present,
                "pcap_missing": not pcap_status.present,
            }

            # Write manifest LAST after all files are added
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        os.chmod(zip_path, 0o600)

        logger.info(
            f"Built evidence bundle file for lab {lab.id}: {len(files_actually_added)} files, "
            f"terminal_logs={artifacts['terminal_logs']['present']}, "
            f"pcap={artifacts['pcap']['present']}"
        )

        return zip_path, temp_dir

    except Exception as e:
        # On any error, try to at least return an empty manifest
        logger.warning(f"Error building evidence bundle for lab {lab.id}: {type(e).__name__}")
        try:
            # Create minimal manifest-only ZIP
            manifest = {
                "lab_id": lab_id_str,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "bundle_version": 2,
                "evidence_version": "3.0",
                "artifacts": {
                    "terminal_logs": {"present": False, "reason": f"Extraction error: {type(e).__name__}"},
                    "pcap": {"present": False, "reason": f"Extraction error: {type(e).__name__}"},
                    "screenshots": {"present": False, "reason": "Screenshot capture not enabled"},
                },
                "included_files": [],
                "tlog_enabled": False,
                "pcap_included": False,
                "error": f"Evidence extraction failed: {type(e).__name__}",
            }

            manifest_path = temp_dir / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2))
            os.chmod(manifest_path, 0o600)

            zip_path = temp_dir / f"evidence-{lab.id}.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                copy_file_to_zip_streaming(zf, manifest_path, "manifest.json")

            os.chmod(zip_path, 0o600)
            return zip_path, temp_dir

        except Exception:
            # Complete failure - cleanup and re-raise
            rmtree_hardened(temp_dir)
            raise

