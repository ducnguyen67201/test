#!/usr/bin/env bash
# dev/db_migrate.sh - Run database migrations
#
# Usage:
#   ./dev/db_migrate.sh              # Run all pending migrations (upgrade head)
#   ./dev/db_migrate.sh upgrade head # Same as above
#   ./dev/db_migrate.sh downgrade -1 # Rollback one migration
#   ./dev/db_migrate.sh current      # Show current revision
#   ./dev/db_migrate.sh history      # Show migration history
#   ./dev/db_migrate.sh revision -m "message" # Create new migration
#
# This script:
# - Uses run_with_env.py for secure environment loading
# - Never sources env files
# - Runs alembic with proper DATABASE_URL

set -euo pipefail

# Find repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

BACKEND_DIR="$REPO_ROOT/backend"
RUN_WITH_ENV="$BACKEND_DIR/scripts/run_with_env.py"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

# Check Python availability
check_python() {
    if ! command -v python3 &>/dev/null; then
        log_error "python3 is not installed or not in PATH"
        exit 1
    fi
}

# Check run_with_env.py exists
check_env_loader() {
    if [[ ! -f "$RUN_WITH_ENV" ]]; then
        log_error "run_with_env.py not found: $RUN_WITH_ENV"
        exit 1
    fi
}

# Check alembic is available
check_alembic() {
    if ! python3 -c "import alembic" &>/dev/null; then
        log_error "alembic is not installed. Run: pip install alembic"
        exit 1
    fi
}

# Build env file arguments
get_env_args() {
    local args=""

    # Always include base .env
    if [[ -f "$BACKEND_DIR/.env" ]]; then
        args="--env $BACKEND_DIR/.env"
    fi

    # Include .env.local if it exists
    if [[ -f "$BACKEND_DIR/.env.local" ]]; then
        args="$args --env $BACKEND_DIR/.env.local"
    fi

    echo "$args"
}

# Run alembic command
run_alembic() {
    local env_args
    env_args=$(get_env_args)

    # Change to backend directory for alembic.ini
    cd "$BACKEND_DIR"

    log_info "Running: alembic $*"

    # Use run_with_env.py to load environment and run alembic
    # shellcheck disable=SC2086
    python3 "$RUN_WITH_ENV" $env_args -- python3 -m alembic "$@"
}

usage() {
    echo "Usage: $0 [alembic command] [args...]"
    echo ""
    echo "Common commands:"
    echo "  upgrade head      Run all pending migrations (default)"
    echo "  downgrade -1      Rollback one migration"
    echo "  current           Show current revision"
    echo "  history           Show migration history"
    echo "  revision -m 'msg' Create new migration"
    echo ""
    echo "Examples:"
    echo "  $0                           # upgrade head"
    echo "  $0 upgrade head"
    echo "  $0 downgrade -1"
    echo "  $0 current"
    echo "  $0 revision --autogenerate -m 'Add user table'"
}

main() {
    # Show help
    if [[ "${1:-}" == "-h" ]] || [[ "${1:-}" == "--help" ]]; then
        usage
        exit 0
    fi

    check_python
    check_env_loader
    check_alembic

    # Default to 'upgrade head' if no args
    if [[ $# -eq 0 ]]; then
        run_alembic upgrade head
    else
        run_alembic "$@"
    fi
}

main "$@"
