#!/usr/bin/env bash
# dev/doctor.sh - Health check for OctoLab development environment
#
# Usage:
#   ./dev/doctor.sh
#
# Checks:
# - python3 >= 3.11
# - docker daemon running
# - docker compose available
# - PostgreSQL running and reachable
# - backend/.env.local exists and is valid
# - GUAC_ENC_KEY decodes to 32 bytes (if set)
# - Guacamole stack healthy (if GUAC_ENABLED=true)
#
# Exit codes:
#   0 - All checks passed
#   1 - One or more checks failed

set -uo pipefail

# Find repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

BACKEND_DIR="$REPO_ROOT/backend"
ENV_LOCAL="$BACKEND_DIR/.env.local"
COMPOSE_FILE="$REPO_ROOT/infra/guacamole/docker-compose.yml"

# Track overall status
FAILED=0

# Colors and symbols
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

check_pass() {
    echo -e "  ${GREEN}OK${NC}  $1"
}

check_fail() {
    echo -e "  ${RED}FAIL${NC}  $1"
    FAILED=1
}

check_warn() {
    echo -e "  ${YELLOW}WARN${NC}  $1"
}

check_skip() {
    echo -e "  ${BLUE}SKIP${NC}  $1"
}

section() {
    echo ""
    echo -e "${BLUE}=== $1 ===${NC}"
}

# ============================================================================
# Python Checks
# ============================================================================
check_python() {
    section "Python"

    # Check python3 exists
    if ! command -v python3 &>/dev/null; then
        check_fail "python3 not found"
        return
    fi

    # Check version >= 3.11
    local version
    version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    local major minor
    major=$(echo "$version" | cut -d. -f1)
    minor=$(echo "$version" | cut -d. -f2)

    if [[ "$major" -ge 3 ]] && [[ "$minor" -ge 11 ]]; then
        check_pass "python3 $version (>= 3.11 required)"
    else
        check_fail "python3 $version (>= 3.11 required)"
    fi

    # Check key packages
    if python3 -c "import fastapi" &>/dev/null; then
        check_pass "fastapi installed"
    else
        check_fail "fastapi not installed (pip install fastapi)"
    fi

    if python3 -c "import alembic" &>/dev/null; then
        check_pass "alembic installed"
    else
        check_fail "alembic not installed (pip install alembic)"
    fi

    if python3 -c "import cryptography" &>/dev/null; then
        check_pass "cryptography installed"
    else
        check_fail "cryptography not installed (pip install cryptography)"
    fi
}

# ============================================================================
# Docker Checks
# ============================================================================
check_docker() {
    section "Docker"

    # Check docker exists
    if ! command -v docker &>/dev/null; then
        check_fail "docker not found"
        return
    fi
    check_pass "docker installed"

    # Check docker daemon running
    if docker info &>/dev/null; then
        check_pass "docker daemon running"
    else
        check_fail "docker daemon not running or not accessible"
    fi

    # Check docker compose
    if docker compose version &>/dev/null; then
        local compose_version
        compose_version=$(docker compose version --short 2>/dev/null || echo "unknown")
        check_pass "docker compose $compose_version"
    else
        check_fail "docker compose not available"
    fi
}

# ============================================================================
# Environment File Checks
# ============================================================================
check_env_files() {
    section "Environment Files"

    # Check .env exists
    if [[ -f "$BACKEND_DIR/.env" ]]; then
        check_pass "backend/.env exists"
    else
        check_warn "backend/.env missing (using defaults)"
    fi

    # Check .env.local exists
    if [[ -f "$ENV_LOCAL" ]]; then
        check_pass "backend/.env.local exists"

        # Check permissions (should be 600)
        local perms
        perms=$(stat -c "%a" "$ENV_LOCAL" 2>/dev/null || stat -f "%OLp" "$ENV_LOCAL" 2>/dev/null || echo "unknown")
        if [[ "$perms" == "600" ]]; then
            check_pass "backend/.env.local permissions 600"
        else
            check_warn "backend/.env.local permissions $perms (should be 600)"
        fi
    else
        check_fail "backend/.env.local missing (run: make dev-up or python dev/scripts/ensure_env_local.py)"
    fi

    # Check GUAC_ENC_KEY if .env.local exists
    if [[ -f "$ENV_LOCAL" ]]; then
        local guac_enc_key
        guac_enc_key=$(grep -E "^GUAC_ENC_KEY=" "$ENV_LOCAL" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'" || echo "")

        if [[ -n "$guac_enc_key" ]]; then
            # Validate it decodes to 32 bytes
            local decoded_len
            decoded_len=$(python3 -c "
import base64
import sys
try:
    key = '$guac_enc_key'
    decoded = base64.urlsafe_b64decode(key)
    print(len(decoded))
except Exception as e:
    print('error')
" 2>/dev/null || echo "error")

            if [[ "$decoded_len" == "32" ]]; then
                check_pass "GUAC_ENC_KEY valid (32 bytes)"
            else
                check_fail "GUAC_ENC_KEY invalid (expected 32 bytes, got: $decoded_len)"
            fi
        else
            check_warn "GUAC_ENC_KEY not set in .env.local"
        fi
    fi
}

# ============================================================================
# Database Checks
# ============================================================================
check_database() {
    section "Database"

    # Get DATABASE_URL from env files
    local db_url=""

    # Try .env.local first
    if [[ -f "$ENV_LOCAL" ]]; then
        db_url=$(grep -E "^DATABASE_URL=" "$ENV_LOCAL" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'" || echo "")
    fi

    # Fall back to .env
    if [[ -z "$db_url" ]] && [[ -f "$BACKEND_DIR/.env" ]]; then
        db_url=$(grep -E "^DATABASE_URL=" "$BACKEND_DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'" || echo "")
    fi

    if [[ -z "$db_url" ]]; then
        check_warn "DATABASE_URL not set"
        return
    fi

    # Extract host and port from URL
    # postgresql+asyncpg://user:pass@host:port/db
    local host port
    host=$(echo "$db_url" | sed -n 's|.*@\([^:/]*\).*|\1|p')
    port=$(echo "$db_url" | sed -n 's|.*:\([0-9]*\)/.*|\1|p')
    port=${port:-5432}

    if [[ -z "$host" ]]; then
        check_warn "Could not parse DATABASE_URL"
        return
    fi

    check_pass "DATABASE_URL configured (host: $host)"

    # Try to connect
    if command -v nc &>/dev/null; then
        if nc -z "$host" "$port" 2>/dev/null; then
            check_pass "PostgreSQL reachable at $host:$port"
        else
            check_fail "PostgreSQL not reachable at $host:$port"
        fi
    elif command -v pg_isready &>/dev/null; then
        if pg_isready -h "$host" -p "$port" &>/dev/null; then
            check_pass "PostgreSQL ready at $host:$port"
        else
            check_fail "PostgreSQL not ready at $host:$port"
        fi
    else
        check_skip "Cannot check PostgreSQL (nc/pg_isready not found)"
    fi
}

# ============================================================================
# Alembic Migration Checks
# ============================================================================
check_alembic() {
    section "Alembic Migrations"

    # Check if alembic.ini exists
    if [[ ! -f "$BACKEND_DIR/alembic.ini" ]]; then
        check_warn "alembic.ini not found in backend/"
        return
    fi
    check_pass "alembic.ini exists"

    # Check if we can run alembic (requires database to be reachable)
    # We use run_with_env.py to load env vars safely
    local alembic_current
    local alembic_head

    # Get current revision
    alembic_current=$(python3 "$BACKEND_DIR/scripts/run_with_env.py" \
        --env "$BACKEND_DIR/.env" \
        --env "$ENV_LOCAL" \
        -- python3 -c "
import subprocess
import sys
result = subprocess.run(
    ['alembic', 'current'],
    capture_output=True,
    text=True,
    cwd='$BACKEND_DIR'
)
# Extract revision from output like '7e9c3bfe2f34 (head)'
import re
match = re.search(r'^([a-f0-9]+)', result.stdout.strip(), re.MULTILINE)
if match:
    print(match.group(1))
elif 'FAILED' in result.stderr or result.returncode != 0:
    print('ERROR')
else:
    print('NONE')
" 2>/dev/null || echo "ERROR")

    # Get head revision
    alembic_head=$(cd "$BACKEND_DIR" && alembic heads 2>/dev/null | head -n1 | awk '{print $1}' || echo "ERROR")

    if [[ "$alembic_current" == "ERROR" ]]; then
        check_warn "Cannot check alembic current (DB not reachable?)"
        return
    fi

    if [[ "$alembic_head" == "ERROR" ]]; then
        check_warn "Cannot determine alembic head revision"
        return
    fi

    if [[ "$alembic_current" == "NONE" ]]; then
        check_fail "No migrations applied (run: make db-migrate)"
        return
    fi

    # Compare current to head
    if [[ "$alembic_current" == "$alembic_head" ]]; then
        check_pass "Alembic at head ($alembic_current)"
    else
        check_fail "Alembic not at head (current: $alembic_current, head: $alembic_head)"
        echo "      Fix: make db-migrate"
    fi
}

# ============================================================================
# Guacamole Checks
# ============================================================================
check_guacamole() {
    section "Guacamole"

    # Check if GUAC_ENABLED
    local guac_enabled=""

    if [[ -f "$ENV_LOCAL" ]]; then
        guac_enabled=$(grep -E "^GUAC_ENABLED=" "$ENV_LOCAL" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'" || echo "")
    fi

    if [[ -z "$guac_enabled" ]] && [[ -f "$BACKEND_DIR/.env" ]]; then
        guac_enabled=$(grep -E "^GUAC_ENABLED=" "$BACKEND_DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'" || echo "")
    fi

    if [[ "$guac_enabled" != "true" ]]; then
        check_skip "GUAC_ENABLED is not true (Guacamole integration disabled)"
        return
    fi

    check_pass "GUAC_ENABLED=true"

    # Check compose file exists
    if [[ ! -f "$COMPOSE_FILE" ]]; then
        check_fail "Guacamole compose file not found: $COMPOSE_FILE"
        return
    fi
    check_pass "Guacamole compose file exists"

    # Check containers running
    local containers=("octolab-guac-db" "octolab-guacd" "octolab-guacamole")
    for container in "${containers[@]}"; do
        if docker inspect "$container" &>/dev/null; then
            local status
            status=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null || echo "unknown")
            if [[ "$status" == "running" ]]; then
                check_pass "$container running"
            else
                check_fail "$container status: $status"
            fi
        else
            check_fail "$container not found"
        fi
    done

    # Check web UI
    local guac_url="${GUAC_BASE_URL:-http://127.0.0.1:8081/guacamole}"
    local http_code
    http_code=$(curl -sf -o /dev/null -w "%{http_code}" "${guac_url}/" 2>/dev/null || echo "000")

    if [[ "$http_code" == "200" ]] || [[ "$http_code" == "302" ]]; then
        check_pass "Guacamole web UI responding (HTTP $http_code)"
    else
        check_fail "Guacamole web UI not responding (HTTP $http_code)"
    fi
}

# ============================================================================
# WSL Check
# ============================================================================
check_wsl() {
    section "Platform"

    if grep -qi microsoft /proc/version 2>/dev/null; then
        check_pass "Running on WSL"

        # Check if repo is on Windows mount (bad for performance)
        if [[ "$REPO_ROOT" == /mnt/* ]]; then
            check_warn "Repo on Windows mount ($REPO_ROOT) - may have performance issues"
        else
            check_pass "Repo on Linux filesystem"
        fi
    else
        check_pass "Running on native Linux"
    fi
}

# ============================================================================
# Main
# ============================================================================
main() {
    echo ""
    echo "OctoLab Development Environment Health Check"
    echo "============================================"

    check_wsl
    check_python
    check_docker
    check_env_files
    check_database
    check_alembic
    check_guacamole

    echo ""
    echo "============================================"
    if [[ $FAILED -eq 0 ]]; then
        echo -e "${GREEN}All checks passed!${NC}"
        exit 0
    else
        echo -e "${RED}Some checks failed. Fix the issues above and re-run.${NC}"
        exit 1
    fi
}

main "$@"
