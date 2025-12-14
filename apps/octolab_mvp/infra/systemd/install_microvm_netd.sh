#!/bin/bash
# Install microvm-netd wrapper and systemd unit
# Usage: sudo ./install_microvm_netd.sh [REPO_PATH]
#
# REPO_PATH: Path to octolab repo (defaults to parent of this script's location)

set -euo pipefail

# Determine repo path
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_PATH="${1:-$(dirname "$(dirname "$SCRIPT_DIR")")}"

# Validate repo path
NETD_SOURCE="${REPO_PATH}/infra/microvm/netd/microvm_netd.py"
if [[ ! -f "$NETD_SOURCE" ]]; then
    echo "ERROR: microvm_netd.py not found at: $NETD_SOURCE" >&2
    exit 1
fi

WRAPPER_TEMPLATE="${REPO_PATH}/infra/microvm/netd/microvm-netd-wrapper.py"
if [[ ! -f "$WRAPPER_TEMPLATE" ]]; then
    echo "ERROR: Wrapper template not found at: $WRAPPER_TEMPLATE" >&2
    exit 1
fi

UNIT_FILE="${SCRIPT_DIR}/microvm-netd.service"
if [[ ! -f "$UNIT_FILE" ]]; then
    echo "ERROR: Unit file not found at: $UNIT_FILE" >&2
    exit 1
fi

# Check running as root
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root" >&2
    exit 1
fi

echo "Installing microvm-netd..."
echo "  Repo path: $REPO_PATH"
echo "  Source: $NETD_SOURCE"

# Create wrapper with baked-in path
echo "Creating /usr/local/bin/microvm-netd..."
sed "s|__NETD_SOURCE_PATH__|${NETD_SOURCE}|g" "$WRAPPER_TEMPLATE" > /usr/local/bin/microvm-netd
chmod 755 /usr/local/bin/microvm-netd

# Verify wrapper was created correctly
if grep -q "__NETD_SOURCE_PATH__" /usr/local/bin/microvm-netd; then
    echo "ERROR: Wrapper path substitution failed" >&2
    exit 1
fi

# Create log directory
echo "Creating log directory..."
mkdir -p /var/log/octolab
chmod 755 /var/log/octolab

# Create run directory (will be recreated by systemd at boot)
mkdir -p /run/octolab
chmod 750 /run/octolab

# Install systemd unit
echo "Installing systemd unit..."
cp "$UNIT_FILE" /etc/systemd/system/microvm-netd.service
chmod 644 /etc/systemd/system/microvm-netd.service

# Reload systemd
echo "Reloading systemd..."
systemctl daemon-reload

echo ""
echo "Installation complete!"
echo ""
echo "To start microvm-netd:"
echo "  sudo systemctl start microvm-netd"
echo ""
echo "To enable at boot:"
echo "  sudo systemctl enable microvm-netd"
echo ""
echo "To check status:"
echo "  sudo systemctl status microvm-netd"
echo "  octolabctl netd status"
