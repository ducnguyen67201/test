# OctoLab Scripts

Utility scripts for managing OctoLab infrastructure.

## OctoBox Beta Workflow Scripts

### octobox-refresh.sh (Recommended - One-Command Workflow)

Complete refresh workflow: resets resources, cleans images, rebuilds, and redeploys.

**Usage:**
```bash
./scripts/octobox-refresh.sh [--namespace <ns>] [--delete-evidence] [--yes]
```

**Examples:**
```bash
# Standard refresh (preserves evidence PVC)
./scripts/octobox-refresh.sh

# Refresh and delete evidence PVC
./scripts/octobox-refresh.sh --delete-evidence

# Refresh in different namespace
./scripts/octobox-refresh.sh --namespace my-namespace
```

**What it does:**
1. Resets Kubernetes resources (Deployment/Service/Ingress/Secret)
2. Cleans up old OctoBox images from k3s containerd
3. Builds and imports fresh images
4. Deploys and verifies rollout

**Safety:**
- Preserves evidence PVC by default (use `--delete-evidence` to remove)
- Only removes OctoBox-related images
- Verifies each step before proceeding

---

### octobox-reset.sh

Safely remove OctoBox Beta Kubernetes resources.

**Usage:**
```bash
./scripts/octobox-reset.sh [--namespace <ns>] [--delete-evidence] [--yes]
```

**What it does:**
1. Scales deployment to 0 (graceful shutdown)
2. Waits for pods to terminate
3. Deletes Deployment, Service, Ingress, Secret
4. Conditionally deletes PVC (only if `--delete-evidence` flag set)
5. Verifies all resources are removed

**Safety:**
- Preserves evidence PVC by default
- Only deletes resources with `app=octobox-beta` label
- Bounded timeouts with clear error messages

---

### octobox-cleanup-images.sh

Remove OctoBox-related images from k3s containerd (only when safe).

**Usage:**
```bash
./scripts/octobox-cleanup-images.sh [--namespace <ns>]
```

**What it does:**
1. Verifies no running pods exist (safety check)
2. Lists OctoBox-related images:
   - `octobox-beta:*`
   - `bonigarcia/novnc:*`
   - `theasp/novnc:*` (old sidecar)
3. Removes images that are not in-use
4. Reports what was removed and what was skipped

**Safety:**
- Refuses to run if pods are still running
- Only removes OctoBox-related images (pattern matching)
- Handles "not found" errors gracefully

---

### octobox-build-import.sh

Build attacker image and import both images into k3s with deterministic freshness.

**Usage:**
```bash
./scripts/octobox-build-import.sh
```

**What it does:**
1. Builds `octobox-beta:dev` image
2. Removes old attacker image from k3s (ensures freshness)
3. Imports attacker image into k3s
4. Ensures sidecar image (`bonigarcia/novnc:1.3.0`) is present
5. Verifies both images are available

**Freshness approach:**
- Removes old `octobox-beta:dev` from k3s before re-import
- Ensures k3s always gets the latest build
- Avoids mutable tag issues while keeping dev workflow simple

---

### octobox-deploy.sh

Deploy manifests and verify rollout with security checks.

**Usage:**
```bash
./scripts/octobox-deploy.sh [--namespace <ns>]
```

**What it does:**
1. Applies kustomize manifests
2. Waits for deployment rollout (180s timeout)
3. Verifies pod is 2/2 Ready
4. Verifies Service endpoints are populated
5. **Security check:** Verifies Service does NOT expose port 5900
6. Prints access instructions

**Verification:**
- Pod readiness check
- Endpoint population check
- Port 5900 security check (fails if found)
- Clear error messages if any check fails

---

## Diagnostic Tools

### octolab_doctor.py

Read-only diagnostic utility to identify k3s failures with secure redaction.

**Usage:**
```bash
# Basic diagnostic check
./scripts/octolab_doctor.py

# Verbose output (more journal lines, detailed checks)
./scripts/octolab_doctor.py --verbose

# Run self-tests (redaction and heuristics)
./scripts/octolab_doctor.py --selftest
```

**What it does:**
1. **Kubectl probes:** Checks API server readiness (readyz, openapi, cluster-info)
   - Falls back to `sudo k3s kubectl` if regular kubectl fails
2. **Systemd status:** Checks k3s service status
3. **Journal logs:** Gathers recent k3s logs (bounded output, redacted)
4. **Host environment:** Checks disk space, ports, system time, kernel errors
5. **Diagnosis:** Uses heuristics to identify common issues:
   - k3s not running / crash-loop
   - Port conflicts
   - Disk full / inode exhaustion
   - Certificate / clock skew issues
   - SQLite datastore problems
   - Networking / cgroup issues
   - Unknown (shows top error patterns)

**Exit codes:**
- `0`: k3s healthy (readyz OK, service active)
- `1`: k3s running but unhealthy / partial failures
- `2`: k3s not running / apiserver unreachable

**Security:**
- All secrets redacted (tokens, certs, passwords, base64 blobs)
- kubeconfig paths shown but never contents
- Bounded output (journal limited to 300-500 lines)
- Read-only: never modifies cluster state

**Example output:**
```
=== OctoLab k3s Doctor ===

[DIAGNOSIS]
Status: k3s_not_running
Confidence: high

[EVIDENCE]
  FATA[2024] failed to start: listen tcp 127.0.0.1:6443: bind: address already in use

[KUBECTL PROBES]
readyz: FAILED
openapi: FAILED
cluster-info: FAILED
Method used: kubectl

[SYSTEMD STATUS]
Service: failed

[HOST CHECKS]
Disk: /var/lib/rancher/k3s  45% used
Port 6443: LISTEN (process: 12345)
Time: 2024-01-15 10:25:00 UTC

[NEXT ACTIONS]
1. Check what's using port 6443: sudo ss -ltnp | grep 6443
2. Stop conflicting service or restart k3s: sudo systemctl restart k3s
3. Check k3s logs: sudo journalctl -u k3s -n 50
```

---

## Generic Utility Scripts

### import-image-to-k3s.sh

Import a Docker image into k3s containerd for use in Kubernetes pods.

**Usage:**
```bash
./scripts/import-image-to-k3s.sh <image:tag>
```

**Examples:**
```bash
# Import noVNC sidecar image
./scripts/import-image-to-k3s.sh bonigarcia/novnc:1.3.0

# Import OctoBox attacker image
./scripts/import-image-to-k3s.sh octobox-beta:dev

# Import any Docker image
./scripts/import-image-to-k3s.sh nginx:1.25-alpine
```

**What it does:**
1. Pulls the image with Docker (if not already present locally)
2. Exports the image and imports it into k3s containerd
3. Verifies the import was successful

**Why this is needed:**
- k3s uses containerd, not Docker
- Images built/pulled with Docker are not automatically available to k3s
- This script bridges Docker and k3s image stores

**Prerequisites:**
- Docker installed and running
- k3s installed
- sudo access (for k3s ctr commands)

---

## Typical Workflows

### Complete Refresh (Recommended)
```bash
# One command does everything
./scripts/octobox-refresh.sh
```

### Step-by-Step (For Debugging)
```bash
# 1. Reset resources
./scripts/octobox-reset.sh

# 2. Clean up old images
./scripts/octobox-cleanup-images.sh

# 3. Build and import fresh images
./scripts/octobox-build-import.sh

# 4. Deploy
./scripts/octobox-deploy.sh
```

### Just Rebuild After Code Changes
```bash
# Build and import (skips reset/cleanup)
./scripts/octobox-build-import.sh

# Redeploy
./scripts/octobox-deploy.sh
```

### Clean Slate (Delete Everything Including Evidence)
```bash
# WARNING: This deletes evidence PVC!
./scripts/octobox-refresh.sh --delete-evidence
```

---

## Safety Model

All scripts follow these principles:

1. **Fail fast:** Exit immediately on errors with clear messages
2. **Print actions:** Log what will be done before doing it
3. **Safe defaults:** Preserve data (PVC) unless explicitly requested
4. **Scoped operations:** Only touch OctoBox resources, never system/k3s resources
5. **Verification:** Check results after operations
6. **Re-runnable:** Safe to run multiple times (idempotent where possible)

---

## Troubleshooting

**Script fails with "pods still running":**
- Run `./scripts/octobox-reset.sh` first to stop workloads

**Image cleanup refuses to run:**
- Ensure no pods exist: `kubectl get pods -n octolab-labs -l app=octobox-beta`
- Run reset script if pods exist

**Deployment fails with ImagePullBackOff:**
- Run `./scripts/octobox-build-import.sh` to ensure images are in k3s
- Check image tags match manifests

**502 Bad Gateway after deploy:**
- Check pod is 2/2 Ready: `kubectl get pods -n octolab-labs -l app=octobox-beta`
- Check endpoints: `kubectl get endpoints -n octolab-labs octobox-beta-novnc`
- Usually means pod not ready or image pull failed

