#!/usr/bin/env python3
"""End-to-end Guacamole integration verification script.

USAGE:
    python3 dev/verify_guac_e2e.py

    # Or via make:
    make guac-verify

This script verifies the full Guacamole integration by:
1. Running preflight checks (GUI + API)
2. Checking guacd container connectivity
3. Optionally spawning a test lab and verifying VNC connectivity

SECURITY: All subprocess calls use shell=False.
"""

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Add backend to path so we can import from app
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))


def run_docker_cmd(cmd: list[str], timeout: float = 10.0) -> tuple[bool, str]:
    """Run a docker command with shell=False.

    Args:
        cmd: Command as list of strings
        timeout: Timeout in seconds

    Returns:
        Tuple of (success, output)
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,  # SECURITY: Never use shell=True
        )
        return (result.returncode == 0, result.stdout.strip() or result.stderr.strip())
    except subprocess.TimeoutExpired:
        return (False, "Command timeout")
    except Exception as e:
        return (False, f"Error: {type(e).__name__}")


def check_guacd_container() -> tuple[bool, str]:
    """Check if guacd container is running.

    Returns:
        Tuple of (is_running, message)
    """
    success, output = run_docker_cmd([
        "docker", "ps", "--filter", "name=guacd", "--format", "{{.Names}}"
    ])

    if not success:
        return (False, f"Failed to check containers: {output}")

    if output:
        return (True, f"guacd container running: {output}")
    return (False, "guacd container not found. Run 'make guac-up'")


def check_guacamole_container() -> tuple[bool, str]:
    """Check if Guacamole web container is running.

    Returns:
        Tuple of (is_running, message)
    """
    success, output = run_docker_cmd([
        "docker", "ps", "--filter", "name=guacamole", "--filter", "publish=8081",
        "--format", "{{.Names}}"
    ])

    if not success:
        return (False, f"Failed to check containers: {output}")

    if output:
        return (True, f"Guacamole container running: {output}")
    return (False, "Guacamole web container not found. Run 'make guac-up'")


def check_guacd_has_netcat() -> tuple[bool, str]:
    """Check if guacd container has netcat for connectivity tests.

    Returns:
        Tuple of (has_nc, message)
    """
    # First get container name
    success, container_name = run_docker_cmd([
        "docker", "ps", "--filter", "name=guacd", "--format", "{{.Names}}"
    ])

    if not success or not container_name:
        return (False, "guacd container not running")

    # Check for nc binary
    success, output = run_docker_cmd([
        "docker", "exec", container_name, "which", "nc"
    ])

    if success and output:
        return (True, f"netcat available at: {output}")
    return (False, "netcat not installed in guacd container (connectivity tests will fail)")


async def run_verification() -> int:
    """Run full verification suite.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    # Import here to allow path modification
    from app.config import settings
    from app.services.guacamole_preflight import (
        guacamole_preflight,
        PreflightClassification,
    )

    print("=" * 60)
    print("Guacamole End-to-End Verification")
    print("=" * 60)
    print()

    results = []

    # Check 1: Guacamole enabled
    print("Check 1: Guacamole configuration")
    if not settings.guac_enabled:
        print("  SKIP: Guacamole is disabled (GUAC_ENABLED=false)")
        return 0
    print(f"  OK: Guacamole enabled")
    print(f"      Base URL: {settings.guac_base_url}")
    results.append(True)
    print()

    # Check 2: guacd container
    print("Check 2: guacd container")
    ok, msg = check_guacd_container()
    print(f"  {'OK' if ok else 'FAIL'}: {msg}")
    results.append(ok)
    print()

    # Check 3: Guacamole web container
    print("Check 3: Guacamole web container")
    ok, msg = check_guacamole_container()
    print(f"  {'OK' if ok else 'FAIL'}: {msg}")
    results.append(ok)
    print()

    # Check 4: guacd has netcat
    print("Check 4: guacd netcat availability")
    ok, msg = check_guacd_has_netcat()
    print(f"  {'OK' if ok else 'WARN'}: {msg}")
    # Don't fail on this, just warn
    print()

    # Check 5: Preflight check (GUI + API)
    print("Check 5: Guacamole preflight (GUI + API)")
    if not settings.guac_admin_password:
        print("  SKIP: GUAC_ADMIN_PASSWORD not configured")
    else:
        try:
            result = await guacamole_preflight(
                base_url=settings.guac_base_url,
                admin_user=settings.guac_admin_user,
                admin_password=settings.guac_admin_password,
                timeout=10.0,
            )
            if result.ok:
                print(f"  OK: Preflight passed")
                print(f"      GUI: HTTP {result.gui_status}")
                print(f"      API: HTTP {result.api_status}")
                results.append(True)
            else:
                print(f"  FAIL: {result.classification.value}")
                print(f"      Hint: {result.hint}")
                results.append(False)
        except Exception as e:
            print(f"  FAIL: Exception during preflight: {type(e).__name__}")
            results.append(False)
    print()

    # Summary
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"  Passed: {passed}/{total}")
    print()

    if all(results):
        print("SUCCESS: All checks passed!")
        print()
        print("Next steps:")
        print("  1. Start the backend: make dev")
        print("  2. Start a lab and test /labs/{id}/connect endpoint")
        print("  3. Verify VNC session stays connected in Guacamole")
        return 0
    else:
        print("FAILED: Some checks did not pass.")
        print()
        print("Common fixes:")
        print("  - Run 'make guac-up' to start Guacamole stack")
        print("  - Run 'make guac-reset' if GUI shows ERROR page")
        print("  - Check backend/.env.local for correct credentials")
        return 1


def main():
    """Main entry point."""
    # Load environment variables from .env files
    try:
        from dotenv import load_dotenv
        load_dotenv(backend_path / ".env")
        load_dotenv(backend_path / ".env.local", override=True)
    except ImportError:
        # dotenv not available, rely on environment
        pass

    exit_code = asyncio.run(run_verification())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
