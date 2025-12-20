#!/usr/bin/env bash
# dev/guac_reset_db.sh - Reset Guacamole database (destructive!)
#
# Usage:
#   ./dev/guac_reset_db.sh
#
# This script:
# - Stops the Guacamole stack
# - Removes ONLY the guac-db volume (guac-db-data)
# - Does NOT restart the stack (run: make guac-up)
#
# WARNING: This DELETES all Guacamole data including:
# - Users and permissions
# - Connection configurations
# - Connection history
#
# Use this when:
# - Guac DB healthcheck fails due to stale credentials
# - Volume contains incompatible PostgreSQL data
# - Init SQL script changed and needs to re-run
#
# Exit codes:
#   0 - Reset successful
#   1 - Reset failed

set -euo pipefail

# Find repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

COMPOSE_DIR="$REPO_ROOT/infra/guacamole"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.yml"

# Volume name (must match docker-compose.yml)
# Compose prefixes volume names with project name (directory name)
VOLUME_NAME="guacamole_guac-db-data"

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

# Check docker availability
check_docker() {
    if ! command -v docker &>/dev/null; then
        log_error "docker is not installed or not in PATH"
        exit 1
    fi

    if ! docker info &>/dev/null; then
        log_error "docker daemon is not running or not accessible"
        exit 1
    fi
}

# Check if compose file exists
check_compose_file() {
    if [[ ! -f "$COMPOSE_FILE" ]]; then
        log_error "Compose file not found: $COMPOSE_FILE"
        exit 1
    fi
}

# Stop the stack
stop_stack() {
    log_info "Stopping Guacamole stack..."
    cd "$COMPOSE_DIR"
    docker compose down 2>&1 || true
}

# Remove the database volume
remove_volume() {
    log_info "Removing Guacamole DB volume..."

    # Try to find the actual volume name (compose may prefix differently)
    local actual_volume
    actual_volume=$(docker volume ls --format '{{.Name}}' | grep -E 'guac.*db.*data' | head -1 || echo "")

    if [[ -z "$actual_volume" ]]; then
        log_warn "No Guac DB volume found. May already be removed."
        return 0
    fi

    log_info "Found volume: $actual_volume"

    if docker volume rm "$actual_volume" 2>&1; then
        log_info "Volume removed successfully"
        return 0
    else
        log_error "Failed to remove volume: $actual_volume"
        log_error "It may be in use. Ensure all containers are stopped."
        return 1
    fi
}

# Print summary
print_summary() {
    echo ""
    log_info "Guacamole DB reset complete!"
    echo ""
    echo "  The Guacamole database has been wiped."
    echo "  Init SQL will run again on next startup."
    echo ""
    echo "  To restart Guacamole: make guac-up"
    echo "  Or: ./dev/guac_up.sh"
    echo ""
}

main() {
    log_warn "This will DELETE all Guacamole data!"
    echo "  - Users and permissions"
    echo "  - Connection configurations"
    echo "  - Connection history"
    echo ""

    # Allow non-interactive mode with --yes flag
    if [[ "${1:-}" != "--yes" ]] && [[ "${1:-}" != "-y" ]]; then
        read -p "Continue? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Aborted."
            exit 0
        fi
    fi

    check_docker
    check_compose_file

    stop_stack

    if remove_volume; then
        print_summary
        exit 0
    else
        log_error "Reset failed. Check errors above."
        exit 1
    fi
}

main "$@"
