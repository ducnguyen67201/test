#!/usr/bin/env bash
# Build and import OctoBox images into k3s containerd
# Ensures deterministic freshness by removing old image before re-import
# Usage: ./scripts/octobox-build-import.sh

set -euo pipefail

echo "[octobox-build-import] Building and importing OctoBox images..."
echo ""

# Pre-check: Verify k3s containerd is ready
echo "[octobox-build-import] Pre-check: Verifying k3s containerd is ready..."
CONTAINERD_READY=false
TIMEOUT=60
ELAPSED=0

while [[ $ELAPSED -lt $TIMEOUT ]]; do
    if sudo k3s ctr images ls &>/dev/null; then
        CONTAINERD_READY=true
        echo "[octobox-build-import]   ✓ containerd is ready"
        break
    else
        echo "[octobox-build-import]   ⏳ Waiting for containerd... (${ELAPSED}s/${TIMEOUT}s)"
        sleep 2
        ELAPSED=$((ELAPSED + 2))
    fi
done

if [[ "$CONTAINERD_READY" != "true" ]]; then
    echo "[octobox-build-import]   ✗ Timeout waiting for containerd to be ready" >&2
    echo "[octobox-build-import]   Check k3s status: sudo systemctl status k3s" >&2
    exit 1
fi

echo ""

# Step 1: Build attacker image
echo "[octobox-build-import] Step 1: Building attacker image (octobox-beta:dev)..."
MAX_BUILD_RETRIES=3
BUILD_RETRY=0
BUILD_SUCCESS=false

while [[ $BUILD_RETRY -lt $MAX_BUILD_RETRIES ]]; do
    if docker build -t octobox-beta:dev images/octobox-beta/ 2>&1; then
        echo "[octobox-build-import]   ✓ Image built successfully"
        BUILD_SUCCESS=true
        break
    else
        BUILD_RETRY=$((BUILD_RETRY + 1))
        if [[ $BUILD_RETRY -lt $MAX_BUILD_RETRIES ]]; then
            echo "[octobox-build-import]   ⚠ Build failed (network/timeout?), retrying ($BUILD_RETRY/$MAX_BUILD_RETRIES)..."
            sleep 5
        fi
    fi
done

if [[ "$BUILD_SUCCESS" != "true" ]]; then
    echo "[octobox-build-import]   ✗ Build failed after $MAX_BUILD_RETRIES attempts" >&2
    echo "[octobox-build-import]   This may be a network issue. Check your internet connection and Docker registry access." >&2
    exit 1
fi

# Step 2: Remove old attacker image from k3s (for freshness)
echo ""
echo "[octobox-build-import] Step 2: Removing old attacker image from k3s (ensures freshness)..."
OLD_IMAGES=$(sudo k3s ctr images ls 2>/dev/null | awk '{print $1}' | grep -E "octobox-beta:dev|docker.io/library/octobox-beta:dev" || true)
if [[ -n "$OLD_IMAGES" ]]; then
    while IFS= read -r img; do
        if [[ -n "$img" ]]; then
            echo "[octobox-build-import]   Removing old: $img"
            sudo k3s ctr images rm "$img" 2>/dev/null || true
        fi
    done <<< "$OLD_IMAGES"
    echo "[octobox-build-import]   ✓ Old image removed"
else
    echo "[octobox-build-import]   ℹ No old image found (first import)"
fi

# Step 3: Import attacker image into k3s
echo ""
echo "[octobox-build-import] Step 3: Importing attacker image into k3s..."
TEMP_TAR=$(mktemp /tmp/octobox-beta-import-XXXXXX.tar)
trap "rm -f '$TEMP_TAR'" EXIT

echo "[octobox-build-import]   Saving image to temporary file..."
if ! docker save octobox-beta:dev -o "$TEMP_TAR"; then
    echo "[octobox-build-import]   ✗ Failed to save image" >&2
    exit 1
fi

MAX_RETRIES=3
RETRY=0
IMPORT_SUCCESS=false

while [[ $RETRY -lt $MAX_RETRIES ]]; do
    # Wait for containerd to be ready before each attempt
    sleep 1
    if ! sudo k3s ctr images ls &>/dev/null; then
        echo "[octobox-build-import]   ⚠ containerd not ready, waiting..."
        sleep 3
        continue
    fi
    
    if sudo k3s ctr images import "$TEMP_TAR" 2>&1; then
        echo "[octobox-build-import]   ✓ Attacker image imported"
        IMPORT_SUCCESS=true
        break
    else
        RETRY=$((RETRY + 1))
        if [[ $RETRY -lt $MAX_RETRIES ]]; then
            echo "[octobox-build-import]   ⚠ Import failed, retrying ($RETRY/$MAX_RETRIES)..."
            sleep 3
        fi
    fi
done

rm -f "$TEMP_TAR"
trap - EXIT

if [[ "$IMPORT_SUCCESS" != "true" ]]; then
    echo "[octobox-build-import]   ✗ Import failed after $MAX_RETRIES attempts" >&2
    echo "[octobox-build-import]   This may be a transient containerd issue. Try running the script again." >&2
    exit 1
fi

# Step 4: Ensure sidecar image is present
echo ""
echo "[octobox-build-import] Step 4: Ensuring sidecar image (bonigarcia/novnc:1.3.0) is present..."

# Check if already in k3s
if sudo k3s ctr images ls 2>/dev/null | grep -qE "bonigarcia/novnc:1.3.0|docker.io/bonigarcia/novnc:1.3.0"; then
    echo "[octobox-build-import]   ℹ Sidecar image already in k3s"
else
    echo "[octobox-build-import]   Pulling sidecar image with Docker..."
    MAX_PULL_RETRIES=3
    PULL_RETRY=0
    PULL_SUCCESS=false
    
    while [[ $PULL_RETRY -lt $MAX_PULL_RETRIES ]]; do
        if docker pull bonigarcia/novnc:1.3.0 2>&1; then
            echo "[octobox-build-import]   ✓ Sidecar image pulled"
            PULL_SUCCESS=true
            break
        else
            PULL_RETRY=$((PULL_RETRY + 1))
            if [[ $PULL_RETRY -lt $MAX_PULL_RETRIES ]]; then
                echo "[octobox-build-import]   ⚠ Pull failed (network/timeout?), retrying ($PULL_RETRY/$MAX_PULL_RETRIES)..."
                sleep 5
            fi
        fi
    done
    
    if [[ "$PULL_SUCCESS" != "true" ]]; then
        echo "[octobox-build-import]   ✗ Failed to pull sidecar image after $MAX_PULL_RETRIES attempts" >&2
        echo "[octobox-build-import]   This may be a network issue. Check your internet connection and Docker registry access." >&2
        exit 1
    fi

    echo "[octobox-build-import]   Importing sidecar image into k3s..."
    SIDECAR_TAR=$(mktemp /tmp/novnc-import-XXXXXX.tar)
    trap "rm -f '$SIDECAR_TAR'" EXIT
    
    echo "[octobox-build-import]   Saving sidecar image to temporary file..."
    if ! docker save bonigarcia/novnc:1.3.0 -o "$SIDECAR_TAR"; then
        echo "[octobox-build-import]   ✗ Failed to save sidecar image" >&2
        exit 1
    fi
    
    MAX_RETRIES=3
    RETRY=0
    SIDECAR_SUCCESS=false
    
    while [[ $RETRY -lt $MAX_RETRIES ]]; do
        # Wait for containerd to be ready before each attempt
        sleep 1
        if ! sudo k3s ctr images ls &>/dev/null; then
            echo "[octobox-build-import]   ⚠ containerd not ready, waiting..."
            sleep 3
            continue
        fi
        
        if sudo k3s ctr images import "$SIDECAR_TAR" 2>&1; then
            echo "[octobox-build-import]   ✓ Sidecar image imported"
            SIDECAR_SUCCESS=true
            break
        else
            RETRY=$((RETRY + 1))
            if [[ $RETRY -lt $MAX_RETRIES ]]; then
                echo "[octobox-build-import]   ⚠ Import failed, retrying ($RETRY/$MAX_RETRIES)..."
                sleep 3
            fi
        fi
    done
    
    rm -f "$SIDECAR_TAR"
    trap - EXIT
    
    if [[ "$SIDECAR_SUCCESS" != "true" ]]; then
        echo "[octobox-build-import]   ✗ Import failed after $MAX_RETRIES attempts" >&2
        echo "[octobox-build-import]   This may be a transient containerd issue. Try running the script again." >&2
        exit 1
    fi
fi

# Step 5: Verify both images are present
echo ""
echo "[octobox-build-import] Step 5: Verifying images in k3s..."

# Wait for containerd to be ready before verification
echo "[octobox-build-import]   Waiting for containerd to be ready..."
TIMEOUT=30
ELAPSED=0
while [[ $ELAPSED -lt $TIMEOUT ]]; do
    if sudo k3s ctr images ls &>/dev/null; then
        break
    fi
    sleep 1
    ELAPSED=$((ELAPSED + 1))
done

if [[ $ELAPSED -ge $TIMEOUT ]]; then
    echo "[octobox-build-import]   ⚠ Warning: containerd not ready, verification may fail" >&2
fi

# Get image list once
IMAGE_LIST=$(sudo k3s ctr images ls 2>/dev/null || echo "")

ATTACKER_FOUND=false
SIDECAR_FOUND=false

# Check attacker image (match both short and full names)
if echo "$IMAGE_LIST" | grep -qE "(^| )docker\.io/library/octobox-beta:dev|(^| )octobox-beta:dev"; then
    ATTACKER_FOUND=true
    ATTACKER_INFO=$(echo "$IMAGE_LIST" | grep -E "(^| )docker\.io/library/octobox-beta:dev|(^| )octobox-beta:dev" | head -1 | awk '{print $1}')
    echo "[octobox-build-import]   ✓ Attacker image found: $ATTACKER_INFO"
else
    echo "[octobox-build-import]   ✗ Attacker image not found!" >&2
    echo "[octobox-build-import]   Available images:" >&2
    echo "$IMAGE_LIST" | grep -i octobox | head -5 | sed 's/^/      /' >&2 || true
fi

# Check sidecar image (match both short and full names)
if echo "$IMAGE_LIST" | grep -qE "(^| )docker\.io/bonigarcia/novnc:1\.3\.0|(^| )bonigarcia/novnc:1\.3\.0"; then
    SIDECAR_FOUND=true
    SIDECAR_INFO=$(echo "$IMAGE_LIST" | grep -E "(^| )docker\.io/bonigarcia/novnc:1\.3\.0|(^| )bonigarcia/novnc:1\.3\.0" | head -1 | awk '{print $1}')
    echo "[octobox-build-import]   ✓ Sidecar image found: $SIDECAR_INFO"
else
    echo "[octobox-build-import]   ✗ Sidecar image not found!" >&2
    echo "[octobox-build-import]   Available images:" >&2
    echo "$IMAGE_LIST" | grep -i novnc | head -5 | sed 's/^/      /' >&2 || true
fi

echo ""
if [[ "$ATTACKER_FOUND" == "true" && "$SIDECAR_FOUND" == "true" ]]; then
    echo "[octobox-build-import] ✓ All images ready for deployment!"
    exit 0
else
    echo "[octobox-build-import] ✗ Verification failed - some images missing" >&2
    exit 1
fi

