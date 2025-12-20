#!/usr/bin/env bash
set -euo pipefail

# Install k3s on Ubuntu 22.04 with built-in Traefik disabled
# This script should be run as root or via sudo

echo "OctoLab: Installing k3s (single-node, Traefik disabled)..."

# Check if k3s is already installed
if command -v k3s >/dev/null 2>&1; then
    echo "k3s is already installed. Skipping installation."
    echo "If you need to reinstall, uninstall k3s first: /usr/local/bin/k3s-uninstall.sh"
    exit 0
fi

# Install k3s with Traefik disabled
echo "Downloading and installing k3s..."
curl -sfL https://get.k3s.io | \
    K3S_KUBECONFIG_MODE="644" \
    INSTALL_K3S_EXEC="--disable=traefik" \
    sh -s -

# Wait a moment for k3s to fully start
sleep 5

# Verify k3s service is running
if systemctl is-active --quiet k3s; then
    echo "✓ k3s service is running"
else
    echo "✗ k3s service is not running. Check: sudo systemctl status k3s"
    exit 1
fi

echo ""
echo "k3s installation complete!"
echo ""
echo "Kubeconfig location: /etc/rancher/k3s/k3s.yaml"
echo ""
echo "Next steps:"
echo "  1. Run: bash infra/cluster/verify-cluster.sh"
echo "  2. Install Helm (see docs/infra/cluster-setup.md)"
echo "  3. Install Traefik and cert-manager (see docs/infra/cluster-setup.md)"

