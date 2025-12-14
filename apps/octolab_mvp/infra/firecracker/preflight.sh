#!/bin/bash
# Firecracker preflight check script for OctoLab
#
# Checks system prerequisites for running Firecracker microVMs.
# Exit 0 if basic requirements met, non-zero otherwise.
#
# SECURITY: Does not run as root; only reads system state.
# Run this before attempting to use Firecracker runtime.

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=== OctoLab Firecracker Preflight Check ==="
echo ""

ERRORS=()
WARNINGS=()

# Check /dev/kvm
echo -n "Checking /dev/kvm... "
if [ -e /dev/kvm ]; then
    if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
        echo -e "${GREEN}OK (exists and accessible)${NC}"
    else
        echo -e "${RED}FAIL (exists but not accessible)${NC}"
        ERRORS+=("Cannot access /dev/kvm - check permissions or add user to kvm group")
    fi
else
    echo -e "${RED}FAIL (not found)${NC}"
    ERRORS+=("/dev/kvm not found - KVM not available")
fi

# Check if running in WSL
echo -n "Checking environment... "
if [ -f /proc/sys/fs/binfmt_misc/WSLInterop ]; then
    echo -e "${YELLOW}WSL detected${NC}"
    WARNINGS+=("Running in WSL2 - jailer may not work; set OCTOLAB_DEV_UNSAFE_ALLOW_NO_JAILER=true for POC")
else
    echo -e "${GREEN}Native Linux${NC}"
fi

# Check CPU virtualization
echo -n "Checking CPU virtualization... "
if grep -qE '(vmx|svm)' /proc/cpuinfo 2>/dev/null; then
    echo -e "${GREEN}OK (VT-x/AMD-V available)${NC}"
else
    echo -e "${RED}FAIL${NC}"
    ERRORS+=("CPU virtualization (VT-x/AMD-V) not detected")
fi

# Check for firecracker binary
echo -n "Checking firecracker binary... "
if command -v firecracker &>/dev/null; then
    FC_VERSION=$(firecracker --version 2>&1 | head -n1)
    echo -e "${GREEN}OK ($FC_VERSION)${NC}"
elif [ -x "./bin/firecracker" ]; then
    FC_VERSION=$(./bin/firecracker --version 2>&1 | head -n1)
    echo -e "${GREEN}OK (local: $FC_VERSION)${NC}"
else
    echo -e "${YELLOW}NOT FOUND${NC}"
    WARNINGS+=("firecracker binary not found - run install_firecracker.sh")
fi

# Check for jailer binary
echo -n "Checking jailer binary... "
if command -v jailer &>/dev/null; then
    JAILER_VERSION=$(jailer --version 2>&1 | head -n1)
    echo -e "${GREEN}OK ($JAILER_VERSION)${NC}"
elif [ -x "./bin/jailer" ]; then
    JAILER_VERSION=$(./bin/jailer --version 2>&1 | head -n1)
    echo -e "${GREEN}OK (local: $JAILER_VERSION)${NC}"
else
    echo -e "${YELLOW}NOT FOUND${NC}"
    WARNINGS+=("jailer binary not found - run install_firecracker.sh")
fi

# Check vsock support
echo -n "Checking vsock support... "
if [ -e /dev/vsock ]; then
    echo -e "${GREEN}OK (/dev/vsock exists)${NC}"
elif lsmod 2>/dev/null | grep -q vhost_vsock; then
    echo -e "${GREEN}OK (vhost_vsock module loaded)${NC}"
else
    echo -e "${YELLOW}UNKNOWN${NC}"
    WARNINGS+=("vsock support unclear - /dev/vsock not found, vhost_vsock not loaded")
fi

# Check cgroups
echo -n "Checking cgroups... "
if [ -d /sys/fs/cgroup ]; then
    if [ -f /sys/fs/cgroup/cgroup.controllers ]; then
        echo -e "${GREEN}OK (cgroup v2)${NC}"
    else
        echo -e "${GREEN}OK (cgroup v1)${NC}"
    fi
else
    echo -e "${YELLOW}UNKNOWN${NC}"
    WARNINGS+=("cgroups not found at /sys/fs/cgroup")
fi

# Check for kernel/rootfs artifacts
echo -n "Checking for kernel artifact... "
if [ -f "./artifacts/vmlinux" ] || [ -f "./artifacts/vmlinux.bin" ]; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${YELLOW}NOT FOUND${NC}"
    WARNINGS+=("Kernel not found in ./artifacts/ - run download_kernel_rootfs.sh")
fi

echo -n "Checking for rootfs artifact... "
if [ -f "./artifacts/rootfs.ext4" ]; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${YELLOW}NOT FOUND${NC}"
    WARNINGS+=("Rootfs not found in ./artifacts/ - run download_kernel_rootfs.sh")
fi

# Summary
echo ""
echo "=== Summary ==="

if [ ${#ERRORS[@]} -gt 0 ]; then
    echo -e "${RED}ERRORS (fatal):${NC}"
    for err in "${ERRORS[@]}"; do
        echo "  - $err"
    done
fi

if [ ${#WARNINGS[@]} -gt 0 ]; then
    echo -e "${YELLOW}WARNINGS (non-fatal):${NC}"
    for warn in "${WARNINGS[@]}"; do
        echo "  - $warn"
    done
fi

if [ ${#ERRORS[@]} -eq 0 ] && [ ${#WARNINGS[@]} -eq 0 ]; then
    echo -e "${GREEN}All checks passed!${NC}"
fi

echo ""

# Output JSON summary for programmatic use
echo "=== JSON Summary ==="
cat << EOF
{
  "has_kvm": $([ -e /dev/kvm ] && echo "true" || echo "false"),
  "can_access_kvm": $([ -r /dev/kvm ] && [ -w /dev/kvm ] && echo "true" || echo "false"),
  "is_wsl": $([ -f /proc/sys/fs/binfmt_misc/WSLInterop ] && echo "true" || echo "false"),
  "has_cpu_virt": $(grep -qE '(vmx|svm)' /proc/cpuinfo 2>/dev/null && echo "true" || echo "false"),
  "error_count": ${#ERRORS[@]},
  "warning_count": ${#WARNINGS[@]}
}
EOF

# Exit with error if there are fatal errors
if [ ${#ERRORS[@]} -gt 0 ]; then
    exit 1
fi

exit 0
