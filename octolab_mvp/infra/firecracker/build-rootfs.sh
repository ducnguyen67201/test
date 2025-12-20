#!/bin/bash
# =============================================================================
# OctoLab Firecracker Rootfs & Kernel Build Script
# =============================================================================
#
# This script builds a Debian-based rootfs with Docker for Firecracker microVMs
# and optionally downloads a compatible guest kernel.
#
# Features:
# - Debian 12 (bookworm) minimal rootfs
# - Docker CE + Docker Compose plugin
# - OctoLab guest agent (systemd service)
# - Modern 5.x kernel for container support
#
# Usage:
#   sudo ./build-rootfs.sh [options]
#
# Options:
#   --output DIR      Output directory (default: ./out)
#   --size SIZE       Rootfs size (default: 4G)
#   --with-kernel     Also download/install guest kernel
#   --deploy          Copy artifacts to /var/lib/octolab/firecracker/
#   --help            Show this help
#
# Requirements:
#   - Root privileges (debootstrap needs it)
#   - debootstrap, curl, losetup, mkfs.ext4
#
# Examples:
#   # Build rootfs only
#   sudo ./build-rootfs.sh
#
#   # Build and download kernel
#   sudo ./build-rootfs.sh --with-kernel
#
#   # Build, download kernel, and deploy to /var/lib/octolab/firecracker/
#   sudo ./build-rootfs.sh --with-kernel --deploy
#
# SECURITY:
# - Rootfs is built fresh each time (reproducible)
# - No secrets are baked into the image
# - Agent runs as root inside VM (isolated by hypervisor)
# - Token auth happens at runtime via kernel cmdline
# =============================================================================

set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${SCRIPT_DIR}/out"
ROOTFS_SIZE="4G"
DEBIAN_RELEASE="bookworm"  # Debian 12
ARCH="amd64"

# Build identification
# Generate unique build_id: short git sha + timestamp
BUILD_TIMESTAMP="$(date -u +%Y%m%d%H%M%S)"
GIT_SHA="$(cd "$SCRIPT_DIR" && git rev-parse --short HEAD 2>/dev/null || echo 'nogit')"
BUILD_ID="${GIT_SHA}-${BUILD_TIMESTAMP}"
AGENT_VERSION="1.0.0"

# Kernel configuration
# Using Firecracker CI artifacts - 5.10 LTS kernel known to work with Docker
KERNEL_VERSION="5.10.198"
KERNEL_URL="https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.6/x86_64/vmlinux-${KERNEL_VERSION}"

# Deployment paths
DEPLOY_DIR="/var/lib/octolab/firecracker"
DEPLOY_KERNEL="${DEPLOY_DIR}/vmlinux"
DEPLOY_ROOTFS="${DEPLOY_DIR}/rootfs.ext4"

# Flags
WITH_KERNEL=false
DEPLOY=false

# =============================================================================
# Parse Arguments
# =============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        --output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --size)
            ROOTFS_SIZE="$2"
            shift 2
            ;;
        --with-kernel)
            WITH_KERNEL=true
            shift
            ;;
        --deploy)
            DEPLOY=true
            shift
            ;;
        --help|-h)
            head -50 "$0" | grep -E "^#" | sed 's/^# //' | sed 's/^#//'
            exit 0
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Run with --help for usage"
            exit 1
            ;;
    esac
done

# =============================================================================
# Setup
# =============================================================================

echo "============================================"
echo "OctoLab Firecracker Image Builder"
echo "============================================"
echo ""

mkdir -p "${OUTPUT_DIR}"
ROOTFS_IMG="${OUTPUT_DIR}/rootfs.ext4"
KERNEL_IMG="${OUTPUT_DIR}/vmlinux"
MOUNT_POINT="${OUTPUT_DIR}/mnt"

echo "Configuration:"
echo "  Output directory: ${OUTPUT_DIR}"
echo "  Rootfs size: ${ROOTFS_SIZE}"
echo "  Debian release: ${DEBIAN_RELEASE}"
echo "  Architecture: ${ARCH}"
echo "  With kernel: ${WITH_KERNEL}"
echo "  Deploy to system: ${DEPLOY}"
echo ""

# Check for root
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (or with sudo)"
    echo "  Example: sudo $0 --with-kernel --deploy"
    exit 1
fi

# Check dependencies
echo "Checking dependencies..."
MISSING_DEPS=()
for cmd in debootstrap losetup mkfs.ext4 curl; do
    if ! command -v "$cmd" &>/dev/null; then
        MISSING_DEPS+=("$cmd")
    fi
done

if [[ ${#MISSING_DEPS[@]} -gt 0 ]]; then
    echo "ERROR: Missing required commands: ${MISSING_DEPS[*]}"
    echo "Install with: apt-get install debootstrap curl"
    exit 1
fi
echo "  All dependencies found"
echo ""

# =============================================================================
# Download Kernel (if requested)
# =============================================================================

if [[ "$WITH_KERNEL" == "true" ]]; then
    echo "[KERNEL] Downloading guest kernel ${KERNEL_VERSION}..."

    if [[ -f "$KERNEL_IMG" ]]; then
        echo "  Kernel already exists at ${KERNEL_IMG}"
        echo "  Verifying it's a valid ELF..."
        if file "$KERNEL_IMG" | grep -q "ELF 64-bit"; then
            echo "  Kernel is valid ELF 64-bit"
        else
            echo "  Existing kernel is invalid, re-downloading..."
            rm -f "$KERNEL_IMG"
        fi
    fi

    if [[ ! -f "$KERNEL_IMG" ]]; then
        echo "  Downloading from: ${KERNEL_URL}"
        if curl -fsSL --connect-timeout 30 --max-time 300 -o "${KERNEL_IMG}.tmp" "${KERNEL_URL}"; then
            mv "${KERNEL_IMG}.tmp" "$KERNEL_IMG"
            chmod 644 "$KERNEL_IMG"
            echo "  Downloaded successfully"
        else
            echo "ERROR: Failed to download kernel"
            rm -f "${KERNEL_IMG}.tmp"
            exit 1
        fi
    fi

    # Verify kernel
    if file "$KERNEL_IMG" | grep -q "ELF 64-bit"; then
        KERNEL_SIZE=$(du -h "$KERNEL_IMG" | cut -f1)
        echo "  Kernel: ${KERNEL_IMG} (${KERNEL_SIZE})"
    else
        echo "ERROR: Downloaded kernel is not a valid ELF binary"
        exit 1
    fi
    echo ""
fi

# =============================================================================
# Create Rootfs Image
# =============================================================================

echo "[1/7] Creating ext4 image (${ROOTFS_SIZE})..."
# Atomic output: build to .tmp, rename on success
ROOTFS_IMG_TMP="${ROOTFS_IMG}.tmp"
rm -f "${ROOTFS_IMG_TMP}" "${ROOTFS_IMG}"
truncate -s "${ROOTFS_SIZE}" "${ROOTFS_IMG_TMP}"
mkfs.ext4 -F -q "${ROOTFS_IMG_TMP}"
echo "  Created ${ROOTFS_IMG_TMP} (will rename on success)"

echo "[2/7] Mounting image..."
mkdir -p "${MOUNT_POINT}"
mount -o loop "${ROOTFS_IMG_TMP}" "${MOUNT_POINT}"

# Ensure cleanup on exit
cleanup() {
    echo ""
    echo "Cleaning up..."
    # Unmount bind mounts first
    umount "${MOUNT_POINT}/proc" 2>/dev/null || true
    umount "${MOUNT_POINT}/sys" 2>/dev/null || true
    umount "${MOUNT_POINT}/dev/pts" 2>/dev/null || true
    umount "${MOUNT_POINT}/dev" 2>/dev/null || true
    # Then the main mount
    umount "${MOUNT_POINT}" 2>/dev/null || true
    rmdir "${MOUNT_POINT}" 2>/dev/null || true
}
trap cleanup EXIT

# =============================================================================
# Bootstrap Debian
# =============================================================================

echo "[3/7] Bootstrapping Debian ${DEBIAN_RELEASE} (this takes a few minutes)..."
debootstrap \
    --arch="${ARCH}" \
    --include=systemd,systemd-sysv,dbus,ca-certificates,curl,gnupg,python3,iproute2,iptables,procps \
    "${DEBIAN_RELEASE}" \
    "${MOUNT_POINT}" \
    http://deb.debian.org/debian

echo "  Bootstrap complete"

# =============================================================================
# Configure System
# =============================================================================

echo "[4/7] Configuring system..."

# Set hostname
echo "octolab-vm" > "${MOUNT_POINT}/etc/hostname"
echo "127.0.0.1 localhost octolab-vm" > "${MOUNT_POINT}/etc/hosts"

# Configure networking - kernel handles IP via cmdline (ip=...), we just need to
# enable the interface and not run DHCP. systemd-networkd will preserve kernel IP.
mkdir -p "${MOUNT_POINT}/etc/systemd/network"
cat > "${MOUNT_POINT}/etc/systemd/network/50-eth0.network" <<'EOF'
[Match]
Name=eth0

[Network]
# IP is configured via kernel cmdline (ip=<addr>::<gw>:<mask>::eth0:none)
# This config just ensures the interface is managed and DHCP is off
DHCP=no
# Keep any IP configured by kernel
KeepConfiguration=yes
EOF

# Configure DNS
cat > "${MOUNT_POINT}/etc/resolv.conf" <<'EOF'
# DNS servers for guest VM
nameserver 8.8.8.8
nameserver 1.1.1.1
EOF

# Configure serial console for auto-login (development convenience)
mkdir -p "${MOUNT_POINT}/etc/systemd/system/serial-getty@ttyS0.service.d"
cat > "${MOUNT_POINT}/etc/systemd/system/serial-getty@ttyS0.service.d/override.conf" <<'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I 115200 linux
EOF

# Set root password (empty for dev, change in production)
chroot "${MOUNT_POINT}" passwd -d root

# Configure fstab
cat > "${MOUNT_POINT}/etc/fstab" <<'EOF'
/dev/vda / ext4 defaults,noatime 0 1
EOF

# Bind mount /dev, /proc, /sys for chroot operations
mount --bind /dev "${MOUNT_POINT}/dev"
mount --bind /proc "${MOUNT_POINT}/proc"
mount --bind /sys "${MOUNT_POINT}/sys"
mount -t devpts devpts "${MOUNT_POINT}/dev/pts" 2>/dev/null || true

# Enable essential services via chroot
chroot "${MOUNT_POINT}" systemctl enable systemd-networkd
chroot "${MOUNT_POINT}" systemctl enable serial-getty@ttyS0

echo "  System configured"

# =============================================================================
# Install Docker
# =============================================================================

echo "[5/7] Installing Docker CE..."

# Add Docker GPG key
mkdir -p "${MOUNT_POINT}/etc/apt/keyrings"
curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o "${MOUNT_POINT}/etc/apt/keyrings/docker.gpg"
chmod a+r "${MOUNT_POINT}/etc/apt/keyrings/docker.gpg"

# Add Docker repository
cat > "${MOUNT_POINT}/etc/apt/sources.list.d/docker.list" <<EOF
deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian ${DEBIAN_RELEASE} stable
EOF

# Install Docker packages
chroot "${MOUNT_POINT}" apt-get update -qq
DEBIAN_FRONTEND=noninteractive chroot "${MOUNT_POINT}" apt-get install -y -qq \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-compose-plugin \
    > /dev/null 2>&1

# Configure Docker daemon for Firecracker microVM
# Custom kernel with netfilter support enables Docker NAT for container networking
mkdir -p "${MOUNT_POINT}/etc/docker"
cat > "${MOUNT_POINT}/etc/docker/daemon.json" <<'EOF'
{
    "storage-driver": "overlay2",
    "log-driver": "json-file",
    "log-opts": {
        "max-size": "10m",
        "max-file": "3"
    },
    "live-restore": false
}
EOF

# Switch to iptables-legacy because our custom kernel has legacy netfilter
# (not nf_tables which is required by iptables-nft)
echo "  Configuring iptables-legacy..."
chroot "${MOUNT_POINT}" update-alternatives --set iptables /usr/sbin/iptables-legacy 2>/dev/null || \
    ln -sf /usr/sbin/iptables-legacy "${MOUNT_POINT}/etc/alternatives/iptables"
chroot "${MOUNT_POINT}" update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy 2>/dev/null || \
    ln -sf /usr/sbin/ip6tables-legacy "${MOUNT_POINT}/etc/alternatives/ip6tables"
ln -sf /usr/sbin/iptables-legacy-restore "${MOUNT_POINT}/etc/alternatives/iptables-restore"
ln -sf /usr/sbin/iptables-legacy-save "${MOUNT_POINT}/etc/alternatives/iptables-save"

# Mask docker.socket to disable socket activation
# Docker will create its own socket via daemon.json settings
ln -sf /dev/null "${MOUNT_POINT}/etc/systemd/system/docker.socket"

# Create systemd drop-in for docker.service
# - Removes network-online.target dependency (VMs may not have network)
# - Configures dockerd to create socket directly (not via systemd socket activation)
mkdir -p "${MOUNT_POINT}/etc/systemd/system/docker.service.d"
cat > "${MOUNT_POINT}/etc/systemd/system/docker.service.d/firecracker.conf" <<'EOF'
[Unit]
# Override for Firecracker VMs
# Remove network-online.target dependency since VMs may have no external network
After=
After=containerd.service
Wants=
Wants=containerd.service
Requires=

[Service]
# Override ExecStart to create socket directly (not using systemd socket activation)
ExecStart=
ExecStart=/usr/bin/dockerd -H unix:///var/run/docker.sock --containerd=/run/containerd/containerd.sock
EOF

# Enable Docker and containerd services
chroot "${MOUNT_POINT}" systemctl enable docker.service
chroot "${MOUNT_POINT}" systemctl enable containerd.service

# Verify installation
DOCKER_VERSION=$(chroot "${MOUNT_POINT}" docker --version 2>/dev/null || echo "unknown")
COMPOSE_VERSION=$(chroot "${MOUNT_POINT}" docker compose version 2>/dev/null || echo "unknown")
echo "  Docker: ${DOCKER_VERSION}"
echo "  Compose: ${COMPOSE_VERSION}"

# =============================================================================
# Pre-bake OctoBox Docker Image
# =============================================================================
# Build OctoBox on HOST Docker, save to tarball, copy into rootfs.
# This eliminates the need for apt-get inside VMs during compose_up.

echo "[6/8] Pre-baking OctoBox Docker image..."

# Find OctoBox source directory (relative to repo root)
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OCTOBOX_DIR="${REPO_ROOT}/images/octobox-beta"

if [[ ! -d "$OCTOBOX_DIR" ]]; then
    echo "  WARNING: OctoBox directory not found at ${OCTOBOX_DIR}"
    echo "  Skipping pre-bake (OctoBox will be built on first lab)"
else
    # Build OctoBox image on HOST Docker
    echo "  Building OctoBox image on host Docker..."
    if docker build -t octolab/octobox:latest "$OCTOBOX_DIR" > /dev/null 2>&1; then
        echo "  OctoBox image built successfully"

        # Create directories for pre-baked images and scripts
        mkdir -p "${MOUNT_POINT}/var/lib/octolab/images"
        mkdir -p "${MOUNT_POINT}/opt/octolab"

        # Save image to tarball (gzipped)
        echo "  Saving OctoBox image to tarball..."
        docker save octolab/octobox:latest | gzip > "${MOUNT_POINT}/var/lib/octolab/images/octobox.tar.gz"
        TARBALL_SIZE=$(du -h "${MOUNT_POINT}/var/lib/octolab/images/octobox.tar.gz" | cut -f1)
        echo "  Saved: /var/lib/octolab/images/octobox.tar.gz (${TARBALL_SIZE})"

        # Create script to load image on first boot
        cat > "${MOUNT_POINT}/opt/octolab/load-images.sh" <<'LOADEOF'
#!/bin/bash
# Load pre-baked Docker images on first boot
# This script runs once via systemd and loads saved images into Docker

set -e

IMAGES_DIR="/var/lib/octolab/images"
LOADED_MARKER="/var/lib/octolab/.images-loaded"

# Skip if already loaded
if [[ -f "$LOADED_MARKER" ]]; then
    echo "Images already loaded, skipping"
    exit 0
fi

# Wait for Docker to be ready
echo "Waiting for Docker daemon..."
for i in {1..60}; do
    if docker info > /dev/null 2>&1; then
        echo "Docker is ready"
        break
    fi
    sleep 1
done

if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker not ready after 60s"
    exit 1
fi

# Load OctoBox image
if [[ -f "$IMAGES_DIR/octobox.tar.gz" ]]; then
    echo "Loading OctoBox image..."
    if docker load < "$IMAGES_DIR/octobox.tar.gz"; then
        echo "OctoBox image loaded successfully"
        rm -f "$IMAGES_DIR/octobox.tar.gz"
    else
        echo "WARNING: Failed to load OctoBox image"
    fi
fi

# Mark as loaded
touch "$LOADED_MARKER"
echo "Pre-baked images loaded"
LOADEOF
        chmod 755 "${MOUNT_POINT}/opt/octolab/load-images.sh"

        # Create systemd service to load images (runs in parallel with agent)
        # NOTE: No Before=octolab-agent.service - agent starts immediately,
        # images load in background. Agent doesn't need Docker until compose_up.
        cat > "${MOUNT_POINT}/etc/systemd/system/octolab-load-images.service" <<'SVCEOF'
[Unit]
Description=Load pre-baked Docker images
Documentation=https://github.com/octolab/octolab
After=docker.service
ConditionPathExists=!/var/lib/octolab/.images-loaded

[Service]
Type=oneshot
ExecStart=/opt/octolab/load-images.sh
RemainAfterExit=yes
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=multi-user.target
SVCEOF

        # Enable the load-images service
        ln -sf /etc/systemd/system/octolab-load-images.service \
            "${MOUNT_POINT}/etc/systemd/system/multi-user.target.wants/octolab-load-images.service"

        echo "  Pre-bake complete: OctoBox will load on first boot"
    else
        echo "  WARNING: Failed to build OctoBox image"
        echo "  OctoBox will be built on first lab (slower)"
    fi
fi

# =============================================================================
# Install Guest Agent
# =============================================================================

echo "[7/8] Installing OctoLab guest agent..."

# Create directories
mkdir -p "${MOUNT_POINT}/opt/octolab/project"
mkdir -p "${MOUNT_POINT}/var/log/octolab"

# Copy agent
AGENT_SOURCE="${SCRIPT_DIR}/guest-agent/agent.py"
if [[ ! -f "$AGENT_SOURCE" ]]; then
    echo "ERROR: Guest agent not found at ${AGENT_SOURCE}"
    exit 1
fi

cp "${AGENT_SOURCE}" "${MOUNT_POINT}/opt/octolab/agent.py"
chmod 755 "${MOUNT_POINT}/opt/octolab/agent.py"

# Create systemd service for agent
# NOTE: Agent starts immediately after basic networking - does NOT wait for Docker.
# The agent uses its internal wait_for_docker() when handling compose commands.
# This allows the backend to ping the agent immediately after boot, while Docker
# starts in parallel. Docker readiness is only required for compose_up/compose_down.
cat > "${MOUNT_POINT}/etc/systemd/system/octolab-agent.service" <<'EOF'
[Unit]
Description=OctoLab Guest Agent
Documentation=https://github.com/octolab/octolab
After=network.target
# Docker dependency removed: agent can start immediately and wait for Docker
# internally via wait_for_docker() when handling compose commands

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/octolab/agent.py
Restart=always
RestartSec=3
StandardOutput=journal+console
StandardError=journal+console
# Environment can be overridden via kernel cmdline or drop-in
Environment=OCTOLAB_VM_DOCKER_TIMEOUT=60

[Install]
WantedBy=multi-user.target
EOF

# Enable agent service
mkdir -p "${MOUNT_POINT}/etc/systemd/system/multi-user.target.wants"
ln -sf /etc/systemd/system/octolab-agent.service \
    "${MOUNT_POINT}/etc/systemd/system/multi-user.target.wants/octolab-agent.service"

# Create build metadata (JSON format for agent to read)
# This is the single source of truth for rootfs identity
cat > "${MOUNT_POINT}/etc/octolab-build.json" <<EOF
{
    "build_id": "${BUILD_ID}",
    "agent_version": "${AGENT_VERSION}",
    "build_date": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
    "debian_release": "${DEBIAN_RELEASE}",
    "git_sha": "${GIT_SHA}"
}
EOF
echo "  Build metadata: build_id=${BUILD_ID}, agent_version=${AGENT_VERSION}"

echo "  Agent installed and enabled"

# =============================================================================
# Cleanup
# =============================================================================

echo "[8/8] Cleaning up..."

# Clean apt cache to reduce image size
chroot "${MOUNT_POINT}" apt-get clean
rm -rf "${MOUNT_POINT}/var/lib/apt/lists/"*
rm -rf "${MOUNT_POINT}/var/cache/apt/archives/"*

# Remove machine-id (will be regenerated on first boot)
rm -f "${MOUNT_POINT}/etc/machine-id"
touch "${MOUNT_POINT}/etc/machine-id"

# Clear logs
rm -rf "${MOUNT_POINT}/var/log/"*.log
rm -rf "${MOUNT_POINT}/var/log/"*.gz

# Unmount bind mounts
umount "${MOUNT_POINT}/proc" 2>/dev/null || true
umount "${MOUNT_POINT}/sys" 2>/dev/null || true
umount "${MOUNT_POINT}/dev/pts" 2>/dev/null || true
umount "${MOUNT_POINT}/dev" 2>/dev/null || true

# Get final size before unmounting main rootfs
ROOTFS_SIZE_FINAL=$(du -h "${ROOTFS_IMG_TMP}" | cut -f1)

# Unmount main rootfs (trap will handle any remaining cleanup)
sync
umount "${MOUNT_POINT}" 2>/dev/null || true
rmdir "${MOUNT_POINT}" 2>/dev/null || true

# Atomic rename: .tmp -> final (only on success)
mv "${ROOTFS_IMG_TMP}" "${ROOTFS_IMG}"
echo "  Atomic rename: ${ROOTFS_IMG_TMP} -> ${ROOTFS_IMG}"

echo ""
echo "============================================"
echo "Rootfs build complete!"
echo "============================================"
echo ""
echo "Build ID: ${BUILD_ID}"
echo ""
echo "Artifacts:"
echo "  Rootfs: ${ROOTFS_IMG} (${ROOTFS_SIZE_FINAL})"
if [[ "$WITH_KERNEL" == "true" ]] && [[ -f "$KERNEL_IMG" ]]; then
    KERNEL_SIZE_FINAL=$(du -h "$KERNEL_IMG" | cut -f1)
    echo "  Kernel: ${KERNEL_IMG} (${KERNEL_SIZE_FINAL}, v${KERNEL_VERSION})"
fi

# =============================================================================
# Deploy (if requested)
# =============================================================================

if [[ "$DEPLOY" == "true" ]]; then
    echo ""
    echo "Deploying to ${DEPLOY_DIR}..."

    # Create deployment directory
    mkdir -p "${DEPLOY_DIR}"

    # Deploy rootfs (atomic: copy to .tmp, then rename)
    echo "  Copying rootfs..."
    cp -f "${ROOTFS_IMG}" "${DEPLOY_ROOTFS}.tmp"
    chmod 644 "${DEPLOY_ROOTFS}.tmp"
    chown root:root "${DEPLOY_ROOTFS}.tmp"
    mv -f "${DEPLOY_ROOTFS}.tmp" "${DEPLOY_ROOTFS}"

    # Deploy kernel if built (atomic: copy to .tmp, then rename)
    if [[ "$WITH_KERNEL" == "true" ]] && [[ -f "$KERNEL_IMG" ]]; then
        echo "  Copying kernel..."
        cp -f "$KERNEL_IMG" "${DEPLOY_KERNEL}.tmp"
        chmod 644 "${DEPLOY_KERNEL}.tmp"
        chown root:root "${DEPLOY_KERNEL}.tmp"
        mv -f "${DEPLOY_KERNEL}.tmp" "${DEPLOY_KERNEL}"
    fi

    # Set group ownership for octolab group if it exists
    if getent group octolab &>/dev/null; then
        chown root:octolab "${DEPLOY_DIR}"
        chmod 750 "${DEPLOY_DIR}"
        chown root:octolab "${DEPLOY_ROOTFS}"
        if [[ -f "${DEPLOY_KERNEL}" ]]; then
            chown root:octolab "${DEPLOY_KERNEL}"
        fi
    fi

    echo ""
    echo "Deployed to:"
    echo "  Kernel: ${DEPLOY_KERNEL}"
    echo "  Rootfs: ${DEPLOY_ROOTFS}"
    echo "  Build ID: ${BUILD_ID}"
fi

echo ""
echo "============================================"
echo "Next steps:"
echo "============================================"
if [[ "$DEPLOY" != "true" ]]; then
    echo "  1. Deploy with: sudo $0 --with-kernel --deploy"
    echo "  2. Or manually copy to ${DEPLOY_DIR}"
fi
echo "  3. Start netd: sudo octolabctl netd start"
echo "  4. Run smoke test: sudo octolabctl smoke"
echo "  5. Enable runtime: octolabctl enable-runtime firecracker"
echo ""
