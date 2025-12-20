# OctoLab Firecracker MicroVM Infrastructure

This directory contains the infrastructure for running OctoLab labs inside Firecracker microVMs.

## Quick Start (WSL/Dev)

```bash
# 1. Install Firecracker binary
./infra/firecracker/bootstrap_wsl_dev.sh

# 2. Download kernel and rootfs
./infra/firecracker/download_hello_assets.sh

# 3. Add to backend/.env.local (use paths printed by scripts)
cat >> backend/.env.local << 'EOF'
OCTOLAB_FIRECRACKER_BIN=/home/$USER/.local/bin/firecracker
OCTOLAB_MICROVM_KERNEL_PATH=/path/to/repo/.octolab/firecracker/vmlinux
OCTOLAB_MICROVM_ROOTFS_BASE_PATH=/path/to/repo/.octolab/firecracker/hello-rootfs.ext4
OCTOLAB_MICROVM_STATE_DIR=/path/to/repo/.octolab/microvm-state
OCTOLAB_DEV_UNSAFE_ALLOW_NO_JAILER=true
EOF

# 4. Restart backend
make dev

# 5. Check doctor (Admin page or curl)
curl http://localhost:8000/admin/microvm/doctor -H "Authorization: Bearer $TOKEN"

# 6. Run smoke test
curl -X POST http://localhost:8000/admin/microvm/smoke -H "Authorization: Bearer $TOKEN"
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ Host                                                             │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ OctoLab Backend                                              ││
│  │  - runtime_selector.py (admin toggle)                        ││
│  │  - firecracker_runtime.py                                    ││
│  │  - firecracker_manager.py (VM lifecycle, networking)         ││
│  └──────────────────────────────────────────────────────────────┘│
│                          │                                       │
│                          │ vsock                                 │
│                          ▼                                       │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ Firecracker MicroVM                                          ││
│  │  - kernel (vmlinux)                                          ││
│  │  - rootfs.ext4 (Debian + Docker)                             ││
│  │  - Guest Agent (vsock listener)                              ││
│  │                                                               ││
│  │  ┌──────────────────────────────────────────────────────────┐││
│  │  │ Docker (inside VM)                                       │││
│  │  │  - octobox container                                     │││
│  │  │  - target-web container                                  │││
│  │  │  - lab-gateway container                                 │││
│  │  └──────────────────────────────────────────────────────────┘││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  Port forwarding: 127.0.0.1:<host_port> → <guest_ip>:6080       │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### Guest Agent (`guest-agent/agent.py`)

Python agent that runs inside the microVM and handles:
- **ping**: Health check
- **upload_project**: Receive compose project as base64 tar.gz
- **compose_up**: Start the lab stack inside the VM
- **compose_down**: Tear down the lab stack
- **status**: Get container status

Communication is via vsock (no network required for control plane).

### Rootfs Build Script (`build-rootfs.sh`)

Creates a Debian-based ext4 rootfs with:
- Docker CE
- Docker Compose plugin
- Guest agent (systemd service)
- Minimal system packages

Usage:
```bash
sudo ./build-rootfs.sh --output out/rootfs.ext4 --size 4G
```

## Prerequisites

### Kernel

You need a Linux kernel built for Firecracker. Options:

1. **Download pre-built kernel**:
   ```bash
   # From Firecracker releases
   curl -LO https://github.com/firecracker-microvm/firecracker/releases/download/v1.7.0/firecracker-v1.7.0-x86_64.tgz
   tar xzf firecracker-v1.7.0-x86_64.tgz
   # Use the vmlinux file
   ```

2. **Build from source**:
   ```bash
   # Clone Firecracker repo
   git clone https://github.com/firecracker-microvm/firecracker.git
   cd firecracker
   # Build kernel
   ./tools/devtool build_kernel
   # Kernel at build/kernel/linux-*/vmlinux
   ```

3. **On WSL2 Ubuntu**:
   WSL2 typically has KVM enabled. You may need to:
   ```bash
   # Check KVM access
   ls -la /dev/kvm

   # Add user to kvm group
   sudo usermod -aG kvm $USER

   # Download Firecracker binaries
   RELEASE_URL="https://github.com/firecracker-microvm/firecracker/releases"
   LATEST=$(curl -fsSLI -o /dev/null -w %{url_effective} ${RELEASE_URL}/latest | awk -F'/' '{print $NF}')
   curl -LO ${RELEASE_URL}/download/${LATEST}/firecracker-${LATEST}-x86_64.tgz
   tar xzf firecracker-${LATEST}-x86_64.tgz
   sudo mv release-${LATEST}-x86_64/firecracker-${LATEST}-x86_64 /usr/local/bin/firecracker
   ```

### Rootfs

Build the rootfs using the provided script:
```bash
sudo ./build-rootfs.sh
```

This creates `out/rootfs.ext4` which contains:
- Debian 12 (bookworm) minimal
- Docker CE + Docker Compose plugin
- Guest agent service

## Configuration

Set these environment variables for the backend:

```bash
# Required
OCTOLAB_MICROVM_KERNEL_PATH=/path/to/vmlinux
OCTOLAB_MICROVM_ROOTFS_BASE_PATH=/path/to/rootfs.ext4
OCTOLAB_MICROVM_STATE_DIR=/var/lib/octolab/microvm

# Optional
OCTOLAB_MICROVM_VSOCK_PORT=5000
OCTOLAB_MICROVM_BOOT_TIMEOUT_SECS=30
OCTOLAB_MICROVM_VCPU_COUNT=2
OCTOLAB_MICROVM_MEM_SIZE_MIB=1024

# Development (WSL2)
OCTOLAB_DEV_UNSAFE_ALLOW_NO_JAILER=true
```

## Admin Operations

### Enable Firecracker Runtime

1. **Check doctor**:
   ```bash
   curl -X GET http://localhost:8000/admin/microvm/doctor \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```

2. **Run smoke test**:
   ```bash
   curl -X POST http://localhost:8000/admin/microvm/smoke \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"enable_for_new_labs": true}'
   ```

3. **Enable manually**:
   ```bash
   curl -X POST http://localhost:8000/admin/runtime \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"override": "firecracker"}'
   ```

### Disable Firecracker Runtime

```bash
curl -X POST http://localhost:8000/admin/runtime \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"override": null}'
```

## Troubleshooting

### Check KVM Access
```bash
# Should show /dev/kvm exists
ls -la /dev/kvm

# Try opening it
cat /dev/kvm 2>&1 | head -1
# Expected: "cat: /dev/kvm: Invalid argument" (means access OK)
# Bad: "Permission denied" (add user to kvm group)
```

### Check Firecracker Version
```bash
firecracker --version
```

### Check Jailer (optional, recommended for production)
```bash
jailer --version
```

### View VM Serial Logs
```bash
# Logs are in the lab state directory
cat /var/lib/octolab/microvm/<lab_id>/serial.log
```

### Debug Guest Agent
```bash
# Connect to VM serial console (if available)
# Or check logs via host:
tail -f /var/lib/octolab/microvm/<lab_id>/firecracker.log
```

## Security Considerations

1. **Jailer**: In production, always use jailer for additional isolation.
   The `OCTOLAB_DEV_UNSAFE_ALLOW_NO_JAILER` flag should only be set in development.

2. **Token Authentication**: Each VM gets a unique token passed via kernel cmdline.
   Never log this token.

3. **Network Isolation**: Each VM has its own tap device and IP. DNAT rules
   are scoped to specific lab IDs.

4. **Resource Limits**: VCPUs and memory are limited per VM to prevent DoS.

5. **Fail-Fast**: If Firecracker is enabled but unhealthy, lab creation fails
   immediately rather than falling back to compose.

## File Structure

```
infra/firecracker/
├── README.md                 # This file
├── build-rootfs.sh          # Rootfs build script
├── guest-agent/
│   └── agent.py             # vsock agent for compose operations
└── out/                     # Build output (gitignored)
    └── rootfs.ext4          # Built rootfs image
```
