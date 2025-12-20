#!/bin/bash
# Download pre-built kernel and rootfs for Firecracker smoke testing.
#
# Downloads known-good assets from Firecracker CI or public mirrors.
# Does NOT require sudo.
#
# Usage:
#   ./download_hello_assets.sh [--dir /path/to/assets]
#
# Default download location: <repo>/.octolab/firecracker/
#
# After running, set these env vars in backend/.env.local:
#   OCTOLAB_MICROVM_KERNEL_PATH=<path>/vmlinux
#   OCTOLAB_MICROVM_ROOTFS_BASE_PATH=<path>/hello-rootfs.ext4

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Configurable URLs (can override via env)
# These are from Firecracker's CI test assets
KERNEL_URL="${FIRECRACKER_KERNEL_URL:-https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.7/x86_64/vmlinux-5.10.217}"
ROOTFS_URL="${FIRECRACKER_ROOTFS_URL:-https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.7/x86_64/ubuntu-22.04.ext4}"

# Parse arguments
ASSETS_DIR="${REPO_ROOT}/.octolab/firecracker"
for arg in "$@"; do
    case $arg in
        --dir)
            shift
            ASSETS_DIR="$1"
            shift
            ;;
        --dir=*)
            ASSETS_DIR="${arg#*=}"
            shift
            ;;
    esac
done

echo "=== OctoLab Firecracker Assets Download ==="
echo ""
echo "Download directory: ${ASSETS_DIR}"
echo ""

# Create assets directory
mkdir -p "${ASSETS_DIR}"

# Download kernel
KERNEL_PATH="${ASSETS_DIR}/vmlinux"
if [ -f "${KERNEL_PATH}" ]; then
    echo "[1/2] Kernel already exists: ${KERNEL_PATH}"
    echo "      (delete to re-download)"
else
    echo "[1/2] Downloading kernel..."
    echo "      URL: ${KERNEL_URL}"
    curl -fsSL -o "${KERNEL_PATH}" "${KERNEL_URL}"
    chmod 644 "${KERNEL_PATH}"
    echo "      Downloaded: ${KERNEL_PATH} ($(du -h "${KERNEL_PATH}" | cut -f1))"
fi

# Download rootfs
ROOTFS_PATH="${ASSETS_DIR}/hello-rootfs.ext4"
if [ -f "${ROOTFS_PATH}" ]; then
    echo "[2/2] Rootfs already exists: ${ROOTFS_PATH}"
    echo "      (delete to re-download)"
else
    echo "[2/2] Downloading rootfs..."
    echo "      URL: ${ROOTFS_URL}"
    curl -fsSL -o "${ROOTFS_PATH}" "${ROOTFS_URL}"
    chmod 644 "${ROOTFS_PATH}"
    echo "      Downloaded: ${ROOTFS_PATH} ($(du -h "${ROOTFS_PATH}" | cut -f1))"
fi

# Verify files
echo ""
echo "Verifying downloads..."

if [ ! -s "${KERNEL_PATH}" ]; then
    echo "ERROR: Kernel file is empty or missing"
    exit 1
fi

if [ ! -s "${ROOTFS_PATH}" ]; then
    echo "ERROR: Rootfs file is empty or missing"
    exit 1
fi

# Check kernel magic (should start with ELF or bzImage magic)
KERNEL_MAGIC=$(xxd -l 4 "${KERNEL_PATH}" | head -1 | awk '{print $2$3}')
if [[ "${KERNEL_MAGIC}" != "7f45" ]] && [[ "${KERNEL_MAGIC}" != "4d5a" ]]; then
    echo "WARNING: Kernel may not be a valid ELF or bzImage (magic: ${KERNEL_MAGIC})"
fi

echo "   Kernel: OK ($(stat --printf="%s" "${KERNEL_PATH}") bytes)"
echo "   Rootfs: OK ($(stat --printf="%s" "${ROOTFS_PATH}") bytes)"

# Create state directory
STATE_DIR="${REPO_ROOT}/.octolab/microvm-state"
mkdir -p "${STATE_DIR}"
echo ""
echo "Created state directory: ${STATE_DIR}"

echo ""
echo "=== Download Complete ==="
echo ""
echo "Add to backend/.env.local:"
echo ""
echo "  OCTOLAB_MICROVM_KERNEL_PATH=${KERNEL_PATH}"
echo "  OCTOLAB_MICROVM_ROOTFS_BASE_PATH=${ROOTFS_PATH}"
echo "  OCTOLAB_MICROVM_STATE_DIR=${STATE_DIR}"
echo "  OCTOLAB_DEV_UNSAFE_ALLOW_NO_JAILER=true"
echo ""
echo "Then restart backend and check Admin > MicroVM Doctor"
