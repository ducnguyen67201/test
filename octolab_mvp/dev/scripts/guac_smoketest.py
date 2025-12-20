#!/usr/bin/env python3
"""Guacamole functional readiness smoketest.

Verifies that Guacamole is truly ready:
1. GUI endpoint reachable (GET /guacamole/)
2. API tokens endpoint works (POST /guacamole/api/tokens with admin creds)

Usage:
    # Via run_with_env.py (recommended)
    python3 backend/scripts/run_with_env.py --env backend/.env --env backend/.env.local -- \
        python3 dev/scripts/guac_smoketest.py

    # Or directly with env vars set
    GUAC_BASE_URL=http://127.0.0.1:8081/guacamole \
    GUAC_ADMIN_USER=guacadmin \
    GUAC_ADMIN_PASSWORD=guacadmin \
    python3 dev/scripts/guac_smoketest.py

Exit codes:
    0 - Guacamole is ready
    1 - Guacamole is not ready (see output for classification)
    2 - Configuration error (missing env vars)

SECURITY:
- Never logs passwords or tokens
- Uses redacted output for all sensitive values
"""

import asyncio
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

# Try to import httpx
try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx", file=sys.stderr)
    sys.exit(2)


# ============================================================================
# Configuration
# ============================================================================

DEFAULT_TIMEOUT = 10.0
RETRY_TIMEOUT = 60.0  # Total time to retry
RETRY_INTERVAL = 2.0  # Seconds between retries

# Patterns for sensitive keys that should be redacted
SENSITIVE_PATTERNS = [
    re.compile(r".*PASSWORD.*", re.IGNORECASE),
    re.compile(r".*SECRET.*", re.IGNORECASE),
    re.compile(r".*_KEY$", re.IGNORECASE),
    re.compile(r".*TOKEN.*", re.IGNORECASE),
]


# ============================================================================
# Color output
# ============================================================================

class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[0;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'


def log_info(msg: str) -> None:
    print(f"{Colors.GREEN}[INFO]{Colors.NC} {msg}")


def log_warn(msg: str) -> None:
    print(f"{Colors.YELLOW}[WARN]{Colors.NC} {msg}")


def log_error(msg: str) -> None:
    print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}", file=sys.stderr)


def log_step(step: str, ok: bool, detail: str = "") -> None:
    status = f"{Colors.GREEN}OK{Colors.NC}" if ok else f"{Colors.RED}FAIL{Colors.NC}"
    suffix = f" ({detail})" if detail else ""
    print(f"  {step}: {status}{suffix}")


# ============================================================================
# Redaction
# ============================================================================

def is_sensitive_key(key: str) -> bool:
    """Check if a key should have its value redacted."""
    return any(pattern.match(key) for pattern in SENSITIVE_PATTERNS)


def redact_value(value: str) -> str:
    """Redact a sensitive value for safe logging.

    SECURITY: NEVER shows partial secrets. Always "****".
    """
    if not value:
        return "<empty>"
    return "****"


def sanitize_url(url: str) -> str:
    """Sanitize URL for safe logging (remove any embedded credentials)."""
    try:
        parsed = urlparse(url)
        if parsed.password:
            netloc = f"{parsed.username}:****@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return parsed._replace(netloc=netloc).geturl()
        return url
    except Exception:
        return "<invalid-url>"


# ============================================================================
# URL helpers
# ============================================================================

def build_url(base: str, path: str) -> str:
    """Safely join base URL and path without double slashes."""
    if not base.endswith("/"):
        base = base + "/"
    path = path.lstrip("/")
    return urljoin(base, path)


# ============================================================================
# Preflight checks (standalone, no backend imports)
# ============================================================================

async def check_gui(client: httpx.AsyncClient, base_url: str) -> tuple[bool, Optional[int], Optional[str]]:
    """Check if Guacamole GUI is reachable."""
    gui_url = build_url(base_url, "/")
    try:
        response = await client.get(gui_url, follow_redirects=True)
        if response.status_code in (200, 302):
            return (True, response.status_code, None)
        return (False, response.status_code, f"HTTP {response.status_code}")
    except httpx.ConnectError:
        return (False, None, "Connection refused")
    except httpx.TimeoutException:
        return (False, None, "Connection timeout")
    except httpx.RequestError as e:
        return (False, None, type(e).__name__)


async def check_api(
    client: httpx.AsyncClient,
    base_url: str,
    username: str,
    password: str,
) -> tuple[bool, Optional[int], Optional[str], str]:
    """Check if Guacamole API tokens endpoint works.

    Returns: (ok, status_code, error_detail, classification)
    """
    api_url = build_url(base_url, "api/tokens")
    try:
        response = await client.post(
            api_url,
            data={"username": username, "password": password},
        )

        if response.status_code == 200:
            return (True, 200, None, "ok")
        if response.status_code == 404:
            return (False, 404, "API endpoint not found", "base_url_wrong")
        if response.status_code in (401, 403):
            return (False, response.status_code, "Authentication failed", "creds_wrong")
        if response.status_code >= 500:
            return (False, response.status_code, f"Server error", "server_5xx")
        return (False, response.status_code, f"HTTP {response.status_code}", "unknown")

    except httpx.ConnectError:
        return (False, None, "Connection refused", "network_down")
    except httpx.TimeoutException:
        return (False, None, "Connection timeout", "network_down")
    except httpx.RequestError as e:
        return (False, None, type(e).__name__, "network_down")


def gather_diagnostics() -> None:
    """Gather and print redacted diagnostics for debugging.

    Uses subprocess with shell=False for security.
    """
    import subprocess
    from pathlib import Path

    # Import redactor
    script_dir = Path(__file__).parent
    redact_script = script_dir / "redact_stream.py"

    print(f"\n{Colors.YELLOW}=== Diagnostics (redacted) ==={Colors.NC}")

    # Get compose directory
    repo_root = script_dir.parent.parent
    compose_dir = repo_root / "infra" / "guacamole"

    if not compose_dir.exists():
        log_warn(f"Compose directory not found: {compose_dir}")
        return

    # Gather docker compose logs (last 50 lines)
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_dir / "docker-compose.yml"),
             "logs", "--tail", "50", "guacamole", "guac-db"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.stdout or result.stderr:
            output = result.stdout + result.stderr
            # Redact the output
            if redact_script.exists():
                redact_result = subprocess.run(
                    ["python3", str(redact_script)],
                    input=output,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                output = redact_result.stdout if redact_result.returncode == 0 else output

            print(f"\n{Colors.YELLOW}Container logs (last 50 lines):{Colors.NC}")
            # Print only last 20 lines to keep output manageable
            lines = output.strip().split('\n')
            for line in lines[-20:]:
                print(f"  {line}")
    except subprocess.TimeoutExpired:
        log_warn("Timed out gathering container logs")
    except Exception as e:
        log_warn(f"Failed to gather container logs: {type(e).__name__}")

    # Check if schema exists by exec into db
    try:
        result = subprocess.run(
            ["docker", "exec", "octolab-guac-db",
             "psql", "-U", "guacamole", "-d", "guacamole_db",
             "-c", "SELECT 1 FROM guacamole_entity LIMIT 1;"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            print(f"\n  {Colors.GREEN}Schema check:{Colors.NC} guacamole_entity table exists")
        else:
            print(f"\n  {Colors.RED}Schema check:{Colors.NC} guacamole_entity table MISSING")
            print(f"  This indicates the database schema was not initialized.")
            print(f"  Run: make guac-reset")
    except subprocess.TimeoutExpired:
        log_warn("Timed out checking schema")
    except Exception as e:
        log_warn(f"Failed to check schema: {type(e).__name__}")


async def run_smoketest(
    base_url: str,
    admin_user: str,
    admin_password: str,
    timeout: float = DEFAULT_TIMEOUT,
    retry_timeout: float = RETRY_TIMEOUT,
) -> bool:
    """Run Guacamole smoketest with retries.

    Returns True if Guacamole is ready.
    """
    sanitized_url = sanitize_url(base_url.rstrip("/"))
    print(f"\n{Colors.BLUE}=== Guacamole Smoketest ==={Colors.NC}")
    print(f"  Base URL: {sanitized_url}")
    print(f"  Admin user: {admin_user}")
    print(f"  Admin password: ****")  # SECURITY: Never print password, even redacted form
    print()

    start_time = time.time()
    attempt = 0
    last_classification = None

    while True:
        attempt += 1
        elapsed = time.time() - start_time

        if elapsed > retry_timeout:
            log_error(f"Timed out after {retry_timeout}s waiting for Guacamole")
            # If we timed out with 5xx, show diagnostics
            if last_classification == "server_5xx":
                gather_diagnostics()
                log_error("Guacamole API returned 5xx. Likely DB/schema mismatch.")
                log_error("Run: make guac-reset")
            return False

        if attempt > 1:
            print(f"  Retry attempt {attempt} (elapsed: {elapsed:.0f}s)...")

        async with httpx.AsyncClient(timeout=timeout) as client:
            # Step 1: Check GUI
            gui_ok, gui_status, gui_error = await check_gui(client, base_url)
            log_step("GUI endpoint", gui_ok, f"HTTP {gui_status}" if gui_status else gui_error or "")

            if not gui_ok:
                if gui_error in ("Connection refused", "Connection timeout"):
                    # Network not up yet, retry
                    await asyncio.sleep(RETRY_INTERVAL)
                    continue
                # Other error, still retry but warn
                log_warn(f"GUI check failed: {gui_error}")
                await asyncio.sleep(RETRY_INTERVAL)
                continue

            # Step 2: Check API
            api_ok, api_status, api_error, classification = await check_api(
                client, base_url, admin_user, admin_password
            )
            last_classification = classification
            log_step("API tokens", api_ok, f"HTTP {api_status}" if api_status else api_error or "")

            if api_ok:
                print()
                log_info(f"{Colors.GREEN}Guacamole smoketest: OK{Colors.NC}")
                return True

            # Handle classification
            if classification == "network_down":
                await asyncio.sleep(RETRY_INTERVAL)
                continue
            elif classification == "server_5xx":
                # Server error, might be transient - retry a few times
                if attempt < 5:
                    log_warn("Server returned 5xx, retrying...")
                    await asyncio.sleep(RETRY_INTERVAL)
                    continue
                # After 5 attempts, show diagnostics and fail
                gather_diagnostics()
                log_error("Guacamole API returned 5xx persistently.")
                log_error("Likely cause: DB/schema mismatch or missing initialization.")
                log_error("Fix: run 'make guac-reset' to regenerate the database.")
                return False
            elif classification == "base_url_wrong":
                log_error("Guacamole base URL appears misconfigured.")
                log_error("Check GUAC_BASE_URL - it should end with '/guacamole'")
                log_error(f"Example: http://127.0.0.1:8081/guacamole")
                return False
            elif classification == "creds_wrong":
                log_error("Guacamole admin credentials are invalid.")
                log_error("Check GUAC_ADMIN_USER and GUAC_ADMIN_PASSWORD")
                return False
            else:
                log_error(f"Unexpected error: {api_error}")
                await asyncio.sleep(RETRY_INTERVAL)
                continue


def get_config() -> tuple[str, str, str]:
    """Get configuration from environment variables.

    Returns: (base_url, admin_user, admin_password)
    Raises: SystemExit if required vars are missing
    """
    base_url = os.environ.get("GUAC_BASE_URL", "http://127.0.0.1:8081/guacamole")
    admin_user = os.environ.get("GUAC_ADMIN_USER", "guacadmin")
    admin_password = os.environ.get("GUAC_ADMIN_PASSWORD", "")

    # Check if Guacamole is enabled
    guac_enabled = os.environ.get("GUAC_ENABLED", "false").lower() in ("true", "1", "yes")

    if not guac_enabled:
        log_warn("GUAC_ENABLED is not true. Assuming Guacamole should be tested anyway.")

    if not admin_password:
        log_error("GUAC_ADMIN_PASSWORD is not set.")
        log_error("Set it in backend/.env.local or via environment variable.")
        sys.exit(2)

    return base_url, admin_user, admin_password


def main() -> int:
    """Main entry point."""
    try:
        base_url, admin_user, admin_password = get_config()
    except SystemExit as e:
        return e.code

    # Parse optional timeout from args
    retry_timeout = RETRY_TIMEOUT
    if len(sys.argv) > 1:
        try:
            retry_timeout = float(sys.argv[1])
        except ValueError:
            pass

    try:
        success = asyncio.run(run_smoketest(
            base_url=base_url,
            admin_user=admin_user,
            admin_password=admin_password,
            retry_timeout=retry_timeout,
        ))
        return 0 if success else 1
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
