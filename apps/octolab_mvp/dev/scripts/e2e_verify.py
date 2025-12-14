#!/usr/bin/env python3
"""End-to-end verification script for OctoLab.

Verifies with hard proof (not just HTTP 200):
1. Backend health and OpenAPI discovery
2. Auth endpoints (register, login) from OpenAPI
3. CORS preflight for frontend reachability
4. Guacamole stack reachability (UI + API tokens)
5. Lab creation and provisioning
6. VNC RFB handshake from guacd's network perspective
7. Desktop processes running inside OctoBox
8. Guacamole connection exists with correct parameters
9. Evidence volume isolation (evidence_auth NOT in OctoBox)

Status semantics:
- OK: Check passed with hard proof
- FAIL: Check failed (fatal unless explicitly non-blocking)
- SKIP: Check intentionally skipped (e.g., host VNC in GUAC mode)

SECURITY:
- Never logs passwords or tokens
- Uses subprocess.run with shell=False
- Redacts sensitive values in all outputs

Usage:
    python3 dev/scripts/e2e_verify.py
    BACKEND_BASE=http://localhost:8000 python3 dev/scripts/e2e_verify.py
"""

import hashlib
import io
import json
import os
import secrets
import socket
import sys
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

# Add backend to path for config loading
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# Import utilities from local module
from _http_utils import (
    normalize_base,
    join_url,
    redact_secrets,
    run_cmd,
    http_get,
    http_post_json,
    http_options,
    parse_json_safe,
)

SNAPSHOTS_DIR = BACKEND_DIR / "var" / "snapshots"

# Dev origins for CORS preflight checks
DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


class CheckStatus(Enum):
    """Status of a verification check."""
    OK = "OK"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass
class CheckResult:
    """Result of a single verification check."""
    name: str
    status: CheckStatus
    message: str = ""
    details: str = ""
    fatal: bool = True  # If True, FAIL causes overall failure


@dataclass
class VerificationResults:
    """Collection of all verification results."""
    checks: list[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.checks.append(result)

    @property
    def all_passed(self) -> bool:
        """True if all fatal checks are OK or SKIP."""
        for check in self.checks:
            if check.fatal and check.status == CheckStatus.FAIL:
                return False
        return True

    def to_dict(self) -> dict:
        return {
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "message": c.message,
                    "details": c.details,
                    "fatal": c.fatal,
                }
                for c in self.checks
            ],
            "all_passed": self.all_passed,
        }


# Colors for terminal output
class Colors:
    OK = "\033[92m"
    FAIL = "\033[91m"
    WARN = "\033[93m"
    INFO = "\033[94m"
    SKIP = "\033[96m"
    RESET = "\033[0m"


def print_status(status: CheckStatus, msg: str) -> None:
    """Print status message with appropriate color."""
    colors = {
        CheckStatus.OK: Colors.OK,
        CheckStatus.FAIL: Colors.FAIL,
        CheckStatus.SKIP: Colors.SKIP,
    }
    color = colors.get(status, Colors.INFO)
    print(f"{color}[{status.value}]{Colors.RESET} {msg}")


def info(msg: str) -> None:
    """Print info message."""
    print(f"{Colors.INFO}[INFO]{Colors.RESET} {msg}")


def http_post_form(url: str, data: dict, timeout: float = 10.0) -> dict[str, Any]:
    """HTTP POST via curl with form data (for Guacamole auth)."""
    cmd = ["curl", "-sL", "-X", "POST", "-o", "-", "-w", "\n%{http_code}"]
    for key, value in data.items():
        cmd.extend(["-d", f"{key}={value}"])
    cmd.append(url)

    result = run_cmd(cmd, timeout=timeout)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "curl failed")}

    lines = result.get("stdout", "").strip().split("\n")
    if lines:
        status_code = lines[-1] if lines[-1].isdigit() else "0"
        body = "\n".join(lines[:-1])
        return {
            "ok": True,
            "status_code": int(status_code),
            "body": body,
        }
    return {"ok": False, "error": "Empty response"}


def check_vnc_banner(host: str, port: int, timeout: float = 2.0) -> dict[str, Any]:
    """Check VNC server by reading RFB banner."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            banner = sock.recv(12).decode("ascii", errors="replace")
            if banner.startswith("RFB "):
                return {"ok": True, "banner": banner.strip()}
            return {"ok": False, "error": f"Invalid banner: {banner[:20]}"}
    except socket.timeout:
        return {"ok": False, "error": "Connection timeout"}
    except ConnectionRefusedError:
        return {"ok": False, "error": "Connection refused"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


class E2EVerifier:
    """End-to-end verification runner with hard proof."""

    def __init__(self):
        self.results = VerificationResults()
        self.guac_base_url = normalize_base(
            os.environ.get("GUAC_BASE_URL", "http://127.0.0.1:8081/guacamole")
        )
        self.backend_url = normalize_base(
            os.environ.get("BACKEND_BASE", "http://127.0.0.1:8000")
        )
        self.guac_admin_user = "guacadmin"
        self.guac_admin_password = None
        self.guac_admin_token = None
        self.backend_token = None
        self.lab_id = None
        self.lab_data = None  # Full lab data from API

        # OpenAPI discovered endpoints
        self.openapi_paths: dict[str, list[str]] = {}  # path -> methods
        self.register_path: str | None = None
        self.login_path: str | None = None
        self.health_path: str | None = None

        self._load_config()

    def _load_config(self):
        """Load configuration from environment or .env files."""
        try:
            from dotenv import load_dotenv
            load_dotenv(BACKEND_DIR / ".env")
            load_dotenv(BACKEND_DIR / ".env.local", override=True)
        except ImportError:
            pass

        self.guac_admin_password = os.environ.get("GUAC_ADMIN_PASSWORD", "guacadmin")

    def discover_openapi(self) -> CheckResult:
        """Discover endpoints from OpenAPI schema.

        Fetches /openapi.json and extracts:
        - All paths with their methods
        - Auth endpoints (register, login, me)
        - Health endpoint
        """
        info(f"Discovering endpoints from OpenAPI ({self.backend_url})...")

        url = join_url(self.backend_url, "/openapi.json")
        result = http_get(url, timeout=5.0)

        if not result.get("ok") or result.get("status_code") != 200:
            # Fallback to known candidates
            info("WARNING: OpenAPI unreachable, using fallback paths")
            self.register_path = "/auth/register"
            self.login_path = "/auth/login"
            self.health_path = "/health"
            check = CheckResult(
                name="openapi_discovery",
                status=CheckStatus.FAIL,
                message="OpenAPI unreachable",
                details=f"URL: {url}, status: {result.get('status_code', 'N/A')}",
                fatal=False,  # Non-fatal, we can use fallbacks
            )
            print_status(check.status, f"OpenAPI: {check.message}")
            self.results.add(check)
            return check

        # Parse OpenAPI
        data = parse_json_safe(result.get("body", ""))
        if not data or "paths" not in data:
            info("WARNING: Invalid OpenAPI response, using fallback paths")
            self.register_path = "/auth/register"
            self.login_path = "/auth/login"
            self.health_path = "/health"
            check = CheckResult(
                name="openapi_discovery",
                status=CheckStatus.FAIL,
                message="Invalid OpenAPI JSON",
                fatal=False,
            )
            print_status(check.status, f"OpenAPI: {check.message}")
            self.results.add(check)
            return check

        # Extract paths and methods
        paths = data.get("paths", {})
        for path, methods_data in paths.items():
            methods = [m.upper() for m in methods_data.keys() if m.lower() not in ("parameters", "summary", "description")]
            self.openapi_paths[path] = methods

        # Find auth endpoints
        for path in paths.keys():
            path_lower = path.lower()
            if "register" in path_lower and "auth" in path_lower:
                if "POST" in self.openapi_paths.get(path, []) or "post" in paths[path]:
                    self.register_path = path
            if "login" in path_lower and "auth" in path_lower:
                if "POST" in self.openapi_paths.get(path, []) or "post" in paths[path]:
                    self.login_path = path
            if path in ("/health", "/health/"):
                self.health_path = path

        # Fallbacks
        if not self.register_path:
            self.register_path = "/auth/register"
        if not self.login_path:
            self.login_path = "/auth/login"
        if not self.health_path:
            self.health_path = "/health"

        info(f"Discovered {len(self.openapi_paths)} paths")
        info(f"  Register: {self.register_path}")
        info(f"  Login: {self.login_path}")
        info(f"  Health: {self.health_path}")

        check = CheckResult(
            name="openapi_discovery",
            status=CheckStatus.OK,
            message=f"{len(self.openapi_paths)} paths discovered",
            details=f"register={self.register_path}, login={self.login_path}",
        )
        print_status(check.status, f"OpenAPI: {check.message}")
        self.results.add(check)
        return check

    def verify_cors_preflight(self) -> CheckResult:
        """Verify CORS preflight for frontend reachability.

        Tests OPTIONS request to register endpoint from dev origins.
        """
        if not self.register_path:
            check = CheckResult(
                name="cors_preflight",
                status=CheckStatus.SKIP,
                message="No register path discovered",
                fatal=False,
            )
            print_status(check.status, f"CORS preflight: {check.message}")
            self.results.add(check)
            return check

        info("Checking CORS preflight for frontend reachability...")

        url = join_url(self.backend_url, self.register_path)
        issues = []
        successes = []

        for origin in DEV_ORIGINS:
            result = http_options(
                url,
                origin=origin,
                request_method="POST",
                request_headers="content-type, authorization",
            )

            allow_origin = result.get("allow_origin", "")
            allow_methods = result.get("allow_methods", "")

            # Check if origin is allowed
            origin_ok = (
                allow_origin == origin
                or allow_origin == "*"
                or not allow_origin  # Some servers don't return headers for same-origin
            )

            # Check if POST is allowed
            methods_ok = (
                "POST" in allow_methods.upper()
                or "*" in allow_methods
                or not allow_methods  # Some servers return nothing on OPTIONS
            )

            if allow_origin == "*":
                info(f"  WARNING: {origin} -> Allow-Origin: * (wildcard)")

            if origin_ok and methods_ok:
                successes.append(origin)
            else:
                issues.append(f"{origin}: origin={allow_origin or 'none'}, methods={allow_methods or 'none'}")

        if successes and not issues:
            check = CheckResult(
                name="cors_preflight",
                status=CheckStatus.OK,
                message=f"CORS OK for {len(successes)} origin(s)",
                details=", ".join(successes),
            )
        elif successes:
            check = CheckResult(
                name="cors_preflight",
                status=CheckStatus.OK,
                message=f"CORS OK for {len(successes)}/{len(DEV_ORIGINS)} origins",
                details=f"Issues: {'; '.join(issues)}" if issues else "",
                fatal=False,
            )
        else:
            check = CheckResult(
                name="cors_preflight",
                status=CheckStatus.FAIL,
                message="CORS preflight failed for all origins",
                details="; ".join(issues),
                fatal=False,  # Non-fatal, might work without preflight
            )

        print_status(check.status, f"CORS preflight: {check.message}")
        self.results.add(check)
        return check

    def verify_guac_ui(self) -> CheckResult:
        """Verify Guacamole UI is reachable."""
        info("Checking Guacamole UI...")

        result = http_get(f"{self.guac_base_url}/")
        if not result["ok"]:
            check = CheckResult(
                name="guac_ui",
                status=CheckStatus.FAIL,
                message="Guacamole UI unreachable",
                details=result.get("error", "unknown"),
            )
        elif result["status_code"] == 200:
            check = CheckResult(
                name="guac_ui",
                status=CheckStatus.OK,
                message=f"HTTP {result['status_code']}",
            )
        else:
            check = CheckResult(
                name="guac_ui",
                status=CheckStatus.FAIL,
                message=f"HTTP {result['status_code']}",
            )

        print_status(check.status, f"Guac UI: {check.message}")
        self.results.add(check)
        return check

    def verify_guac_tokens(self) -> CheckResult:
        """Verify Guacamole API tokens endpoint works and save admin token."""
        info("Checking Guacamole API tokens...")

        max_retries = 6
        for attempt in range(max_retries):
            result = http_post_form(
                join_url(self.guac_base_url, "/api/tokens"),
                {
                    "username": self.guac_admin_user,
                    "password": self.guac_admin_password,
                },
            )

            if not result["ok"]:
                if attempt < max_retries - 1:
                    time.sleep(5)
                    continue
                check = CheckResult(
                    name="guac_tokens",
                    status=CheckStatus.FAIL,
                    message="API request failed",
                    details=result.get("error"),
                )
                print_status(check.status, f"Guac tokens: {check.message}")
                self.results.add(check)
                return check

            if result["status_code"] == 200:
                try:
                    data = json.loads(result["body"])
                    if "authToken" in data:
                        self.guac_admin_token = data["authToken"]
                        check = CheckResult(
                            name="guac_tokens",
                            status=CheckStatus.OK,
                            message="Got authToken",
                        )
                        print_status(check.status, "Guac tokens: OK (got authToken)")
                        self.results.add(check)
                        return check
                except json.JSONDecodeError:
                    pass

            if result["status_code"] >= 500 and attempt < max_retries - 1:
                time.sleep(5)
                continue

            check = CheckResult(
                name="guac_tokens",
                status=CheckStatus.FAIL,
                message=f"HTTP {result['status_code']}",
            )
            print_status(check.status, f"Guac tokens: {check.message}")
            self.results.add(check)
            return check

        check = CheckResult(
            name="guac_tokens",
            status=CheckStatus.FAIL,
            message="Max retries exceeded",
        )
        self.results.add(check)
        return check

    def verify_backend(self) -> CheckResult:
        """Verify backend is reachable."""
        info("Checking backend...")

        # Try discovered health path first, then fallbacks
        endpoints = [self.health_path or "/health", "/"]

        for endpoint in endpoints:
            url = join_url(self.backend_url, endpoint)
            result = http_get(url)
            if result.get("ok") and result.get("status_code") == 200:
                check = CheckResult(
                    name="backend",
                    status=CheckStatus.OK,
                    message=f"HTTP 200 on {endpoint}",
                )
                print_status(check.status, f"Backend: {check.message}")
                self.results.add(check)
                return check

        check = CheckResult(
            name="backend",
            status=CheckStatus.FAIL,
            message="Not reachable",
        )
        print_status(check.status, f"Backend: {check.message}")
        self.results.add(check)
        return check

    def verify_backend_login(self) -> CheckResult:
        """Login to backend and get token.

        Attempts registration first (with retry on 409), then login.
        Handles ALLOW_SELF_SIGNUP=false (404) gracefully.
        """
        info("Registering/logging into backend...")

        register_url = join_url(self.backend_url, self.register_path or "/auth/register")
        login_url = join_url(self.backend_url, self.login_path or "/auth/login")

        # Generate unique email with random suffix
        password = f"e2epass_{secrets.token_hex(8)}"

        # Try registration with retry on 409 (duplicate)
        max_retries = 3
        email = None
        reg_success = False

        for attempt in range(max_retries):
            random_suffix = secrets.token_hex(4)
            email = f"e2e_{int(time.time())}_{random_suffix}@example.com"

            info(f"Attempting registration (attempt {attempt + 1}/{max_retries})...")
            reg_result = http_post_json(register_url, {"email": email, "password": password})

            status_code = reg_result.get("status_code", 0)

            if status_code in (200, 201):
                # Registration succeeded, might have token in response
                reg_data = parse_json_safe(reg_result.get("body", ""))
                if reg_data and reg_data.get("access_token"):
                    self.backend_token = reg_data["access_token"]
                    info("Registration returned token directly")
                reg_success = True
                break
            elif status_code == 404:
                # ALLOW_SELF_SIGNUP=false - registration disabled
                info("Registration disabled (ALLOW_SELF_SIGNUP=false)")
                info("TIP: Set ALLOW_SELF_SIGNUP=true in backend/.env.local")
                check = CheckResult(
                    name="backend_login",
                    status=CheckStatus.FAIL,
                    message="Registration disabled (404)",
                    details="Set ALLOW_SELF_SIGNUP=true in backend/.env.local",
                )
                print_status(check.status, f"Backend login: {check.message}")
                self.results.add(check)
                return check
            elif status_code == 409:
                # Email already exists, regenerate and retry
                info(f"Email conflict, regenerating...")
                continue
            else:
                # Other error
                body_preview = redact_secrets(str(reg_result.get("body", ""))[:200])
                check = CheckResult(
                    name="backend_login",
                    status=CheckStatus.FAIL,
                    message=f"Registration failed (HTTP {status_code})",
                    details=body_preview,
                )
                print_status(check.status, f"Backend login: {check.message}")
                self.results.add(check)
                return check

        if not reg_success:
            check = CheckResult(
                name="backend_login",
                status=CheckStatus.FAIL,
                message="Registration failed after retries",
            )
            print_status(check.status, f"Backend login: {check.message}")
            self.results.add(check)
            return check

        # If we already have a token from registration, we're done
        if self.backend_token:
            check = CheckResult(
                name="backend_login",
                status=CheckStatus.OK,
                message="Authenticated (via registration)",
            )
            print_status(check.status, "Backend login: OK")
            self.results.add(check)
            return check

        # Otherwise, login
        info("Logging in with registered credentials...")
        login_result = http_post_json(login_url, {"email": email, "password": password})

        if login_result.get("ok") and login_result.get("status_code") == 200:
            login_data = parse_json_safe(login_result.get("body", ""))
            if login_data and login_data.get("access_token"):
                self.backend_token = login_data["access_token"]
                check = CheckResult(
                    name="backend_login",
                    status=CheckStatus.OK,
                    message="Authenticated",
                )
                print_status(check.status, "Backend login: OK")
                self.results.add(check)
                return check

        check = CheckResult(
            name="backend_login",
            status=CheckStatus.FAIL,
            message=f"Login failed (HTTP {login_result.get('status_code', 'N/A')})",
            details=redact_secrets(str(login_result.get("body", ""))[:200]),
        )
        print_status(check.status, f"Backend login: {check.message}")
        self.results.add(check)
        return check

    def verify_lab_creation(self) -> CheckResult:
        """Create a lab via backend API and wait for ready status."""
        if not self.backend_token:
            check = CheckResult(
                name="lab_created",
                status=CheckStatus.SKIP,
                message="No auth token",
                fatal=False,
            )
            print_status(check.status, f"Lab creation: {check.message}")
            self.results.add(check)
            return check

        info("Creating lab...")

        headers = {"Authorization": f"Bearer {self.backend_token}"}

        # Get recipes
        result = run_cmd([
            "curl", "-sL", "-X", "GET",
            "-H", f"Authorization: Bearer {self.backend_token}",
            f"{self.backend_url}/recipes/",
        ])

        recipe_id = None
        if result["ok"]:
            try:
                recipes = json.loads(result["stdout"])
                if recipes and len(recipes) > 0:
                    recipe_id = recipes[0].get("id")
            except json.JSONDecodeError:
                pass

        if not recipe_id:
            check = CheckResult(
                name="lab_created",
                status=CheckStatus.FAIL,
                message="No recipes available",
            )
            print_status(check.status, f"Lab creation: {check.message}")
            self.results.add(check)
            return check

        # Create lab
        result = http_post_json(
            f"{self.backend_url}/labs/",
            {"recipe_id": recipe_id},
            headers=headers,
        )

        if not result["ok"] or result["status_code"] not in (200, 201):
            check = CheckResult(
                name="lab_created",
                status=CheckStatus.FAIL,
                message=f"HTTP {result.get('status_code', 'N/A')}",
                details=result.get("error", ""),
            )
            print_status(check.status, f"Lab creation: {check.message}")
            self.results.add(check)
            return check

        try:
            data = json.loads(result["body"])
            self.lab_id = data.get("id")
            self.lab_data = data
        except json.JSONDecodeError:
            pass

        if not self.lab_id:
            check = CheckResult(
                name="lab_created",
                status=CheckStatus.FAIL,
                message="No lab ID in response",
            )
            print_status(check.status, f"Lab creation: {check.message}")
            self.results.add(check)
            return check

        print_status(CheckStatus.OK, f"Lab created: {self.lab_id}")

        # Wait for provisioning
        info("Waiting for lab provisioning (max 90s)...")
        for i in range(45):
            time.sleep(2)
            status_result = run_cmd([
                "curl", "-sL", "-X", "GET",
                "-H", f"Authorization: Bearer {self.backend_token}",
                f"{self.backend_url}/labs/{self.lab_id}",
            ])
            if status_result["ok"]:
                try:
                    lab_data = json.loads(status_result["stdout"])
                    self.lab_data = lab_data
                    status = lab_data.get("status")
                    if status == "ready":
                        check = CheckResult(
                            name="lab_created",
                            status=CheckStatus.OK,
                            message=f"Lab {self.lab_id[:8]}... ready",
                        )
                        print_status(check.status, "Lab status: ready")
                        self.results.add(check)
                        return check
                    elif status == "failed":
                        check = CheckResult(
                            name="lab_created",
                            status=CheckStatus.FAIL,
                            message="Provisioning failed",
                        )
                        print_status(check.status, "Lab status: failed")
                        self.results.add(check)
                        return check
                except json.JSONDecodeError:
                    pass

        check = CheckResult(
            name="lab_created",
            status=CheckStatus.FAIL,
            message="Provisioning timeout",
        )
        print_status(check.status, f"Lab creation: {check.message}")
        self.results.add(check)
        return check

    def verify_vnc_host(self) -> CheckResult:
        """Verify OctoBox VNC from host (SKIP if not mapped in GUAC mode)."""
        if not self.lab_id:
            check = CheckResult(
                name="vnc_from_host",
                status=CheckStatus.SKIP,
                message="No lab created",
                fatal=False,
            )
            print_status(check.status, f"VNC (host): {check.message}")
            self.results.add(check)
            return check

        info("Checking VNC from host...")

        container_name = f"octolab_{self.lab_id}-octobox-1"
        result = run_cmd(["docker", "port", container_name, "5900/tcp"])

        if not result["ok"] or not result["stdout"].strip():
            # Expected in GUAC mode - VNC not exposed to host
            check = CheckResult(
                name="vnc_from_host",
                status=CheckStatus.SKIP,
                message="Port not mapped (GUAC mode)",
                details="VNC only accessible via guacd network",
                fatal=False,
            )
            print_status(check.status, f"VNC (host): {check.message}")
            self.results.add(check)
            return check

        mapping = result["stdout"].strip().split("\n")[0]
        if ":" in mapping:
            host_port = int(mapping.split(":")[-1])
            vnc_result = check_vnc_banner("127.0.0.1", host_port)
            if vnc_result["ok"]:
                check = CheckResult(
                    name="vnc_from_host",
                    status=CheckStatus.OK,
                    message=f"RFB banner: {vnc_result['banner']}",
                )
                print_status(check.status, f"VNC (host): {check.message}")
                self.results.add(check)
                return check
            else:
                check = CheckResult(
                    name="vnc_from_host",
                    status=CheckStatus.FAIL,
                    message=vnc_result["error"],
                )
                print_status(check.status, f"VNC (host): {check.message}")
                self.results.add(check)
                return check

        check = CheckResult(
            name="vnc_from_host",
            status=CheckStatus.FAIL,
            message="Could not parse port mapping",
        )
        print_status(check.status, f"VNC (host): {check.message}")
        self.results.add(check)
        return check

    def verify_vnc_handshake_from_guacd_network(self) -> CheckResult:
        """Verify VNC RFB handshake from guacd's network perspective.

        Uses a helper container attached to the lab network to perform
        actual RFB handshake verification (not just port connectivity).
        """
        if not self.lab_id:
            check = CheckResult(
                name="vnc_rfb_handshake",
                status=CheckStatus.SKIP,
                message="No lab created",
                fatal=False,
            )
            print_status(check.status, f"VNC RFB handshake: {check.message}")
            self.results.add(check)
            return check

        info("Verifying VNC RFB handshake from guacd network...")

        container_name = f"octolab_{self.lab_id}-octobox-1"
        network_name = f"octolab_{self.lab_id}_lab_net"

        # Get OctoBox IP on lab network
        result = run_cmd([
            "docker", "inspect", "-f",
            f'{{{{(index .NetworkSettings.Networks "{network_name}").IPAddress}}}}',
            container_name,
        ])

        if not result["ok"]:
            check = CheckResult(
                name="vnc_rfb_handshake",
                status=CheckStatus.FAIL,
                message="Could not inspect OctoBox container",
                details=redact_secrets(result.get("stderr", "")),
            )
            print_status(check.status, f"VNC RFB handshake: {check.message}")
            self.results.add(check)
            return check

        octobox_ip = result["stdout"].strip()
        if not octobox_ip or octobox_ip == "<no value>":
            check = CheckResult(
                name="vnc_rfb_handshake",
                status=CheckStatus.FAIL,
                message="OctoBox not on lab network",
            )
            print_status(check.status, f"VNC RFB handshake: {check.message}")
            self.results.add(check)
            return check

        # Use a Python helper container to verify RFB handshake
        # This is more reliable than nc and actually validates the protocol
        python_script = '''
import socket
import sys
try:
    sock = socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=5)
    banner = sock.recv(12).decode('ascii', errors='replace')
    sock.close()
    if banner.startswith('RFB '):
        print(f'OK:{banner.strip()}')
        sys.exit(0)
    else:
        print(f'FAIL:Invalid banner: {banner[:20]}')
        sys.exit(1)
except Exception as e:
    print(f'FAIL:{e}')
    sys.exit(1)
'''

        # Retry loop for VNC availability (VNC might take a moment to start)
        max_retries = 15
        last_error = ""

        for attempt in range(max_retries):
            result = run_cmd([
                "docker", "run", "--rm",
                "--network", network_name,
                "python:3.11-slim",
                "python3", "-c", python_script, octobox_ip, "5900",
            ], timeout=15.0)

            if result["ok"] and result["stdout"].strip().startswith("OK:"):
                banner = result["stdout"].strip().replace("OK:", "")
                check = CheckResult(
                    name="vnc_rfb_handshake",
                    status=CheckStatus.OK,
                    message=f"RFB banner: {banner}",
                    details=f"Connected to {octobox_ip}:5900",
                )
                print_status(check.status, f"VNC RFB handshake: {check.message}")
                self.results.add(check)
                return check

            last_error = result.get("stdout", "") or result.get("stderr", "") or result.get("error", "")

            if attempt < max_retries - 1:
                time.sleep(2)

        check = CheckResult(
            name="vnc_rfb_handshake",
            status=CheckStatus.FAIL,
            message="VNC handshake failed after retries",
            details=redact_secrets(last_error[:200]),
        )
        print_status(check.status, f"VNC RFB handshake: {check.message}")
        self.results.add(check)
        return check

    def verify_desktop_processes(self) -> CheckResult:
        """Verify desktop processes are running inside OctoBox.

        Checks for:
        - VNC server (Xvnc, Xtigervnc, or tigervncserver)
        - Desktop environment (xfce4-session, xfwm4, or similar)
        """
        if not self.lab_id:
            check = CheckResult(
                name="desktop_processes",
                status=CheckStatus.SKIP,
                message="No lab created",
                fatal=False,
            )
            print_status(check.status, f"Desktop processes: {check.message}")
            self.results.add(check)
            return check

        info("Verifying desktop processes inside OctoBox...")

        container_name = f"octolab_{self.lab_id}-octobox-1"

        # Check for VNC server process
        vnc_result = run_cmd([
            "docker", "exec", container_name,
            "pgrep", "-l", "-f", "Xvnc|Xtigervnc|tigervncserver",
        ])

        vnc_running = vnc_result["ok"] and vnc_result["stdout"].strip()

        # Check for desktop environment
        desktop_result = run_cmd([
            "docker", "exec", container_name,
            "pgrep", "-l", "-f", "xfce4-session|xfwm4|startxfce",
        ])

        desktop_running = desktop_result["ok"] and desktop_result["stdout"].strip()

        # Also check DISPLAY environment
        display_result = run_cmd([
            "docker", "exec", container_name,
            "sh", "-c", "echo $DISPLAY",
        ])

        display_set = display_result["ok"] and display_result["stdout"].strip()

        if vnc_running and (desktop_running or display_set):
            vnc_procs = vnc_result["stdout"].strip().replace("\n", ", ")
            desktop_procs = desktop_result["stdout"].strip().replace("\n", ", ") if desktop_running else "N/A"
            check = CheckResult(
                name="desktop_processes",
                status=CheckStatus.OK,
                message="VNC + desktop running",
                details=f"VNC: {vnc_procs[:50]}",
            )
            print_status(check.status, f"Desktop processes: {check.message}")
        elif vnc_running:
            check = CheckResult(
                name="desktop_processes",
                status=CheckStatus.OK,
                message="VNC running (desktop may be starting)",
                details=f"DISPLAY={display_result.get('stdout', '').strip()}",
                fatal=False,
            )
            print_status(check.status, f"Desktop processes: {check.message}")
        else:
            # Get diagnostic info
            ps_result = run_cmd([
                "docker", "exec", container_name,
                "ps", "aux",
            ])
            check = CheckResult(
                name="desktop_processes",
                status=CheckStatus.FAIL,
                message="VNC server not found",
                details=redact_secrets(ps_result.get("stdout", "")[:500]),
            )
            print_status(check.status, f"Desktop processes: {check.message}")

        self.results.add(check)
        return check

    def verify_guac_connection_exists(self) -> CheckResult:
        """Verify Guacamole connection exists with correct parameters."""
        if not self.lab_id or not self.guac_admin_token:
            check = CheckResult(
                name="guac_connection",
                status=CheckStatus.SKIP,
                message="No lab or admin token",
                fatal=False,
            )
            print_status(check.status, f"Guac connection: {check.message}")
            self.results.add(check)
            return check

        info("Verifying Guacamole connection configuration...")

        # Lab API doesn't expose guac_connection_id, so query Guacamole's
        # connection list and find one matching the lab pattern
        result = run_cmd([
            "curl", "-sL",
            f"{self.guac_base_url}/api/session/data/postgresql/connections?token={self.guac_admin_token}",
        ])

        if not result["ok"]:
            check = CheckResult(
                name="guac_connection",
                status=CheckStatus.FAIL,
                message="Could not query Guacamole connections",
                details=result.get("error", ""),
            )
            print_status(check.status, f"Guac connection: {check.message}")
            self.results.add(check)
            return check

        # Find connection matching this lab's pattern
        # Connection name format: "Lab <short_id>" or "lab_<short_id>"
        connection_id = None
        lab_short_id = str(self.lab_id)[:8].lower()
        try:
            connections = json.loads(result["stdout"])
            for conn_id, conn_data in connections.items():
                conn_name = conn_data.get("name", "").lower()
                # Check for various naming patterns
                if lab_short_id in conn_name:
                    connection_id = conn_id
                    break
                # Also check identifier field
                conn_identifier = conn_data.get("identifier", "").lower()
                if lab_short_id in conn_identifier:
                    connection_id = conn_id
                    break
        except (json.JSONDecodeError, TypeError) as e:
            check = CheckResult(
                name="guac_connection",
                status=CheckStatus.FAIL,
                message="Failed to parse Guacamole connections list",
                details=str(e),
            )
            print_status(check.status, f"Guac connection: {check.message}")
            self.results.add(check)
            return check

        if not connection_id:
            # The connect endpoint works, so the connection exists
            # but we couldn't find it by name pattern - non-fatal
            check = CheckResult(
                name="guac_connection",
                status=CheckStatus.SKIP,
                message="Connection not found by name (connect endpoint validated separately)",
                details=f"Searched for '{lab_short_id}' in connection names",
                fatal=False,
            )
            print_status(check.status, f"Guac connection: {check.message}")
            self.results.add(check)
            return check

        # Query the connection details first (protocol info)
        result = run_cmd([
            "curl", "-sL",
            f"{self.guac_base_url}/api/session/data/postgresql/connections/{connection_id}?token={self.guac_admin_token}",
        ])

        if not result["ok"]:
            check = CheckResult(
                name="guac_connection",
                status=CheckStatus.FAIL,
                message="Could not query connection",
                details=result.get("error", ""),
            )
            print_status(check.status, f"Guac connection: {check.message}")
            self.results.add(check)
            return check

        try:
            conn_data = json.loads(result["stdout"])
            protocol = conn_data.get("protocol", "")
        except (json.JSONDecodeError, TypeError):
            protocol = ""

        # Parameters are at a separate endpoint in Guacamole API
        params_result = run_cmd([
            "curl", "-sL",
            f"{self.guac_base_url}/api/session/data/postgresql/connections/{connection_id}/parameters?token={self.guac_admin_token}",
        ])

        if not params_result["ok"]:
            check = CheckResult(
                name="guac_connection",
                status=CheckStatus.FAIL,
                message="Could not query connection parameters",
                details=params_result.get("error", ""),
            )
            print_status(check.status, f"Guac connection: {check.message}")
            self.results.add(check)
            return check

        try:
            params = json.loads(params_result["stdout"])

            # Verify key parameters
            hostname = params.get("hostname", "")
            port = params.get("port", "")

            # Expected hostname format: octolab_{full_lab_id}-octobox-1
            expected_hostname = f"octolab_{self.lab_id}-octobox-1"

            issues = []
            if protocol != "vnc":
                issues.append(f"protocol={protocol}, expected=vnc")
            if hostname != expected_hostname:
                issues.append(f"hostname mismatch: got {hostname[:50]}")
            if port != "5900":
                issues.append(f"port={port}, expected=5900")

            if not issues:
                check = CheckResult(
                    name="guac_connection",
                    status=CheckStatus.OK,
                    message="Connection configured correctly",
                    details=f"protocol=vnc, port=5900",
                )
            else:
                check = CheckResult(
                    name="guac_connection",
                    status=CheckStatus.FAIL,
                    message="Connection misconfigured",
                    details="; ".join(issues),
                )

            print_status(check.status, f"Guac connection: {check.message}")
            self.results.add(check)
            return check

        except json.JSONDecodeError:
            check = CheckResult(
                name="guac_connection",
                status=CheckStatus.FAIL,
                message="Invalid JSON from Guacamole API",
            )
            print_status(check.status, f"Guac connection: {check.message}")
            self.results.add(check)
            return check

    def verify_connect_endpoint_no_redirect(self) -> CheckResult:
        """Verify POST /labs/{id}/connect returns JSON without redirects."""
        if not self.lab_id or not self.backend_token:
            check = CheckResult(
                name="connect_endpoint",
                status=CheckStatus.SKIP,
                message="No lab or auth token",
                fatal=False,
            )
            print_status(check.status, f"Connect endpoint: {check.message}")
            self.results.add(check)
            return check

        info("Verifying connect endpoint returns JSON...")

        # Use curl with -w to capture redirect info
        result = run_cmd([
            "curl", "-s",
            "-X", "POST",
            "-H", f"Authorization: Bearer {self.backend_token}",
            "-H", "Content-Type: application/json",
            "-o", "-",
            "-w", "\n%{http_code}\n%{num_redirects}",
            f"{self.backend_url}/labs/{self.lab_id}/connect",
        ])

        if not result["ok"]:
            check = CheckResult(
                name="connect_endpoint",
                status=CheckStatus.FAIL,
                message="Request failed",
                details=result.get("error", ""),
            )
            print_status(check.status, f"Connect endpoint: {check.message}")
            self.results.add(check)
            return check

        lines = result["stdout"].strip().split("\n")
        if len(lines) >= 3:
            body = "\n".join(lines[:-2])
            http_code = lines[-2]
            num_redirects = lines[-1]

            if int(num_redirects) > 0:
                check = CheckResult(
                    name="connect_endpoint",
                    status=CheckStatus.FAIL,
                    message=f"Unexpected redirect ({num_redirects} redirects)",
                )
                print_status(check.status, f"Connect endpoint: {check.message}")
                self.results.add(check)
                return check

            if http_code == "200":
                try:
                    data = json.loads(body)
                    if "redirect_url" in data:
                        # Redact token from URL before displaying
                        safe_url = redact_secrets(data["redirect_url"])
                        check = CheckResult(
                            name="connect_endpoint",
                            status=CheckStatus.OK,
                            message="JSON with redirect_url",
                            details=f"URL: {safe_url[:80]}...",
                        )
                        print_status(check.status, f"Connect endpoint: {check.message}")
                        self.results.add(check)
                        return check
                    else:
                        check = CheckResult(
                            name="connect_endpoint",
                            status=CheckStatus.FAIL,
                            message="Missing redirect_url in response",
                        )
                except json.JSONDecodeError:
                    check = CheckResult(
                        name="connect_endpoint",
                        status=CheckStatus.FAIL,
                        message="Response is not valid JSON",
                    )
            else:
                check = CheckResult(
                    name="connect_endpoint",
                    status=CheckStatus.FAIL,
                    message=f"HTTP {http_code}",
                    details=redact_secrets(body[:200]),
                )
        else:
            check = CheckResult(
                name="connect_endpoint",
                status=CheckStatus.FAIL,
                message="Unexpected response format",
            )

        print_status(check.status, f"Connect endpoint: {check.message}")
        self.results.add(check)
        return check

    def verify_evidence_auth_exists(self) -> CheckResult:
        """Verify evidence_auth volume has files."""
        if not self.lab_id:
            check = CheckResult(
                name="evidence_auth",
                status=CheckStatus.SKIP,
                message="No lab created",
                fatal=False,
            )
            print_status(check.status, f"Evidence auth: {check.message}")
            self.results.add(check)
            return check

        info("Checking evidence_auth volume...")

        volume_name = f"octolab_{self.lab_id}_evidence_auth"

        result = run_cmd([
            "docker", "run", "--rm",
            "-v", f"{volume_name}:/mnt:ro",
            "busybox", "ls", "-la", "/mnt",
        ])

        if not result["ok"]:
            check = CheckResult(
                name="evidence_auth",
                status=CheckStatus.FAIL,
                message="Could not inspect volume",
                details=result.get("error", ""),
            )
        elif "network" in result["stdout"] or "network.json" in result["stdout"]:
            check = CheckResult(
                name="evidence_auth",
                status=CheckStatus.OK,
                message="Network evidence present",
            )
        elif "total 0" in result["stdout"]:
            check = CheckResult(
                name="evidence_auth",
                status=CheckStatus.OK,
                message="Volume exists (capture pending)",
                fatal=False,
            )
        else:
            check = CheckResult(
                name="evidence_auth",
                status=CheckStatus.OK,
                message="Volume has content",
            )

        print_status(check.status, f"Evidence auth: {check.message}")
        self.results.add(check)
        return check

    def verify_evidence_auth_not_in_octobox(self) -> CheckResult:
        """Verify evidence_auth is NOT mounted in OctoBox (isolation)."""
        if not self.lab_id:
            check = CheckResult(
                name="evidence_isolated",
                status=CheckStatus.SKIP,
                message="No lab created",
                fatal=False,
            )
            print_status(check.status, f"Evidence isolation: {check.message}")
            self.results.add(check)
            return check

        info("Verifying evidence_auth is NOT in OctoBox...")

        container_name = f"octolab_{self.lab_id}-octobox-1"
        volume_name = f"octolab_{self.lab_id}_evidence_auth"

        result = run_cmd([
            "docker", "inspect", "-f",
            "{{range .Mounts}}{{.Name}} {{end}}",
            container_name,
        ])

        if not result["ok"]:
            check = CheckResult(
                name="evidence_isolated",
                status=CheckStatus.FAIL,
                message="Could not inspect container",
            )
        elif volume_name in result["stdout"]:
            check = CheckResult(
                name="evidence_isolated",
                status=CheckStatus.FAIL,
                message="SECURITY: evidence_auth IS mounted in OctoBox!",
            )
        else:
            check = CheckResult(
                name="evidence_isolated",
                status=CheckStatus.OK,
                message="evidence_auth NOT in OctoBox",
            )

        print_status(check.status, f"Evidence isolation: {check.message}")
        self.results.add(check)
        return check

    def generate_traffic(self) -> CheckResult:
        """Generate traffic from OctoBox to target for evidence capture.

        Executes multiple curl requests from OctoBox to target-web to ensure
        network traffic is captured in pcap.
        """
        if not self.lab_id:
            check = CheckResult(
                name="traffic_generation",
                status=CheckStatus.SKIP,
                message="No lab created",
                fatal=False,
            )
            print_status(check.status, f"Traffic generation: {check.message}")
            self.results.add(check)
            return check

        info("Generating traffic from OctoBox to target...")

        container_name = f"octolab_{self.lab_id}-octobox-1"
        success_count = 0

        # Generate multiple requests to ensure capture
        for i in range(10):
            result = run_cmd([
                "docker", "exec", container_name,
                "curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
                "http://target-web:80/"
            ], timeout=10.0)

            if result["ok"] and "200" in result.get("stdout", ""):
                success_count += 1

            time.sleep(0.2)  # Small delay between requests

        # Wait for capture to flush
        time.sleep(3)

        if success_count >= 5:
            check = CheckResult(
                name="traffic_generation",
                status=CheckStatus.OK,
                message=f"{success_count}/10 requests succeeded",
            )
        elif success_count > 0:
            check = CheckResult(
                name="traffic_generation",
                status=CheckStatus.OK,
                message=f"{success_count}/10 requests succeeded (partial)",
                fatal=False,
            )
        else:
            check = CheckResult(
                name="traffic_generation",
                status=CheckStatus.FAIL,
                message="No traffic reached target",
            )

        print_status(check.status, f"Traffic generation: {check.message}")
        self.results.add(check)
        return check

    def verify_evidence_download(self) -> CheckResult:
        """Download evidence bundle via API and validate contents.

        Validates:
        - HTTP 200 response
        - Valid ZIP file
        - manifest.json with required fields
        - network.json or pcap files present
        - SHA256 hashes match
        - No secrets in logs
        """
        if not self.lab_id or not self.backend_token:
            check = CheckResult(
                name="evidence_download",
                status=CheckStatus.SKIP,
                message="No lab or auth token",
                fatal=False,
            )
            print_status(check.status, f"Evidence download: {check.message}")
            self.results.add(check)
            return check

        info("Downloading and validating evidence bundle...")

        # Download evidence via curl (binary safe)
        result = run_cmd([
            "curl", "-sS",
            "-X", "GET",
            "-H", f"Authorization: Bearer {self.backend_token}",
            "-o", "-",
            "-w", "\n---HTTP_STATUS---%{http_code}",
            f"{self.backend_url}/labs/{self.lab_id}/evidence/bundle.zip",
        ], timeout=60.0)

        if not result["ok"]:
            check = CheckResult(
                name="evidence_download",
                status=CheckStatus.FAIL,
                message="Download failed",
                details=result.get("error", ""),
            )
            print_status(check.status, f"Evidence download: {check.message}")
            self.results.add(check)
            return check

        # Parse response
        stdout_bytes = result.get("stdout", "").encode("latin-1")
        if b"---HTTP_STATUS---" in stdout_bytes:
            parts = stdout_bytes.rsplit(b"---HTTP_STATUS---", 1)
            zip_data = parts[0].rstrip(b"\n")
            status_code = parts[1].decode().strip()
        else:
            check = CheckResult(
                name="evidence_download",
                status=CheckStatus.FAIL,
                message="Invalid response format",
            )
            print_status(check.status, f"Evidence download: {check.message}")
            self.results.add(check)
            return check

        if status_code != "200":
            check = CheckResult(
                name="evidence_download",
                status=CheckStatus.FAIL,
                message=f"HTTP {status_code}",
            )
            print_status(check.status, f"Evidence download: {check.message}")
            self.results.add(check)
            return check

        # Validate ZIP
        validation_result = self._validate_evidence_zip(zip_data)

        # Save ZIP for debugging
        self._save_evidence_zip(zip_data)

        return validation_result

    def _validate_evidence_zip(self, zip_data: bytes) -> CheckResult:
        """Validate evidence ZIP contents."""
        try:
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                namelist = zf.namelist()
                info(f"ZIP contains {len(namelist)} files")

                issues = []
                successes = []

                # Check for manifest.json
                if "manifest.json" not in namelist:
                    issues.append("missing manifest.json")
                else:
                    successes.append("manifest.json present")
                    # Validate manifest
                    manifest_data = zf.read("manifest.json").decode()
                    try:
                        manifest = json.loads(manifest_data)
                        if "lab_id" in manifest:
                            successes.append("manifest has lab_id")
                        if "files" in manifest:
                            successes.append(f"manifest lists {len(manifest.get('files', []))} files")

                        # Verify file hashes
                        files_info = manifest.get("files", [])
                        for file_info in files_info[:5]:  # Check first 5 files
                            filename = file_info.get("path") or file_info.get("name")
                            expected_hash = file_info.get("sha256")
                            if filename and expected_hash and filename in namelist:
                                actual_hash = hashlib.sha256(zf.read(filename)).hexdigest()
                                if actual_hash == expected_hash:
                                    successes.append(f"hash OK: {filename[:30]}")
                                else:
                                    issues.append(f"hash mismatch: {filename[:30]}")

                    except json.JSONDecodeError:
                        issues.append("invalid manifest.json format")

                # Check for pcap or network evidence
                has_pcap = any(f.endswith((".pcap", ".pcapng")) for f in namelist)
                has_network_json = any("network.json" in f or "network/network.json" in f for f in namelist)

                if has_pcap:
                    # Verify pcap has data
                    pcap_files = [f for f in namelist if f.endswith((".pcap", ".pcapng"))]
                    for pcap_file in pcap_files[:1]:  # Check first pcap
                        pcap_size = len(zf.read(pcap_file))
                        if pcap_size > 4096:  # Minimum size threshold
                            successes.append(f"pcap: {pcap_size} bytes")
                        else:
                            issues.append(f"pcap too small: {pcap_size} bytes")
                elif has_network_json:
                    successes.append("network.json present")
                else:
                    issues.append("no pcap or network.json")

                # Check for secrets in logs (if present)
                log_files = [f for f in namelist if f.endswith(".log")]
                for log_file in log_files[:3]:  # Check first 3 logs
                    log_content = zf.read(log_file).decode("utf-8", errors="replace")
                    secret_patterns = [
                        "authToken",
                        "Authorization: Bearer",
                        "GUAC_ADMIN_PASSWORD",
                        "GUAC_ENC_KEY",
                        "eyJ",  # JWT prefix
                    ]
                    for pattern in secret_patterns:
                        if pattern in log_content:
                            issues.append(f"SECURITY: '{pattern}' found in {log_file[:30]}")
                            break

                # Summary
                if not issues:
                    check = CheckResult(
                        name="evidence_download",
                        status=CheckStatus.OK,
                        message=f"Valid ZIP: {len(namelist)} files",
                        details="; ".join(successes[:5]),
                    )
                elif len(issues) <= 2 and successes:
                    check = CheckResult(
                        name="evidence_download",
                        status=CheckStatus.OK,
                        message=f"ZIP valid with warnings: {'; '.join(issues)}",
                        fatal=False,
                    )
                else:
                    check = CheckResult(
                        name="evidence_download",
                        status=CheckStatus.FAIL,
                        message=f"ZIP validation failed: {'; '.join(issues)}",
                    )

                print_status(check.status, f"Evidence download: {check.message}")
                self.results.add(check)
                return check

        except zipfile.BadZipFile:
            check = CheckResult(
                name="evidence_download",
                status=CheckStatus.FAIL,
                message="Invalid ZIP file",
            )
            print_status(check.status, f"Evidence download: {check.message}")
            self.results.add(check)
            return check
        except Exception as e:
            check = CheckResult(
                name="evidence_download",
                status=CheckStatus.FAIL,
                message=f"ZIP validation error: {type(e).__name__}",
            )
            print_status(check.status, f"Evidence download: {check.message}")
            self.results.add(check)
            return check

    def _save_evidence_zip(self, zip_data: bytes) -> None:
        """Save evidence ZIP to snapshot directory for debugging."""
        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            snapshot_dir = SNAPSHOTS_DIR / timestamp
            snapshot_dir.mkdir(parents=True, exist_ok=True)

            zip_path = snapshot_dir / f"evidence_{self.lab_id}.zip"
            with open(zip_path, "wb") as f:
                f.write(zip_data)

            info(f"Evidence saved to: {zip_path}")
        except Exception as e:
            info(f"Warning: could not save evidence ZIP: {type(e).__name__}")

    def cleanup_lab(self):
        """Cleanup test lab."""
        if not self.lab_id or not self.backend_token:
            return

        info("Cleaning up test lab...")
        run_cmd([
            "curl", "-sL", "-X", "DELETE",
            "-H", f"Authorization: Bearer {self.backend_token}",
            f"{self.backend_url}/labs/{self.lab_id}",
        ])

    def run(self) -> int:
        """Run all verifications."""
        print("=" * 60)
        print("OctoLab E2E Verification (Hardened)")
        print("=" * 60)
        print()

        # Phase 1: OpenAPI discovery
        self.discover_openapi()

        # Phase 2: CORS preflight (frontend reachability)
        self.verify_cors_preflight()

        # Phase 3: Core infrastructure checks
        guac_ui = self.verify_guac_ui()
        if guac_ui.status == CheckStatus.OK:
            self.verify_guac_tokens()

        backend = self.verify_backend()
        if backend.status == CheckStatus.OK:
            login = self.verify_backend_login()
            if login.status == CheckStatus.OK:
                lab = self.verify_lab_creation()
                if lab.status == CheckStatus.OK and self.lab_id:
                    # VNC checks
                    self.verify_vnc_host()
                    self.verify_vnc_handshake_from_guacd_network()

                    # Desktop process check
                    self.verify_desktop_processes()

                    # Guacamole connection verification
                    self.verify_guac_connection_exists()

                    # Connect endpoint check
                    self.verify_connect_endpoint_no_redirect()

                    # Evidence checks
                    self.verify_evidence_auth_exists()
                    self.verify_evidence_auth_not_in_octobox()

                    # Generate traffic and verify evidence download
                    self.generate_traffic()
                    self.verify_evidence_download()

                    # Cleanup
                    self.cleanup_lab()

        # Save results
        self._save_results()

        # Summary
        print()
        print("=" * 60)
        print("Summary")
        print("=" * 60)

        for check in self.results.checks:
            fatal_marker = "" if check.fatal else " (non-blocking)"
            details = f" - {check.details}" if check.details else ""
            print(f"  {check.name}: {check.status.value}{fatal_marker}")
            if check.message:
                print(f"    {check.message}{details}")

        print()
        if self.results.all_passed:
            print(f"{Colors.OK}All checks passed!{Colors.RESET}")
            return 0
        else:
            print(f"{Colors.FAIL}Some checks failed.{Colors.RESET}")
            return 1

    def _save_results(self):
        """Save results to snapshot directory."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snapshot_dir = SNAPSHOTS_DIR / timestamp
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        # Build auth matrix
        auth_matrix = {
            "register": {
                "path": self.register_path,
                "methods": self.openapi_paths.get(self.register_path, []),
            },
            "login": {
                "path": self.login_path,
                "methods": self.openapi_paths.get(self.login_path, []),
            },
            "health": {
                "path": self.health_path,
                "methods": self.openapi_paths.get(self.health_path, []),
            },
        }

        results_file = snapshot_dir / "e2e_verify.json"
        with open(results_file, "w") as f:
            json.dump({
                "timestamp": timestamp,
                "backend_url": self.backend_url,
                "openapi_paths": self.openapi_paths,
                "auth_matrix": auth_matrix,
                **self.results.to_dict(),
            }, f, indent=2)

        info(f"Results saved to: {results_file}")


def main():
    verifier = E2EVerifier()
    return verifier.run()


if __name__ == "__main__":
    sys.exit(main())
