#!/usr/bin/env python3
"""Guacamole smoketest - exercises preflight checks from the host.

USAGE:
    python3 dev/guac_smoketest.py

    # Or via make:
    make guac-smoketest

Runs the Guacamole preflight check using the configured credentials
and reports the result with actionable hints if it fails.

SECURITY: Uses shell=False for all subprocess calls.
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path so we can import from app
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))


async def run_smoketest() -> int:
    """Run Guacamole preflight smoketest.

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
    print("Guacamole Smoketest")
    print("=" * 60)
    print()

    # Check if Guacamole is enabled
    if not settings.guac_enabled:
        print("SKIP: Guacamole is disabled (GUAC_ENABLED=false)")
        print("Set GUAC_ENABLED=true in backend/.env.local to enable.")
        return 0

    # Check if credentials are configured
    if not settings.guac_admin_password:
        print("ERROR: GUAC_ADMIN_PASSWORD not configured")
        print("Set GUAC_ADMIN_PASSWORD in backend/.env.local")
        return 1

    print(f"Configuration:")
    print(f"  GUAC_BASE_URL:    {settings.guac_base_url}")
    print(f"  GUAC_ADMIN_USER:  {settings.guac_admin_user}")
    print(f"  GUAC_ADMIN_PASSWORD: ****")  # Never log password
    print()

    print("Running preflight check...")
    print()

    try:
        result = await guacamole_preflight(
            base_url=settings.guac_base_url,
            admin_user=settings.guac_admin_user,
            admin_password=settings.guac_admin_password,
            timeout=10.0,
        )
    except Exception as e:
        print(f"ERROR: Unexpected exception during preflight: {type(e).__name__}")
        print(f"  {e}")
        return 1

    # Report results
    print("Results:")
    print(f"  GUI reachable:     {result.gui_ok} (HTTP {result.gui_status})")
    print(f"  API tokens works:  {result.api_ok} (HTTP {result.api_status})")
    print(f"  Classification:    {result.classification.value}")
    print()

    if result.ok:
        print("SUCCESS: Guacamole is ready!")
        return 0
    else:
        print(f"FAILED: {result.classification.value}")
        print()
        print("Hint:")
        print(f"  {result.hint}")

        if result.error_detail:
            print()
            print(f"Error detail: {result.error_detail}")

        # Provide additional context based on classification
        if result.classification == PreflightClassification.NETWORK_DOWN:
            print()
            print("Troubleshooting steps:")
            print("  1. Run 'make guac-up' to start the Guacamole stack")
            print("  2. Check if containers are running: docker ps | grep guac")
            print("  3. Check container logs: docker compose -f infra/guacamole/docker-compose.yml logs")

        elif result.classification == PreflightClassification.BASE_URL_WRONG:
            print()
            print("Troubleshooting steps:")
            print("  1. Check GUAC_BASE_URL in backend/.env.local")
            print("  2. Ensure it ends with '/guacamole' (e.g., http://127.0.0.1:8081/guacamole)")
            print("  3. Try opening the URL in a browser")

        elif result.classification == PreflightClassification.CREDS_WRONG:
            print()
            print("Troubleshooting steps:")
            print("  1. Check GUAC_ADMIN_USER and GUAC_ADMIN_PASSWORD in backend/.env.local")
            print("  2. Default credentials are guacadmin/guacadmin")
            print("  3. If you changed the password, update .env.local")

        elif result.classification == PreflightClassification.GUI_UNREACHABLE:
            print()
            print("Troubleshooting steps:")
            print("  1. If GUI shows ERROR page, run: make guac-reset")
            print("  2. Check Guacamole container logs")
            print("  3. Wait a few seconds for Guacamole to fully start")

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

    exit_code = asyncio.run(run_smoketest())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
