#!/bin/bash
# =============================================================================
# WSL Ubuntu 24.04 Firecracker Setup Script
# =============================================================================
#
# Sets up Firecracker microVM runtime for development on WSL Ubuntu 24.04.
# This script is idempotent and safe to re-run.
#
# SECURITY NOTES:
# - This is for DEV ONLY. Jailer is required in production.
# - WSL nested virtualization has different security properties than bare-metal.
# - Never use OCTOLAB_DEV_UNSAFE_ALLOW_NO_JAILER=true in production.
#
# Usage:
#   ./wsl_ubuntu24_setup.sh
#
# Prerequisites:
#   - WSL2 with nested virtualization enabled (Windows 11)
#   - Ubuntu 24.04 distribution
#   - /dev/kvm must be accessible
#
# After running:
#   1. Source your shell or restart terminal
#   2. Run: make dev (restart backend)
#   3. Verify: bash infra/microvm/verify_firecracker.sh
#
# =============================================================================

set -euo pipefail

# ==== Constants ====
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Firecracker version (pinned for reproducibility)
FC_VERSION="${FC_VERSION:-v1.7.0}"

# Paths
MICROVM_BASE="/var/lib/octolab/microvm"
KERNEL_DIR="${MICROVM_BASE}/kernel"
IMAGES_DIR="${MICROVM_BASE}/images"
STATE_DIR="${MICROVM_BASE}/state"

# Kernel and rootfs URLs (Firecracker CI assets)
KERNEL_URL="https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.7/x86_64/vmlinux-5.10.217"
ROOTFS_URL="https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.7/x86_64/ubuntu-22.04.ext4"

# Backend env file
ENV_LOCAL="${REPO_ROOT}/backend/.env.local"
ENV_MARKER_START="# >>> OCTOLAB_MICROVM_WSL_SETUP >>>"
ENV_MARKER_END="# <<< OCTOLAB_MICROVM_WSL_SETUP <<<"

# ==== Helper Functions ====

log_info() {
    echo "[INFO] $*"
}

log_warn() {
    echo "[WARN] $*" >&2
}

log_error() {
    echo "[ERROR] $*" >&2
}

log_fatal() {
    echo "[FATAL] $*" >&2
    exit 1
}

# Check if running on x86_64
check_arch() {
    local arch
    arch="$(uname -m)"
    if [ "$arch" != "x86_64" ]; then
        log_fatal "Unsupported architecture: $arch. Only x86_64 is supported."
    fi
    log_info "Architecture: $arch"
}

# Check if running in WSL
check_wsl() {
    if [ -f /proc/sys/fs/binfmt_misc/WSLInterop ] || \
       [ -n "${WSL_INTEROP:-}" ] || \
       grep -qi "microsoft" /proc/version 2>/dev/null; then
        log_info "WSL environment detected"
        return 0
    fi
    log_warn "Not running in WSL - this script is designed for WSL Ubuntu 24.04"
    return 0  # Continue anyway, but warn
}

# Check KVM availability
check_kvm() {
    if [ ! -e /dev/kvm ]; then
        log_fatal "/dev/kvm not found. Enable nested virtualization in WSL:
  1. Edit %USERPROFILE%\\.wslconfig (Windows side):
     [wsl2]
     nestedVirtualization=true

  2. Run in PowerShell: wsl --shutdown
  3. Restart your WSL distribution"
    fi

    # Check read/write access
    if [ ! -r /dev/kvm ] || [ ! -w /dev/kvm ]; then
        log_warn "/dev/kvm exists but is not accessible. Attempting to fix..."
        sudo chmod 666 /dev/kvm 2>/dev/null || \
            log_fatal "Cannot access /dev/kvm. Try: sudo chmod 666 /dev/kvm"
    fi

    log_info "/dev/kvm is accessible"
}

# Install system dependencies
install_deps() {
    log_info "Installing system dependencies..."

    # Update package lists
    sudo apt-get update -qq

    # Install required packages
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        curl \
        jq \
        ca-certificates \
        e2fsprogs \
        qemu-utils \
        tar \
        gzip \
        iptables \
        socat \
        iproute2 \
        xxd \
        > /dev/null

    log_info "Dependencies installed"
}

# Create directory structure
create_directories() {
    log_info "Creating directory structure..."

    # Create base directories with sudo
    sudo mkdir -p "$KERNEL_DIR"
    sudo mkdir -p "$IMAGES_DIR"
    sudo mkdir -p "$STATE_DIR"

    # Set ownership to current user for state dir (backend writes here)
    sudo chown -R "$USER:$USER" "$STATE_DIR"
    sudo chmod 0700 "$STATE_DIR"

    # Kernel and images can be read-only for the user
    sudo chown -R "$USER:$USER" "$KERNEL_DIR"
    sudo chown -R "$USER:$USER" "$IMAGES_DIR"
    sudo chmod 0755 "$KERNEL_DIR"
    sudo chmod 0755 "$IMAGES_DIR"

    log_info "Directories created:"
    log_info "  Kernel:  $KERNEL_DIR"
    log_info "  Images:  $IMAGES_DIR"
    log_info "  State:   $STATE_DIR"
}

# Install Firecracker binary
install_firecracker() {
    log_info "Installing Firecracker ${FC_VERSION}..."

    local temp_dir
    temp_dir="$(mktemp -d)"
    # shellcheck disable=SC2064
    trap "rm -rf '$temp_dir'" EXIT

    local tarball="firecracker-${FC_VERSION}-x86_64.tgz"
    local url="https://github.com/firecracker-microvm/firecracker/releases/download/${FC_VERSION}/${tarball}"

    log_info "Downloading from: $url"

    # Download tarball
    if ! curl -fsSL -o "${temp_dir}/${tarball}" "$url"; then
        log_fatal "Failed to download Firecracker. Check network and URL."
    fi

    # Extract
    tar -xzf "${temp_dir}/${tarball}" -C "$temp_dir"

    # Find binaries (naming: firecracker-vX.Y.Z-arch)
    local fc_bin
    fc_bin="$(find "$temp_dir" -name "firecracker-*" -type f -executable | head -1)"

    if [ -z "$fc_bin" ] || [ ! -f "$fc_bin" ]; then
        log_fatal "Firecracker binary not found in release archive"
    fi

    # Install to /usr/local/bin
    sudo cp "$fc_bin" /usr/local/bin/firecracker
    sudo chmod 0755 /usr/local/bin/firecracker

    # Verify
    local version
    version="$(/usr/local/bin/firecracker --version 2>&1 | head -1)"
    log_info "Installed: $version"

    # Note: We don't install jailer for WSL dev - it doesn't work properly
    log_info "Note: Jailer not installed (not required for WSL dev)"

    # Clear trap
    trap - EXIT
    rm -rf "$temp_dir"
}

# Download kernel
download_kernel() {
    local kernel_path="${KERNEL_DIR}/vmlinux"

    if [ -f "$kernel_path" ]; then
        log_info "Kernel already exists: $kernel_path"
        return 0
    fi

    log_info "Downloading kernel..."
    log_info "URL: $KERNEL_URL"

    if ! curl -fsSL -o "$kernel_path" "$KERNEL_URL"; then
        log_fatal "Failed to download kernel"
    fi

    chmod 0644 "$kernel_path"

    local size
    size="$(du -h "$kernel_path" | cut -f1)"
    log_info "Kernel downloaded: $kernel_path ($size)"
}

# Download or build rootfs
download_rootfs() {
    local rootfs_path="${IMAGES_DIR}/base.ext4"

    if [ -f "$rootfs_path" ]; then
        log_info "Rootfs already exists: $rootfs_path"
        return 0
    fi

    # Check if we have a repo-local build script
    local build_script="${REPO_ROOT}/infra/firecracker/build-rootfs.sh"
    if [ -x "$build_script" ]; then
        log_info "Found build-rootfs.sh - building custom rootfs..."
        # Build rootfs and copy to standard location
        if bash "$build_script"; then
            local built_rootfs="${REPO_ROOT}/infra/firecracker/artifacts/rootfs.ext4"
            if [ -f "$built_rootfs" ]; then
                cp "$built_rootfs" "$rootfs_path"
                chmod 0644 "$rootfs_path"
                log_info "Custom rootfs built and copied to: $rootfs_path"
                return 0
            fi
        fi
        log_warn "build-rootfs.sh failed, falling back to CI rootfs"
    fi

    # Fallback: download from Firecracker CI
    log_info "Downloading rootfs from Firecracker CI..."
    log_info "URL: $ROOTFS_URL"

    if ! curl -fsSL -o "$rootfs_path" "$ROOTFS_URL"; then
        log_fatal "Failed to download rootfs"
    fi

    chmod 0644 "$rootfs_path"

    local size
    size="$(du -h "$rootfs_path" | cut -f1)"
    log_info "Rootfs downloaded: $rootfs_path ($size)"
}

# Update backend/.env.local with microvm configuration
write_env_config() {
    log_info "Updating backend/.env.local..."

    local kernel_path="${KERNEL_DIR}/vmlinux"
    local rootfs_path="${IMAGES_DIR}/base.ext4"

    # Create env block
    local env_block
    env_block="$ENV_MARKER_START
OCTOLAB_MICROVM_KERNEL_PATH=${kernel_path}
OCTOLAB_MICROVM_ROOTFS_BASE_PATH=${rootfs_path}
OCTOLAB_MICROVM_STATE_DIR=${STATE_DIR}
OCTOLAB_DEV_UNSAFE_ALLOW_NO_JAILER=true
$ENV_MARKER_END"

    # Ensure .env.local exists
    if [ ! -f "$ENV_LOCAL" ]; then
        log_info "Creating $ENV_LOCAL"
        touch "$ENV_LOCAL"
    fi

    # Remove existing block if present
    if grep -q "$ENV_MARKER_START" "$ENV_LOCAL" 2>/dev/null; then
        log_info "Removing existing microvm config block..."
        # Use sed to remove the block
        sed -i "/$ENV_MARKER_START/,/$ENV_MARKER_END/d" "$ENV_LOCAL"
    fi

    # Append new block
    echo "" >> "$ENV_LOCAL"
    echo "$env_block" >> "$ENV_LOCAL"

    log_info "Environment config written to: $ENV_LOCAL"
    log_info "Note: OCTOLAB_RUNTIME is NOT set - microvm is opt-in only"
}

# Verify installation by running doctor
run_verification() {
    log_info "Running verification..."

    # Check firecracker binary
    if ! command -v firecracker &>/dev/null && [ ! -x /usr/local/bin/firecracker ]; then
        log_error "Firecracker binary not found"
        return 1
    fi

    # Check kernel exists
    local kernel_path="${KERNEL_DIR}/vmlinux"
    if [ ! -f "$kernel_path" ]; then
        log_error "Kernel not found: $kernel_path"
        return 1
    fi

    # Check rootfs exists
    local rootfs_path="${IMAGES_DIR}/base.ext4"
    if [ ! -f "$rootfs_path" ]; then
        log_error "Rootfs not found: $rootfs_path"
        return 1
    fi

    # Check state dir is writable
    local test_file="${STATE_DIR}/.setup_test"
    if ! touch "$test_file" 2>/dev/null; then
        log_error "State directory not writable: $STATE_DIR"
        return 1
    fi
    rm -f "$test_file"

    # Check KVM
    if [ ! -r /dev/kvm ] || [ ! -w /dev/kvm ]; then
        log_error "/dev/kvm not accessible"
        return 1
    fi

    log_info "All checks passed!"
    return 0
}

# Print summary
print_summary() {
    echo ""
    echo "============================================================"
    echo "  WSL Ubuntu 24.04 Firecracker Setup Complete"
    echo "============================================================"
    echo ""
    echo "Installed:"
    echo "  - Firecracker: /usr/local/bin/firecracker"
    echo "  - Kernel:      ${KERNEL_DIR}/vmlinux"
    echo "  - Rootfs:      ${IMAGES_DIR}/base.ext4"
    echo "  - State dir:   ${STATE_DIR}"
    echo ""
    echo "Environment config written to: ${ENV_LOCAL}"
    echo ""
    echo "IMPORTANT: This setup is for DEVELOPMENT ONLY."
    echo "  - Jailer is not installed (doesn't work in WSL)"
    echo "  - OCTOLAB_DEV_UNSAFE_ALLOW_NO_JAILER=true is set"
    echo "  - NEVER use this configuration in production"
    echo ""
    echo "Next steps:"
    echo "  1. Verify setup:    bash infra/microvm/verify_firecracker.sh"
    echo "  2. Restart backend: make dev"
    echo "  3. (Optional) To enable microvm runtime:"
    echo "     export OCTOLAB_RUNTIME=firecracker"
    echo ""
    echo "Note: Default runtime remains 'compose'. Microvm is opt-in only."
    echo ""
}

# ==== Main ====

main() {
    echo ""
    echo "============================================================"
    echo "  OctoLab Firecracker Setup for WSL Ubuntu 24.04"
    echo "============================================================"
    echo ""

    # Pre-flight checks
    check_arch
    check_wsl
    check_kvm

    # Install and configure
    install_deps
    create_directories
    install_firecracker
    download_kernel
    download_rootfs
    write_env_config

    # Verify
    if ! run_verification; then
        log_fatal "Verification failed. Check errors above."
    fi

    print_summary
}

main "$@"
