#!/bin/bash
# OctoLab Deployment Progress Checker
# ====================================
# Run this to see what's done and what's next.
# Works on both WSL (local dev) and cloud server.

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
warn() { echo -e "  ${YELLOW}?${NC} $1"; }
info() { echo -e "${BLUE}===${NC} $1 ${BLUE}===${NC}"; }

ISSUES=()

# =============================================================================
info "Phase 1: Server Prerequisites"
# =============================================================================

# Docker
if command -v docker &>/dev/null; then
    pass "Docker installed: $(docker --version | head -1)"
else
    fail "Docker not installed"
    ISSUES+=("Install Docker: sudo apt install docker.io")
fi

# Docker Compose
if docker compose version &>/dev/null 2>&1; then
    pass "Docker Compose installed"
else
    fail "Docker Compose not installed"
    ISSUES+=("Install: sudo apt install docker-compose-v2")
fi

# User groups
if groups | grep -q docker; then
    pass "User in docker group"
else
    fail "User not in docker group"
    ISSUES+=("Run: sudo usermod -aG docker \$USER && logout")
fi

if groups | grep -q kvm; then
    pass "User in kvm group"
else
    warn "User not in kvm group (needed for Firecracker)"
    ISSUES+=("Run: sudo usermod -aG kvm \$USER && logout")
fi

# =============================================================================
info "Phase 2: Firecracker Assets"
# =============================================================================

# Kernel
if [[ -f /var/lib/octolab/firecracker/vmlinux ]]; then
    pass "Kernel found: $(ls -lh /var/lib/octolab/firecracker/vmlinux | awk '{print $5}')"
else
    fail "Kernel not found at /var/lib/octolab/firecracker/vmlinux"
    ISSUES+=("Transfer kernel from WSL")
fi

# Rootfs
if [[ -f /var/lib/octolab/firecracker/rootfs.ext4 ]]; then
    pass "Rootfs found: $(ls -lh /var/lib/octolab/firecracker/rootfs.ext4 | awk '{print $5}')"
else
    fail "Rootfs not found at /var/lib/octolab/firecracker/rootfs.ext4"
    ISSUES+=("Transfer rootfs from WSL")
fi

# Firecracker binary
if command -v firecracker &>/dev/null; then
    pass "Firecracker: $(firecracker --version 2>&1 | head -1)"
else
    fail "Firecracker not installed"
    ISSUES+=("Install Firecracker (see deploy docs)")
fi

# vsock
if [[ -e /dev/vhost-vsock ]]; then
    pass "/dev/vhost-vsock exists"
else
    fail "/dev/vhost-vsock not found"
    ISSUES+=("Run: sudo modprobe vhost_vsock")
fi

# KVM
if [[ -e /dev/kvm ]]; then
    pass "/dev/kvm exists"
else
    fail "/dev/kvm not found (KVM not available)"
    ISSUES+=("Enable nested virtualization or use bare metal")
fi

# =============================================================================
info "Phase 3: Backend"
# =============================================================================

BACKEND_DIR="${HOME}/octolab_mvp/backend"
if [[ -d "$BACKEND_DIR" ]]; then
    pass "Backend directory exists"
    
    if [[ -d "$BACKEND_DIR/.venv" ]]; then
        pass "Python venv exists"
    else
        fail "Python venv not created"
        ISSUES+=("Run: cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -e .[dev]")
    fi
    
    if [[ -f "$BACKEND_DIR/.env" ]]; then
        pass "Environment file exists"
    else
        fail "No backend/.env found"
        ISSUES+=("Copy and configure: cp backend/.env.example backend/.env")
    fi
else
    fail "Backend directory not found"
    ISSUES+=("Rsync codebase from WSL")
fi

# =============================================================================
info "Phase 4: Frontend"
# =============================================================================

FRONTEND_DIR="${HOME}/octolab_mvp/frontend"
if [[ -d "$FRONTEND_DIR" ]]; then
    pass "Frontend directory exists"
    
    if [[ -d "$FRONTEND_DIR/node_modules" ]]; then
        pass "node_modules exists"
    else
        warn "node_modules not installed"
        ISSUES+=("Run: cd frontend && npm install")
    fi
    
    if [[ -d "$FRONTEND_DIR/dist" ]]; then
        pass "Frontend built (dist/ exists)"
    else
        warn "Frontend not built"
        ISSUES+=("Run: cd frontend && npm run build")
    fi
else
    fail "Frontend directory not found"
fi

# =============================================================================
info "Phase 5: Services"
# =============================================================================

# netd socket
if [[ -S /run/octolab/microvm-netd.sock ]]; then
    pass "netd socket exists"
else
    warn "netd socket not running"
    ISSUES+=("Start netd: sudo python3 infra/microvm/netd/microvm_netd.py --socket-path /run/octolab/microvm-netd.sock --group octolab")
fi

# Docker services
if docker ps 2>/dev/null | grep -q octolab; then
    pass "Docker containers running"
    docker ps --format "table {{.Names}}\t{{.Status}}" | grep octolab || true
else
    warn "No octolab Docker containers running"
    ISSUES+=("Run: ./deploy.sh")
fi

# Backend health
if curl -sf http://localhost:8000/health &>/dev/null; then
    pass "Backend responding at localhost:8000"
else
    warn "Backend not responding"
fi

# Frontend
if curl -sf http://localhost/ &>/dev/null; then
    pass "Frontend responding at localhost:80"
else
    warn "Frontend not responding"
fi

# =============================================================================
info "Summary"
# =============================================================================

echo ""
if [[ ${#ISSUES[@]} -eq 0 ]]; then
    echo -e "${GREEN}All checks passed! Ready to test.${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Test: curl http://localhost:8000/health"
    echo "  2. Smoke test: ./infra/octolabctl/octolabctl.sh smoke"
    echo "  3. Access UI: http://localhost/ or https://dev.cyberoctopusvn.com"
else
    echo -e "${YELLOW}Issues found (${#ISSUES[@]}):${NC}"
    echo ""
    for i in "${!ISSUES[@]}"; do
        echo "  $((i+1)). ${ISSUES[$i]}"
    done
    echo ""
    echo "Fix these issues and run this script again."
fi
