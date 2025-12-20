#!/usr/bin/env bash
# Create k3d cluster for OctoLab local development
#
# This script is idempotent: it checks if the cluster exists before creating.
#
# IMPORTANT: Only run from Linux/WSL filesystem (not Windows mounts)
# See README.md for requirements

set -euo pipefail

# Get script directory (works on Linux/WSL, repo-relative)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLUSTER_CONFIG="${SCRIPT_DIR}/cluster.yaml"
CLUSTER_NAME="octolab-dev"

echo "==> k3d cluster creation for OctoLab"

# Check if running from Windows mount (safety check)
if [[ "$SCRIPT_DIR" == /mnt/* ]]; then
    echo "ERROR: Running from Windows filesystem mount ($SCRIPT_DIR)"
    echo "This is not supported. Please clone the repository to Linux filesystem."
    echo "Example: /home/<user>/octolab_mvp"
    exit 1
fi

# Check prerequisites
if ! command -v k3d &> /dev/null; then
    echo "ERROR: k3d is not installed"
    echo "Install: curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo "ERROR: docker is not installed or not running"
    exit 1
fi

if ! docker ps &> /dev/null; then
    echo "ERROR: docker daemon is not running or not accessible"
    echo "Start Docker and try again"
    exit 1
fi

# Check if cluster already exists
if k3d cluster list | grep -q "^${CLUSTER_NAME}"; then
    echo "INFO: Cluster '${CLUSTER_NAME}' already exists"

    # Check if it's running
    if k3d cluster list | grep "^${CLUSTER_NAME}" | grep -q "running"; then
        echo "INFO: Cluster is running"
        echo "To recreate: run ./delete_cluster.sh first"
        exit 0
    else
        echo "INFO: Cluster exists but not running. Starting..."
        k3d cluster start "${CLUSTER_NAME}"
        echo "✓ Cluster started successfully"
        exit 0
    fi
fi

# Create cluster from config
echo "INFO: Creating cluster '${CLUSTER_NAME}' from ${CLUSTER_CONFIG}"
k3d cluster create --config "${CLUSTER_CONFIG}"

# Wait for cluster to be ready
echo "INFO: Waiting for cluster to be ready..."
kubectl wait --for=condition=Ready nodes --all --timeout=60s

# Apply base manifests (namespaces)
echo "INFO: Applying base namespaces..."
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
kubectl apply -f "${REPO_ROOT}/infra/base/namespaces/"

echo ""
echo "✓ k3d cluster '${CLUSTER_NAME}' created successfully"
echo ""
echo "Next steps:"
echo "  1. Verify cluster: ./smoke_test.sh (or: make k3d-smoke)"
echo "  2. Import images: make k3d-import-image IMAGE=<name:tag>"
echo "  3. Deploy apps: kubectl apply -k infra/apps/"
echo ""
echo "Access:"
echo "  - HTTP ingress:  http://127.0.0.1:8080"
echo "  - HTTPS ingress: https://127.0.0.1:8443"
echo "  - kubectl context: k3d-${CLUSTER_NAME}"
echo ""
