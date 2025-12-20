#!/bin/bash
# Download kernel and rootfs artifacts for Firecracker
#
# Downloads a minimal kernel and rootfs suitable for Firecracker POC.
# These are official Firecracker CI artifacts.
#
# SECURITY:
# - Downloads from official sources
# - Artifacts are for POC only; production should use custom images
# - Rootfs includes a minimal guest agent

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACTS_DIR="${SCRIPT_DIR}/artifacts"

# Detect architecture
ARCH=$(uname -m)
case "$ARCH" in
    x86_64)
        KERNEL_URL="https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.5/x86_64/vmlinux-5.10.186"
        ROOTFS_URL="https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.5/x86_64/ubuntu-22.04.ext4"
        ;;
    aarch64)
        KERNEL_URL="https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.5/aarch64/vmlinux-5.10.186"
        ROOTFS_URL="https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.5/aarch64/ubuntu-22.04.ext4"
        ;;
    *)
        echo "Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

echo "=== Downloading Firecracker Kernel and Rootfs for ${ARCH} ==="
echo ""

# Create artifacts directory
mkdir -p "${ARTIFACTS_DIR}"

# Download kernel
KERNEL_PATH="${ARTIFACTS_DIR}/vmlinux"
if [ -f "${KERNEL_PATH}" ]; then
    echo "Kernel already exists: ${KERNEL_PATH}"
else
    echo "Downloading kernel..."
    curl -fSL -o "${KERNEL_PATH}" "${KERNEL_URL}"
    chmod 644 "${KERNEL_PATH}"
    echo "Kernel downloaded: ${KERNEL_PATH}"
fi

# Download rootfs
ROOTFS_PATH="${ARTIFACTS_DIR}/rootfs.ext4"
if [ -f "${ROOTFS_PATH}" ]; then
    echo "Rootfs already exists: ${ROOTFS_PATH}"
else
    echo "Downloading rootfs (this may take a while)..."
    curl -fSL -o "${ROOTFS_PATH}" "${ROOTFS_URL}"
    chmod 644 "${ROOTFS_PATH}"
    echo "Rootfs downloaded: ${ROOTFS_PATH}"
fi

# Show sizes
echo ""
echo "=== Artifact Sizes ==="
ls -lh "${ARTIFACTS_DIR}/"

echo ""
echo "=== Setup Instructions ==="
echo ""
echo "Set these environment variables to use the artifacts:"
echo ""
echo "  export OCTOLAB_MICROVM_KERNEL_PATH=${KERNEL_PATH}"
echo "  export OCTOLAB_MICROVM_ROOTFS_BASE_PATH=${ROOTFS_PATH}"
echo ""
echo "NOTE: The downloaded rootfs is a standard Ubuntu image."
echo "For the POC guest agent to work, you need to either:"
echo "  1. Mount the rootfs and install the agent (requires root)"
echo "  2. Use a custom rootfs with the agent pre-installed"
echo ""
echo "See docs/README.md for detailed instructions."
echo ""
