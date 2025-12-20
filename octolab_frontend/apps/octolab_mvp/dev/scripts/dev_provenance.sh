#!/usr/bin/env bash
# dev_provenance.sh - Verify OctoBox image provenance and cmdlog wiring
#
# This script:
# 1. Builds octobox with a fresh CMDLOG_BUST
# 2. Runs a one-off container (no deps, no entrypoint) to verify files
# 3. Cleans up
#
# Usage:
#   ./dev/scripts/dev_provenance.sh
#   make dev-provenance
#
# Exit codes:
#   0 - All checks passed
#   1 - Verification failed
#   2 - Docker/prerequisites not available

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/octolab-hackvm/docker-compose.yml"
PROJECT_NAME="octolab_provenance_$$"
CMDLOG_BUST="prov-$(date +%s)"
BUILD_TIMESTAMP="$(date -Iseconds)"

# ANSI colors (safe for terminals)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_check() { echo -e "  ${GREEN}✓${NC} $*"; }
log_fail() { echo -e "  ${RED}✗${NC} $*"; }

cleanup() {
    local exit_code=$?
    echo ""
    log_info "Cleaning up project $PROJECT_NAME..."

    # Remove the specific run container if it exists (compose run --rm handles it usually, but for safety)
    # Pass VNC_PASSWORD to satisfy compose file requirement
    VNC_PASSWORD_ALLOW_DEFAULT=1 VNC_PASSWORD=cleanup \
        docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" down --volumes --remove-orphans 2>/dev/null || true

    if [[ $exit_code -eq 0 ]]; then
        log_info "Cleanup complete. All checks passed!"
    else
        log_warn "Cleanup complete. Script exited with code $exit_code."
    fi
}

trap cleanup EXIT

# Check prerequisites
if ! command -v docker &>/dev/null; then
    log_error "docker command not found"
    exit 2
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
    log_error "Compose file not found: $COMPOSE_FILE"
    exit 2
fi

echo "=========================================="
echo "OctoBox Image Provenance Verification"
echo "=========================================="
echo ""
log_info "CMDLOG_BUST: $CMDLOG_BUST"
log_info "BUILD_TIMESTAMP: $BUILD_TIMESTAMP"
log_info "PROJECT: $PROJECT_NAME"
echo ""

# Step 1: Build with cache bust
log_info "Step 1/3: Building octobox with CMDLOG_BUST=$CMDLOG_BUST..."
export CMDLOG_BUST BUILD_TIMESTAMP
# Dev convenience: allow default VNC password for provenance testing
# SECURITY: This is for testing only; backend-provisioned labs use server-generated passwords
export VNC_PASSWORD_ALLOW_DEFAULT=1
export VNC_PASSWORD=provenance_test
# We only build octobox. We don't need other services.
docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" build --quiet octobox
log_check "Build completed"
echo ""

# Step 2: Verify using run --rm --no-deps --entrypoint bash
log_info "Step 2/3: Verifying build markers and scripts inside container..."

# We construct a bash script to run inside the container
# This avoids complex escaping issues with 'bash -c'
VERIFY_SCRIPT=$(cat <<INNER
set -e

echo "--- CHECK: Build Markers ---"
if [ -f /etc/octolab-cmdlog.build-id ]; then
    CONTENT=\$(cat /etc/octolab-cmdlog.build-id)
    if [ "\$CONTENT" = "cmdlog-bust=$CMDLOG_BUST" ]; then
        echo "PASS: /etc/octolab-cmdlog.build-id matches bust"
    else
        echo "FAIL: /etc/octolab-cmdlog.build-id mismatch. Got: \$CONTENT"
        exit 1
    fi
else
    echo "FAIL: /etc/octolab-cmdlog.build-id missing"
    exit 1
fi

if [ -f /etc/octolab-image.build-id ]; then
    if grep -q "cmdlog-bust=$CMDLOG_BUST" /etc/octolab-image.build-id; then
        echo "PASS: /etc/octolab-image.build-id contains bust"
    else
        echo "FAIL: /etc/octolab-image.build-id missing bust"
        exit 1
    fi
else
    echo "FAIL: /etc/octolab-image.build-id missing"
    exit 1
fi

echo "--- CHECK: Cmdlog Scripts ---"
if [ -f /etc/profile.d/octolab-cmdlog.sh ]; then
    echo "PASS: /etc/profile.d/octolab-cmdlog.sh exists"
else
    echo "FAIL: /etc/profile.d/octolab-cmdlog.sh missing"
    exit 1
fi

if [ -f /etc/octolab-cmdlog.sh ]; then
    echo "PASS: /etc/octolab-cmdlog.sh exists"
else
    echo "FAIL: /etc/octolab-cmdlog.sh missing"
    exit 1
fi

if [ -f /etc/profile.d/octolog.sh ]; then
    echo "FAIL: Legacy /etc/profile.d/octolog.sh exists (should be gone)"
    exit 1
else
    echo "PASS: Legacy /etc/profile.d/octolog.sh absent"
fi

echo "--- CHECK: Bashrc Sourcing ---"
if grep -q "octolab-cmdlog" /etc/bash.bashrc; then
    echo "PASS: /etc/bash.bashrc sources octolab-cmdlog"
else
    echo "FAIL: /etc/bash.bashrc does NOT source octolab-cmdlog"
    exit 1
fi

echo "--- CHECK: Interactive Shell Hook ---"
# We spawn a sub-shell to test interactive behavior
# We redirect stderr to stdout to capture errors
OUTPUT=\$(bash -ic 'type __octo_log_prompt' 2>&1 || true)
if echo "\$OUTPUT" | grep -q "function"; then
    echo "PASS: __octo_log_prompt is a function in interactive shell"
else
    echo "FAIL: __octo_log_prompt not found in interactive shell. Output: \$OUTPUT"
    exit 1
fi

echo "ALL CHECKS PASSED"
INNER
)

# Run the verification
# Use -T to disable TTY allocation to avoid issues in some environments, 
# but we need to ensure bash -ic works. 
if docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" run --rm -T --no-deps --entrypoint bash octobox -c "$VERIFY_SCRIPT"; then
    log_check "Verification script completed successfully"
else
    log_fail "Verification script failed"
    exit 1
fi

echo ""

# Step 3: Verify VNC reachability from sibling container
log_info "Step 3/3: Verifying VNC port 5900 reachability from sibling container..."

# Start octobox in detached mode (needs VNC_PASSWORD)
docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" up -d octobox

# Wait for container to become healthy (up to 60 seconds)
log_info "Waiting for octobox container to become healthy..."
MAX_WAIT=60
WAITED=0
while [[ $WAITED -lt $MAX_WAIT ]]; do
    HEALTH=$(docker inspect --format='{{.State.Health.Status}}' "${PROJECT_NAME}-octobox-1" 2>/dev/null || echo "not_found")
    if [[ "$HEALTH" == "healthy" ]]; then
        log_check "Container is healthy after ${WAITED}s"
        break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
done

if [[ "$HEALTH" != "healthy" ]]; then
    log_fail "Container did not become healthy within ${MAX_WAIT}s (status: $HEALTH)"
    docker logs "${PROJECT_NAME}-octobox-1" 2>&1 | tail -30
    exit 1
fi

# Get the lab network name
LAB_NETWORK="${PROJECT_NAME}_lab_net"

# Run sibling container to test VNC reachability on port 5900
log_info "Testing VNC port 5900 from sibling container on $LAB_NETWORK..."

# Use busybox with nc to test port 5900 on octobox
# The container name resolves via Docker DNS on the same network
if docker run --rm --network "$LAB_NETWORK" busybox nc -vz "${PROJECT_NAME}-octobox-1" 5900 2>&1; then
    log_check "VNC port 5900 is reachable from sibling container"
else
    log_fail "VNC port 5900 NOT reachable from sibling container"
    log_error "guacd would fail to connect to this lab"
    # Show VNC-related logs
    log_warn "Last 20 lines of octobox logs:"
    docker logs "${PROJECT_NAME}-octobox-1" 2>&1 | tail -20
    exit 1
fi

echo ""
echo -e "${GREEN}PROVENANCE AND VNC REACHABILITY VERIFIED${NC}"
exit 0
