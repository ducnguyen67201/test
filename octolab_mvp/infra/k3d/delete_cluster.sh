#!/usr/bin/env bash
# Delete k3d cluster for OctoLab local development
#
# This script is idempotent: it tolerates missing cluster.

set -euo pipefail

CLUSTER_NAME="octolab-dev"

echo "==> k3d cluster deletion for OctoLab"

# Check prerequisites
if ! command -v k3d &> /dev/null; then
    echo "ERROR: k3d is not installed"
    exit 1
fi

# Check if cluster exists
if ! k3d cluster list | grep -q "^${CLUSTER_NAME}"; then
    echo "INFO: Cluster '${CLUSTER_NAME}' does not exist"
    echo "Nothing to delete"
    exit 0
fi

# Delete cluster
echo "INFO: Deleting cluster '${CLUSTER_NAME}'..."
k3d cluster delete "${CLUSTER_NAME}"

echo ""
echo "✓ Cluster '${CLUSTER_NAME}' deleted successfully"
echo ""
echo "To recreate: ./create_cluster.sh (or: make k3d-up)"
echo ""
