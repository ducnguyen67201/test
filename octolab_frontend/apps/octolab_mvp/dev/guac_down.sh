#!/usr/bin/env bash
# dev/guac_down.sh - Stop the Guacamole stack
#
# Usage:
#   ./dev/guac_down.sh         # Stop containers (preserves data)
#   ./dev/guac_down.sh -v      # Stop and remove volumes (DESTROYS DATA!)
#
# This script:
# - Stops the Guacamole stack safely
# - By default preserves data volumes
# - Use -v flag to remove volumes (destructive!)

set -euo pipefail

# Find repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

COMPOSE_FILE="$REPO_ROOT/infra/guacamole/docker-compose.yml"

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

# Check docker compose availability
check_docker() {
    if ! command -v docker &>/dev/null; then
        log_error "docker is not installed or not in PATH"
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

usage() {
    echo "Usage: $0 [-v]"
    echo ""
    echo "Options:"
    echo "  -v    Remove volumes (DESTROYS DATA!)"
    echo "  -h    Show this help"
}

main() {
    local remove_volumes=false

    while getopts "vh" opt; do
        case $opt in
            v)
                remove_volumes=true
                ;;
            h)
                usage
                exit 0
                ;;
            *)
                usage
                exit 1
                ;;
        esac
    done

    check_docker
    check_compose_file

    # Change to compose directory for consistent project naming
    cd "$(dirname "$COMPOSE_FILE")"

    if [[ "$remove_volumes" == "true" ]]; then
        log_warn "Stopping Guacamole stack AND removing volumes (data will be lost!)..."
        docker compose down -v
        log_info "Guacamole stack stopped and volumes removed."
    else
        log_info "Stopping Guacamole stack (data preserved)..."
        docker compose down
        log_info "Guacamole stack stopped. Data volumes preserved."
        echo ""
        echo "  To remove data volumes: ./dev/guac_down.sh -v"
    fi
}

main "$@"
