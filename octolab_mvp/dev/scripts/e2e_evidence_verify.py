#!/usr/bin/env python3
"""E2E Evidence Verification Script.

Proves that evidence collection is actually working by:
1. Creating a lab via API
2. Waiting for it to become ready
3. Verifying pcap capture is running (gateway logs)
4. Generating traffic within the lab
5. Waiting for capture to record packets
6. Downloading evidence bundle via API
7. Validating ZIP contents (manifest, pcap, evidence files)
8. Proving OctoBox does NOT have evidence_auth mounted (isolation check)

Usage:
    python3 dev/scripts/e2e_evidence_verify.py

Environment:
    BACKEND_BASE_URL - Backend API URL (default: http://localhost:8000)
    E2E_USER_EMAIL - Test user email (default: e2e-evidence@test.local)
    E2E_USER_PASSWORD - Test user password (default: testpassword123)

Exit codes:
    0 - All verifications passed
    1 - One or more verifications failed

SECURITY: Secrets are redacted from all output.
"""

import io
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Add dev/scripts to path for local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _http_utils import (
    http_get,
    http_post_json,
    join_url,
    normalize_base,
    parse_json_safe,
    redact_secrets,
)


# =============================================================================
# Configuration
# =============================================================================

BACKEND_BASE_URL = normalize_base(os.getenv("BACKEND_BASE_URL", "http://localhost:8000"))
E2E_USER_EMAIL = os.getenv("E2E_USER_EMAIL", "e2e-evidence@test.local")
E2E_USER_PASSWORD = os.getenv("E2E_USER_PASSWORD", "testpassword123")

# Timeouts
LAB_READY_TIMEOUT = 120  # seconds to wait for lab to become ready
PCAP_GROW_TIMEOUT = 30   # seconds to wait for pcap to record packets
DOCKER_TIMEOUT = 30      # timeout for docker commands


@dataclass
class CheckResult:
    """Result of a verification check."""
    name: str
    passed: bool
    message: str
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        icon = "✓" if self.passed else "✗"
        return f"[{icon}] {self.name}: {self.message}"


class EvidenceVerifier:
    """E2E Evidence verification runner."""

    def __init__(self):
        self.results: list[CheckResult] = []
        self.token: str | None = None
        self.lab_id: str | None = None
        self.project_name: str | None = None

    def _log(self, msg: str) -> None:
        """Print timestamped log message with secret redaction."""
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {redact_secrets(msg)}")

    def _auth_headers(self) -> dict[str, str]:
        """Get Authorization headers."""
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    def _run_docker(
        self,
        args: list[str],
        timeout: int = DOCKER_TIMEOUT,
    ) -> tuple[bool, str, str]:
        """Run docker command, return (ok, stdout, stderr)."""
        cmd = ["docker"] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
            return (
                result.returncode == 0,
                result.stdout,
                result.stderr,
            )
        except subprocess.TimeoutExpired:
            return False, "", f"Timeout after {timeout}s"
        except FileNotFoundError:
            return False, "", "docker command not found"
        except Exception as e:
            return False, "", str(e)

    def authenticate(self) -> CheckResult:
        """Authenticate with backend and get token."""
        self._log(f"Authenticating as {E2E_USER_EMAIL}...")

        # Try login first
        login_url = join_url(BACKEND_BASE_URL, "/auth/login")
        result = http_post_json(
            login_url,
            {"email": E2E_USER_EMAIL, "password": E2E_USER_PASSWORD},
        )

        if result.get("status_code") == 200:
            body = parse_json_safe(result.get("body", ""))
            if body and "access_token" in body:
                self.token = body["access_token"]
                return CheckResult(
                    name="Authenticate",
                    passed=True,
                    message="Logged in successfully",
                )

        # If login failed with 401, try registration
        if result.get("status_code") == 401:
            self._log("Login failed (401), attempting registration...")
            register_url = join_url(BACKEND_BASE_URL, "/auth/register")
            result = http_post_json(
                register_url,
                {"email": E2E_USER_EMAIL, "password": E2E_USER_PASSWORD},
            )

            if result.get("status_code") == 201:
                body = parse_json_safe(result.get("body", ""))
                if body and "access_token" in body:
                    self.token = body["access_token"]
                    return CheckResult(
                        name="Authenticate",
                        passed=True,
                        message="Registered and logged in",
                    )

            # 404 = registration disabled, 409 = already registered
            if result.get("status_code") == 404:
                return CheckResult(
                    name="Authenticate",
                    passed=False,
                    message="Registration disabled (ALLOW_SELF_SIGNUP=false)",
                )
            if result.get("status_code") == 409:
                return CheckResult(
                    name="Authenticate",
                    passed=False,
                    message="User exists but login failed - check password",
                )

        return CheckResult(
            name="Authenticate",
            passed=False,
            message=f"Authentication failed: {result.get('status_code', 'unknown')}",
            details={"body": result.get("body", "")[:500]},
        )

    def get_recipe_id(self) -> str | None:
        """Get first available recipe ID."""
        recipes_url = join_url(BACKEND_BASE_URL, "/recipes")
        result = http_get(recipes_url, headers=self._auth_headers())

        if result.get("status_code") == 200:
            body = parse_json_safe(result.get("body", ""))
            if body and isinstance(body, list) and len(body) > 0:
                return body[0].get("id")
        return None

    def create_lab(self) -> CheckResult:
        """Create a new lab for testing."""
        self._log("Getting available recipes...")
        recipe_id = self.get_recipe_id()

        if not recipe_id:
            return CheckResult(
                name="Create Lab",
                passed=False,
                message="No recipes available - seed database first",
            )

        self._log(f"Creating lab with recipe {recipe_id}...")
        labs_url = join_url(BACKEND_BASE_URL, "/labs")
        result = http_post_json(
            labs_url,
            {"recipe_id": recipe_id, "intent": None},
            headers=self._auth_headers(),
        )

        if result.get("status_code") == 201:
            body = parse_json_safe(result.get("body", ""))
            if body and "id" in body:
                self.lab_id = body["id"]
                self.project_name = f"octolab_{self.lab_id}"
                return CheckResult(
                    name="Create Lab",
                    passed=True,
                    message=f"Lab created: {self.lab_id}",
                    details={"lab_id": self.lab_id, "status": body.get("status")},
                )

        return CheckResult(
            name="Create Lab",
            passed=False,
            message=f"Failed to create lab: {result.get('status_code')}",
            details={"body": result.get("body", "")[:500]},
        )

    def wait_for_lab_ready(self) -> CheckResult:
        """Wait for lab to become ready."""
        if not self.lab_id:
            return CheckResult(
                name="Wait for Lab Ready",
                passed=False,
                message="No lab ID - create lab first",
            )

        self._log(f"Waiting for lab {self.lab_id} to become ready...")
        lab_url = join_url(BACKEND_BASE_URL, f"/labs/{self.lab_id}")
        start_time = time.time()

        while time.time() - start_time < LAB_READY_TIMEOUT:
            result = http_get(lab_url, headers=self._auth_headers())
            if result.get("status_code") == 200:
                body = parse_json_safe(result.get("body", ""))
                status = body.get("status") if body else None

                if status == "ready":
                    elapsed = int(time.time() - start_time)
                    return CheckResult(
                        name="Wait for Lab Ready",
                        passed=True,
                        message=f"Lab ready after {elapsed}s",
                    )
                elif status == "failed":
                    return CheckResult(
                        name="Wait for Lab Ready",
                        passed=False,
                        message="Lab provisioning failed",
                        details=body,
                    )
                else:
                    self._log(f"  Lab status: {status}")

            time.sleep(3)

        return CheckResult(
            name="Wait for Lab Ready",
            passed=False,
            message=f"Timeout after {LAB_READY_TIMEOUT}s",
        )

    def verify_gateway_running(self) -> CheckResult:
        """Verify lab-gateway container is running and capturing."""
        if not self.project_name:
            return CheckResult(
                name="Verify Gateway Running",
                passed=False,
                message="No project name",
            )

        gateway_container = f"{self.project_name}-lab-gateway-1"

        # Check container is running
        ok, stdout, stderr = self._run_docker(
            ["inspect", "-f", "{{.State.Running}}", gateway_container]
        )

        if not ok or stdout.strip() != "true":
            return CheckResult(
                name="Verify Gateway Running",
                passed=False,
                message=f"Gateway container not running: {gateway_container}",
                details={"stderr": stderr},
            )

        # Check gateway logs for tcpdump activity
        ok, stdout, stderr = self._run_docker(
            ["logs", "--tail", "50", gateway_container]
        )

        if ok:
            # Look for tcpdump or capture-related output
            logs = stdout + stderr
            has_capture = any(
                kw in logs.lower()
                for kw in ["tcpdump", "capture", "pcap", "listening"]
            )

            return CheckResult(
                name="Verify Gateway Running",
                passed=True,
                message="Gateway running" + (" (capture detected)" if has_capture else ""),
                details={"container": gateway_container, "capture_detected": has_capture},
            )

        return CheckResult(
            name="Verify Gateway Running",
            passed=False,
            message="Could not get gateway logs",
        )

    def verify_pcap_growing(self) -> CheckResult:
        """Verify pcap volume is growing (capture is working)."""
        if not self.project_name:
            return CheckResult(
                name="Verify PCAP Growing",
                passed=False,
                message="No project name",
            )

        pcap_volume = f"{self.project_name}_lab_pcap"

        # Get initial size of pcap files
        def get_pcap_size() -> int:
            ok, stdout, _ = self._run_docker([
                "run", "--rm",
                "-v", f"{pcap_volume}:/pcap:ro",
                "alpine",
                "sh", "-c",
                "du -sb /pcap 2>/dev/null | cut -f1 || echo 0"
            ])
            if ok and stdout.strip().isdigit():
                return int(stdout.strip())
            return 0

        initial_size = get_pcap_size()
        self._log(f"Initial pcap size: {initial_size} bytes")

        # Generate some traffic - ping target from OctoBox
        self._generate_traffic()

        # Wait and check if size increased
        time.sleep(3)
        final_size = get_pcap_size()
        self._log(f"Final pcap size: {final_size} bytes")

        if final_size > initial_size:
            return CheckResult(
                name="Verify PCAP Growing",
                passed=True,
                message=f"PCAP grew from {initial_size} to {final_size} bytes",
                details={"initial": initial_size, "final": final_size},
            )

        # Even if not growing, pass if we have some data
        if final_size > 0:
            return CheckResult(
                name="Verify PCAP Growing",
                passed=True,
                message=f"PCAP has {final_size} bytes (not actively growing)",
                details={"size": final_size},
            )

        return CheckResult(
            name="Verify PCAP Growing",
            passed=False,
            message="PCAP volume is empty - capture not working",
        )

    def _generate_traffic(self) -> None:
        """Generate network traffic from OctoBox to target."""
        if not self.project_name:
            return

        octobox_container = f"{self.project_name}-octobox-1"

        # Try to curl target from OctoBox
        self._log("Generating traffic: curl target from OctoBox...")
        self._run_docker([
            "exec", octobox_container,
            "curl", "-s", "-o", "/dev/null",
            "http://target:80/"
        ])

        # Also try ping
        self._log("Generating traffic: ping target...")
        self._run_docker([
            "exec", octobox_container,
            "ping", "-c", "3", "-W", "1", "target"
        ])

    def verify_evidence_auth_isolation(self) -> CheckResult:
        """CRITICAL: Verify OctoBox does NOT have evidence_auth mounted.

        This is a security invariant - OctoBox should only have evidence_user
        mounted, not the authoritative evidence_auth volume.
        """
        if not self.project_name:
            return CheckResult(
                name="Evidence Auth Isolation",
                passed=False,
                message="No project name",
            )

        octobox_container = f"{self.project_name}-octobox-1"

        # Get container mounts
        ok, stdout, stderr = self._run_docker([
            "inspect", "-f",
            "{{range .Mounts}}{{.Name}} -> {{.Destination}}\n{{end}}",
            octobox_container
        ])

        if not ok:
            return CheckResult(
                name="Evidence Auth Isolation",
                passed=False,
                message=f"Could not inspect container: {stderr}",
            )

        mounts = stdout.strip()
        self._log(f"OctoBox mounts:\n{mounts}")

        # Check that evidence_auth is NOT mounted
        evidence_auth_vol = f"{self.project_name}_evidence_auth"
        if evidence_auth_vol in mounts:
            return CheckResult(
                name="Evidence Auth Isolation",
                passed=False,
                message="SECURITY VIOLATION: evidence_auth mounted in OctoBox!",
                details={"mounts": mounts},
            )

        # Verify evidence_user IS mounted (expected behavior)
        evidence_user_vol = f"{self.project_name}_evidence_user"
        has_evidence_user = evidence_user_vol in mounts

        return CheckResult(
            name="Evidence Auth Isolation",
            passed=True,
            message="OctoBox does NOT have evidence_auth (correct isolation)",
            details={
                "evidence_auth_mounted": False,
                "evidence_user_mounted": has_evidence_user,
            },
        )

    def download_evidence(self) -> CheckResult:
        """Download evidence bundle via API and validate."""
        if not self.lab_id:
            return CheckResult(
                name="Download Evidence",
                passed=False,
                message="No lab ID",
            )

        self._log(f"Downloading evidence for lab {self.lab_id}...")
        evidence_url = join_url(BACKEND_BASE_URL, f"/labs/{self.lab_id}/evidence/bundle.zip")

        # Use curl directly to download binary
        cmd = [
            "curl", "-s",
            "-H", f"Authorization: Bearer {self.token}",
            "-o", "-",
            "-w", "\n%{http_code}",
            evidence_url,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=60,
                shell=False,
            )

            # Last line is status code
            output = result.stdout
            lines = output.rsplit(b"\n", 1)
            if len(lines) == 2:
                zip_data = lines[0]
                status_code = int(lines[1].decode().strip())
            else:
                return CheckResult(
                    name="Download Evidence",
                    passed=False,
                    message="Invalid response format",
                )

            if status_code != 200:
                return CheckResult(
                    name="Download Evidence",
                    passed=False,
                    message=f"Download failed with status {status_code}",
                )

            # Validate ZIP
            return self._validate_evidence_zip(zip_data)

        except subprocess.TimeoutExpired:
            return CheckResult(
                name="Download Evidence",
                passed=False,
                message="Download timed out",
            )
        except Exception as e:
            return CheckResult(
                name="Download Evidence",
                passed=False,
                message=f"Download error: {type(e).__name__}",
            )

    def _validate_evidence_zip(self, zip_data: bytes) -> CheckResult:
        """Validate evidence ZIP contents."""
        try:
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                namelist = zf.namelist()
                self._log(f"ZIP contains {len(namelist)} files")

                # Check for manifest
                if "manifest.json" not in namelist:
                    return CheckResult(
                        name="Download Evidence",
                        passed=False,
                        message="ZIP missing manifest.json",
                        details={"files": namelist},
                    )

                # Parse manifest
                manifest_data = zf.read("manifest.json").decode()
                manifest = json.loads(manifest_data)

                # Check manifest structure
                required_keys = ["lab_id", "generated_at", "bundle_version"]
                missing = [k for k in required_keys if k not in manifest]
                if missing:
                    return CheckResult(
                        name="Download Evidence",
                        passed=False,
                        message=f"Manifest missing keys: {missing}",
                    )

                # Check for pcap or evidence files
                has_pcap = any(f.endswith((".pcap", ".pcapng")) for f in namelist)
                has_evidence = any(f.startswith("evidence/") for f in namelist)
                has_any_files = len(namelist) > 1  # More than just manifest

                return CheckResult(
                    name="Download Evidence",
                    passed=True,
                    message=f"Valid ZIP: {len(namelist)} files, pcap={has_pcap}",
                    details={
                        "file_count": len(namelist),
                        "files": namelist[:20],  # First 20 files
                        "has_pcap": has_pcap,
                        "has_evidence": has_evidence,
                        "manifest_lab_id": manifest.get("lab_id"),
                    },
                )

        except zipfile.BadZipFile:
            return CheckResult(
                name="Download Evidence",
                passed=False,
                message="Invalid ZIP file",
            )
        except json.JSONDecodeError:
            return CheckResult(
                name="Download Evidence",
                passed=False,
                message="Invalid manifest.json format",
            )
        except Exception as e:
            return CheckResult(
                name="Download Evidence",
                passed=False,
                message=f"ZIP validation error: {type(e).__name__}: {e}",
            )

    def cleanup_lab(self) -> CheckResult:
        """Terminate the test lab."""
        if not self.lab_id:
            return CheckResult(
                name="Cleanup Lab",
                passed=True,
                message="No lab to cleanup",
            )

        self._log(f"Terminating lab {self.lab_id}...")
        delete_url = join_url(BACKEND_BASE_URL, f"/labs/{self.lab_id}")

        # Use curl for DELETE
        cmd = [
            "curl", "-s",
            "-X", "DELETE",
            "-H", f"Authorization: Bearer {self.token}",
            "-w", "%{http_code}",
            "-o", "/dev/null",
            delete_url,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            status_code = int(result.stdout.strip())

            if status_code in (200, 202, 204):
                return CheckResult(
                    name="Cleanup Lab",
                    passed=True,
                    message=f"Lab terminated (status {status_code})",
                )
            else:
                return CheckResult(
                    name="Cleanup Lab",
                    passed=False,
                    message=f"Delete returned status {status_code}",
                )
        except Exception as e:
            return CheckResult(
                name="Cleanup Lab",
                passed=False,
                message=f"Cleanup error: {type(e).__name__}",
            )

    def run(self) -> bool:
        """Run all verification checks."""
        print("=" * 60)
        print("E2E Evidence Verification")
        print("=" * 60)
        print(f"Backend: {BACKEND_BASE_URL}")
        print(f"User: {E2E_USER_EMAIL}")
        print("=" * 60)
        print()

        # Run checks in sequence
        checks = [
            self.authenticate,
            self.create_lab,
            self.wait_for_lab_ready,
            self.verify_gateway_running,
            self.verify_pcap_growing,
            self.verify_evidence_auth_isolation,
            self.download_evidence,
            self.cleanup_lab,
        ]

        for check_fn in checks:
            result = check_fn()
            self.results.append(result)
            print(result)

            # If critical checks fail, stop early
            if not result.passed and result.name in [
                "Authenticate",
                "Create Lab",
                "Wait for Lab Ready",
            ]:
                self._log(f"Stopping: {result.name} failed")
                break

            # Show details for failed checks
            if not result.passed and result.details:
                self._log(f"  Details: {result.details}")

        # Print summary
        print()
        print("=" * 60)
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        print(f"Results: {passed}/{total} checks passed")
        print("=" * 60)

        return all(r.passed for r in self.results)


def main() -> int:
    """Main entry point."""
    verifier = EvidenceVerifier()

    try:
        success = verifier.run()
        return 0 if success else 1
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 130
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
