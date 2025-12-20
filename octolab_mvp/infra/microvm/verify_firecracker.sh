#!/bin/bash
# =============================================================================
# Firecracker Verification Script - "Hello microVM" Boot Test
# =============================================================================
#
# Verifies Firecracker installation by booting a minimal microVM and
# confirming successful startup via the Firecracker API.
#
# This is a dev verification script - it boots a VM, verifies it starts,
# then cleans up (unless KEEP=1 is set).
#
# Usage:
#   ./verify_firecracker.sh           # Run verification, cleanup on exit
#   KEEP=1 ./verify_firecracker.sh    # Keep VM state after exit for debugging
#
# Prerequisites:
#   - Run wsl_ubuntu24_setup.sh first
#   - Or manually set:
#     OCTOLAB_MICROVM_KERNEL_PATH
#     OCTOLAB_MICROVM_ROOTFS_BASE_PATH
#     OCTOLAB_MICROVM_STATE_DIR
#
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

# ==== Configuration ====

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Load env from backend/.env.local if it exists
ENV_LOCAL="${REPO_ROOT}/backend/.env.local"
if [ -f "$ENV_LOCAL" ]; then
    # Source env file safely (export only specific vars)
    while IFS='=' read -r key value; do
        # Skip comments and empty lines
        [[ -z "$key" || "$key" =~ ^# ]] && continue
        # Only export MICROVM_* and relevant vars
        if [[ "$key" =~ ^MICROVM_ ]] || [[ "$key" =~ ^OCTOLAB_MICROVM_ ]]; then
            export "$key=$value"
        fi
    done < "$ENV_LOCAL"
fi

# Required paths (from env or defaults matching wsl_setup_ubuntu24.sh)
KERNEL_PATH="${MICROVM_KERNEL_PATH:-${OCTOLAB_MICROVM_KERNEL_PATH:-/var/lib/octolab/firecracker/vmlinux}}"
ROOTFS_PATH="${MICROVM_ROOTFS_BASE_PATH:-${OCTOLAB_MICROVM_ROOTFS_BASE_PATH:-/var/lib/octolab/firecracker/rootfs.ext4}}"
STATE_DIR="${MICROVM_STATE_DIR:-${OCTOLAB_MICROVM_STATE_DIR:-/var/lib/octolab/microvm}}"

# Firecracker binary
FC_BIN="${OCTOLAB_FIRECRACKER_BIN:-firecracker}"
if ! command -v "$FC_BIN" &>/dev/null; then
    FC_BIN="/usr/local/bin/firecracker"
fi

# VM configuration
VCPU_COUNT=1
MEM_SIZE_MIB=512
BOOT_ARGS="console=ttyS0 reboot=k panic=1 pci=off"

# Keep state on exit?
KEEP="${KEEP:-0}"

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

# Cleanup function
cleanup() {
    local exit_code=$?

    if [ "${KEEP}" = "1" ]; then
        log_info "KEEP=1 set, preserving state at: $WORKDIR"
        log_info "To cleanup manually: rm -rf $WORKDIR"
    else
        log_info "Cleaning up..."
        # Kill firecracker if running
        if [ -n "${FC_PID:-}" ] && kill -0 "$FC_PID" 2>/dev/null; then
            kill "$FC_PID" 2>/dev/null || true
            wait "$FC_PID" 2>/dev/null || true
        fi
        # Remove workdir
        if [ -n "${WORKDIR:-}" ] && [ -d "$WORKDIR" ]; then
            rm -rf "$WORKDIR"
        fi
    fi

    exit $exit_code
}

# API helper: PUT request to Firecracker API
fc_api_put() {
    local endpoint="$1"
    local data="$2"

    curl --silent --show-error --fail \
        --unix-socket "$API_SOCK" \
        -X PUT "http://localhost${endpoint}" \
        -H 'Content-Type: application/json' \
        -d "$data"
}

# API helper: PUT request expecting 204 No Content
fc_api_put_204() {
    local endpoint="$1"
    local data="$2"

    local http_code
    http_code=$(curl --silent --show-error \
        --unix-socket "$API_SOCK" \
        -X PUT "http://localhost${endpoint}" \
        -H 'Content-Type: application/json' \
        -d "$data" \
        -w "%{http_code}" \
        -o /dev/null)

    if [ "$http_code" != "204" ] && [ "$http_code" != "200" ]; then
        log_error "API call to $endpoint returned HTTP $http_code"
        return 1
    fi
    return 0
}

# ==== Validation ====

validate_prerequisites() {
    log_info "Validating prerequisites..."

    # Check /dev/kvm
    if [ ! -e /dev/kvm ]; then
        log_fatal "/dev/kvm not found. Enable KVM/nested virtualization."
    fi
    if [ ! -r /dev/kvm ] || [ ! -w /dev/kvm ]; then
        log_fatal "/dev/kvm not accessible. Check permissions."
    fi
    log_info "  /dev/kvm: OK"

    # Check firecracker binary
    if [ ! -x "$FC_BIN" ]; then
        log_fatal "Firecracker binary not found: $FC_BIN"
    fi
    local fc_version
    fc_version=$("$FC_BIN" --version 2>&1 | head -1)
    log_info "  Firecracker: $fc_version"

    # Check kernel
    if [ ! -f "$KERNEL_PATH" ]; then
        log_fatal "Kernel not found: $KERNEL_PATH"
    fi
    if [ ! -r "$KERNEL_PATH" ]; then
        log_fatal "Kernel not readable: $KERNEL_PATH"
    fi
    log_info "  Kernel: OK ($(basename "$KERNEL_PATH"))"

    # Check rootfs
    if [ ! -f "$ROOTFS_PATH" ]; then
        log_fatal "Rootfs not found: $ROOTFS_PATH"
    fi
    if [ ! -r "$ROOTFS_PATH" ]; then
        log_fatal "Rootfs not readable: $ROOTFS_PATH"
    fi
    log_info "  Rootfs: OK ($(basename "$ROOTFS_PATH"))"

    # Check state dir
    if [ ! -d "$STATE_DIR" ]; then
        log_fatal "State directory not found: $STATE_DIR"
    fi
    if [ ! -w "$STATE_DIR" ]; then
        log_fatal "State directory not writable: $STATE_DIR"
    fi
    log_info "  State dir: OK"

    log_info "All prerequisites validated"
}

# ==== Main Verification ====

run_verification() {
    # Create unique VM ID and working directory
    VM_ID="verify-$(date +%s)"
    WORKDIR="${STATE_DIR}/${VM_ID}"
    API_SOCK="${WORKDIR}/firecracker.sock"
    LOG_FILE="${WORKDIR}/firecracker.log"
    ROOTFS_COPY="${WORKDIR}/rootfs.ext4"

    log_info "Creating verification VM: $VM_ID"
    log_info "  Working directory: $WORKDIR"

    mkdir -p "$WORKDIR"

    # Copy rootfs (Firecracker modifies it)
    log_info "Copying rootfs for VM..."
    cp "$ROOTFS_PATH" "$ROOTFS_COPY"

    # Start Firecracker in background
    log_info "Starting Firecracker process..."

    "$FC_BIN" \
        --api-sock "$API_SOCK" \
        --log-path "$LOG_FILE" \
        --level Info \
        &

    FC_PID=$!
    log_info "  PID: $FC_PID"

    # Wait for API socket
    log_info "Waiting for API socket..."
    local retries=30
    while [ ! -S "$API_SOCK" ] && [ $retries -gt 0 ]; do
        sleep 0.1
        retries=$((retries - 1))
    done

    if [ ! -S "$API_SOCK" ]; then
        log_fatal "Firecracker API socket did not appear"
    fi
    log_info "  API socket ready"

    # Configure machine
    log_info "Configuring VM..."

    # Machine config
    fc_api_put_204 "/machine-config" "{
        \"vcpu_count\": ${VCPU_COUNT},
        \"mem_size_mib\": ${MEM_SIZE_MIB},
        \"ht_enabled\": false
    }" || log_fatal "Failed to configure machine"
    log_info "  Machine config: OK"

    # Boot source
    fc_api_put_204 "/boot-source" "{
        \"kernel_image_path\": \"${KERNEL_PATH}\",
        \"boot_args\": \"${BOOT_ARGS}\"
    }" || log_fatal "Failed to configure boot source"
    log_info "  Boot source: OK"

    # Root drive
    fc_api_put_204 "/drives/rootfs" "{
        \"drive_id\": \"rootfs\",
        \"path_on_host\": \"${ROOTFS_COPY}\",
        \"is_root_device\": true,
        \"is_read_only\": false
    }" || log_fatal "Failed to configure root drive"
    log_info "  Root drive: OK"

    # Start the VM
    log_info "Starting VM instance..."

    fc_api_put_204 "/actions" "{
        \"action_type\": \"InstanceStart\"
    }" || log_fatal "Failed to start VM instance"

    log_info "  InstanceStart: OK"

    # Verify process is still alive after 2 seconds
    log_info "Verifying VM is running..."
    sleep 2

    if ! kill -0 "$FC_PID" 2>/dev/null; then
        log_error "Firecracker process died after start"
        log_error "Last 20 lines of log:"
        tail -20 "$LOG_FILE" 2>/dev/null || true
        log_fatal "VM failed to stay running"
    fi
    log_info "  VM process alive: OK"

    # Check log for boot progress
    if grep -q "Guest-boot-time" "$LOG_FILE" 2>/dev/null || \
       grep -q "Running" "$LOG_FILE" 2>/dev/null || \
       grep -q "vmm:Firecracker" "$LOG_FILE" 2>/dev/null; then
        log_info "  Boot indicators found in log: OK"
    else
        log_warn "  No explicit boot success indicators in log (may still be booting)"
    fi

    # Print success
    echo ""
    echo "============================================================"
    echo "  Firecracker Verification PASSED"
    echo "============================================================"
    echo ""
    echo "  VM ID:      $VM_ID"
    echo "  PID:        $FC_PID"
    echo "  API Socket: $API_SOCK"
    echo "  Log File:   $LOG_FILE"
    echo ""
    if [ "${KEEP}" = "1" ]; then
        echo "  KEEP=1 set - VM will continue running"
        echo "  To stop: kill $FC_PID"
        echo "  To cleanup: rm -rf $WORKDIR"
    else
        echo "  VM will be stopped and cleaned up"
    fi
    echo ""

    # Stop VM for cleanup (unless KEEP=1)
    if [ "${KEEP}" != "1" ]; then
        log_info "Stopping VM..."
        kill "$FC_PID" 2>/dev/null || true
        wait "$FC_PID" 2>/dev/null || true
        FC_PID=""  # Clear so cleanup doesn't try again
    fi

    return 0
}

# ==== Main ====

main() {
    echo ""
    echo "============================================================"
    echo "  Firecracker Verification - Hello microVM"
    echo "============================================================"
    echo ""

    # Set up cleanup trap
    trap cleanup EXIT

    # Validate prerequisites
    validate_prerequisites

    # Run verification
    run_verification

    log_info "Verification complete!"
}

main "$@"
