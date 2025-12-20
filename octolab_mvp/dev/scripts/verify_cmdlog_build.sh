#!/usr/bin/env bash
# verify_cmdlog_build.sh - Verify cmdlog cache-busting works correctly
#
# This script:
# 1. Builds octobox-beta with a known CMDLOG_BUST value
# 2. Runs the container and reads /etc/octolab-cmdlog.build-id
# 3. Verifies the build-id matches expected value
# 4. Cleans up (removes test container and image)
#
# Usage:
#   ./dev/scripts/verify_cmdlog_build.sh
#   make verify-cmdlog
#
# Exit codes:
#   0 - Success
#   1 - Verification failed
#   2 - Docker not available

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OCTOBOX_DIR="$REPO_ROOT/images/octobox-beta"
TEST_IMAGE="octobox-cmdlog-verify:test"
TEST_CONTAINER="octobox-cmdlog-verify-$$"
BUST_VALUE="verify-$(date +%s)"

# Cleanup function
cleanup() {
    local exit_code=$?
    echo ""
    echo "==> Cleaning up..."

    # Remove container if exists (ignore errors)
    docker rm -f "$TEST_CONTAINER" 2>/dev/null || true

    # Remove test image (ignore errors)
    docker rmi -f "$TEST_IMAGE" 2>/dev/null || true

    if [[ $exit_code -eq 0 ]]; then
        echo "==> Cleanup complete."
    else
        echo "==> Cleanup complete (script exited with code $exit_code)."
    fi
}

# Register cleanup on exit
trap cleanup EXIT

# Check docker is available
if ! command -v docker &>/dev/null; then
    echo "ERROR: docker command not found"
    exit 2
fi

if ! docker info &>/dev/null; then
    echo "ERROR: Docker daemon not running or not accessible"
    exit 2
fi

# Check octobox-beta directory exists
if [[ ! -d "$OCTOBOX_DIR" ]]; then
    echo "ERROR: octobox-beta directory not found at $OCTOBOX_DIR"
    exit 1
fi

if [[ ! -f "$OCTOBOX_DIR/Dockerfile" ]]; then
    echo "ERROR: Dockerfile not found at $OCTOBOX_DIR/Dockerfile"
    exit 1
fi

echo "==> Verifying cmdlog cache-busting mechanism"
echo ""
echo "    CMDLOG_BUST value: $BUST_VALUE"
echo "    Image tag: $TEST_IMAGE"
echo ""

# Step 1: Build with specific CMDLOG_BUST
echo "==> Step 1/3: Building octobox-beta with CMDLOG_BUST=$BUST_VALUE..."
docker build \
    --build-arg "CMDLOG_BUST=$BUST_VALUE" \
    -t "$TEST_IMAGE" \
    "$OCTOBOX_DIR" \
    --quiet

echo "    Build complete."
echo ""

# Step 2: Run container and read build-id
echo "==> Step 2/3: Reading /etc/octolab-cmdlog.build-id from container..."
BUILD_ID=$(docker run \
    --rm \
    --name "$TEST_CONTAINER" \
    --entrypoint cat \
    "$TEST_IMAGE" \
    /etc/octolab-cmdlog.build-id)

echo "    Build ID: $BUILD_ID"
echo ""

# Step 3: Verify
echo "==> Step 3/3: Verifying build-id matches expected value..."
EXPECTED="cmdlog-bust=$BUST_VALUE"

if [[ "$BUILD_ID" == "$EXPECTED" ]]; then
    echo ""
    echo "✓ SUCCESS: Build ID matches expected value"
    echo ""
    echo "  Expected: $EXPECTED"
    echo "  Got:      $BUILD_ID"
    echo ""
    exit 0
else
    echo ""
    echo "✗ FAILED: Build ID does not match expected value"
    echo ""
    echo "  Expected: $EXPECTED"
    echo "  Got:      $BUILD_ID"
    echo ""
    exit 1
fi
