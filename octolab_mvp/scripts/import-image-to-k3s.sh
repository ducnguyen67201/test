#!/usr/bin/env bash
# Import Docker image into k3s containerd
# Usage: ./import-image-to-k3s.sh <image:tag>
# Example: ./import-image-to-k3s.sh bonigarcia/novnc:1.3.0

set -euo pipefail

if [[ $# -eq 0 ]]; then
    echo "Usage: $0 <image:tag>"
    echo "Example: $0 bonigarcia/novnc:1.3.0"
    echo "Example: $0 octobox-beta:dev"
    exit 1
fi

IMAGE="$1"

echo "Importing image: $IMAGE"
echo ""

# Step 1: Pull image with Docker (if not already present)
echo "[1/3] Pulling image with Docker..."
if docker image inspect "$IMAGE" &>/dev/null; then
    echo "  ✓ Image already exists locally: $IMAGE"
else
    echo "  → Pulling $IMAGE..."
    docker pull "$IMAGE"
    echo "  ✓ Image pulled successfully"
fi

# Step 2: Import into k3s
echo ""
echo "[2/3] Importing into k3s containerd..."
if docker save "$IMAGE" | sudo k3s ctr images import -; then
    echo "  ✓ Image imported successfully"
else
    echo "  ✗ Failed to import image"
    exit 1
fi

# Step 3: Verify
echo ""
echo "[3/3] Verifying import..."
if sudo k3s ctr images ls | grep -q "$IMAGE"; then
    echo "  ✓ Image found in k3s:"
    sudo k3s ctr images ls | grep "$IMAGE" | sed 's/^/    /'
else
    echo "  ⚠ Warning: Image not found in k3s (may need a moment to appear)"
fi

echo ""
echo "Done! Image $IMAGE is now available to k3s."



