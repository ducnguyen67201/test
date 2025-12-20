"""Pytest configuration and fixtures.

This conftest.py provides:
1. Hard guardrails to prevent tests from running against dev/production databases
2. Common fixtures for test setup
3. Support for `no_db` marker to exempt tests from database requirements

SAFETY REQUIREMENTS:
- Tests MUST run with APP_ENV=test (unless all tests have @pytest.mark.no_db)
- Database name MUST end with "_test"
- Database host should be localhost or test-specific (no production DBs)

MARKERS:
- @pytest.mark.no_db - Mark test as not requiring a database. Tests with this
  marker will run even if DATABASE_URL is not configured.

These checks run before ANY test, preventing accidental data corruption.
"""

import os
import re
from urllib.parse import urlparse

import pytest


# ============================================================================
# Marker Registration and Collection Hooks
# ============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "no_db: mark test as not requiring database access"
    )


def pytest_collection_modifyitems(config, items):
    """Determine if any tests require database access.

    Sets config._octolab_requires_db = True if ANY collected test
    does NOT have the @pytest.mark.no_db marker.
    """
    requires_db = any(
        not item.get_closest_marker("no_db")
        for item in items
    )
    config._octolab_requires_db = requires_db


def redact_password(url: str) -> str:
    """Redact password from database URL for safe logging.

    Args:
        url: Database URL (may contain password)

    Returns:
        URL with password replaced by "****"

    Examples:
        postgresql://user:pass@host/db -> postgresql://user:****@host/db
    """
    # Simple regex to redact password
    return re.sub(r'://([^:]+):([^@]+)@', r'://\1:****@', url)


@pytest.fixture(scope="session", autouse=True)
def enforce_test_database(request):
    """Enforce that tests only run against test databases.

    This fixture runs ONCE per test session (before any tests) and validates:
    1. APP_ENV environment variable is set to "test"
    2. DATABASE_URL points to a database ending with "_test"
    3. Database host is local (localhost/127.0.0.1) or explicitly allowed

    SKIP CONDITION:
    If ALL collected tests have the @pytest.mark.no_db marker, this fixture
    skips all database checks. This allows running unit tests that don't
    need a database without configuring DATABASE_URL.

    Raises:
        RuntimeError: If any safety check fails (and tests require DB)

    This is a critical safety measure to prevent:
    - Tests creating/dropping tables in development database
    - Test data polluting development environment
    - Accidental data loss from test cleanup operations
    """
    # Check if any tests require database
    requires_db = getattr(request.config, "_octolab_requires_db", True)

    if not requires_db:
        print("\n✓ All tests marked with @pytest.mark.no_db, skipping database safety checks")
        return

    # Check 1: APP_ENV must be "test"
    app_env = os.getenv("APP_ENV", "").lower()
    if app_env != "test":
        raise RuntimeError(
            f"Refusing to run tests: APP_ENV is '{app_env}' (expected 'test').\n"
            f"Tests can only run with APP_ENV=test to prevent accidental dev DB usage.\n"
            f"Use: export APP_ENV=test or source backend/.env.test"
        )

    # Check 2: DATABASE_URL must point to a test database
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError(
            "Refusing to run tests: DATABASE_URL is not set.\n"
            "Tests require an explicit test database URL.\n"
            "Use: backend/.env.test or export DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/octolab_test"
        )

    # Parse database URL (safely, without exposing password)
    try:
        parsed = urlparse(database_url)
        db_name = parsed.path.lstrip('/')  # Remove leading /
        db_host = parsed.hostname or ""
    except Exception as e:
        # Don't expose the URL in error message
        raise RuntimeError(
            f"Refusing to run tests: Failed to parse DATABASE_URL (error: {type(e).__name__}).\n"
            "Ensure DATABASE_URL is a valid PostgreSQL URL."
        )

    # Check 2a: Database name must end with "_test"
    if not db_name.endswith("_test"):
        raise RuntimeError(
            f"Refusing to run tests: Database name '{db_name}' does not end with '_test'.\n"
            f"Test databases MUST have names ending in '_test' for safety.\n"
            f"DATABASE_URL (redacted): {redact_password(database_url)}\n"
            f"Example: postgresql+asyncpg://octolab:password@localhost:5432/octolab_test"
        )

    # Check 2b: Database host should be local (optional but recommended)
    # Allow localhost, 127.0.0.1, or docker service names (for CI)
    safe_hosts = {
        "localhost",
        "127.0.0.1",
        "::1",
        "postgres",        # Docker Compose service name
        "octolab-postgres",  # Common test DB service name
    }

    # Allow override for CI or remote test DBs
    allow_remote_test_db = os.getenv("ALLOW_REMOTE_TEST_DB", "").lower() in ("1", "true", "yes")

    if db_host.lower() not in safe_hosts and not allow_remote_test_db:
        raise RuntimeError(
            f"Refusing to run tests: Database host '{db_host}' is not in safe list.\n"
            f"Test database host should be localhost or a known test service.\n"
            f"DATABASE_URL (redacted): {redact_password(database_url)}\n"
            f"Safe hosts: {', '.join(sorted(safe_hosts))}\n"
            f"To allow remote test DB: export ALLOW_REMOTE_TEST_DB=true (use with caution)"
        )

    # All checks passed
    print(f"\n✓ Test database safety checks passed:")
    print(f"  - APP_ENV: {app_env}")
    print(f"  - Database: {db_name} (on {db_host})")
    print(f"  - DATABASE_URL (redacted): {redact_password(database_url)}")
    print("")


# Additional fixtures can be added here as needed
# Examples:
# - Database session fixtures
# - Mock runtime fixtures
# - Test user creation fixtures
