#!/usr/bin/env python3
"""Smoke test for Authoritative Evidence v1.

Validates the evidence sealing and verification system:
1. OctoBox cannot access authoritative evidence volume
2. Authoritative evidence exists (network.json)
3. Evidence is sealed (seal_status == "sealed")
4. Verified bundle endpoint returns 200
5. Optional: Tamper test confirms 422 on modified evidence

Usage:
    python3 -m app.scripts.smoke_evidence_v1 --lab-id <uuid> --token "$TOKEN"

SECURITY:
- Never log tokens or secrets
- All subprocess calls use shell=False
- Tamper mode requires explicit --tamper flag
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import NamedTuple
from uuid import UUID

import httpx

# Ensure we can import from app
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.utils.subprocess_utils import run_cmd, format_cmd_for_display


# Result tracking
class CheckResult(NamedTuple):
    """Result of a single check."""
    name: str
    passed: bool
    message: str


def print_result(result: CheckResult) -> None:
    """Print check result with formatting."""
    status = "[PASS]" if result.passed else "[FAIL]"
    print(f"{status} {result.name}")
    if result.message:
        for line in result.message.split("\n"):
            print(f"       {line}")


def redact_token_header(headers: dict[str, str]) -> dict[str, str]:
    """Redact Authorization header for safe logging."""
    redacted = dict(headers)
    if "Authorization" in redacted:
        redacted["Authorization"] = "Bearer ***REDACTED***"
    return redacted


async def fetch_lab_from_api(
    api_base: str,
    lab_id: str,
    token: str,
    timeout: float,
) -> tuple[bool, dict | None, str]:
    """
    Fetch lab details from API.

    Returns:
        (success, lab_data, error_message)
    """
    url = f"{api_base}/labs/{lab_id}"
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                return True, resp.json(), ""
            elif resp.status_code == 401:
                return False, None, "401 Unauthorized - check your token"
            elif resp.status_code == 404:
                return False, None, "404 Not Found - lab does not exist or you don't own it"
            else:
                return False, None, f"{resp.status_code}: {resp.text[:200]}"
        except httpx.RequestError as e:
            return False, None, f"Request failed: {type(e).__name__}"


async def fetch_lab_evidence_fields(lab_id: str) -> tuple[str | None, str | None]:
    """
    Fetch evidence fields directly from database.

    Returns:
        (evidence_auth_volume, evidence_seal_status)
    """
    try:
        from app.db import AsyncSessionLocal
        from app.models.lab import Lab

        async with AsyncSessionLocal() as session:
            lab = await session.get(Lab, UUID(lab_id))
            if lab:
                return lab.evidence_auth_volume, lab.evidence_seal_status
            return None, None
    except Exception:
        return None, None


def check_octobox_cannot_access_auth(
    compose_file: str,
    project_name: str,
    timeout: float,
    print_commands: bool,
) -> CheckResult:
    """
    Check that OctoBox container cannot access /evidence/auth.

    This is the critical security invariant.
    """
    # Try sh first, fall back to bash
    probe_script = (
        "set -eu; "
        "echo 'EVIDENCE_ROOT'; ls -la /evidence 2>&1 || true; "
        "echo 'AUTH_PROBE'; "
        "if ls -la /evidence/auth 2>/dev/null; then exit 2; fi; "
        "echo 'auth inaccessible (expected)'"
    )

    cmd = [
        "docker", "compose",
        "-f", compose_file,
        "-p", project_name,
        "exec", "-T", "octobox",
        "sh", "-c", probe_script,
    ]

    if print_commands:
        print(f"  CMD: {format_cmd_for_display(cmd)}")

    try:
        result = run_cmd(cmd, timeout=timeout)

        # Exit code 2 means auth was accessible (FAIL)
        if result.returncode == 2:
            return CheckResult(
                name="OctoBox cannot access auth",
                passed=False,
                message="SECURITY VIOLATION: OctoBox can access /evidence/auth!\n" + result.stdout[:500],
            )

        # Check output for auth directory listing (should not happen)
        if "AUTH_PROBE" in result.stdout:
            lines_after_probe = result.stdout.split("AUTH_PROBE")[-1]
            # If there's actual file listing after AUTH_PROBE (not error), it's a fail
            if any(x in lines_after_probe.lower() for x in ["total", "drwx", "-rw"]):
                return CheckResult(
                    name="OctoBox cannot access auth",
                    passed=False,
                    message="SECURITY VIOLATION: auth directory is listable!\n" + lines_after_probe[:300],
                )

        return CheckResult(
            name="OctoBox cannot access auth",
            passed=True,
            message="",
        )

    except Exception as e:
        # If container doesn't exist or isn't running, we can't test this
        return CheckResult(
            name="OctoBox cannot access auth",
            passed=False,
            message=f"Could not exec into octobox: {type(e).__name__}",
        )


def check_auth_evidence_exists(
    auth_volume: str,
    timeout: float,
    print_commands: bool,
) -> CheckResult:
    """
    Check that authoritative evidence files exist in the auth volume.

    Uses helper container to inspect volume contents.
    """
    # List volume contents and check for network.json
    # The volume structure is: /evidence/auth/network/network.json when mounted
    # But when we mount the volume directly, it's at /data/network/network.json
    probe_script = (
        "set -eu; "
        "echo 'VOLUME_ROOT:'; ls -la /data 2>&1 || true; "
        "echo 'NETWORK_DIR:'; ls -la /data/network 2>&1 || true; "
        "test -f /data/network/network.json && echo 'FOUND:network.json' || "
        "test -f /data/auth/network/network.json && echo 'FOUND:auth/network.json' || "
        "echo 'NOT_FOUND'"
    )

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{auth_volume}:/data:ro",
        "debian:12-slim",
        "sh", "-c", probe_script,
    ]

    if print_commands:
        print(f"  CMD: {format_cmd_for_display(cmd)}")

    try:
        result = run_cmd(cmd, timeout=timeout)

        if "FOUND:" in result.stdout:
            return CheckResult(
                name="Auth network.json exists",
                passed=True,
                message="",
            )

        return CheckResult(
            name="Auth network.json exists",
            passed=False,
            message=f"network.json not found in auth volume\n{result.stdout[:500]}",
        )

    except Exception as e:
        return CheckResult(
            name="Auth network.json exists",
            passed=False,
            message=f"Could not inspect auth volume: {type(e).__name__}",
        )


def check_seal_status(seal_status: str | None) -> CheckResult:
    """Check that evidence seal status is SEALED."""
    if seal_status == "sealed":
        return CheckResult(
            name="Seal status SEALED",
            passed=True,
            message="",
        )

    return CheckResult(
        name="Seal status SEALED",
        passed=False,
        message=f"Current status: {seal_status or 'none'}\nEnd lab / trigger sealing; then rerun",
    )


async def check_verified_bundle_download(
    api_base: str,
    lab_id: str,
    token: str,
    out_path: str,
    timeout: float,
    no_unzip: bool,
    print_commands: bool,
) -> CheckResult:
    """
    Download verified evidence bundle and validate contents.
    """
    url = f"{api_base}/labs/{lab_id}/evidence/verified-bundle.zip"
    headers = {"Authorization": f"Bearer {token}"}

    if print_commands:
        print(f"  GET {url} (Authorization: ***REDACTED***)")

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.get(url, headers=headers)

            if resp.status_code == 409:
                return CheckResult(
                    name="Verified bundle 200",
                    passed=False,
                    message="409 Conflict - evidence not sealed yet",
                )
            elif resp.status_code == 422:
                detail = resp.json().get("detail", resp.text[:200])
                return CheckResult(
                    name="Verified bundle 200",
                    passed=False,
                    message=f"422 Unprocessable - verification failed: {detail}",
                )
            elif resp.status_code == 404:
                return CheckResult(
                    name="Verified bundle 200",
                    passed=False,
                    message="404 Not Found - lab not found or evidence expired",
                )
            elif resp.status_code != 200:
                return CheckResult(
                    name="Verified bundle 200",
                    passed=False,
                    message=f"{resp.status_code}: {resp.text[:200]}",
                )

            # Write bundle to file
            with open(out_path, "wb") as f:
                f.write(resp.content)

            if no_unzip:
                return CheckResult(
                    name="Verified bundle 200",
                    passed=True,
                    message=f"Saved to {out_path} (skipped unzip verification)",
                )

            # Verify ZIP contents
            try:
                with zipfile.ZipFile(out_path, "r") as zf:
                    names = zf.namelist()

                required_files = ["auth/manifest.json", "auth/manifest.sig"]
                network_files = ["auth/network/network.json", "auth/network.json"]

                missing = []
                for req in required_files:
                    if req not in names:
                        missing.append(req)

                has_network = any(nf in names for nf in network_files)
                if not has_network:
                    missing.append("auth/network/network.json")

                if missing:
                    return CheckResult(
                        name="Verified bundle 200",
                        passed=False,
                        message=f"Missing files in bundle: {missing}\nFound: {names[:10]}...",
                    )

                return CheckResult(
                    name="Verified bundle 200 + contains manifest",
                    passed=True,
                    message=f"Saved to {out_path}\nContains {len(names)} files",
                )

            except zipfile.BadZipFile:
                return CheckResult(
                    name="Verified bundle 200",
                    passed=False,
                    message="Downloaded file is not a valid ZIP",
                )

        except httpx.RequestError as e:
            return CheckResult(
                name="Verified bundle 200",
                passed=False,
                message=f"Request failed: {type(e).__name__}",
            )


def tamper_auth_evidence(
    auth_volume: str,
    tamper_file: str,
    timeout: float,
    print_commands: bool,
) -> CheckResult:
    """
    Tamper with authoritative evidence by appending bytes.

    This mutates the evidence volume!
    """
    # Resolve tamper file path
    # If tamper_file is "network/network.json", it's relative to /data
    tamper_path = f"/data/{tamper_file}"

    # Use shell to append tamper marker
    # This is safe because we control the script content
    tamper_script = (
        f"set -eu; "
        f"test -f '{tamper_path}' || exit 1; "
        f"printf '\\n#TAMPERED_BY_SMOKE_TEST\\n' >> '{tamper_path}'; "
        f"echo 'TAMPERED'"
    )

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{auth_volume}:/data",  # Note: NO :ro - we need write access
        "debian:12-slim",
        "sh", "-c", tamper_script,
    ]

    if print_commands:
        print(f"  CMD: {format_cmd_for_display(cmd)}")

    try:
        result = run_cmd(cmd, timeout=timeout)

        if "TAMPERED" in result.stdout:
            return CheckResult(
                name="Tamper applied",
                passed=True,
                message=f"Modified {tamper_file}",
            )

        return CheckResult(
            name="Tamper applied",
            passed=False,
            message=f"Failed to tamper: {result.stderr[:200]}",
        )

    except Exception as e:
        return CheckResult(
            name="Tamper applied",
            passed=False,
            message=f"Tamper failed: {type(e).__name__}",
        )


async def check_tamper_causes_422(
    api_base: str,
    lab_id: str,
    token: str,
    timeout: float,
    print_commands: bool,
) -> CheckResult:
    """
    Verify that tampered evidence returns 422 from verified-bundle endpoint.
    """
    url = f"{api_base}/labs/{lab_id}/evidence/verified-bundle.zip"
    headers = {"Authorization": f"Bearer {token}"}

    if print_commands:
        print(f"  GET {url} (expecting 422)")

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.get(url, headers=headers)

            if resp.status_code == 422:
                return CheckResult(
                    name="Tamper causes 422",
                    passed=True,
                    message="Tampered evidence correctly rejected",
                )
            elif resp.status_code == 200:
                return CheckResult(
                    name="Tamper causes 422",
                    passed=False,
                    message="SECURITY ISSUE: Tampered evidence still returns 200!",
                )
            else:
                return CheckResult(
                    name="Tamper causes 422",
                    passed=False,
                    message=f"Unexpected status {resp.status_code}: {resp.text[:200]}",
                )

        except httpx.RequestError as e:
            return CheckResult(
                name="Tamper causes 422",
                passed=False,
                message=f"Request failed: {type(e).__name__}",
            )


def resolve_compose_file() -> str:
    """Resolve the compose file path using runtime logic."""
    try:
        from app.runtime import _resolve_compose_path
        return str(_resolve_compose_path())
    except Exception:
        # Fallback to default location
        repo_root = Path(__file__).resolve().parents[3]
        return str(repo_root / "octolab-hackvm" / "docker-compose.yml")


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke test for Authoritative Evidence v1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic test (requires running lab)
  python3 -m app.scripts.smoke_evidence_v1 --lab-id <uuid> --token "$TOKEN"

  # With tamper test (WARNING: mutates evidence)
  python3 -m app.scripts.smoke_evidence_v1 --lab-id <uuid> --token "$TOKEN" --tamper

  # Debug mode with command printing
  python3 -m app.scripts.smoke_evidence_v1 --lab-id <uuid> --token "$TOKEN" --print-commands
""",
    )

    parser.add_argument(
        "--lab-id",
        required=True,
        help="Lab UUID to test",
    )
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:8000",
        help="API base URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--token",
        required=True,
        help="Bearer token for API authentication",
    )
    parser.add_argument(
        "--compose-file",
        default=None,
        help="Path to docker-compose.yml (auto-detected if not specified)",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Compose project name (default: octolab_<lab-id>)",
    )
    parser.add_argument(
        "--auth-volume",
        default=None,
        help="Auth evidence volume name (default: from DB or octolab_<lab-id>_evidence_auth)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output path for downloaded bundle (default: /tmp/octolab_evidence_<labid>.zip)",
    )
    parser.add_argument(
        "--tamper",
        action="store_true",
        help="Run tamper test (WARNING: mutates evidence volume)",
    )
    parser.add_argument(
        "--tamper-file",
        default="network/network.json",
        help="File to tamper with (relative to auth volume, default: network/network.json)",
    )
    parser.add_argument(
        "--no-unzip",
        action="store_true",
        help="Skip unzip verification of downloaded bundle",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="Timeout for API calls (default: 30)",
    )
    parser.add_argument(
        "--docker-timeout",
        type=float,
        default=60.0,
        help="Timeout for docker operations (default: 60)",
    )
    parser.add_argument(
        "--print-commands",
        action="store_true",
        help="Print sanitized commands being executed",
    )

    args = parser.parse_args()

    # Validate lab_id is a valid UUID
    try:
        lab_uuid = UUID(args.lab_id)
        lab_id = str(lab_uuid)
    except ValueError:
        print(f"[FAIL] Invalid lab ID: {args.lab_id}")
        return 1

    print("=" * 60)
    print("Evidence v1 Smoke Test")
    print("=" * 60)
    print(f"Lab ID: {lab_id}")
    print(f"API Base: {args.api_base}")
    print()

    results: list[CheckResult] = []

    # -------------------------------------------------------------------------
    # Step 1: Resolve identifiers
    # -------------------------------------------------------------------------
    print("[1] Resolving identifiers...")

    project_name = args.project or f"octolab_{lab_id}"
    print(f"    Project: {project_name}")

    compose_file = args.compose_file or resolve_compose_file()
    print(f"    Compose: {compose_file}")

    if not Path(compose_file).exists():
        print(f"[FAIL] Compose file not found: {compose_file}")
        return 1

    # Get auth volume from DB or use deterministic name
    db_auth_vol, db_seal_status = await fetch_lab_evidence_fields(lab_id)

    auth_volume = args.auth_volume or db_auth_vol or f"octolab_{lab_id}_evidence_auth"
    print(f"    Auth Volume: {auth_volume}")

    out_path = args.out or f"/tmp/octolab_evidence_{lab_id}.zip"
    print(f"    Output: {out_path}")
    print()

    # -------------------------------------------------------------------------
    # Step 2: API preflight - check lab exists
    # -------------------------------------------------------------------------
    print("[2] API preflight...")

    success, lab_data, error = await fetch_lab_from_api(
        args.api_base, lab_id, args.token, args.timeout_seconds
    )

    if not success:
        result = CheckResult("API lab fetch", False, error)
        print_result(result)
        return 1

    result = CheckResult("API lab fetch", True, "")
    results.append(result)
    print_result(result)

    # Print lab info (without owner_id for security)
    print(f"    Status: {lab_data.get('status')}")
    if db_seal_status:
        print(f"    Seal Status: {db_seal_status}")
    print()

    # -------------------------------------------------------------------------
    # Step 3: Check OctoBox cannot access auth volume
    # -------------------------------------------------------------------------
    print("[3] Checking OctoBox auth isolation...")

    result = check_octobox_cannot_access_auth(
        compose_file, project_name, args.docker_timeout, args.print_commands
    )
    results.append(result)
    print_result(result)
    print()

    # -------------------------------------------------------------------------
    # Step 4: Check authoritative evidence exists
    # -------------------------------------------------------------------------
    print("[4] Checking auth evidence exists...")

    result = check_auth_evidence_exists(
        auth_volume, args.docker_timeout, args.print_commands
    )
    results.append(result)
    print_result(result)
    print()

    # -------------------------------------------------------------------------
    # Step 5: Check seal status
    # -------------------------------------------------------------------------
    print("[5] Checking seal status...")

    # Use DB value if we have it, otherwise we can't check this reliably
    seal_status = db_seal_status
    if seal_status is None:
        result = CheckResult(
            "Seal status SEALED",
            False,
            "Could not read seal status from DB (ensure DB is accessible)",
        )
    else:
        result = check_seal_status(seal_status)
    results.append(result)
    print_result(result)
    print()

    # -------------------------------------------------------------------------
    # Step 6: Download verified bundle
    # -------------------------------------------------------------------------
    print("[6] Downloading verified bundle...")

    result = await check_verified_bundle_download(
        args.api_base,
        lab_id,
        args.token,
        out_path,
        args.timeout_seconds,
        args.no_unzip,
        args.print_commands,
    )
    results.append(result)
    print_result(result)
    print()

    # -------------------------------------------------------------------------
    # Step 7: Optional tamper test
    # -------------------------------------------------------------------------
    if args.tamper:
        print("=" * 60)
        print("WARNING: TAMPER TEST")
        print("This will MUTATE authoritative evidence for lab {lab_id}")
        print("Use ONLY on disposable labs!")
        print("=" * 60)
        print()

        print("[7a] Applying tamper...")
        result = tamper_auth_evidence(
            auth_volume, args.tamper_file, args.docker_timeout, args.print_commands
        )
        results.append(result)
        print_result(result)

        if result.passed:
            print()
            print("[7b] Verifying tamper causes 422...")
            result = await check_tamper_causes_422(
                args.api_base, lab_id, args.token, args.timeout_seconds, args.print_commands
            )
            results.append(result)
            print_result(result)
        print()

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)

    for result in results:
        status = "[PASS]" if result.passed else "[FAIL]"
        print(f"  {status} {result.name}")

    print()
    print(f"Passed: {passed}/{len(results)}")

    if failed > 0:
        print(f"Failed: {failed}")
        return 1

    print("All checks passed!")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
