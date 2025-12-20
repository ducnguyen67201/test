#!/usr/bin/env bash
# dev/guac_status.sh - Check Guacamole stack status
#
# Usage:
#   ./dev/guac_status.sh
#
# This script:
# - Shows docker compose ps output
# - Checks if Guacamole web UI is responding
# - Shows container health status

set -euo pipefail

# Find repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

COMPOSE_FILE="$REPO_ROOT/infra/guacamole/docker-compose.yml"
GUAC_URL="${GUAC_BASE_URL:-http://127.0.0.1:8081/guacamole}"

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
    echo -e "${RED}[ERROR]${NC} $1"
}

log_header() {
    echo -e "${BLUE}=== $1 ===${NC}"
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

# Show container status
show_container_status() {
    log_header "Container Status"
    echo ""
    cd "$(dirname "$COMPOSE_FILE")"
    docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Health}}\t{{.Ports}}"
    echo ""
}

# Check individual container health
check_container_health() {
    local container=$1
    local health_status

    health_status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "not_found")

    case "$health_status" in
        healthy)
            echo -e "  $container: ${GREEN}healthy${NC}"
            return 0
            ;;
        unhealthy)
            echo -e "  $container: ${RED}unhealthy${NC}"
            return 1
            ;;
        starting)
            echo -e "  $container: ${YELLOW}starting${NC}"
            return 1
            ;;
        not_found)
            echo -e "  $container: ${RED}not running${NC}"
            return 1
            ;;
        *)
            echo -e "  $container: ${YELLOW}$health_status${NC}"
            return 1
            ;;
    esac
}

# Check if Guacamole web UI is responding
check_web_ui() {
    log_header "Web UI Health Check"
    echo ""
    echo "  URL: $GUAC_URL/"

    local http_code
    http_code=$(curl -sf -o /dev/null -w "%{http_code}" "${GUAC_URL}/" 2>/dev/null || echo "000")

    if [[ "$http_code" == "200" ]] || [[ "$http_code" == "302" ]]; then
        echo -e "  Status: ${GREEN}OK${NC} (HTTP $http_code)"
        return 0
    else
        echo -e "  Status: ${RED}FAILED${NC} (HTTP $http_code)"
        return 1
    fi
}

# Show health summary
show_health_summary() {
    log_header "Container Health"
    echo ""

    local all_healthy=true

    check_container_health "octolab-guac-db" || all_healthy=false
    check_container_health "octolab-guacd" || all_healthy=false
    check_container_health "octolab-guacamole" || all_healthy=false

    echo ""
    return 0
}

# Print summary
print_summary() {
    local web_ok=$1

    echo ""
    if [[ "$web_ok" == "true" ]]; then
        log_info "Guacamole stack is running and healthy"
        echo ""
        echo "  Web UI:   $GUAC_URL/"
        echo "  Login:    guacadmin / guacadmin"
    else
        log_warn "Guacamole stack has issues"
        echo ""
        echo "  View logs: cd infra/guacamole && docker compose logs"
        echo "  Restart:   ./dev/guac_down.sh && ./dev/guac_up.sh"
        echo "  Reset DB:  make guac-reset-db"
    fi
    echo ""
}

main() {
    check_docker
    check_compose_file

    echo ""
    show_container_status
    show_health_summary

    local web_ok="false"
    if check_web_ui; then
        web_ok="true"
    fi

    print_summary "$web_ok"
}

main "$@"
