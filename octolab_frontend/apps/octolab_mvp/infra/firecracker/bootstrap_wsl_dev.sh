#!/bin/bash
# Bootstrap Firecracker for WSL development environment.
#
# Downloads and installs Firecracker binary to a local directory.
# Does NOT require sudo (installs to ~/.local/bin or repo-local .octolab/bin).
#
# Usage:
#   ./bootstrap_wsl_dev.sh [--local]
#
# Options:
#   --local    Install to repo-local .octolab/bin instead of ~/.local/bin
#
# After running, add the printed env vars to your backend/.env.local

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Parse arguments
INSTALL_LOCAL=false
for arg in "$@"; do
    case $arg in
        --local)
            INSTALL_LOCAL=true
            shift
            ;;
    esac
done

# Determine install directory
if [ "$INSTALL_LOCAL" = true ]; then
    INSTALL_DIR="${REPO_ROOT}/.octolab/bin"
else
    INSTALL_DIR="${HOME}/.local/bin"
fi

echo "=== OctoLab Firecracker Bootstrap for WSL ==="
echo ""
echo "Install directory: ${INSTALL_DIR}"
echo ""

# Create install directory
mkdir -p "${INSTALL_DIR}"

# Detect architecture
ARCH=$(uname -m)
case $ARCH in
    x86_64)
        FC_ARCH="x86_64"
        ;;
    aarch64)
        FC_ARCH="aarch64"
        ;;
    *)
        echo "ERROR: Unsupported architecture: ${ARCH}"
        exit 1
        ;;
esac

echo "[1/4] Detecting latest Firecracker release..."

# Get latest release tag using Python (no jq dependency)
LATEST_TAG=$(python3 -c "
import urllib.request
import json
import ssl

# Handle SSL (some WSL setups have cert issues)
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

url = 'https://api.github.com/repos/firecracker-microvm/firecracker/releases/latest'
req = urllib.request.Request(url, headers={'User-Agent': 'octolab-bootstrap'})
with urllib.request.urlopen(req, context=ctx) as response:
    data = json.loads(response.read().decode())
    print(data['tag_name'])
")

echo "   Latest release: ${LATEST_TAG}"

# Construct download URL
# Release assets are named: firecracker-v1.7.0-x86_64.tgz
DOWNLOAD_URL="https://github.com/firecracker-microvm/firecracker/releases/download/${LATEST_TAG}/firecracker-${LATEST_TAG}-${FC_ARCH}.tgz"

echo "[2/4] Downloading Firecracker ${LATEST_TAG} for ${FC_ARCH}..."
echo "   URL: ${DOWNLOAD_URL}"

# Create temp directory
TEMP_DIR=$(mktemp -d)
trap "rm -rf ${TEMP_DIR}" EXIT

# Download
cd "${TEMP_DIR}"
curl -fsSL -o firecracker.tgz "${DOWNLOAD_URL}"

echo "[3/4] Extracting and installing..."

# Extract
tar xzf firecracker.tgz

# Find the extracted directory (format: release-vX.Y.Z-arch)
EXTRACT_DIR=$(ls -d release-* 2>/dev/null | head -1)
if [ -z "${EXTRACT_DIR}" ]; then
    echo "ERROR: Could not find extracted release directory"
    ls -la
    exit 1
fi

# Copy binaries
# Binaries are named: firecracker-vX.Y.Z-arch, jailer-vX.Y.Z-arch
FC_BIN=$(ls "${EXTRACT_DIR}"/firecracker-* 2>/dev/null | head -1)
JAILER_BIN=$(ls "${EXTRACT_DIR}"/jailer-* 2>/dev/null | head -1)

if [ -n "${FC_BIN}" ]; then
    cp "${FC_BIN}" "${INSTALL_DIR}/firecracker"
    chmod +x "${INSTALL_DIR}/firecracker"
    echo "   Installed: ${INSTALL_DIR}/firecracker"
else
    echo "ERROR: firecracker binary not found in release"
    exit 1
fi

if [ -n "${JAILER_BIN}" ]; then
    cp "${JAILER_BIN}" "${INSTALL_DIR}/jailer"
    chmod +x "${INSTALL_DIR}/jailer"
    echo "   Installed: ${INSTALL_DIR}/jailer"
else
    echo "   WARNING: jailer binary not found (OK for WSL dev)"
fi

echo "[4/4] Verifying installation..."

# Verify firecracker
FC_VERSION=$("${INSTALL_DIR}/firecracker" --version 2>&1 || echo "ERROR")
if [[ "${FC_VERSION}" == *"Firecracker"* ]]; then
    echo "   ${FC_VERSION}"
else
    echo "ERROR: firecracker --version failed"
    exit 1
fi

# Check if jailer works (may fail on WSL)
if [ -x "${INSTALL_DIR}/jailer" ]; then
    JAILER_VERSION=$("${INSTALL_DIR}/jailer" --version 2>&1 || echo "not available")
    echo "   jailer: ${JAILER_VERSION}"
fi

echo ""
echo "=== Bootstrap Complete ==="
echo ""
echo "Add to your PATH or set OCTOLAB_FIRECRACKER_BIN:"
echo ""
echo "  export PATH=\"${INSTALL_DIR}:\$PATH\""
echo ""
echo "Or add to backend/.env.local:"
echo ""
echo "  OCTOLAB_FIRECRACKER_BIN=${INSTALL_DIR}/firecracker"
echo ""
echo "Next steps:"
echo "  1. Run: ./infra/firecracker/download_hello_assets.sh"
echo "  2. Set kernel/rootfs paths in backend/.env.local"
echo "  3. Run: make dev (restart backend)"
echo "  4. Check Admin > MicroVM Doctor"
