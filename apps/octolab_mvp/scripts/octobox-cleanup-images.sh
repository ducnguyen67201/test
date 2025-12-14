#!/usr/bin/env bash
# Remove OctoBox-related images from k3s containerd
# Only removes images that are NOT in-use by running containers
# Usage: ./scripts/octobox-cleanup-images.sh [--namespace <ns>]

set -euo pipefail

NAMESPACE="${NAMESPACE:-octolab-labs}"

# Parse flags
while [[ $# -gt 0 ]]; do
    case $1 in
        --namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Usage: $0 [--namespace <ns>]" >&2
            exit 1
            ;;
    esac
done

echo "[octobox-cleanup-images] Checking for OctoBox-related images in k3s containerd..."
echo ""

# Precondition: Verify no pods exist
POD_LIST=$(kubectl -n "$NAMESPACE" get pods -l app=octobox-beta --no-headers 2>/dev/null || echo "")
POD_COUNT=$(echo "$POD_LIST" | grep -v "^$" | wc -l | tr -d '[:space:]' || echo "0")
POD_COUNT=$((POD_COUNT + 0))  # Convert to integer
if [[ "$POD_COUNT" -gt 0 ]]; then
    echo "[octobox-cleanup-images] ✗ ERROR: Found $POD_COUNT pod(s) with label app=octobox-beta" >&2
    echo "[octobox-cleanup-images]   Please run ./scripts/octobox-reset.sh first to stop workloads" >&2
    exit 1
fi

echo "[octobox-cleanup-images] ✓ No running pods found - safe to remove images"
echo ""

# List all images in k3s containerd
ALL_IMAGES=$(sudo k3s ctr images ls 2>/dev/null | awk '{print $1}' | grep -v "^REF" || true)

# Define image patterns to match (OctoBox-related only)
PATTERNS=(
    "octobox-beta"
    "docker.io/library/octobox-beta"
    "bonigarcia/novnc"
    "docker.io/bonigarcia/novnc"
    "theasp/novnc"
    "docker.io/theasp/novnc"
)

# Find candidate images
CANDIDATES=()
for pattern in "${PATTERNS[@]}"; do
    while IFS= read -r image; do
        if [[ -n "$image" ]] && echo "$image" | grep -qE "$pattern"; then
            CANDIDATES+=("$image")
        fi
    done <<< "$ALL_IMAGES"
done

# Remove duplicates
IFS=$'\n' CANDIDATES=($(printf '%s\n' "${CANDIDATES[@]}" | sort -u))
unset IFS

if [[ ${#CANDIDATES[@]} -eq 0 ]]; then
    echo "[octobox-cleanup-images] ℹ No OctoBox-related images found in k3s containerd"
    exit 0
fi

echo "[octobox-cleanup-images] Found ${#CANDIDATES[@]} OctoBox-related image(s) to remove:"
for img in "${CANDIDATES[@]}"; do
    echo "  - $img"
done
echo ""

# Remove images one by one
REMOVED=0
SKIPPED=0

for img in "${CANDIDATES[@]}"; do
    echo "[octobox-cleanup-images] Removing: $img"
    if sudo k3s ctr images rm "$img" 2>&1; then
        echo "[octobox-cleanup-images]   ✓ Removed"
        REMOVED=$((REMOVED + 1))
    else
        # Check if error is "not found" (ok) or something else
        if sudo k3s ctr images rm "$img" 2>&1 | grep -q "not found"; then
            echo "[octobox-cleanup-images]   ℹ Not found (may already be removed)"
        else
            echo "[octobox-cleanup-images]   ⚠ Warning: Failed to remove (may be in-use)"
            SKIPPED=$((SKIPPED + 1))
        fi
    fi
done

echo ""
echo "[octobox-cleanup-images] Summary:"
echo "  - Removed: $REMOVED"
echo "  - Skipped/Failed: $SKIPPED"

# Verify what remains
echo ""
echo "[octobox-cleanup-images] Verifying remaining OctoBox images..."
REMAINING=$(sudo k3s ctr images ls 2>/dev/null | awk '{print $1}' | grep -E "(octobox-beta|novnc)" || true)

if [[ -z "$REMAINING" ]]; then
    echo "[octobox-cleanup-images] ✓ No OctoBox-related images remain"
else
    echo "[octobox-cleanup-images] ⚠ Remaining images:"
    echo "$REMAINING" | sed 's/^/  - /'
fi

echo ""
echo "[octobox-cleanup-images] Done!"

