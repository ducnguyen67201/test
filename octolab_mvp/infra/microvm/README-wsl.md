# Firecracker microVM Setup for WSL Ubuntu 24.04

This directory contains scripts for setting up and verifying Firecracker microVM runtime on WSL Ubuntu 24.04.

## Overview

The Firecracker runtime provides kernel-level isolation for OctoLab labs, running each lab in its own microVM. This is the **dev-only** setup path for WSL environments.

**IMPORTANT**: This configuration is for development only. Production deployments require:
- Bare-metal Linux (not WSL)
- Firecracker jailer for additional sandboxing
- Proper cgroup and namespace configuration

**NOTE**: The setup script downloads the Firecracker "hello" kernel and rootfs images. These are minimal verification images (~3MB each) that print "Hello, World!" and halt. They are suitable for verifying the Firecracker installation works, but production labs require custom images with the full OctoBox environment.

## Prerequisites

### Windows Host
- Windows 11 Build 22000+ (or Windows 10 with nested virtualization support)
- WSL2 enabled
- Nested virtualization enabled in WSL config

### WSL Configuration

Create or edit `%USERPROFILE%\.wslconfig` on Windows:

```ini
[wsl2]
nestedVirtualization=true
```

Then restart WSL:
```powershell
wsl --shutdown
```

### Ubuntu 24.04

After restarting WSL, verify KVM is available:
```bash
ls -la /dev/kvm
```

If `/dev/kvm` doesn't exist or isn't accessible, nested virtualization isn't working.

## Quick Start

### 1. Run Setup Script

```bash
# From repo root
bash infra/microvm/wsl_setup_ubuntu24.sh
```

This script:
- Installs system dependencies (curl, jq, tar, ca-certificates, util-linux, iptables)
- Downloads and installs Firecracker v1.7.0 to `/usr/local/bin/firecracker`
- Downloads hello kernel/rootfs to `/var/lib/octolab/firecracker/`
- Creates state directory at `/var/lib/octolab/microvm/`
- Writes microVM configuration to `backend/.env.local`
- Runs doctor check to verify setup

The script is idempotent - safe to run multiple times.

### 2. Start the Network Daemon (microvm-netd)

The microvm-netd daemon is required for Firecracker networking. It creates bridge/TAP devices (requires root).

**Start manually (recommended for WSL):**
```bash
sudo ./infra/microvm/netd/run_netd.sh
```

**Or run in background:**
```bash
sudo nohup ./infra/microvm/netd/run_netd.sh > /var/log/microvm-netd.log 2>&1 &
```

**For systems with systemd:**
```bash
sudo cp infra/microvm/netd/microvm-netd.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now microvm-netd
```

The netd daemon:
- Listens on `/run/octolab/microvm-netd.sock`
- Creates bridges named `obr<lab_id_hex[:10]>` (e.g., `obr00000000`)
- Creates TAP devices named `otp<lab_id_hex[:10]>` (e.g., `otp00000000`)
- Requires root (CAP_NET_ADMIN for bridge/TAP creation)

### 3. Verify Installation

```bash
./verify_firecracker.sh
```

This boots a minimal "hello microVM" and verifies:
- `/dev/kvm` is accessible
- Firecracker binary works
- Kernel and rootfs are readable
- VM boots successfully

To keep the VM running for debugging:
```bash
KEEP=1 ./verify_firecracker.sh
```

### 4. Start the Backend

The setup script automatically sets `OCTOLAB_RUNTIME=firecracker` in `.env.local`.

```bash
make dev
```

**NOTE**: The backend will **fail hard** at startup if microVM prerequisites aren't met. This is intentional - there is NO fallback to compose runtime.

## Directory Structure

After setup:

```
/var/lib/octolab/
├── firecracker/
│   ├── vmlinux              # Linux kernel for VMs (hello kernel for dev)
│   └── rootfs.ext4          # Base rootfs image (hello rootfs for dev)
└── microvm/                 # Per-lab VM state (runtime, user-writable)
    └── lab_<uuid>/          # Created per-lab
        ├── firecracker.sock # API socket
        ├── firecracker.log  # VM logs
        └── rootfs.ext4      # Lab rootfs copy
```

Note: `/var/lib/octolab/microvm/` is chowned to the current user for dev convenience.

## Configuration Reference

Environment variables written to `backend/.env.local`:

| Variable | Description |
|----------|-------------|
| `OCTOLAB_MICROVM_KERNEL_PATH` | Path to vmlinux kernel |
| `OCTOLAB_MICROVM_ROOTFS_BASE_PATH` | Path to base ext4 rootfs |
| `OCTOLAB_MICROVM_STATE_DIR` | Directory for per-lab VM state |
| `OCTOLAB_DEV_UNSAFE_ALLOW_NO_JAILER` | Allow running without jailer (dev only!) |

Optional overrides:

| Variable | Default | Description |
|----------|---------|-------------|
| `OCTOLAB_RUNTIME` | `compose` | Runtime selection (`compose`, `firecracker`) |
| `OCTOLAB_FIRECRACKER_BIN` | `firecracker` | Path to firecracker binary |
| `OCTOLAB_MICROVM_VCPU_COUNT` | `1` | vCPUs per VM |
| `OCTOLAB_MICROVM_MEM_SIZE_MIB` | `512` | Memory per VM (MiB) |

## Fail-Hard Behavior

When `OCTOLAB_RUNTIME=firecracker` is set, the backend performs comprehensive doctor checks at startup:

- `/dev/kvm` availability and permissions
- Firecracker binary presence and version
- Kernel file exists and is readable
- Rootfs file exists and is readable
- State directory exists and is writable
- **microvm-netd** socket exists and responds
- (In WSL) Missing jailer is WARN, not FATAL

If any FATAL check fails, the backend refuses to start with a clear error message. **There is no fallback to compose runtime** - this is intentional to prevent silent degradation.

## Security Notes

### WSL Development Environment

- **Jailer is not installed**: The Firecracker jailer doesn't work properly in WSL due to cgroup/namespace differences. The `OCTOLAB_DEV_UNSAFE_ALLOW_NO_JAILER=true` setting allows running without it.

- **This is UNSAFE for production**: Without the jailer:
  - The VMM process runs with elevated privileges
  - No cgroup resource limits are enforced
  - No chroot isolation for the VMM

- **Nested virtualization security**: WSL's nested virtualization has different security properties than bare-metal KVM. Don't use this for production workloads.

### Production Requirements

For production microVM deployment:

1. Use bare-metal Linux (not WSL)
2. Install and use Firecracker jailer
3. Configure proper cgroups (v2 recommended)
4. Use dedicated state directories with restrictive permissions
5. Implement network isolation via TAP devices and iptables
6. Never set `OCTOLAB_DEV_UNSAFE_ALLOW_NO_JAILER=true`

## Troubleshooting

### "/dev/kvm not found"

Nested virtualization isn't enabled. Check:
1. Windows 11 Build 22000+ (check: `winver`)
2. `.wslconfig` has `nestedVirtualization=true`
3. Restart WSL: `wsl --shutdown`

### "/dev/kvm permission denied"

```bash
sudo chmod 666 /dev/kvm
```

Note: This may need to be re-run after WSL restarts.

### "Firecracker binary not found"

Re-run setup or manually install:
```bash
./wsl_ubuntu24_setup.sh
# Or just the binary:
cd ../firecracker && ./install_firecracker.sh
```

### "Kernel/rootfs not found"

Re-run setup to download:
```bash
./wsl_ubuntu24_setup.sh
```

### Backend fails to start with OCTOLAB_RUNTIME=firecracker

Check the doctor output:
```bash
# Run doctor check manually
cd backend
python3 -c "from app.services.firecracker_doctor import run_doctor; r = run_doctor(); print(r.to_dict())"
```

Common issues:
- Missing files (re-run setup)
- Permission issues (check file ownership)
- Wrong paths in `.env.local`
- microvm-netd not running (see below)

### "netd socket not found" / "netd not running"

The microvm-netd daemon is required for Firecracker networking:

1. Start netd:
   ```bash
   sudo ./infra/microvm/netd/run_netd.sh
   ```

2. Verify socket exists:
   ```bash
   ls -la /run/octolab/microvm-netd.sock
   ```

3. Test netd ping:
   ```bash
   cd backend
   python3 -c "from app.services.microvm_net_client import ping_netd_sync; print(ping_netd_sync())"
   ```

### "Permission denied connecting to netd socket"

Add your user to the `octolab` group:
```bash
sudo groupadd octolab  # if doesn't exist
sudo usermod -aG octolab $USER
# Log out and log back in, or:
newgrp octolab
```

### VM boots but immediately exits

Check the Firecracker log:
```bash
cat /var/lib/octolab/microvm/verify-*/firecracker.log
```

Common issues:
- Kernel doesn't match rootfs (version mismatch)
- Rootfs is corrupted (re-download)
- Insufficient memory (increase `MEM_SIZE_MIB`)

**Note**: The hello kernel/rootfs will print "Hello, World!" and halt immediately. This is expected behavior for verification.

## Rollback

To remove microVM configuration:

```bash
# 1. Remove env block from .env.local
sed -i '/### BEGIN OCTOLAB MICROVM ###/,/### END OCTOLAB MICROVM ###/d' backend/.env.local

# 2. Set runtime back to compose (if .env.local still exists)
echo "OCTOLAB_RUNTIME=compose" >> backend/.env.local

# 3. Remove downloaded files (optional)
sudo rm -rf /var/lib/octolab/firecracker
sudo rm -rf /var/lib/octolab/microvm

# 4. Remove Firecracker binary (optional)
sudo rm -f /usr/local/bin/firecracker /usr/local/bin/jailer
```

This does not affect the compose runtime - labs will continue working normally.
