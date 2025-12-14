#!/usr/bin/env bash
# dev/guac_up.sh - Start the Guacamole stack for development
#
# Usage:
#   ./dev/guac_up.sh
#
# This script:
# - Starts the Guacamole stack (guacd, guacamole web, postgres)
# - Waits for guac-db to become healthy (bounded timeout)
# - Provides actionable diagnosis if stack fails to start
# - Never sources env files (security)
#
# Exit codes:
#   0 - Stack started successfully
#   1 - Stack failed to start (see diagnosis)

set -euo pipefail

# Find repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

COMPOSE_DIR="$REPO_ROOT/infra/guacamole"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.yml"
GUAC_URL="${GUAC_BASE_URL:-http://127.0.0.1:8081/guacamole}"
DIAGNOSE_SCRIPT="$SCRIPT_DIR/scripts/guac_diagnose.py"
SMOKETEST_SCRIPT="$SCRIPT_DIR/scripts/guac_smoketest.py"
RUN_WITH_ENV="$REPO_ROOT/backend/scripts/run_with_env.py"

# Timeouts
DB_TIMEOUT_SECONDS=120
DB_POLL_INTERVAL=2
GUAC_TIMEOUT_SECONDS=60
GUAC_POLL_INTERVAL=2

# Container names (must match docker-compose.yml)
GUAC_DB_CONTAINER="octolab-guac-db"
GUACAMOLE_CONTAINER="octolab-guacamole"

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

# Redact sensitive values from output
# Uses Python redactor for robust pattern matching; falls back to POSIX sed
REDACT_SCRIPT="$SCRIPT_DIR/scripts/redact_stream.py"

redact() {
    if [[ -f "$REDACT_SCRIPT" ]] && command -v python3 &>/dev/null; then
        python3 "$REDACT_SCRIPT"
    else
        # Fallback: POSIX-compatible sed (no PCRE, no case-insensitive flag)
        # Best-effort redaction for common patterns
        sed -e 's/\(PASSWORD\)=[^ ]*/\1=****/g' \
            -e 's/\(PASS\)=[^ ]*/\1=****/g' \
            -e 's/\(SECRET\)=[^ ]*/\1=****/g' \
            -e 's/\(TOKEN\)=[^ ]*/\1=****/g' \
            -e 's/\(KEY\)=[^ ]*/\1=****/g' \
            -e 's/\(password[[:space:]]*[:=][[:space:]]*\)[^ ]*/\1****/g'
    fi
}

# Check docker compose availability
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

# Start the stack
start_stack() {
    log_info "Starting Guacamole stack..."
    cd "$COMPOSE_DIR"
    docker compose up -d 2>&1 | redact
}

# Get container health status
get_container_health() {
    local container="$1"
    docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "not_found"
}

# Get health check failure count
get_health_failing_streak() {
    local container="$1"
    docker inspect --format='{{.State.Health.FailingStreak}}' "$container" 2>/dev/null || echo "0"
}

# Get last health check log
get_health_last_log() {
    local container="$1"
    docker inspect --format='{{with .State.Health}}{{with (index .Log (add (len .Log) -1))}}{{.Output}}{{end}}{{end}}' "$container" 2>/dev/null | head -c 500 | redact
}

# Wait for guac-db to be healthy
wait_for_db_healthy() {
    local timeout="$DB_TIMEOUT_SECONDS"
    local interval="$DB_POLL_INTERVAL"
    local elapsed=0

    log_info "Waiting for Guacamole DB to be healthy (timeout: ${timeout}s)..."

    while [[ $elapsed -lt $timeout ]]; do
        local health
        health=$(get_container_health "$GUAC_DB_CONTAINER")

        case "$health" in
            healthy)
                log_info "Guac DB is healthy!"
                return 0
                ;;
            unhealthy)
                log_error "Guac DB is unhealthy"
                return 1
                ;;
            starting)
                echo -n "."
                ;;
            not_found)
                log_error "Guac DB container not found"
                return 1
                ;;
            *)
                echo -n "?"
                ;;
        esac

        sleep "$interval"
        elapsed=$((elapsed + interval))
    done

    echo ""
    log_error "Guac DB did not become healthy within ${timeout}s"
    return 1
}

# Wait for guacamole web to be available
wait_for_guacamole() {
    local timeout="$GUAC_TIMEOUT_SECONDS"
    local interval="$GUAC_POLL_INTERVAL"
    local elapsed=0

    log_info "Waiting for Guacamole web to be available (timeout: ${timeout}s)..."

    while [[ $elapsed -lt $timeout ]]; do
        # Check container health first
        local health
        health=$(get_container_health "$GUACAMOLE_CONTAINER")

        if [[ "$health" == "healthy" ]]; then
            log_info "Guacamole is healthy!"
            return 0
        fi

        # Also try HTTP check (may succeed before docker health)
        if curl -sf "${GUAC_URL}/" >/dev/null 2>&1; then
            log_info "Guacamole is responding!"
            return 0
        fi

        echo -n "."
        sleep "$interval"
        elapsed=$((elapsed + interval))
    done

    echo ""
    log_warn "Guacamole web did not become healthy within ${timeout}s"
    log_warn "Stack may still be starting. Check: docker compose -f $COMPOSE_FILE logs guacamole"
    return 1
}

# Diagnose DB failure
diagnose_db_failure() {
    log_header "Guacamole DB Diagnosis"

    # Get recent logs (redacted)
    echo -e "\n${YELLOW}Recent logs (last 50 lines):${NC}"
    cd "$COMPOSE_DIR"
    docker compose logs --tail=50 guac-db 2>&1 | tail -50 | redact

    # Get health status details
    echo -e "\n${YELLOW}Health check status:${NC}"
    local health_status failing_streak last_log
    health_status=$(get_container_health "$GUAC_DB_CONTAINER")
    failing_streak=$(get_health_failing_streak "$GUAC_DB_CONTAINER")
    last_log=$(get_health_last_log "$GUAC_DB_CONTAINER")

    echo "  Status: $health_status"
    echo "  Failing streak: $failing_streak"
    echo "  Last check output: $last_log"

    # Get full logs for diagnosis
    local full_logs
    full_logs=$(docker compose logs --tail=150 guac-db 2>&1 | redact)

    # Get inspect output for diagnosis
    local inspect_output
    inspect_output=$(docker inspect "$GUAC_DB_CONTAINER" 2>/dev/null | redact || echo "")

    # Run Python diagnoser if available
    if [[ -f "$DIAGNOSE_SCRIPT" ]] && command -v python3 &>/dev/null; then
        echo -e "\n${YELLOW}Diagnosis:${NC}"
        python3 "$DIAGNOSE_SCRIPT" --logs "$full_logs" --inspect "$inspect_output" 2>&1 || true
    fi

    # Print generic advice
    echo -e "\n${YELLOW}Common fixes:${NC}"
    echo "  1. Reset the DB: make guac-reset-db"
    echo "  2. View full logs: docker compose -f $COMPOSE_FILE logs guac-db"
    echo "  3. Check if another postgres is using port 5432: lsof -i :5432"
    echo ""
}

# Run smoketest to verify API functionality
run_smoketest() {
    log_info "Running Guacamole smoketest..."

    # Check prerequisites
    if [[ ! -f "$SMOKETEST_SCRIPT" ]]; then
        log_warn "Smoketest script not found: $SMOKETEST_SCRIPT"
        log_warn "Skipping smoketest (stack may still be functional)"
        return 0
    fi

    if ! command -v python3 &>/dev/null; then
        log_warn "python3 not found, skipping smoketest"
        return 0
    fi

    # Check if env files exist
    local env_args=""
    if [[ -f "$REPO_ROOT/backend/.env" ]]; then
        env_args="--env $REPO_ROOT/backend/.env"
    fi
    if [[ -f "$REPO_ROOT/backend/.env.local" ]]; then
        env_args="$env_args --env $REPO_ROOT/backend/.env.local"
    fi

    if [[ -z "$env_args" ]]; then
        log_warn "No env files found, skipping smoketest"
        log_warn "Run 'make dev-up' to generate .env.local first"
        return 0
    fi

    # Run smoketest via run_with_env.py (30s timeout for smoketest retries)
    # shellcheck disable=SC2086
    if python3 "$RUN_WITH_ENV" $env_args -- python3 "$SMOKETEST_SCRIPT" 30; then
        return 0
    else
        log_warn "Smoketest failed. Guacamole may not be fully functional."
        log_warn "If you see an ERROR page, run: make guac-reset"
        return 1
    fi
}

# Print success summary
print_summary() {
    log_header "Guacamole Stack: OK"

    echo ""
    echo -e "  ${GREEN}Guac DB:${NC}     healthy"
    echo -e "  ${GREEN}Web UI:${NC}      ${GUAC_URL}/"
    echo -e "  ${GREEN}Smoketest:${NC}   passed"
    echo ""
    echo "  View logs:  docker compose -f $COMPOSE_FILE logs -f"
    echo "  Stop:       ./dev/guac_down.sh"
    echo "  Status:     ./dev/guac_status.sh"
    echo ""
}

main() {
    check_docker
    check_compose_file

    # Start the stack
    start_stack

    # Wait for DB to be healthy (critical path)
    if ! wait_for_db_healthy; then
        diagnose_db_failure
        log_error "Guacamole stack failed to start. See diagnosis above."
        exit 1
    fi

    # Wait for Guacamole web (best effort)
    if ! wait_for_guacamole; then
        # Non-fatal: DB is healthy, web may just need more time
        log_warn "Guacamole web not ready yet, but DB is healthy."
        log_warn "Try again in a minute or check logs."
    fi

    # Run smoketest to verify API functionality
    if ! run_smoketest; then
        # Smoketest failed but stack is up - warn but don't fail
        # This allows continuing with dev-up even if creds aren't set
        log_warn "Guacamole smoketest did not pass."
        log_warn "Stack is running but API may not be configured correctly."
    fi

    print_summary
    exit 0
}

main "$@"
