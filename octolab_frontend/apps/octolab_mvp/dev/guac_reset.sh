#!/usr/bin/env bash
# dev/guac_reset.sh - Reset Guacamole stack (nuke and pave)
#
# DEV-ONLY: This script completely destroys and recreates the Guacamole stack.
# Use when Guacamole shows an ERROR page or has stale DB state.
#
# Usage:
#   ./dev/guac_reset.sh          # Interactive (prompts for confirmation)
#   ./dev/guac_reset.sh --yes    # Non-interactive (for scripts)
#   ./dev/guac_reset.sh -y       # Non-interactive (short form)
#
# This script:
# 1. Stops the Guacamole compose project
# 2. Removes all containers and volumes (docker compose down -v --remove-orphans)
# 3. Starts the stack fresh
# 4. Waits for DB health + web readiness
# 5. Runs the smoketest to verify API is functional
#
# SAFETY:
# - Only operates on the infra/guacamole compose project
# - Does NOT affect the main database or other services
# - Does NOT delete any code or configuration files
#
# Exit codes:
#   0 - Reset successful, Guacamole is ready
#   1 - Reset failed (see output)

set -euo pipefail

# Find repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

COMPOSE_DIR="$REPO_ROOT/infra/guacamole"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.yml"
GUAC_UP_SCRIPT="$SCRIPT_DIR/guac_up.sh"
INITDB_GENERATOR="$SCRIPT_DIR/scripts/guac_generate_initdb.py"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
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

log_header() {
    echo -e "\n${BLUE}=== $1 ===${NC}"
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

# Confirm destructive action
confirm_reset() {
    log_warn "This will DESTROY all Guacamole data and restart fresh!"
    echo ""
    echo "  This will delete:"
    echo "    - All Guacamole users and connections"
    echo "    - Connection history"
    echo "    - All database data"
    echo ""
    echo "  This will NOT affect:"
    echo "    - Your backend database (octolab_dev)"
    echo "    - Your code or configuration files"
    echo "    - Other Docker services"
    echo ""

    read -p "Continue? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Aborted."
        exit 0
    fi
}

# Regenerate initdb.sql from image tag
regenerate_initdb() {
    log_header "Regenerating initdb.sql from image tag"

    if [[ ! -f "$INITDB_GENERATOR" ]]; then
        log_warn "InitDB generator not found: $INITDB_GENERATOR"
        log_warn "Skipping regeneration - using existing initdb.sql"
        return 0
    fi

    log_info "Running: python3 $INITDB_GENERATOR"
    if python3 "$INITDB_GENERATOR"; then
        log_info "InitDB regeneration complete."
    else
        log_error "InitDB generation failed!"
        log_error "The existing initdb.sql will be used, but may not match the image version."
        log_warn "Check infra/guacamole/init/initdb.sql manually if you see schema errors."
        # Don't fail - continue with existing file
    fi
}

# Nuke the compose project
nuke_compose() {
    log_header "Stopping and removing Guacamole stack"

    cd "$COMPOSE_DIR"

    # Stop all containers, remove orphans, and delete volumes
    log_info "Running: docker compose down -v --remove-orphans"
    docker compose down -v --remove-orphans 2>&1 || true

    # Double-check volumes are gone
    log_info "Cleaning up any remaining volumes..."
    local volumes
    volumes=$(docker volume ls --format '{{.Name}}' | grep -E '^guacamole_' || true)
    if [[ -n "$volumes" ]]; then
        echo "$volumes" | while read -r vol; do
            log_info "Removing volume: $vol"
            docker volume rm "$vol" 2>/dev/null || true
        done
    fi

    log_info "Guacamole stack removed."
}

# Start fresh using guac_up.sh
start_fresh() {
    log_header "Starting fresh Guacamole stack"

    if [[ ! -x "$GUAC_UP_SCRIPT" ]]; then
        log_error "guac_up.sh not found or not executable: $GUAC_UP_SCRIPT"
        exit 1
    fi

    # Run guac_up.sh which handles starting, waiting, and smoketest
    "$GUAC_UP_SCRIPT"
}

# Print success message
print_success() {
    log_header "Guacamole Reset: COMPLETE"
    echo ""
    echo -e "  ${GREEN}Stack:${NC}      Reset and running"
    echo -e "  ${GREEN}Database:${NC}   Fresh (init SQL applied)"
    echo -e "  ${GREEN}Web UI:${NC}     http://127.0.0.1:8081/guacamole/"
    echo ""
    echo "  Default login: guacadmin / guacadmin"
    echo ""
    echo "  Next steps:"
    echo "    make dev-up   # Continue with dev bootstrap"
    echo "    make dev      # Start the backend"
    echo ""
}

usage() {
    echo "Usage: $0 [-y|--yes]"
    echo ""
    echo "Options:"
    echo "  -y, --yes    Skip confirmation prompt"
    echo "  -h, --help   Show this help"
    echo ""
    echo "This script destroys and recreates the Guacamole stack."
    echo "Use when Guacamole shows an ERROR page or has database issues."
}

main() {
    local skip_confirm=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -y|--yes)
                skip_confirm=true
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done

    check_docker
    check_compose_file

    # Confirm unless --yes
    if [[ "$skip_confirm" != "true" ]]; then
        confirm_reset
    fi

    # Regenerate initdb.sql to match image version
    regenerate_initdb

    # Nuke and start fresh
    nuke_compose
    start_fresh

    print_success
    exit 0
}

main "$@"
