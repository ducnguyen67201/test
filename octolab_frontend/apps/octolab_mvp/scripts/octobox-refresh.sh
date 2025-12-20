#!/usr/bin/env bash
# Complete refresh workflow for OctoBox Beta
# Resets resources, cleans images, rebuilds, and redeploys
# Usage: ./scripts/octobox-refresh.sh [--namespace <ns>] [--delete-evidence] [--yes]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Change to repo root for relative paths
cd "$REPO_ROOT"

echo "[octobox-refresh] Starting complete refresh workflow..."
echo "[octobox-refresh] Working directory: $REPO_ROOT"
echo ""

# Parse flags and pass them through
FLAGS=()
DELETE_EVIDENCE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --namespace)
            FLAGS+=("--namespace" "$2")
            shift 2
            ;;
        --delete-evidence)
            DELETE_EVIDENCE=true
            FLAGS+=("--delete-evidence")
            shift
            ;;
        --yes)
            FLAGS+=("--yes")
            shift
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Usage: $0 [--namespace <ns>] [--delete-evidence] [--yes]" >&2
            exit 1
            ;;
    esac
done

# Step 1: Reset resources
echo "=========================================="
echo "[octobox-refresh] Step 1/4: Resetting Kubernetes resources"
echo "=========================================="
if "$SCRIPT_DIR/octobox-reset.sh" "${FLAGS[@]}"; then
    echo "[octobox-refresh] ✓ Reset complete"
else
    echo "[octobox-refresh] ✗ Reset failed" >&2
    exit 1
fi

echo ""

# Step 2: Cleanup images
echo "=========================================="
echo "[octobox-refresh] Step 2/4: Cleaning up old images"
echo "=========================================="
NAMESPACE_FLAG=""
if [[ " ${FLAGS[*]} " =~ " --namespace " ]]; then
    # Extract namespace from flags
    for i in "${!FLAGS[@]}"; do
        if [[ "${FLAGS[$i]}" == "--namespace" ]]; then
            NAMESPACE_FLAG="--namespace ${FLAGS[$((i+1))]}"
            break
        fi
    done
fi

if eval "$SCRIPT_DIR/octobox-cleanup-images.sh $NAMESPACE_FLAG"; then
    echo "[octobox-refresh] ✓ Image cleanup complete"
else
    echo "[octobox-refresh] ✗ Image cleanup failed" >&2
    exit 1
fi

echo ""

# Step 3: Build and import
echo "=========================================="
echo "[octobox-refresh] Step 3/4: Building and importing images"
echo "=========================================="
if "$SCRIPT_DIR/octobox-build-import.sh"; then
    echo "[octobox-refresh] ✓ Build and import complete"
else
    echo "[octobox-refresh] ✗ Build/import failed" >&2
    exit 1
fi

echo ""

# Step 4: Deploy
echo "=========================================="
echo "[octobox-refresh] Step 4/4: Deploying OctoBox Beta"
echo "=========================================="
if eval "$SCRIPT_DIR/octobox-deploy.sh $NAMESPACE_FLAG"; then
    echo "[octobox-refresh] ✓ Deployment complete"
else
    echo "[octobox-refresh] ✗ Deployment failed" >&2
    exit 1
fi

echo ""
echo "=========================================="
echo "[octobox-refresh] ✓ Complete refresh workflow finished successfully!"
echo "=========================================="

