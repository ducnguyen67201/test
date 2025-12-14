> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# Firecracker microVM Runtime - WSL/KVM POC

This document describes the Firecracker microVM runtime for OctoLab, designed to provide kernel-level isolation for lab environments.

## Overview

The Firecracker runtime provides stronger isolation than container-based runtimes by running each lab in its own microVM with a dedicated Linux kernel. This is particularly useful for:

- Isolating kernel-level exploits
- Preventing container escape attacks
- Running untrusted code with maximum isolation

## Prerequisites

### Hardware Requirements

- x86_64 or aarch64 CPU with hardware virtualization (VT-x/AMD-V or ARM virtualization extensions)
- KVM enabled and accessible (`/dev/kvm` must exist and be readable/writable)

### Software Requirements

- Linux kernel 4.14+ with KVM support
- Firecracker binaries (firecracker, jailer)
- Kernel image (vmlinux)
- Root filesystem (ext4)

## Quick Start

### 1. Run Preflight Check

```bash
cd infra/firecracker
./preflight.sh
```

This checks:
- `/dev/kvm` availability and permissions
- CPU virtualization support
- Firecracker/jailer binaries
- vsock support
- Kernel and rootfs artifacts

### 2. Install Firecracker Binaries

```bash
cd infra/firecracker
./install_firecracker.sh
```

Binaries are installed to `infra/firecracker/bin/`. You can specify a version:

```bash
FC_VERSION=v1.5.1 ./install_firecracker.sh
```

### 3. Download Kernel and Rootfs

```bash
cd infra/firecracker
./download_kernel_rootfs.sh
```

Artifacts are downloaded to `infra/firecracker/artifacts/`:
- `vmlinux` - Linux kernel
- `rootfs.ext4` - Ubuntu 22.04 root filesystem

### 4. Configure Environment

Set the following environment variables:

```bash
# Enable Firecracker runtime
export OCTOLAB_RUNTIME=firecracker

# Path to Firecracker binaries (optional if in PATH)
export OCTOLAB_FIRECRACKER_BIN=/path/to/firecracker
export OCTOLAB_JAILER_BIN=/path/to/jailer

# Path to kernel and rootfs
export OCTOLAB_MICROVM_KERNEL_PATH=/path/to/vmlinux
export OCTOLAB_MICROVM_ROOTFS_BASE_PATH=/path/to/rootfs.ext4

# State directory for VM files
export OCTOLAB_MICROVM_STATE_DIR=/var/lib/octolab/microvm
```

### 5. Verify Configuration

Use the admin preflight endpoint:

```bash
curl -X GET http://localhost:8000/admin/microvm/preflight \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

## WSL2 Considerations

### KVM Support in WSL2

WSL2 supports nested virtualization on Windows 11 with recent builds. To enable:

1. Ensure Windows 11 build 22000+ or Windows 10 with nested virtualization enabled
2. Create/edit `.wslconfig` in your Windows user folder:

```ini
[wsl2]
nestedVirtualization=true
```

3. Restart WSL: `wsl --shutdown`
4. Verify: `ls /dev/kvm`

### Jailer Limitations

The Firecracker jailer may not work correctly in WSL2 due to differences in cgroup and namespace handling. For development/POC purposes only, you can bypass the jailer:

```bash
export OCTOLAB_DEV_UNSAFE_ALLOW_NO_JAILER=true
```

**WARNING**: This is insecure and should NEVER be used in production. Without the jailer:
- The VMM process runs with elevated privileges
- No cgroup resource limits are enforced
- No chroot isolation for the VMM

### Performance Notes

- WSL2 nested virtualization has significant performance overhead
- Expect ~30-50% slower boot times compared to bare-metal Linux
- For production workloads, use native Linux

## Architecture

### Host-Guest Communication

The runtime uses vsock (Virtual Socket) for communication between the host and guest agent:

```
Host (OctoLab Backend)                Guest (microVM)
+-------------------+                 +------------------+
|                   |                 |                  |
| firecracker_mgr   | <-- vsock -->   |   guest agent    |
|                   |   (AF_VSOCK)    |                  |
+-------------------+                 +------------------+
```

- vsock CID is deterministically generated from lab ID
- Port 5000 (configurable via `OCTOLAB_MICROVM_VSOCK_PORT`)
- JSON-over-line protocol with token authentication

### Guest Agent Protocol

Request format:
```json
{"token": "<auth_token>", "action": "ping|uname|id"}
```

Response format:
```json
{"ok": true, "stdout": "...", "stderr": "...", "exit_code": 0}
```

### Allowed Actions

The guest agent enforces a strict allowlist (deny-by-default):
- `ping` - Health check
- `uname` - System information
- `id` - Current user info

Any action not in this list is rejected.

### Security Model

1. **Token Authentication**: Each VM gets a unique 256-bit token passed via kernel cmdline
2. **Action Allowlist**: Only explicitly allowed commands can be executed
3. **Output Limits**: Response size capped at 64KB to prevent DoS
4. **Request Timeout**: 5-second timeout per request
5. **Path Containment**: All VM state files are validated to prevent path traversal

## Configuration Reference

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `OCTOLAB_RUNTIME` | `compose` | Runtime selection (`compose`, `k8s`, `firecracker`, `noop`) |
| `OCTOLAB_MICROVM_STATE_DIR` | `/var/lib/octolab/microvm` | Directory for VM state files |
| `OCTOLAB_FIRECRACKER_BIN` | `firecracker` | Path to firecracker binary |
| `OCTOLAB_JAILER_BIN` | `jailer` | Path to jailer binary |
| `OCTOLAB_MICROVM_KERNEL_PATH` | None | Path to Linux kernel |
| `OCTOLAB_MICROVM_ROOTFS_BASE_PATH` | None | Path to base rootfs image |
| `OCTOLAB_MICROVM_VSOCK_PORT` | `5000` | vsock port for agent |
| `OCTOLAB_MICROVM_BOOT_TIMEOUT_SECS` | `20` | Boot timeout |
| `OCTOLAB_MICROVM_CMD_TIMEOUT_SECS` | `5` | Command timeout |
| `OCTOLAB_MICROVM_MAX_OUTPUT_BYTES` | `65536` | Max output size |
| `OCTOLAB_MICROVM_VCPU_COUNT` | `1` | vCPUs per VM |
| `OCTOLAB_MICROVM_MEM_SIZE_MIB` | `512` | Memory per VM (MiB) |
| `OCTOLAB_DEV_UNSAFE_ALLOW_NO_JAILER` | `false` | Skip jailer (DEV ONLY) |

## Troubleshooting

### "KVM not available"

1. Check virtualization is enabled in BIOS/UEFI
2. On WSL2, ensure nested virtualization is enabled
3. Verify `/dev/kvm` exists: `ls -la /dev/kvm`
4. Add user to kvm group: `sudo usermod -aG kvm $USER`

### "Firecracker binary not found"

Run `./infra/firecracker/install_firecracker.sh` or set `OCTOLAB_FIRECRACKER_BIN`.

### "Kernel/rootfs not found"

Run `./infra/firecracker/download_kernel_rootfs.sh` or set the appropriate env vars.

### "vsock connection failed"

1. Load vhost_vsock module: `sudo modprobe vhost_vsock`
2. Check `/dev/vsock` exists
3. Verify the VM booted successfully (check VM logs)

### "Authentication failed" from guest agent

1. Token mismatch - verify token was passed correctly via kernel cmdline
2. Check guest agent is running inside the VM

## Development

### Running Tests

```bash
cd backend
python3 -m pytest tests/test_firecracker_paths.py tests/test_firecracker_agent_protocol.py -v
```

### Manual VM Testing

For debugging, you can start a VM manually:

```bash
./bin/firecracker --api-sock /tmp/fc.sock
# In another terminal:
curl --unix-socket /tmp/fc.sock -X PUT http://localhost/machine-config \
  -H 'Content-Type: application/json' \
  -d '{"vcpu_count": 1, "mem_size_mib": 512}'
```

See [Firecracker documentation](https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md) for details.

## Security Notes

- **Never expose** `/dev/kvm` to untrusted containers
- **Never disable** the jailer in production
- **Always validate** lab IDs before constructing paths
- **Never log** authentication tokens
- The guest agent runs as root inside the VM but has limited capabilities via the allowlist

## Future Enhancements

This POC provides the foundation. Future work may include:

- Custom rootfs with pre-installed OctoBox tools
- Network isolation via TAP devices
- Evidence collection from VM filesystem
- Snapshot/restore for faster startup
- Resource accounting and quotas
