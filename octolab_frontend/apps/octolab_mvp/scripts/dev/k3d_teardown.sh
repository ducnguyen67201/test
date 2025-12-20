#!/bin/bash
#
# k3d Teardown Script for OctoLab Development
#
# Safely removes a k3d cluster without affecting other k3d clusters.
# Only deletes the cluster specified by name (default: octolab-dev).
# Does not remove kubeconfig files (user manages those).

set -euo pipefail

# Configuration with defaults
CLUSTER_NAME="${K3D_CLUSTER_NAME:-octolab-dev}"

echo "=== OctoLab k3d Teardown ==="
echo "Target cluster: $CLUSTER_NAME"
echo

# Preflight checks
echo "Checking prerequisites..."

# Verify required tools exist
if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker command not found. Cannot check k3d cluster status." >&2
    exit 1
fi

if ! command -v k3d >/dev/null 2>&1; then
    echo "ERROR: k3d command not found. Please ensure k3d is installed." >&2
    echo "  Install k3d:" >&2
    echo "    Windows (Chocolatey): choco install k3d" >&2
    echo "    Linux/WSL: curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | sh" >&2
    exit 1
fi

# Check that Docker daemon is responsive
if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker daemon is not responding. Please start Docker Desktop." >&2
    exit 1
fi

# Check if cluster exists
if k3d cluster list "$CLUSTER_NAME" >/dev/null 2>&1; then
    echo "Found cluster: $CLUSTER_NAME"
    
    # Get current context to see if it's the cluster we're about to delete
    CURRENT_CONTEXT=$(kubectl config current-context 2>/dev/null || echo "none")
    EXPECTED_CONTEXT="k3d-$CLUSTER_NAME"
    
    if [ "$CURRENT_CONTEXT" = "$EXPECTED_CONTEXT" ]; then
        echo "Current kubectl context is $CURRENT_CONTEXT, will switch after deletion if other contexts exist."
    fi
    
    echo "Deleting cluster: $CLUSTER_NAME..."
    k3d cluster delete "$CLUSTER_NAME"
    echo "✓ Cluster $CLUSTER_NAME deleted successfully"
    
    # If the cluster context was active, switch to a different one if available
    if [ "$CURRENT_CONTEXT" = "$EXPECTED_CONTEXT" ]; then
        # Find another available context
        OTHER_CONTEXT=$(kubectl config get-contexts -o name 2>/dev/null | grep -v "^$EXPECTED_CONTEXT$" | head -n 1 || echo "")
        if [ -n "$OTHER_CONTEXT" ] && [ "$OTHER_CONTEXT" != "" ]; then
            echo "Switching to different context: $OTHER_CONTEXT"
            kubectl config use-context "$OTHER_CONTEXT" 2>/dev/null || echo "  (could not switch, current context lost)"
        else
            echo "No other contexts available to switch to."
        fi
    fi
    
    # Note about kubeconfig files
    K3D_KUBECONFIG_PATH="$HOME/.kube/k3d/k3d-$CLUSTER_NAME.yaml"
    if [ -f "$K3D_KUBECONFIG_PATH" ]; then
        echo
        echo "ℹ️  Note: Kubeconfig file still exists at: $K3D_KUBECONFIG_PATH"
        echo "   You may want to remove this file manually if no longer needed:"
        echo "   rm $K3D_KUBECONFIG_PATH"
    fi
else
    echo "ℹ️  No k3d cluster found with name: $CLUSTER_NAME"
    echo "Available k3d clusters:"
    k3d cluster list 2>/dev/null || echo "  (no k3d clusters found)"
    
    # Show all kubectl contexts
    echo
    echo "Available kubectl contexts:"
    kubectl config get-contexts -o name 2>/dev/null || echo "  (kubectl not responding)"
    exit 0
fi

echo
echo "Cluster teardown completed."
echo "Other k3d clusters remain untouched."