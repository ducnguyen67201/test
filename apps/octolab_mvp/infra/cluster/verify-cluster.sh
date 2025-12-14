#!/usr/bin/env bash
set -euo pipefail

# Verify k3s cluster is healthy and configure kubectl access
# This script should be run as a normal user (not root)

echo "OctoLab: Verifying k3s cluster..."

# Check if k3s kubeconfig exists
K3S_CONFIG="/etc/rancher/k3s/k3s.yaml"
if [ ! -f "$K3S_CONFIG" ]; then
    echo "✗ Error: k3s kubeconfig not found at $K3S_CONFIG"
    echo "  Make sure k3s is installed. Run: sudo bash infra/cluster/install-k3s.sh"
    exit 1
fi

# Set up user's kubeconfig
KUBE_DIR="$HOME/.kube"
KUBE_CONFIG="$KUBE_DIR/config"

echo "Setting up kubectl configuration..."

mkdir -p "$KUBE_DIR"

# Copy k3s kubeconfig to user's home
if [ ! -f "$KUBE_CONFIG" ] || [ "$K3S_CONFIG" -nt "$KUBE_CONFIG" ]; then
    sudo cp "$K3S_CONFIG" "$KUBE_CONFIG"
    sudo chown "$(id -u):$(id -g)" "$KUBE_CONFIG"
    echo "✓ kubeconfig copied to $KUBE_CONFIG"
else
    echo "✓ kubeconfig already up to date"
fi

# Check if kubectl is available
if ! command -v kubectl >/dev/null 2>&1; then
    echo "⚠ Warning: kubectl not found in PATH"
    echo "  You can use k3s's kubectl: /usr/local/bin/kubectl"
    echo "  Or install kubectl separately: https://kubernetes.io/docs/tasks/tools/"
    KUBECTL="/usr/local/bin/kubectl"
else
    KUBECTL="kubectl"
fi

# Verify cluster connectivity
echo ""
echo "Verifying cluster connectivity..."

if ! $KUBECTL get nodes >/dev/null 2>&1; then
    echo "✗ Error: Cannot connect to cluster"
    echo "  Check k3s service: sudo systemctl status k3s"
    exit 1
fi

echo "✓ Cluster is reachable"
echo ""

# Show cluster status
echo "Cluster nodes:"
$KUBECTL get nodes
echo ""

echo "All pods (all namespaces):"
$KUBECTL get pods -A
echo ""

echo "✓ Cluster verification complete!"
echo ""
echo "Healthy cluster should show:"
echo "  - One node in 'Ready' state"
echo "  - Core system pods running (coredns, local-path-provisioner, etc.)"
echo ""
echo "Next steps:"
echo "  1. Install Helm (see docs/infra/cluster-setup.md)"
echo "  2. Install Traefik ingress controller"
echo "  3. Install cert-manager"
echo "  4. Create namespaces: kubectl apply -k infra/base/namespaces/"

