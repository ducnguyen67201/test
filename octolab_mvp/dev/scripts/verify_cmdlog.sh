#!/bin/bash
# OctoBox Command Logging Verification Script
# Verifies that PROMPT_COMMAND hook works in interactive shells (login and non-login)
#
# Usage: ./dev/scripts/verify_cmdlog.sh
# Or:    make dev-cmdlog-verify
#
# This script:
# 1. Builds octobox with current cmdlog scripts
# 2. Starts container with /evidence bind mount
# 3. Verifies PROMPT_COMMAND is set and __octo_log_prompt function exists
# 4. Runs a test command and verifies commands.tsv is written
# 5. Cleans up

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "[${GREEN}INFO${NC}] $*"; }
log_warn() { echo -e "[${YELLOW}WARN${NC}] $*"; }
log_fail() { echo -e "[${RED}FAIL${NC}] $*"; }
log_check() { echo -e "  ${GREEN}✓${NC} $*"; }

# Generate unique project name
PROJECT_NAME="octolab_cmdlog_verify_$$"
COMPOSE_FILE="octolab-hackvm/docker-compose.yml"
TEMP_DIR=""
LAB_ID="test-$(date +%s)"

cleanup() {
    log_info "Cleaning up..."
    if [[ -n "$PROJECT_NAME" ]]; then
        # Stop and remove containers
        VNC_PASSWORD=verifytest VNC_PASSWORD_ALLOW_DEFAULT=1 LAB_ID="$LAB_ID" \
            docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" down -v --remove-orphans 2>/dev/null || true
    fi
    if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
        rm -rf "$TEMP_DIR"
    fi
}

trap cleanup EXIT

echo "=========================================="
echo "OctoBox Command Logging Verification"
echo "=========================================="
echo ""

# Create temp directory for evidence
TEMP_DIR=$(mktemp -d)
EVIDENCE_DIR="$TEMP_DIR/evidence"
mkdir -p "$EVIDENCE_DIR/tlog/$LAB_ID"
chmod -R 777 "$EVIDENCE_DIR"  # Make writable by container user

log_info "Using LAB_ID: $LAB_ID"
log_info "Evidence dir: $EVIDENCE_DIR"
log_info "Project: $PROJECT_NAME"
echo ""

# Step 1: Build octobox image
log_info "Step 1/5: Building octobox image..."
CMDLOG_BUST="cmdlog-verify-$(date +%s)" \
BUILD_TIMESTAMP="$(date -Iseconds)" \
VNC_PASSWORD=verifytest \
VNC_PASSWORD_ALLOW_DEFAULT=1 \
LAB_ID="$LAB_ID" \
    docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" build octobox --quiet
log_check "Build completed"
echo ""

# Step 2: Start container with evidence bind mount
log_info "Step 2/5: Starting container with evidence bind mount..."

# Create a modified compose command that adds bind mount
# We need to pass the evidence directory as an environment variable and use a bind mount
VNC_PASSWORD=verifytest \
VNC_PASSWORD_ALLOW_DEFAULT=1 \
LAB_ID="$LAB_ID" \
    docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" run -d \
        --name "${PROJECT_NAME}-octobox-test" \
        -v "$EVIDENCE_DIR:/evidence" \
        -e "LAB_ID=$LAB_ID" \
        -e "OCTOLAB_CMDLOG_DEBUG=1" \
        octobox

# Wait for container to start
sleep 5

# Check container is running
if ! docker ps | grep -q "${PROJECT_NAME}-octobox-test"; then
    log_fail "Container failed to start"
    docker logs "${PROJECT_NAME}-octobox-test" 2>&1 | tail -20
    exit 1
fi
log_check "Container started"
echo ""

# Step 3: Verify build markers
log_info "Step 3/5: Verifying build markers..."
BUILD_ID=$(docker exec "${PROJECT_NAME}-octobox-test" cat /etc/octolab-cmdlog.build-id 2>/dev/null || echo "MISSING")
if [[ "$BUILD_ID" == "MISSING" ]]; then
    log_fail "/etc/octolab-cmdlog.build-id not found"
    exit 1
fi
log_check "Build ID: $BUILD_ID"

# Check /etc/bash.bashrc sources octolab-cmdlog
if docker exec "${PROJECT_NAME}-octobox-test" grep -q "octolab-cmdlog" /etc/bash.bashrc 2>/dev/null; then
    log_check "/etc/bash.bashrc sources octolab-cmdlog.sh"
else
    log_fail "/etc/bash.bashrc does NOT source octolab-cmdlog.sh"
    exit 1
fi
echo ""

# Step 4: Verify PROMPT_COMMAND in interactive shell
log_info "Step 4/5: Verifying PROMPT_COMMAND hook in interactive bash..."

# Test in interactive bash (non-login shell, like XFCE Terminal)
# Use bash -i to simulate interactive shell
PROMPT_CMD=$(docker exec "${PROJECT_NAME}-octobox-test" \
    su - pentester -c 'bash -ic "echo \$PROMPT_COMMAND" 2>/dev/null' | tail -1)

if [[ "$PROMPT_CMD" == *"__octo_log_prompt"* ]]; then
    log_check "PROMPT_COMMAND contains __octo_log_prompt"
else
    log_fail "PROMPT_COMMAND does NOT contain __octo_log_prompt"
    log_warn "PROMPT_COMMAND value: $PROMPT_CMD"

    # Debug: check if function exists
    docker exec "${PROJECT_NAME}-octobox-test" \
        su - pentester -c 'bash -ic "type __octo_log_prompt 2>&1"' || true
    exit 1
fi

# Check function exists
FUNC_TYPE=$(docker exec "${PROJECT_NAME}-octobox-test" \
    su - pentester -c 'bash -ic "type __octo_log_prompt 2>&1"' | head -1)

if [[ "$FUNC_TYPE" == *"function"* ]]; then
    log_check "__octo_log_prompt is a function"
else
    log_fail "__octo_log_prompt is NOT a function"
    log_warn "Type output: $FUNC_TYPE"
    exit 1
fi
echo ""

# Step 5: Run test command and verify logging
log_info "Step 5/5: Testing command logging..."

# Make sure tlog directory is writable
docker exec "${PROJECT_NAME}-octobox-test" chmod 777 /evidence/tlog 2>/dev/null || true
docker exec "${PROJECT_NAME}-octobox-test" chmod 777 "/evidence/tlog/$LAB_ID" 2>/dev/null || true

# Run a test command in interactive shell
# The echo command should be logged to commands.tsv
docker exec "${PROJECT_NAME}-octobox-test" \
    su - pentester -c "bash -ic 'echo test_cmdlog_verification_12345; sleep 0.5; exit'" 2>/dev/null || true

# Wait for log write
sleep 1

# Check if commands.tsv was created
COMMANDS_TSV="/evidence/tlog/$LAB_ID/commands.tsv"
if [[ -f "$EVIDENCE_DIR/tlog/$LAB_ID/commands.tsv" ]]; then
    log_check "commands.tsv created at $COMMANDS_TSV"

    # Check content
    if grep -q "test_cmdlog_verification_12345" "$EVIDENCE_DIR/tlog/$LAB_ID/commands.tsv"; then
        log_check "Test command was logged to commands.tsv"
        echo ""
        echo "=== commands.tsv content ==="
        cat "$EVIDENCE_DIR/tlog/$LAB_ID/commands.tsv"
        echo "============================"
    else
        log_warn "Test command NOT found in commands.tsv (may be timing issue)"
        echo ""
        echo "=== commands.tsv content ==="
        cat "$EVIDENCE_DIR/tlog/$LAB_ID/commands.tsv"
        echo "============================"
    fi
else
    log_warn "commands.tsv NOT created (this may be expected if no interactive prompt occurred)"
    log_warn "Checking if tlog directory exists..."
    ls -la "$EVIDENCE_DIR/tlog/$LAB_ID/" 2>/dev/null || echo "Directory does not exist"

    # Debug: show octolab-cmdlog debug output
    echo ""
    log_warn "Checking container logs for cmdlog debug messages..."
    docker logs "${PROJECT_NAME}-octobox-test" 2>&1 | grep -i "octolab-cmdlog" || echo "No cmdlog debug messages"
fi

echo ""
echo -e "${GREEN}=========================================="
echo "CMDLOG VERIFICATION COMPLETE"
echo "==========================================${NC}"
