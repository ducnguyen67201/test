#!/usr/bin/env bash
# ============================================================================
# OctoLab MicroVM Setup Script for WSL Ubuntu 24.04
# ============================================================================
#
# This script sets up Firecracker microVM prerequisites for development on
# WSL Ubuntu 24.04. It installs Firecracker binary, downloads kernel/rootfs,
# and configures the backend environment.
#
# USAGE:
#   bash infra/microvm/wsl_setup_ubuntu24.sh
#
# REQUIREMENTS:
#   - Ubuntu 24.04 on WSL2
#   - sudo access (for firecracker binary installation)
#   - x86_64 architecture
#
# WHAT THIS SCRIPT DOES:
#   1. Detects WSL environment
#   2. Installs required packages (curl, jq, tar, etc.)
#   3. Downloads and installs Firecracker v1.7.0 to /usr/local/bin
#   4. Downloads kernel and rootfs to ~/.octolab/firecracker
#   5. Creates microVM state directory at ~/.octolab/microvm
#   6. Updates backend/.env.local with microVM configuration
#   7. Runs doctor check to verify setup
#
# ROLLBACK:
#   See infra/microvm/README-wsl.md for rollback instructions
#
# SECURITY:
#   - Never logs secrets
#   - Uses shell=False equivalent (no eval/source of untrusted input)
#   - Downloads from verified sources with checksums where available
#
# ============================================================================

set -euo pipefail
IFS=$'\n\t'

# ===========================================================================
# Configuration
# ===========================================================================

FIRECRACKER_VERSION="v1.7.0"
FIRECRACKER_ARCH="x86_64"

# Firecracker hello kernel/rootfs (stable, always available)
# These are minimal images for verification - production uses custom images
DEFAULT_KERNEL_URL="https://s3.amazonaws.com/spec.ccfc.min/img/hello/kernel/hello-vmlinux.bin"
DEFAULT_ROOTFS_URL="https://s3.amazonaws.com/spec.ccfc.min/img/hello/fsfiles/hello-rootfs.ext4"

# Allow overriding via environment
KERNEL_URL="${OCTOLAB_KERNEL_URL:-${DEFAULT_KERNEL_URL}}"
ROOTFS_URL="${OCTOLAB_ROOTFS_URL:-${DEFAULT_ROOTFS_URL}}"

# Local paths (system-owned, requires sudo)
OCTOLAB_BASE_DIR="/var/lib/octolab"
FIRECRACKER_DIR="${OCTOLAB_BASE_DIR}/firecracker"
MICROVM_STATE_DIR="${OCTOLAB_BASE_DIR}/microvm"
KERNEL_PATH="${FIRECRACKER_DIR}/vmlinux"
ROOTFS_PATH="${FIRECRACKER_DIR}/rootfs.ext4"

# Backend env file
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_LOCAL="${REPO_ROOT}/backend/.env.local"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ===========================================================================
# Helper Functions
# ===========================================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

# Check if running on WSL
is_wsl() {
    if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
        return 0
    fi
    if grep -qi "microsoft" /proc/version 2>/dev/null; then
        return 0
    fi
    if [[ -n "${WSL_INTEROP:-}" ]]; then
        return 0
    fi
    return 1
}

# Check architecture
check_architecture() {
    local arch
    arch="$(uname -m)"
    if [[ "${arch}" != "x86_64" ]]; then
        log_error "Unsupported architecture: ${arch}"
        log_error "Firecracker on WSL currently only supports x86_64"
        exit 1
    fi
}

# Check sudo availability
check_sudo() {
    if ! command -v sudo &>/dev/null; then
        log_error "sudo is not available"
        log_error "Please install sudo or run as root"
        exit 1
    fi
    if ! sudo -n true 2>/dev/null; then
        log_info "sudo access required. You may be prompted for your password."
    fi
}

# ===========================================================================
# Installation Functions
# ===========================================================================

install_packages() {
    log_info "Installing required packages..."

    local packages=(curl jq tar ca-certificates util-linux iptables wget)

    # Check which packages need installation
    local to_install=()
    for pkg in "${packages[@]}"; do
        if ! dpkg -s "${pkg}" &>/dev/null; then
            to_install+=("${pkg}")
        fi
    done

    if [[ ${#to_install[@]} -eq 0 ]]; then
        log_success "All required packages already installed"
        return 0
    fi

    log_info "Installing: ${to_install[*]}"
    sudo apt-get update -qq
    sudo apt-get install -y -qq "${to_install[@]}"
    log_success "Packages installed"
}

install_firecracker() {
    log_info "Checking Firecracker installation..."

    local fc_bin="/usr/local/bin/firecracker"

    # Check if already installed with correct version
    if [[ -x "${fc_bin}" ]]; then
        local current_version
        current_version="$("${fc_bin}" --version 2>/dev/null | head -1 || echo "")"
        if [[ "${current_version}" == *"${FIRECRACKER_VERSION#v}"* ]]; then
            log_success "Firecracker ${FIRECRACKER_VERSION} already installed"
            return 0
        fi
        log_info "Updating Firecracker to ${FIRECRACKER_VERSION}..."
    fi

    log_info "Downloading Firecracker ${FIRECRACKER_VERSION}..."

    local release_url="https://github.com/firecracker-microvm/firecracker/releases/download/${FIRECRACKER_VERSION}/firecracker-${FIRECRACKER_VERSION}-${FIRECRACKER_ARCH}.tgz"
    local tmp_dir
    tmp_dir="$(mktemp -d)"

    # Download and extract
    curl -fsSL "${release_url}" -o "${tmp_dir}/firecracker.tgz"
    tar -xzf "${tmp_dir}/firecracker.tgz" -C "${tmp_dir}"

    # Find the firecracker binary (inside release-*/firecracker-*-x86_64 directory)
    local fc_release_bin
    fc_release_bin="$(find "${tmp_dir}" -name "firecracker-${FIRECRACKER_VERSION}-${FIRECRACKER_ARCH}" -type f | head -1)"

    if [[ -z "${fc_release_bin}" || ! -f "${fc_release_bin}" ]]; then
        log_error "Firecracker binary not found in release archive"
        rm -rf "${tmp_dir}"
        exit 1
    fi

    # Install
    sudo install -m 0755 "${fc_release_bin}" "${fc_bin}"

    # Also install jailer if present (optional for WSL)
    local jailer_bin
    jailer_bin="$(find "${tmp_dir}" -name "jailer-${FIRECRACKER_VERSION}-${FIRECRACKER_ARCH}" -type f | head -1)"
    if [[ -n "${jailer_bin}" && -f "${jailer_bin}" ]]; then
        sudo install -m 0755 "${jailer_bin}" "/usr/local/bin/jailer"
        log_success "Jailer installed (optional for WSL dev)"
    fi

    # Cleanup
    rm -rf "${tmp_dir}"

    # Verify
    if ! "${fc_bin}" --version &>/dev/null; then
        log_error "Firecracker installation verification failed"
        exit 1
    fi

    log_success "Firecracker ${FIRECRACKER_VERSION} installed to ${fc_bin}"
}

download_kernel_rootfs() {
    log_info "Setting up kernel and rootfs..."

    # Create directories (requires sudo since /var/lib/octolab is system-owned)
    sudo mkdir -p "${FIRECRACKER_DIR}"
    sudo mkdir -p "${MICROVM_STATE_DIR}"
    sudo chmod 755 "${OCTOLAB_BASE_DIR}"
    sudo chmod 755 "${FIRECRACKER_DIR}"
    sudo chmod 700 "${MICROVM_STATE_DIR}"
    # Make state dir writable by current user for dev
    sudo chown "${USER}:${USER}" "${MICROVM_STATE_DIR}"

    # Download kernel if not exists or force refresh
    if [[ ! -f "${KERNEL_PATH}" ]]; then
        log_info "Downloading kernel..."
        sudo curl -fsSL "${KERNEL_URL}" -o "${KERNEL_PATH}"
        sudo chmod 644 "${KERNEL_PATH}"
        log_success "Kernel downloaded to ${KERNEL_PATH}"
    else
        log_success "Kernel already exists at ${KERNEL_PATH}"
    fi

    # Download rootfs if not exists
    if [[ ! -f "${ROOTFS_PATH}" ]]; then
        log_info "Downloading rootfs (this may take a while)..."
        sudo curl -fsSL "${ROOTFS_URL}" -o "${ROOTFS_PATH}"
        sudo chmod 644 "${ROOTFS_PATH}"
        log_success "Rootfs downloaded to ${ROOTFS_PATH}"
    else
        log_success "Rootfs already exists at ${ROOTFS_PATH}"
    fi
}

check_kvm() {
    log_info "Checking /dev/kvm access..."

    if [[ ! -e /dev/kvm ]]; then
        log_error "/dev/kvm does not exist"
        log_error ""
        log_error "REMEDIATION:"
        log_error "  1. Ensure WSL2 is configured for nested virtualization"
        log_error "  2. In PowerShell (Admin), create/edit: %USERPROFILE%\\.wslconfig"
        log_error "     Add:"
        log_error "       [wsl2]"
        log_error "       nestedVirtualization=true"
        log_error "  3. Restart WSL: wsl --shutdown"
        log_error "  4. Reopen your WSL terminal"
        log_error ""
        return 1
    fi

    if [[ ! -r /dev/kvm ]] || [[ ! -w /dev/kvm ]]; then
        log_warn "/dev/kvm exists but is not readable/writable"
        log_info ""
        log_info "REMEDIATION (try in order):"
        log_info ""
        log_info "  Option 1: Add user to kvm group (recommended)"
        log_info "    sudo usermod -aG kvm \$USER"
        log_info "    # Then restart your shell OR run: wsl --shutdown"
        log_info ""
        log_info "  Option 2: Dev-only workaround (NOT for production)"
        log_info "    sudo chmod 666 /dev/kvm"
        log_info "    # Note: This resets on WSL restart"
        log_info ""

        # Try to add user to kvm group
        if groups | grep -q kvm 2>/dev/null; then
            log_info "User already in kvm group. Try: wsl --shutdown and reopen terminal"
        else
            log_info "Attempting to add user to kvm group..."
            if sudo usermod -aG kvm "$USER" 2>/dev/null; then
                log_warn "Added to kvm group. You MUST restart: wsl --shutdown"
                log_warn "Then reopen your terminal and run this script again."
            fi
        fi

        return 1
    fi

    log_success "/dev/kvm is accessible"
    return 0
}

update_env_local() {
    log_info "Updating backend/.env.local..."

    local env_block_start="# BEGIN OCTOLAB_MICROVM"
    local env_block_end="# END OCTOLAB_MICROVM"

    # Create .env.local if it doesn't exist
    if [[ ! -f "${ENV_LOCAL}" ]]; then
        log_warn "${ENV_LOCAL} does not exist. Creating with microVM config only."
        log_warn "You may need to run 'make dev-up' first to generate full config."
        touch "${ENV_LOCAL}"
    fi

    # Backup existing file (in case of issues)
    cp "${ENV_LOCAL}" "${ENV_LOCAL}.bak.$$"

    # Create temp file for new content
    local temp_file
    temp_file="$(mktemp)"

    # Copy all lines EXCEPT those between BEGIN/END markers (both old and new style)
    # This preserves DATABASE_URL, SECRET_KEY, and everything outside the microVM block
    local in_block=false
    while IFS= read -r line || [[ -n "$line" ]]; do
        # Skip old-style markers too
        if [[ "$line" =~ ^#.*===.*MicroVM.*runtime ]]; then
            in_block=true
            continue
        fi
        if [[ "$line" =~ ^#.*===.*end.*MicroVM.*runtime ]]; then
            in_block=false
            continue
        fi
        # Handle new-style markers
        if [[ "$line" == *"$env_block_start"* ]] || [[ "$line" == "### BEGIN OCTOLAB MICROVM ###" ]]; then
            in_block=true
            continue
        fi
        if [[ "$line" == *"$env_block_end"* ]] || [[ "$line" == "### END OCTOLAB MICROVM ###" ]]; then
            in_block=false
            continue
        fi
        # Skip lines inside the block
        if [[ "$in_block" == "true" ]]; then
            continue
        fi
        # Keep all other lines
        echo "$line" >> "$temp_file"
    done < "${ENV_LOCAL}"

    # Ensure newline before appending block
    if [[ -s "$temp_file" ]]; then
        # Add newline if file doesn't end with one
        if [[ -n "$(tail -c1 "$temp_file")" ]]; then
            echo "" >> "$temp_file"
        fi
    fi

    # Append new microVM block
    cat >> "$temp_file" << EOF
${env_block_start}
OCTOLAB_RUNTIME=firecracker
OCTOLAB_MICROVM_KERNEL_PATH=${KERNEL_PATH}
OCTOLAB_MICROVM_ROOTFS_BASE_PATH=${ROOTFS_PATH}
OCTOLAB_MICROVM_STATE_DIR=${MICROVM_STATE_DIR}
OCTOLAB_DEV_UNSAFE_ALLOW_NO_JAILER=true
OCTOLAB_MICROVM_USE_JAILER=false
OCTOLAB_MICROVM_NETD_SOCK=/run/octolab/microvm-netd.sock
${env_block_end}
EOF

    # Move temp file to actual file
    mv "$temp_file" "${ENV_LOCAL}"

    # Remove backup on success
    rm -f "${ENV_LOCAL}.bak.$$"

    log_success "Updated ${ENV_LOCAL} with microVM configuration"
    log_info "Preserved existing configuration (DATABASE_URL, SECRET_KEY, etc.)"
}

run_doctor() {
    log_info "Running microVM doctor checks..."

    # Try to run standalone doctor via Python
    # IMPORTANT: Uses standalone microvm_doctor module that does NOT require
    # app.config/Settings (no database_url or secret_key needed)
    if command -v python3 &>/dev/null; then
        # Load environment for the doctor check
        # These are microVM-specific vars only, no secrets needed
        if [[ -f "${ENV_LOCAL}" ]]; then
            set -a
            # Only source microVM-related vars to avoid Settings validation issues
            while IFS='=' read -r key value; do
                # Skip comments and empty lines
                [[ -z "$key" || "$key" =~ ^# ]] && continue
                # Only export microVM-related vars
                case "$key" in
                    MICROVM_*|OCTOLAB_RUNTIME|DEV_UNSAFE_ALLOW_NO_JAILER|OCTOLAB_MICROVM_*|OCTOLAB_DEV_*)
                        export "${key}=${value}"
                        ;;
                esac
            done < "${ENV_LOCAL}"
            set +a
        fi

        # Run the standalone doctor module
        # This module imports ONLY stdlib, not app.config
        (cd "${REPO_ROOT}/backend" && python3 -m app.services.microvm_doctor --pretty)
        local doctor_exit=$?

        if [[ ${doctor_exit} -eq 0 ]]; then
            echo ""
            log_success "All checks passed! You can now start the backend with:"
            echo "  make dev"
            return 0
        elif [[ ${doctor_exit} -eq 2 ]]; then
            echo ""
            log_error "Fatal check(s) failed. Fix issues above before starting."
            return 1
        else
            log_error "Doctor check encountered an unexpected error."
            return 1
        fi
    else
        log_warn "Python3 not found. Skipping doctor check."
        log_info "Run 'make dev' to verify configuration."
        return 0
    fi
}

# ===========================================================================
# Main
# ===========================================================================

main() {
    echo ""
    echo "=============================================="
    echo "  OctoLab MicroVM Setup for WSL Ubuntu 24.04"
    echo "=============================================="
    echo ""

    # Detect WSL
    if is_wsl; then
        log_success "WSL environment detected"
    else
        log_warn "Not running under WSL. Script may still work on native Linux."
    fi

    # Check architecture
    check_architecture

    # Check sudo
    check_sudo

    # Install packages
    install_packages

    # Install Firecracker
    install_firecracker

    # Download kernel and rootfs
    download_kernel_rootfs

    # Check /dev/kvm (may fail but continue)
    local kvm_ok=true
    if ! check_kvm; then
        kvm_ok=false
    fi

    # Update .env.local
    update_env_local

    echo ""
    echo "=============================================="
    echo "  Setup Summary"
    echo "=============================================="
    echo ""
    log_success "Firecracker binary: /usr/local/bin/firecracker"
    log_success "Kernel: ${KERNEL_PATH}"
    log_success "Rootfs: ${ROOTFS_PATH}"
    log_success "State dir: ${MICROVM_STATE_DIR}"
    log_success "Config: ${ENV_LOCAL}"
    echo ""

    if [[ "${kvm_ok}" != "true" ]]; then
        log_warn "/dev/kvm access issue detected. See remediation above."
        log_warn "Fix KVM access, then run this script again to verify."
        exit 1
    fi

    # Check/create octolab group for netd socket access
    local group_created=false
    local user_added=false

    if ! getent group octolab &>/dev/null; then
        log_info "Creating 'octolab' group for netd socket access..."
        sudo groupadd -f octolab
        log_success "Created octolab group"
        group_created=true
    else
        log_success "Group 'octolab' already exists"
    fi

    # Add current user to octolab group
    if ! id -nG "$USER" | grep -qw octolab; then
        log_info "Adding $USER to octolab group..."
        sudo usermod -aG octolab "$USER"
        log_success "Added $USER to octolab group"
        user_added=true
    else
        log_success "User $USER already in octolab group"
    fi

    # Create netd socket directory with proper ownership
    log_info "Setting up /run/octolab directory..."
    sudo mkdir -p /run/octolab
    sudo chown root:octolab /run/octolab
    sudo chmod 750 /run/octolab
    log_success "Socket directory configured: /run/octolab (root:octolab 750)"

    # Warn about group membership requiring new session
    if [[ "$user_added" == "true" ]]; then
        echo ""
        log_warn "=============================================="
        log_warn "  GROUP MEMBERSHIP CHANGE DETECTED"
        log_warn "=============================================="
        log_warn "You were added to the 'octolab' group."
        log_warn "This change requires a new login session to take effect."
        echo ""
        log_info "For WSL, run in PowerShell:"
        echo "    wsl --terminate ${WSL_DISTRO_NAME:-Ubuntu-24.04}"
        echo "    # Then reopen your WSL terminal"
        echo ""
        log_info "Alternatively, you can run:"
        echo "    newgrp octolab"
        echo "    # This opens a new shell with the group active"
        echo ""
    fi

    echo ""
    echo "=============================================="
    echo "  Network Daemon (microvm-netd) Setup"
    echo "=============================================="
    echo ""
    log_info "The microvm-netd daemon is required for Firecracker networking."
    log_info "It creates bridge/TAP devices (requires root)."
    echo ""
    log_info "To start netd manually (recommended for WSL):"
    echo "    sudo ${REPO_ROOT}/infra/microvm/netd/run_netd.sh"
    echo ""
    log_info "Or to run in background:"
    echo "    sudo nohup ${REPO_ROOT}/infra/microvm/netd/run_netd.sh > /var/log/microvm-netd.log 2>&1 &"
    echo ""
    log_info "For systems with systemd:"
    echo "    sudo cp ${REPO_ROOT}/infra/microvm/netd/microvm-netd.service /etc/systemd/system/"
    echo "    sudo systemctl daemon-reload"
    echo "    sudo systemctl enable --now microvm-netd"
    echo ""

    # Run doctor check
    run_doctor
}

main "$@"
