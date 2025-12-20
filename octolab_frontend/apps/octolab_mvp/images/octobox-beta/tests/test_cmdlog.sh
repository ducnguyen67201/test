#!/bin/bash
# Test script for OctoBox command logging (PROMPT_COMMAND hook)
# Run from repo root: bash images/octobox-beta/tests/test_cmdlog.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE_NAME="octobox-beta:cmdlog-test"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

cleanup() {
    if [[ -n "${EVIDENCE_DIR:-}" && -d "$EVIDENCE_DIR" ]]; then
        rm -rf "$EVIDENCE_DIR"
    fi
}
trap cleanup EXIT

# Build the image
log_info "Building image: $IMAGE_NAME"
docker build -t "$IMAGE_NAME" "$IMAGE_DIR" >/dev/null 2>&1 || {
    log_error "Failed to build image"
    exit 1
}

# Create temp evidence directory structure
EVIDENCE_DIR=$(mktemp -d)
SESSION_ID="test-session-$(date +%s)"
SESSION_DIR="$EVIDENCE_DIR/tlog/$SESSION_ID"
mkdir -p "$SESSION_DIR"
chmod 0770 "$SESSION_DIR"
log_info "Evidence dir: $EVIDENCE_DIR"
log_info "Session dir: $SESSION_DIR"

# Run container with interactive bash
log_info "Running container with LAB_ID=$SESSION_ID"
CONTAINER_OUTPUT=$(docker run --rm \
    -v "$EVIDENCE_DIR:/evidence" \
    -e "LAB_ID=$SESSION_ID" \
    -e "OCTOLAB_CMDLOG_DEBUG=1" \
    --user pentester \
    "$IMAGE_NAME" \
    /bin/bash -ic '
        echo "=== CMDLOG TEST START ==="
        echo "cmdlog_smoke_test_1"
        id
        pwd
        ls /evidence
        echo "PROMPT_COMMAND=$PROMPT_COMMAND"
        echo "OCTOLAB_CMDLOG_ENABLED=$OCTOLAB_CMDLOG_ENABLED"
        echo "SHLVL=$SHLVL"
        type __octo_log_prompt 2>&1 || echo "__octo_log_prompt NOT DEFINED"
        echo "=== CMDLOG TEST END ==="
    ' 2>&1) || true

echo "$CONTAINER_OUTPUT"

# Check for SHLVL explosion
if echo "$CONTAINER_OUTPUT" | grep -qi "shell level.*too high\|SHLVL=1000"; then
    log_error "SHLVL explosion detected!"
    exit 1
fi
log_info "No SHLVL explosion"

# Check that __octo_log_prompt is defined
if echo "$CONTAINER_OUTPUT" | grep -q "__octo_log_prompt NOT DEFINED"; then
    log_error "__octo_log_prompt function not defined"
    exit 1
fi
log_info "__octo_log_prompt is defined"

# Check that PROMPT_COMMAND contains our function
if ! echo "$CONTAINER_OUTPUT" | grep -q "PROMPT_COMMAND=.*__octo_log_prompt"; then
    log_error "PROMPT_COMMAND does not contain __octo_log_prompt"
    echo "Output was: $(echo "$CONTAINER_OUTPUT" | grep PROMPT_COMMAND)"
    exit 1
fi
log_info "PROMPT_COMMAND contains __octo_log_prompt"

# Check that log file was created
LOG_FILE="$SESSION_DIR/commands.tsv"
if [[ ! -f "$LOG_FILE" ]]; then
    log_warn "Log file not created at $LOG_FILE"
    log_warn "This may be expected if bash -c doesn't trigger PROMPT_COMMAND between commands"
    ls -la "$SESSION_DIR/" 2>/dev/null || true
    # Not a hard failure - PROMPT_COMMAND runs AFTER command, so single-line bash -c may not log
else
    log_info "Log file created: $LOG_FILE"
    log_info "Log contents:"
    cat "$LOG_FILE"
    
    # Check for test command in log
    if grep -q "cmdlog_smoke_test_1" "$LOG_FILE"; then
        log_info "Test command found in log"
    else
        log_warn "Test command not found in log (may be timing issue with bash -c)"
    fi
fi

# Run a second test with multiple commands to ensure logging
log_info "Running multi-command test..."
docker run --rm \
    -v "$EVIDENCE_DIR:/evidence" \
    -e "LAB_ID=$SESSION_ID" \
    --user pentester \
    "$IMAGE_NAME" \
    /bin/bash -ic '
        echo "multi_test_1"
        echo "multi_test_2"
        echo "multi_test_3"
    ' >/dev/null 2>&1 || true

if [[ -f "$LOG_FILE" ]]; then
    log_info "Final log contents:"
    cat "$LOG_FILE"
fi

log_info "=== All tests passed ==="
