# Troubleshooting Guide

Quick reference for common OctoLab issues, where to find logs, and how to fix them.

> **Note**: For netd management commands (start/stop/restart/logs), see the [main docs](README.md#microvm-netd-management).

## Quick Diagnostics

```bash
# Run comprehensive health check
./infra/octolabctl/octolabctl.sh doctor

# Check netd status (exit codes: 0=running, 1=stopped, 2=degraded)
./infra/octolabctl/octolabctl.sh netd status

# Run smoke test
./infra/octolabctl/octolabctl.sh smoke
```

## Log Locations

| Component | Linux (systemd) | WSL (manual) |
|-----------|-----------------|--------------|
| Backend | `journalctl -u octolab-backend` | Terminal output |
| netd | `journalctl -u microvm-netd` | `/run/octolab/microvm-netd.log` |
| Firecracker | `<state_dir>/<lab_id>/firecracker.log` | Same |
| Smoke test | `<state_dir>/smoke_<id>/firecracker.log` | Same |
| Guacamole | `docker logs octolab-guac-web` | Same |
| PostgreSQL | `journalctl -u postgresql` | Docker logs |

**State directory** is typically `/var/lib/octolab/microvm/`.

## Common Issues

### KVM Not Available

**Symptom:**
```
Checking /dev/kvm... [ERROR] not found
```

**Cause:** KVM kernel module not loaded or not accessible.

**Solutions:**

*On bare metal Linux:*
```bash
# Load module
sudo modprobe kvm_intel  # or kvm_amd

# Make persistent
echo "kvm_intel" | sudo tee /etc/modules-load.d/kvm.conf

# Check permissions
ls -l /dev/kvm
# Should show: crw-rw---- root kvm
sudo usermod -aG kvm $USER
```

*On WSL:*
1. Edit `%USERPROFILE%\.wslconfig`:
   ```ini
   [wsl2]
   nestedVirtualization=true
   ```
2. Restart WSL: `wsl --shutdown` in PowerShell
3. Reopen WSL terminal

*In cloud VM (Hetzner, AWS, etc.):*
- Use dedicated/bare-metal instances, OR
- Enable nested virtualization in hypervisor settings

---

### Permission Denied on Socket

**Symptom:**
```
Checking microvm-netd socket... [ERROR] permission denied
```
or
```
PermissionError: [Errno 13] Permission denied: '/run/octolab/microvm-netd.sock'
```

**Cause:** User not in `octolab` group.

**Solution:**
```bash
# Check current groups
id | grep octolab

# If not present, add yourself
sudo usermod -aG octolab $USER

# Apply immediately (opens new shell)
newgrp octolab

# Or log out and back in

# WSL: restart WSL entirely
# In PowerShell: wsl --terminate Ubuntu-24.04
```

---

### netd Not Running

**Symptom:**
```
Checking microvm-netd... [WARN] not running
```

**Solution:**
```bash
# WSL (no systemd):
sudo ./infra/octolabctl/octolabctl.sh netd start

# Linux with systemd:
sudo systemctl start microvm-netd
```

---

### netd Not Responding

**Symptom:**
```
Checking microvm-netd... [WARN] socket exists but not responding
```

**Cause:** netd process hung or crashed.

**Solution:**
```bash
# View logs (redacted)
./infra/octolabctl/octolabctl.sh netd logs -n 50

# Restart
sudo ./infra/octolabctl/octolabctl.sh netd restart
```

---

### netd Stale PID File

**Symptom:** Status shows "PID in pidfile but process gone (stale)"

**Cause:** netd crashed without cleaning up.

**Solution:**
```bash
# Stop will clean up stale files automatically
sudo ./infra/octolabctl/octolabctl.sh netd stop
sudo ./infra/octolabctl/octolabctl.sh netd start
```

---

### netd PID Mismatch (Security Refusal)

**Symptom:** Stop fails with "PID is NOT a microvm-netd process"

**Cause:** PID file points to wrong process. This is a security feature - octolabctl refuses to kill processes that don't match the expected cmdline.

**Solution:**
```bash
# Find actual netd process
pgrep -f microvm_netd

# Kill manually if found
sudo kill <actual_pid>

# Clean up stale files
sudo rm -f /run/octolab/microvm-netd.pid /run/octolab/microvm-netd.sock

# Start fresh
sudo ./infra/octolabctl/octolabctl.sh netd start
```

---

### Firecracker Binary Not Found

**Symptom:**
```
Checking firecracker binary... [ERROR] not found
```

**Solution:**
```bash
sudo infra/octolabctl/octolabctl.sh install

# Verify
which firecracker
firecracker --version
```

---

### Smoke Test Fails

**Symptom:**
```
[ERROR] Smoke test FAILED - boot did not complete
```

**Diagnosis:**
```bash
# Run with verbose output
infra/octolabctl/octolabctl.sh smoke -v

# Keep VM running for inspection
infra/octolabctl/octolabctl.sh smoke --keep
```

**Common causes:**

1. **Kernel/rootfs missing:**
   ```bash
   ls -l /var/lib/octolab/firecracker/
   # Should show vmlinux and rootfs.ext4

   # Re-download if missing
   sudo infra/octolabctl/octolabctl.sh install
   ```

2. **State directory not writable:**
   ```bash
   ls -la /var/lib/octolab/microvm/
   # Should be owned by root:octolab with mode 2775

   sudo chown root:octolab /var/lib/octolab/microvm
   sudo chmod 2775 /var/lib/octolab/microvm
   ```

3. **KVM permission:**
   ```bash
   ls -l /dev/kvm
   # User must have access (in kvm group or root)
   ```

---

### Backend Won't Start

**Symptom:**
```
RuntimeError: Cannot start with OCTOLAB_RUNTIME=firecracker - NO FALLBACK
```

**Cause:** Doctor check failed for Firecracker prerequisites.

**Solution:**
```bash
# Run doctor to see what's wrong
infra/octolabctl/octolabctl.sh doctor

# Fix identified issues, then retry
```

**Alternative:** Switch to compose runtime for development:
```bash
infra/octolabctl/octolabctl.sh enable-runtime compose
```

---

### Database Connection Failed

**Symptom:**
```
sqlalchemy.exc.OperationalError: could not connect to server
```

**Solutions:**

1. **Check PostgreSQL is running:**
   ```bash
   systemctl status postgresql
   # or
   docker ps | grep postgres
   ```

2. **Check connection string:**
   ```bash
   cat backend/.env.local | grep DATABASE_URL
   # Test connection manually
   psql "postgresql://user:pass@host/db"
   ```

3. **Check network:**
   ```bash
   # If using Docker PostgreSQL
   docker logs octolab-guac-db
   ```

---

### Lab Stuck in "provisioning"

**Symptom:** Lab never reaches "ready" state.

**Diagnosis:**
```bash
# Check backend logs
journalctl -u octolab-backend | grep -i error

# Check if VM exists
ps aux | grep firecracker

# Check netd created network
sudo ip link show | grep obr
```

**Common causes:**

1. **vsock agent not responding:**
   - Guest rootfs may not have agent installed
   - Agent may have crashed

2. **Network creation failed:**
   ```bash
   sudo infra/octolabctl/octolabctl.sh netd status
   ```

3. **Resource limits:**
   - Check disk space: `df -h /var/lib/octolab`
   - Check memory: `free -h`

---

### Guacamole Shows ERROR Page

**Symptom:** Browser shows generic "ERROR" at http://localhost:8081/guacamole/

**Solution:**
```bash
# Full reset
make guac-reset

# If that doesn't work, nuke and restart
docker compose -f infra/guacamole/docker-compose.yml down -v
make guac-up
```

---

## Debug Commands

### View All Labs State

```bash
# API endpoint (requires auth)
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/labs

# Direct database query
psql -U octolab -d octolab -c "SELECT id, status, runtime, created_at FROM labs ORDER BY created_at DESC LIMIT 10;"
```

### Force Cleanup Stuck Lab

```bash
# Find lab processes
ps aux | grep firecracker

# Kill VM (get PID from above)
sudo kill <pid>

# Clean up network (requires lab_id)
sudo python3 -c "
import socket, json
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect('/run/octolab/microvm-netd.sock')
s.send(json.dumps({'op': 'destroy', 'lab_id': 'YOUR_LAB_ID'}).encode())
print(s.recv(1024))
"
```

### Check Network Interfaces

```bash
# List all octolab bridges/taps
ip link show | grep -E "obr|otp"

# Should be empty if no labs running
# If stale, netd cleanup may be needed
```

### Inspect Smoke Test Artifacts

```bash
# List available artifacts
ls -la /var/lib/octolab/microvm/smoke_*

# View specific smoke test log
cat /var/lib/octolab/microvm/smoke_XXXX/firecracker.log
```

## Getting Help

1. **Run full diagnostics:**
   ```bash
   infra/octolabctl/octolabctl.sh doctor 2>&1 | tee doctor_output.txt
   ```

2. **Collect logs:**
   ```bash
   journalctl -u octolab-backend -n 500 > backend.log
   journalctl -u microvm-netd -n 500 > netd.log
   ```

3. **File an issue** with:
   - Doctor output
   - Relevant logs (redact secrets!)
   - Steps to reproduce
   - OS/environment info
