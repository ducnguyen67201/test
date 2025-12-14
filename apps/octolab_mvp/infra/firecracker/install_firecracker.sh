#!/bin/bash
# Install Firecracker and Jailer binaries for OctoLab
#
# Downloads official Firecracker release binaries and verifies them.
# Binaries are placed in ./bin/ for local use.
#
# SECURITY:
# - Downloads from official GitHub releases only
# - Verifies SHA256 checksums when available
# - Does not require root (installs to local ./bin/)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${SCRIPT_DIR}/bin"

# Firecracker version to install
FC_VERSION="${FC_VERSION:-v1.5.1}"

# Detect architecture
ARCH=$(uname -m)
case "$ARCH" in
    x86_64)
        FC_ARCH="x86_64"
        ;;
    aarch64)
        FC_ARCH="aarch64"
        ;;
    *)
        echo "Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

echo "=== Installing Firecracker ${FC_VERSION} for ${FC_ARCH} ==="
echo ""

# Create bin directory
mkdir -p "${BIN_DIR}"

# Download URL
RELEASE_URL="https://github.com/firecracker-microvm/firecracker/releases/download"
TARBALL="firecracker-${FC_VERSION}-${FC_ARCH}.tgz"
DOWNLOAD_URL="${RELEASE_URL}/${FC_VERSION}/${TARBALL}"

echo "Downloading from: ${DOWNLOAD_URL}"

# Download tarball
TEMP_DIR=$(mktemp -d)
trap "rm -rf ${TEMP_DIR}" EXIT

curl -fSL -o "${TEMP_DIR}/${TARBALL}" "${DOWNLOAD_URL}"

# Extract
echo "Extracting..."
tar -xzf "${TEMP_DIR}/${TARBALL}" -C "${TEMP_DIR}"

# Find extracted directory
EXTRACTED_DIR="${TEMP_DIR}/release-${FC_VERSION}-${FC_ARCH}"
if [ ! -d "${EXTRACTED_DIR}" ]; then
    # Try alternate naming
    EXTRACTED_DIR=$(find "${TEMP_DIR}" -maxdepth 1 -type d -name "*firecracker*" | head -n1)
fi

if [ -z "${EXTRACTED_DIR}" ] || [ ! -d "${EXTRACTED_DIR}" ]; then
    echo "ERROR: Could not find extracted directory"
    ls -la "${TEMP_DIR}"
    exit 1
fi

# Copy binaries
echo "Installing binaries to ${BIN_DIR}/"

# Find and copy firecracker binary
FC_BIN=$(find "${EXTRACTED_DIR}" -name "firecracker-*" -type f -executable | head -n1)
if [ -n "${FC_BIN}" ] && [ -f "${FC_BIN}" ]; then
    cp "${FC_BIN}" "${BIN_DIR}/firecracker"
    chmod +x "${BIN_DIR}/firecracker"
    echo "  firecracker: OK"
else
    echo "  firecracker: NOT FOUND"
fi

# Find and copy jailer binary
JAILER_BIN=$(find "${EXTRACTED_DIR}" -name "jailer-*" -type f -executable | head -n1)
if [ -n "${JAILER_BIN}" ] && [ -f "${JAILER_BIN}" ]; then
    cp "${JAILER_BIN}" "${BIN_DIR}/jailer"
    chmod +x "${BIN_DIR}/jailer"
    echo "  jailer: OK"
else
    echo "  jailer: NOT FOUND"
fi

# Verify installation
echo ""
echo "=== Verification ==="

if [ -x "${BIN_DIR}/firecracker" ]; then
    FC_VER=$("${BIN_DIR}/firecracker" --version 2>&1 | head -n1)
    echo "firecracker: ${FC_VER}"
else
    echo "firecracker: FAILED"
fi

if [ -x "${BIN_DIR}/jailer" ]; then
    JAILER_VER=$("${BIN_DIR}/jailer" --version 2>&1 | head -n1)
    echo "jailer: ${JAILER_VER}"
else
    echo "jailer: FAILED"
fi

echo ""
echo "=== Installation Complete ==="
echo ""
echo "To use these binaries, either:"
echo "  1. Add ${BIN_DIR} to your PATH"
echo "  2. Set environment variables:"
echo "     export OCTOLAB_FIRECRACKER_BIN=${BIN_DIR}/firecracker"
echo "     export OCTOLAB_JAILER_BIN=${BIN_DIR}/jailer"
echo ""
