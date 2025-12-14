#!/usr/bin/env bash
# Run backend tests with test database configuration
#
# This script ensures tests run with the correct test environment:
# - Loads .env.test for test database configuration
# - Sets APP_ENV=test to enable test mode
# - Runs pytest with proper isolation
#
# IMPORTANT: Tests will REFUSE to run without APP_ENV=test and DATABASE_URL ending in "_test"
#
# Usage:
#   ./backend/scripts/test.sh           # Run all tests
#   ./backend/scripts/test.sh -v        # Verbose output
#   ./backend/scripts/test.sh -k test_name  # Run specific test

set -euo pipefail

# Get script directory (works on Linux/WSL, repo-relative)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEST_ENV_FILE="${BACKEND_DIR}/.env.test"

echo "==> OctoLab Backend Tests"
echo ""

# Safety check: ensure not running from Windows mount
if [[ "$SCRIPT_DIR" == /mnt/* ]]; then
    echo "ERROR: Running from Windows filesystem mount ($SCRIPT_DIR)"
    echo "This is not supported. Please run from Linux filesystem."
    exit 1
fi

# Check prerequisites
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 is not installed"
    exit 1
fi

if ! python3 -m pytest --version &> /dev/null; then
    echo "ERROR: pytest is not installed"
    echo "Install: pip install pytest pytest-asyncio"
    exit 1
fi

# Check test environment file exists
if [ ! -f "${TEST_ENV_FILE}" ]; then
    echo "ERROR: Test environment file not found: ${TEST_ENV_FILE}"
    echo "Create it by copying .env.example and modifying for tests"
    exit 1
fi

# Load test environment variables
echo "Loading test environment from: ${TEST_ENV_FILE}"
set -a  # Export all variables
# shellcheck disable=SC1090
source "${TEST_ENV_FILE}"
set +a

# Verify critical env vars are set
if [ -z "${APP_ENV:-}" ]; then
    echo "ERROR: APP_ENV not set in ${TEST_ENV_FILE}"
    echo "Tests require APP_ENV=test"
    exit 1
fi

if [ "${APP_ENV}" != "test" ]; then
    echo "ERROR: APP_ENV is '${APP_ENV}' (expected 'test')"
    echo "Update ${TEST_ENV_FILE} to set APP_ENV=test"
    exit 1
fi

if [ -z "${DATABASE_URL:-}" ]; then
    echo "ERROR: DATABASE_URL not set in ${TEST_ENV_FILE}"
    echo "Tests require DATABASE_URL pointing to a test database"
    exit 1
fi

# Extract database name from URL (basic parsing)
DB_NAME=$(echo "${DATABASE_URL}" | sed -n 's|.*/\([^/?]*\).*|\1|p')
if [[ ! "$DB_NAME" =~ _test$ ]]; then
    echo "ERROR: Database name '${DB_NAME}' does not end with '_test'"
    echo "Update DATABASE_URL in ${TEST_ENV_FILE} to use a test database"
    echo "Example: postgresql+asyncpg://user:pass@localhost:5432/octolab_test"
    exit 1
fi

echo "✓ Test environment validated:"
echo "  - APP_ENV: ${APP_ENV}"
echo "  - Database: ${DB_NAME}"
echo ""

# Change to backend directory for pytest
cd "${BACKEND_DIR}"

# Run pytest with arguments passed to script
echo "Running pytest..."
echo ""

python3 -m pytest tests/ "$@"

exit_code=$?

echo ""
if [ $exit_code -eq 0 ]; then
    echo "✓ All tests passed"
else
    echo "✗ Some tests failed (exit code: $exit_code)"
fi

exit $exit_code
