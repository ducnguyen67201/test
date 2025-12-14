#!/bin/bash
#
# k3d Bootstrap Script for OctoLab Development
# 
# Creates a k3d (k3s-in-Docker) cluster to avoid WSL kubelet mount parsing crashes.
# Uses secure localhost-only binding by default.
#
# Configuration (environment variables):
# - CLUSTER_NAME: k3d cluster name (default: octolab-dev) 
# - API_PORT: API server port (default: 6550, bound to localhost)
# - AGENTS: Number of agent nodes (default: 1)
#
# Security: Only binds to 127.0.0.1 by default (not 0.0.0.0 for security)

set -euo pipefail

# Configuration with defaults
CLUSTER_NAME="${K3D_CLUSTER_NAME:-octolab-dev}"
API_PORT="${K3D_API_PORT:-6550}"
AGENTS="${K3D_AGENTS:-1}"
BIND_HOST="${K3D_BIND_HOST:-127.0.0.1}"

echo "=== OctoLab k3d Bootstrap ==="
echo "Cluster: $CLUSTER_NAME"
echo "API Port: $BIND_HOST:$API_PORT" 
echo "Agents: $AGENTS"
echo

# Preflight checks
echo "Checking prerequisites..."

# Check docker is available
if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker command not found." >&2
    echo "  Please install Docker Desktop and ensure WSL integration is enabled." >&2
    echo "" >&2
    echo "  Install Docker Desktop from: https://www.docker.com/products/docker-desktop" >&2
    echo "  Enable WSL integration in: Docker Desktop Settings > Resources > WSL Integration" >&2
    exit 1
fi

# Check kubectl is available  
if ! command -v kubectl >/dev/null 2>&1; then
    echo "ERROR: kubectl command not found." >&2
    echo "  Install with one of:" >&2
    echo "    Windows (Chocolatey): choco install kubernetes-cli" >&2
    echo "    Linux/WSL: curl -LO \"https://dl.k8s.io/release/\$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl\" && chmod +x kubectl && sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl" >&2
    exit 1
fi

# Check k3d is available
if ! command -v k3d >/dev/null 2>&1; then
    echo "ERROR: k3d command not found." >&2
    echo "  Install with one of:" >&2
    echo "    Windows (Chocolatey): choco install k3d" >&2
    echo "    Linux/WSL: curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | sh" >&2
    exit 1
fi

# Check that Docker daemon is responsive
echo "Verifying Docker daemon connectivity..."
if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker daemon is not responding." >&2
    echo "  Please:" >&2
    echo "    1. Start Docker Desktop" >&2
    echo "    2. Ensure WSL integration is enabled" >&2
    exit 1
fi

# Check if cluster already exists
echo "Checking for existing cluster: $CLUSTER_NAME"
if k3d cluster list "$CLUSTER_NAME" >/dev/null 2>&1; then
    echo "Found existing cluster: $CLUSTER_NAME"
    
    # Check if cluster is running
    if k3d cluster list "$CLUSTER_NAME" | grep -q "running"; then
        echo "Cluster $CLUSTER_NAME is already running"
    else
        echo "Cluster $CLUSTER_NAME exists but is stopped. Starting..."
        k3d cluster start "$CLUSTER_NAME"
        echo "Cluster $CLUSTER_NAME started"
    fi
else
    echo "Creating k3d cluster: $CLUSTER_NAME"
    echo "  Binding API to $BIND_HOST:$API_PORT (localhost only for security)"
    
    # Create cluster with secure localhost binding
    k3d cluster create "$CLUSTER_NAME" \
        --agents "$AGENTS" \
        --api-port "$BIND_HOST:$API_PORT" \
        --k3s-arg "--disable=traefik@server:0" \
        --k3s-arg "--disable=servicelb@server:0" \
        --wait
    
    echo "✓ Cluster $CLUSTER_NAME created successfully"
fi

# Set kubectl context to the new cluster
EXPECTED_CONTEXT="k3d-$CLUSTER_NAME"
echo "Setting kubectl context to: $EXPECTED_CONTEXT"
kubectl config use-context "$EXPECTED_CONTEXT"

# Verify cluster readiness
echo
echo "Waiting for cluster readiness..."
MAX_WAIT=60
WAIT_COUNT=0
while [ $WAIT_COUNT -lt $MAX_WAIT ]; do
    if kubectl get nodes >/dev/null 2>&1; then
        NODE_COUNT=$(kubectl get nodes --no-headers 2>/dev/null | wc -l || echo 0)
        if [ $NODE_COUNT -ge 1 ]; then
            READY_NODES=$(kubectl get nodes --no-headers 2>/dev/null | awk '$2 ~ /Ready/ {count++} END {print count+0}')
            if [ "$READY_NODES" -ge 1 ]; then
                echo "✓ Cluster is ready with $NODE_COUNT node(s), $READY_NODES ready."
                
                # Display node status
                echo
                echo "[CLUSTER STATUS]"
                kubectl get nodes
                break
            fi
        fi
    fi
    sleep 2
    ((WAIT_COUNT+=2))
done

if [ $WAIT_COUNT -ge $MAX_WAIT ]; then
    echo "⚠ WARNING: Timed out waiting for nodes to be ready (after $MAX_WAIT seconds)" >&2
    echo "  Cluster may still be initializing; check: kubectl get nodes" >&2
fi

echo
echo "==================================================="
echo "k3d cluster $CLUSTER_NAME is ready!"
echo "==================================================="
echo
echo "Next steps:"
echo "1. Verify context: kubectl config current-context # should show $EXPECTED_CONTEXT"
echo "2. Check nodes: kubectl get nodes"
echo "3. Run OctoLab backend with k3d context:"
echo "   export KUBECTL_CONTEXT=$EXPECTED_CONTEXT"
echo "   python -m uvicorn app.main:app --reload"
echo
echo "Cluster details:"
echo "  - Name: $CLUSTER_NAME"
echo "  - Context: $EXPECTED_CONTEXT"
echo "  - API Endpoint: $BIND_HOST:$API_PORT"
echo "  - Nodes: $NODE_COUNT (ready: $READY_NODES)"
echo

exit 0