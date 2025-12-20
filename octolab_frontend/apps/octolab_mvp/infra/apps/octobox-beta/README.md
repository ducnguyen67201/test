# OctoBox Beta Deployment

Single OctoBox Beta attacker pod accessible via noVNC web interface inside `octolab-labs` namespace.

## Prerequisites

**Minimum required:**
- k3s cluster running and accessible via `kubectl`
- Traefik ingress controller installed (comes with k3s by default)
- Docker installed (for building the image)
- OctoBox Beta image built: `docker build -t octobox-beta:dev images/octobox-beta/`
- Image available to k3s (see Step 1 for loading into k3s)

**Optional (for full functionality):**
- Guacamole deployed (not required for noVNC access)
- cert-manager installed (for TLS on Ingress)

**Quick start - if you already have a working k3s cluster:**

```bash
# 1. Build the attacker image
docker build -t octobox-beta:dev images/octobox-beta/

# 2. Import images into k3s (required for k3s to use the images)
# Option A: Use the automation script (recommended)
./scripts/import-image-to-k3s.sh octobox-beta:dev
./scripts/import-image-to-k3s.sh bonigarcia/novnc:1.3.0

# Option B: Manual import (if script not available)
docker save octobox-beta:dev | sudo k3s ctr images import -
docker save bonigarcia/novnc:1.3.0 | sudo k3s ctr images import -

# 3. Deploy
kubectl apply -k infra/apps/octobox-beta/
```

For detailed verification and troubleshooting, see **Step 1: Pre-deployment Checks** in the Testing section below.

## Quick Start for Testing

**Complete refresh workflow (recommended - one command):**

```bash
# Resets everything, rebuilds, and redeploys fresh
./scripts/octobox-refresh.sh

# Then test via port-forward (script will print this command)
kubectl port-forward -n octolab-labs svc/octobox-beta-novnc 6080:6080
# Open browser: http://localhost:6080/
# Password: octo123
```

**Manual step-by-step (for debugging):**

```bash
# 1. Build attacker image
docker build -t octobox-beta:dev images/octobox-beta/

# 2. Import both images into k3s (attacker + sidecar)
./scripts/import-image-to-k3s.sh octobox-beta:dev
./scripts/import-image-to-k3s.sh bonigarcia/novnc:1.3.0

# 3. Deploy all resources
kubectl apply -k infra/apps/octobox-beta/

# 4. Watch pod startup (should become 2/2 Ready)
kubectl get pods -n octolab-labs -l app=octobox-beta -w

# 5. Once ready, test via port-forward
kubectl port-forward -n octolab-labs svc/octobox-beta-novnc 6080:6080
# Then open browser: http://localhost:6080/
# Password: octo123
```

## Deployment

From repo root:

```bash
kubectl apply -k infra/apps/octobox-beta/
```

## Verification

Check pod and service status:

```bash
kubectl get pods -n octolab-labs
kubectl get svc -n octolab-labs octobox-beta-novnc
kubectl get ingress -n octolab-labs octobox-beta-novnc
kubectl get pvc -n octolab-labs octobox-beta-evidence
```

Expected output:
- Pod: `octobox-beta-xxxxx` in `Running` state with 2 containers (octobox-beta, novnc)
- Service: `octobox-beta-novnc` with ClusterIP exposing port 6080 only
- Ingress: `octobox-beta-novnc` routing to the service
- PVC: `octobox-beta-evidence` in `Bound` state

**Important:** VNC port 5900 is NOT exposed via any Service or Ingress. VNC is bound to localhost inside the pod and only accessible via the noVNC sidecar.

**Sidecar Configuration:**
- Image: `bonigarcia/novnc:1.3.0` (pinned version, not :latest)
- Environment variables:
  - `VNC_SERVER=localhost:5900` (connects to attacker container's VNC)
  - `AUTOCONNECT=true` (auto-connects on page load)
  - `VNC_PASSWORD` (from Secret `octobox-beta-novnc-secret`)
- Listens on port 6080 (HTTP/WebSocket)

## Network Flow

```
Browser
  ↓ (HTTP/HTTPS)
Traefik Ingress (octolab-system)
  ↓ (port 6080)
noVNC sidecar container
  ↓ (localhost:5900)
Xtigervnc (attacker container)
  ↓
XFCE desktop
  ↓
octolog-shell
  ↓
/evidence (PVC)
```

## Access via noVNC

### Option 1: Via Ingress (if DNS configured)

1. Add to `/etc/hosts` (or configure DNS):
   ```
   <cluster-ip> octobox-beta.octolab.local
   ```

2. Open browser: `http://octobox-beta.octolab.local/` (or `https://` if TLS configured)

3. Enter VNC password when prompted: `octo123`

### Option 2: Port-forward (for testing)

```bash
kubectl port-forward -n octolab-labs svc/octobox-beta-novnc 6080:6080
```

Then open browser: `http://localhost:6080/` and enter password `octo123`

### Option 3: Direct pod port-forward

```bash
POD_NAME=$(kubectl get pod -n octolab-labs -l app=octobox-beta -o jsonpath='{.items[0].metadata.name}')
kubectl port-forward -n octolab-labs $POD_NAME 6080:6080
```

Then open browser: `http://localhost:6080/` and enter password `octo123`

## Evidence Logging

Check command logs:

```bash
# List evidence files (use attacker container name)
kubectl exec -n octolab-labs <octobox-pod> -c octobox-beta -- ls -lh /evidence

# View recent commands
kubectl exec -n octolab-labs <octobox-pod> -c octobox-beta -- tail -20 /evidence/commands.log

# View timing data
kubectl exec -n octolab-labs <octobox-pod> -c octobox-beta -- tail -20 /evidence/commands.time
```

All interactive shells for `pentester` are logged via `octolog-shell` to:
- `/evidence/commands.log` - Full PTY transcript
- `/evidence/commands.time` - Timing data for scriptreplay

## Reset & Refresh Workflow

For a clean reset and fresh deployment, use the automated scripts. These scripts ensure deterministic image freshness without relying on mutable tags.

### Complete Refresh (Recommended - One Command)

```bash
# One command: reset, cleanup, rebuild, deploy
./scripts/octobox-refresh.sh
```

This single command will:
1. **Reset Kubernetes resources**: Scales deployment to 0, deletes Deployment/Service/Ingress/Secret (preserves evidence PVC by default)
2. **Clean up old images**: Removes OctoBox-related images from k3s containerd (only when safe)
3. **Build and import fresh images**: Builds attacker image, removes old image from k3s, imports fresh build, ensures sidecar image is present
4. **Deploy and verify**: Applies manifests, waits for rollout, verifies pod readiness and security checks

### Delete Evidence PVC

By default, the refresh workflow **preserves** the evidence PVC to retain command logs. To delete it:

```bash
# WARNING: This deletes the evidence PVC and all command logs!
./scripts/octobox-refresh.sh --delete-evidence
```

**When to use `--delete-evidence`:**
- Starting completely fresh (no need to preserve logs)
- Evidence PVC is corrupted or taking up too much space
- Testing evidence collection from scratch

### Freshness Approach (Option B)

The refresh workflow uses **Option B: Remove + Re-Import** to ensure deterministic freshness:

- **Keeps `octobox-beta:dev` tag** in manifests (simple, deterministic)
- **Removes old image from k3s** before re-import (ensures k3s gets new build)
- **Avoids mutable tag issues** while keeping dev workflow simple

This approach ensures that k3s always uses the latest build without requiring kustomize image replacement per build (which would be more complex).

### Step-by-Step (For Debugging)

If you need to debug a specific step, run the scripts individually:

```bash
# 1. Reset resources (preserves PVC by default)
./scripts/octobox-reset.sh

# 2. Clean up old images from k3s containerd
./scripts/octobox-cleanup-images.sh

# 3. Build and import fresh images
./scripts/octobox-build-import.sh

# 4. Deploy and verify
./scripts/octobox-deploy.sh
```

### Just Rebuild After Code Changes

If you only changed the attacker image code and don't need a full reset:

```bash
# Build and import (skips reset/cleanup)
./scripts/octobox-build-import.sh

# Redeploy
./scripts/octobox-deploy.sh
```

**Note:** The build-import script automatically removes the old `octobox-beta:dev` image from k3s before re-importing, ensuring freshness even without a full reset.

### Script Options

All scripts support a `--namespace` flag to target a different namespace:

```bash
# Refresh in custom namespace
./scripts/octobox-refresh.sh --namespace my-custom-ns
```

See `scripts/README.md` for detailed documentation of all scripts and their options.

**k3s Image Import Tip:**
When importing images into k3s, use the pipe method (process substitution doesn't work with sudo):
```bash
docker save <image:tag> | sudo k3s ctr images import -
```

See `scripts/README.md` for detailed documentation of all scripts.

## Testing & Validation

### Step 1: Pre-deployment Checks

**Quick path:** If you're confident your cluster is set up, you can skip to the essential commands:

```bash
# Essential: Build and import images
docker build -t octobox-beta:dev images/octobox-beta/
./scripts/import-image-to-k3s.sh octobox-beta:dev
./scripts/import-image-to-k3s.sh bonigarcia/novnc:1.3.0
```

**Full verification:** Run all these commands to verify prerequisites before deploying:

```bash
# 1. Verify kubectl is installed and configured
kubectl version --client
# Expected: Client Version: version.Info{...}

# 2. Check cluster connectivity
kubectl cluster-info
# Expected: Kubernetes control plane is running at https://...

# 3. Verify current context (should point to your k3s cluster)
kubectl config current-context
# Expected: Something like "default" or your cluster name

# 4. Check if namespace exists, create if missing
kubectl get namespace octolab-labs
# Expected: NAME            STATUS   AGE
#          octolab-labs     Active   ...

# If namespace doesn't exist, create it:
kubectl create namespace octolab-labs

# 5. Verify storage class exists (needed for PVC)
kubectl get storageclass
# Expected: NAME                   PROVISIONER      ...
#          local-path (default)   rancher.io/...   ...

# If no storage class, check what's available:
kubectl get storageclass -A

# 6. Check if Traefik ingress controller is running (for Ingress to work)
kubectl get pods -n kube-system -l app.kubernetes.io/name=traefik
# Expected: NAME                       READY   STATUS    ...
#          traefik-xxxxxxxxxx-xxxxx   1/1     Running   ...

# If Traefik is not running, check if it exists:
kubectl get deployment -n kube-system traefik

# 7. Navigate to repo root (if not already there)
cd /path/to/octolab_mvp
# Or: cd $(git rev-parse --show-toplevel)

# 8. Build the OctoBox Beta Docker image
docker build -t octobox-beta:dev images/octobox-beta/
# Expected: Successfully built <image-id>
#          Successfully tagged octobox-beta:dev

# 9. Verify image was built successfully
docker images | grep octobox-beta
# Expected: octobox-beta    dev      <image-id>   <time>   <size>

# 10. Import images into k3s (if using local k3s cluster)
# For k3s, images need to be imported into containerd
# Option A: Use the automation script (recommended)
./scripts/import-image-to-k3s.sh octobox-beta:dev
./scripts/import-image-to-k3s.sh bonigarcia/novnc:1.3.0

# Option B: Manual import using pipe method (process substitution doesn't work with sudo)
docker save octobox-beta:dev | sudo k3s ctr images import -
docker save bonigarcia/novnc:1.3.0 | sudo k3s ctr images import -

# Option C: Use imagePullSecrets with a registry (production approach)
# For now, assuming local k3s with direct image import

# 11. Verify images are available to k3s
sudo k3s ctr images ls | grep -E "(octobox-beta|bonigarcia/novnc)"
# Expected: 
# docker.io/library/octobox-beta:dev    ...
# docker.io/bonigarcia/novnc:1.3.0      ...

# Alternative: If using a registry, verify image is pushed:
# docker push <registry>/octobox-beta:dev
# kubectl run test-pull --image=<registry>/octobox-beta:dev --dry-run=client -o yaml

# 12. Check if PVC already exists (will be created by kustomize if missing)
kubectl get pvc -n octolab-labs octobox-beta-evidence
# Expected (if exists): NAME                      STATUS   VOLUME   ...
#                      octobox-beta-evidence     Bound    pvc-xxx   ...

# Expected (if missing): Error from server (NotFound): persistentvolumeclaims "octobox-beta-evidence" not found
# This is OK - it will be created during deployment

# 13. Verify deployment manifests are valid (dry-run)
kubectl apply -k infra/apps/octobox-beta/ --dry-run=client
# Expected: persistentvolumeclaim/octobox-beta-evidence created (dry-run)
#          deployment.apps/octobox-beta created (dry-run)
#          service/octobox-beta-novnc created (dry-run)
#          ingress.networking.k8s.io/octobox-beta-novnc created (dry-run)

# 14. Check for any existing OctoBox deployment (optional cleanup)
kubectl get deployment -n octolab-labs octobox-beta
# Expected: Error from server (NotFound): deployments.apps "octobox-beta" not found
# OR if exists: NAME           READY   UP-TO-DATE   ...
#              octobox-beta   1/1     1            ...

# If deployment exists and you want to start fresh:
# kubectl delete deployment -n octolab-labs octobox-beta
# kubectl delete svc -n octolab-labs octobox-beta-novnc
# kubectl delete ingress -n octolab-labs octobox-beta-novnc
```

**Summary of prerequisites:**
- ✅ kubectl installed and configured
- ✅ Cluster accessible
- ✅ Namespace `octolab-labs` exists
- ✅ Storage class available (for PVC)
- ✅ Traefik ingress controller running (for Ingress)
- ✅ Docker image `octobox-beta:dev` built
- ✅ Image available to k3s (loaded or in registry)
- ✅ Manifests are valid (dry-run succeeded)

**If any check fails:**
- Fix the issue before proceeding to Step 2
- Common issues:
  - Image not built: Run `docker build` command
  - Image not in k3s: Import image using `k3s ctr images import`
  - Namespace missing: Create with `kubectl create namespace octolab-labs`
  - Traefik not running: Install Traefik or use different ingress controller

### Step 2: Deploy Manifests

```bash
# Deploy all resources
kubectl apply -k infra/apps/octobox-beta/

# Expected output:
# persistentvolumeclaim/octobox-beta-evidence created (or unchanged)
# deployment.apps/octobox-beta created (or configured)
# service/octobox-beta-novnc created (or configured)
# ingress.networking.k8s.io/octobox-beta-novnc created (or configured)
```

### Step 3: Wait for Pod Startup

```bash
# Wait for deployment rollout to complete
kubectl rollout status deployment/octobox-beta -n octolab-labs --timeout=120s

# Expected output:
# deployment "octobox-beta" successfully rolled out
```

**If rollout hangs or fails:**

```bash
# Check deployment status
kubectl describe deployment octobox-beta -n octolab-labs

# Check pod events
kubectl get events -n octolab-labs --sort-by='.lastTimestamp' | grep octobox-beta

# Check pod status
kubectl get pods -n octolab-labs -l app=octobox-beta
```

### Step 4: Verify Pod Status

```bash
# Get pod name
POD_NAME=$(kubectl get pod -n octolab-labs -l app=octobox-beta -o jsonpath='{.items[0].metadata.name}')
echo "Pod name: $POD_NAME"

# Check pod is Running with both containers ready
kubectl get pod -n octolab-labs -l app=octobox-beta

# Expected output:
# NAME                            READY   STATUS    RESTARTS   AGE
# octobox-beta-xxxxxxxxxx-xxxxx   2/2     Running   0          XXs
# 
# Note: READY should show "2/2" (both containers: octobox-beta and novnc)

# Detailed pod status
kubectl describe pod -n octolab-labs -l app=octobox-beta

# Expected in Conditions section:
#   Ready: True
#   ContainersReady: True
```

**If pod is not ready:**

```bash
# Check container status
kubectl get pod -n octolab-labs -l app=octobox-beta -o jsonpath='{.items[0].status.containerStatuses[*]}' | jq

# Check for ImagePull errors
kubectl describe pod -n octolab-labs -l app=octobox-beta | grep -A 5 "Events:"

# Common issues:
# - ImagePullBackOff: Image not found, check image name/tag
# - CrashLoopBackOff: Container crashing, check logs
# - Init:Error: Init container failed
```

### Step 5: Verify Container Logs

**Attacker container (octobox-beta) logs:**

```bash
# Get full logs
kubectl logs -n octolab-labs $POD_NAME -c octobox-beta

# Check for VNC startup messages
kubectl logs -n octolab-labs $POD_NAME -c octobox-beta | grep -i vnc

# Expected output should include:
# [start-vnc] Using DISPLAY=:0 RFBPORT=5900 LOCALHOST=1 GEOMETRY=1280x800 DEPTH=24
# [start-vnc] Preparing X/ICE socket directories
# [start-vnc] Generating VNC password file
# [start-vnc] Starting Xtigervnc
# [start-vnc] Launching XFCE session for pentester

# Check for errors
kubectl logs -n octolab-labs $POD_NAME -c octobox-beta | grep -i error

# Should NOT see:
# - "vncpasswd: command not found"
# - "_XSERVTransmkdir: ERROR"
# - "_IceTransmkdir: ERROR"
```

**noVNC sidecar logs:**

```bash
# Get noVNC logs
kubectl logs -n octolab-labs $POD_NAME -c novnc

# Expected: noVNC/websockify startup messages, connection attempts to localhost:5900
# Should NOT see:
# - Connection refused errors (VNC should be ready)
# - Port binding errors
```

**Follow logs in real-time:**

```bash
# Attacker container
kubectl logs -n octolab-labs $POD_NAME -c octobox-beta -f

# noVNC sidecar
kubectl logs -n octolab-labs $POD_NAME -c novnc -f
```

### Step 6: Verify Service Configuration

```bash
# Check Service exists and exposes only port 6080
kubectl get svc -n octolab-labs octobox-beta-novnc

# Expected output:
# NAME                  TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)    AGE
# octobox-beta-novnc   ClusterIP   10.43.xxx.xxx   <none>        6080/TCP   XXs

# Detailed Service description
kubectl describe svc -n octolab-labs octobox-beta-novnc

# Expected in output:
# Port:              novnc  6080/TCP
# TargetPort:        6080/TCP
# Endpoints:         <pod-ip>:6080
# 
# CRITICAL: Should NOT see port 5900 anywhere in the output

# Verify endpoints
kubectl get endpoints -n octolab-labs octobox-beta-novnc

# Expected output:
# NAME                  ENDPOINTS              AGE
# octobox-beta-novnc     <pod-ip>:6080          XXs
# 
# Note: Only port 6080 should be listed, NOT 5900
```

### Step 7: Verify Ingress Configuration

```bash
# Check Ingress exists
kubectl get ingress -n octolab-labs octobox-beta-novnc

# Expected output:
# NAME                  CLASS    HOSTS                        ADDRESS   PORTS   AGE
# octobox-beta-novnc   traefik  octobox-beta.octolab.local             80      XXs

# Detailed Ingress description
kubectl describe ingress -n octolab-labs octobox-beta-novnc

# Expected in output:
# Rules:
#   Host                        Path  Backends
#   ----                        ----  --------
#   octobox-beta.octolab.local
#                               /   octobox-beta-novnc:6080 (<pod-ip>:6080)
# 
# Annotations:
#   traefik.ingress.kubernetes.io/service-upgrade: websocket
#   traefik.ingress.kubernetes.io/request-timeout: 300s
```

### Step 8: Port-Forward Test (Recommended First Test)

```bash
# Start port-forward in background or separate terminal
kubectl port-forward -n octolab-labs svc/octobox-beta-novnc 6080:6080

# Expected output:
# Forwarding from 127.0.0.1:6080 -> 6080
# Forwarding from [::1]:6080 -> 6080

# In browser, navigate to:
# http://localhost:6080/

# Expected behavior:
# 1. noVNC interface loads (gray screen with connection controls)
# 2. Password prompt appears (or auto-connects)
# 3. Enter password: octo123
# 4. XFCE desktop appears
# 5. Can interact with desktop, open terminal, etc.
```

**If port-forward fails:**

```bash
# Check if port 6080 is already in use
lsof -i :6080

# Use different local port
kubectl port-forward -n octolab-labs svc/octobox-beta-novnc 8080:6080
# Then access http://localhost:8080/
```

### Step 9: Negative Test - VNC Port 5900 Unreachable

This test verifies that VNC is properly bound to localhost and NOT exposed externally.

```bash
# Get pod IP address
POD_NAME=$(kubectl get pod -n octolab-labs -l app=octobox-beta -o jsonpath='{.items[0].metadata.name}')
POD_IP=$(kubectl get pod -n octolab-labs -l app=octobox-beta -o jsonpath='{.items[0].status.podIP}')
echo "Testing pod IP: $POD_IP"

# Create debug pod in same namespace
kubectl run debug-test -n octolab-labs --image=busybox --rm -it --restart=Never -- sh

# Inside the debug pod, run:
# Test 1: VNC port 5900 should be unreachable
nc -zv $POD_IP 5900
# Expected output:
# nc: <pod-ip> (10.42.x.x):5900: Connection refused
# OR
# nc: <pod-ip> (10.42.x.x):5900: Operation timed out
# 
# This confirms VNC is bound to localhost only

# Test 2: noVNC port 6080 should be reachable
nc -zv $POD_IP 6080
# Expected output:
# <pod-ip> (10.42.x.x):6080 open
# 
# This confirms noVNC sidecar is accessible

# Exit debug pod
exit
```

**Alternative test from host (if cluster allows):**

```bash
# Try to connect directly to pod IP (should fail for 5900, succeed for 6080)
POD_IP=$(kubectl get pod -n octolab-labs -l app=octobox-beta -o jsonpath='{.items[0].status.podIP}')

# Test 5900 (should fail)
timeout 2 nc -zv $POD_IP 5900 || echo "Port 5900 correctly unreachable"

# Test 6080 (should succeed)
nc -zv $POD_IP 6080 && echo "Port 6080 correctly reachable"
```

### Step 10: Verify VNC Server is Listening

```bash
# Check if VNC is listening inside the pod (on localhost)
kubectl exec -n octolab-labs $POD_NAME -c octobox-beta -- netstat -tlnp 2>/dev/null | grep 5900

# Expected output:
# tcp        0      0 127.0.0.1:5900          0.0.0.0:*               LISTEN      <pid>/Xtigervnc
# 
# CRITICAL: Should show 127.0.0.1:5900 (localhost), NOT 0.0.0.0:5900

# Alternative check using ss
kubectl exec -n octolab-labs $POD_NAME -c octobox-beta -- ss -tlnp | grep 5900

# Check noVNC is listening on all interfaces (within pod network)
kubectl exec -n octolab-labs $POD_NAME -c novnc -- netstat -tlnp 2>/dev/null | grep 6080

# Expected output:
# tcp        0      0 0.0.0.0:6080            0.0.0.0:*               LISTEN      <pid>/...
```

### Step 11: Evidence Logging Test

Verify that command logging to `/evidence` still works:

```bash
# List evidence directory
kubectl exec -n octolab-labs $POD_NAME -c octobox-beta -- ls -lh /evidence

# Expected output:
# total XX
# -rw-r--r-- 1 pentester pentester  XXXX commands.log
# -rw-r--r-- 1 pentester pentester  XXXX commands.time

# View recent commands (should be empty on first boot, or show startup commands)
kubectl exec -n octolab-labs $POD_NAME -c octobox-beta -- tail -n 20 /evidence/commands.log

# View timing data
kubectl exec -n octolab-labs $POD_NAME -c octobox-beta -- tail -n 20 /evidence/commands.time

# Test: Execute a command via VNC terminal and verify it's logged
# 1. Connect via noVNC (port-forward)
# 2. Open XFCE Terminal
# 3. Run: echo "test command" && ls -la
# 4. Check logs:
kubectl exec -n octolab-labs $POD_NAME -c octobox-beta -- tail -n 50 /evidence/commands.log | grep "test command"

# Expected: Should see the command in the log
```

### Step 12: Ingress Access Test (If DNS Configured)

```bash
# Get Traefik ingress controller IP/address
kubectl get svc -n kube-system traefik

# Add to /etc/hosts (replace <traefik-ip> with actual IP or use cluster IP)
# <traefik-ip> octobox-beta.octolab.local

# Or use port-forward to Traefik if needed
# kubectl port-forward -n kube-system svc/traefik 80:80

# Test HTTP access
curl -v http://octobox-beta.octolab.local/

# Expected: Should return HTML from noVNC interface
# If TLS is configured, use https:// instead

# In browser, navigate to:
# http://octobox-beta.octolab.local/
# Enter password: octo123
# Should see XFCE desktop
```

### Step 13: Resource Usage Check

```bash
# Check resource usage
kubectl top pod -n octolab-labs -l app=octobox-beta

# Expected output:
# NAME                            CPU(cores)   MEMORY(bytes)
# octobox-beta-xxxxxxxxxx-xxxxx   XXm          XXXMi

# Check individual container resource usage
kubectl top pod -n octolab-labs -l app=octobox-beta --containers

# Verify limits are not exceeded
kubectl describe pod -n octolab-labs -l app=octobox-beta | grep -A 10 "Limits:"
```

## Troubleshooting

### Pod Won't Start

**Symptoms:** Pod status is `Pending`, `ImagePullBackOff`, or `CrashLoopBackOff`

```bash
# Check pod events
kubectl describe pod -n octolab-labs -l app=octobox-beta

# Common causes:
# 1. Image not found (ImagePullBackOff)
#    Solution: Import missing images into k3s:
#    # Use automation script (recommended):
#    ./scripts/import-image-to-k3s.sh octobox-beta:dev
#    ./scripts/import-image-to-k3s.sh bonigarcia/novnc:1.3.0
#    # Or manual import:
#    docker pull bonigarcia/novnc:1.3.0
#    docker save bonigarcia/novnc:1.3.0 | sudo k3s ctr images import -
# 2. PVC not bound
#    Solution: Check storage class, verify PVC status
# 3. Resource limits too low
#    Solution: Increase CPU/memory limits in deployment.yaml
# 4. Secret not found (if sidecar fails to start)
#    Solution: Ensure secret-novnc.yaml is applied:
#    kubectl get secret -n octolab-labs octobox-beta-novnc-secret
```

### VNC Password Not Working

**Symptoms:** Can connect to noVNC but password prompt fails

```bash
# Check VNC password file exists and has correct permissions
kubectl exec -n octolab-labs $POD_NAME -c octobox-beta -- ls -la /home/pentester/.vnc/

# Expected:
# drwx------ 2 pentester pentester  ... passwd
# -rw------- 1 pentester pentester  ... passwd

# Verify password was generated
kubectl exec -n octolab-labs $POD_NAME -c octobox-beta -- cat /home/pentester/.vnc/passwd | wc -c
# Expected: Non-zero (file should exist and have content)

# Check logs for password generation errors
kubectl logs -n octolab-labs $POD_NAME -c octobox-beta | grep -i password
```

### noVNC Shows "Connecting..." Forever

**Symptoms:** noVNC interface loads but never connects to VNC

```bash
# Check VNC server is running
kubectl exec -n octolab-labs $POD_NAME -c octobox-beta -- ps aux | grep -i vnc

# Check VNC is listening on localhost:5900
kubectl exec -n octolab-labs $POD_NAME -c octobox-beta -- netstat -tlnp | grep 5900

# Check noVNC can reach localhost:5900
kubectl exec -n octolab-labs $POD_NAME -c novnc -- nc -zv localhost 5900

# Check noVNC logs for connection errors
kubectl logs -n octolab-labs $POD_NAME -c novnc | tail -50
```

### XFCE Desktop Not Appearing

**Symptoms:** VNC connects but shows blank/black screen

```bash
# Check XFCE process is running
kubectl exec -n octolab-labs $POD_NAME -c octobox-beta -- ps aux | grep -i xfce

# Check XFCE logs
kubectl logs -n octolab-labs $POD_NAME -c octobox-beta | grep -i xfce

# Check DISPLAY variable
kubectl exec -n octolab-labs $POD_NAME -c octobox-beta -- env | grep DISPLAY
# Expected: DISPLAY=:0

# Restart XFCE session (if needed)
kubectl exec -n octolab-labs $POD_NAME -c octobox-beta -- sudo -u pentester DISPLAY=:0 startxfce4 &
```

### Evidence Directory Not Writable

**Symptoms:** Commands not logged to `/evidence`

```bash
# Check PVC is mounted
kubectl exec -n octolab-labs $POD_NAME -c octobox-beta -- mount | grep evidence

# Check permissions
kubectl exec -n octolab-labs $POD_NAME -c octobox-beta -- ls -ld /evidence

# Expected: drwxr-xr-x ... pentester pentester ... /evidence

# Test write access
kubectl exec -n octolab-labs $POD_NAME -c octobox-beta -- sudo -u pentester touch /evidence/test-write
kubectl exec -n octolab-labs $POD_NAME -c octobox-beta -- ls -l /evidence/test-write
kubectl exec -n octolab-labs $POD_NAME -c octobox-beta -- rm /evidence/test-write
```

### Service Not Accessible

**Symptoms:** Can't connect via Service/Ingress, returns 502 Bad Gateway

**502 Bad Gateway usually means endpoints are empty (pod not Ready):**

```bash
# Verify Service endpoints
kubectl get endpoints -n octolab-labs octobox-beta-novnc

# Should show pod IP:6080
# If empty, check:
# 1. Pod is Running with 2/2 containers ready
# 2. Pod labels match Service selector
# 3. Sidecar container is listening on port 6080

# Check pod readiness
kubectl get pods -n octolab-labs -l app=octobox-beta
# Expected: READY shows "2/2", STATUS shows "Running"

# If pod not ready, check container status
kubectl describe pod -n octolab-labs -l app=octobox-beta | grep -A 10 "Containers:"

# Test Service from within cluster
kubectl run test-curl -n octolab-labs --image=curlimages/curl --rm -it --restart=Never -- \
  curl -v http://octobox-beta-novnc.octolab-labs.svc.cluster.local:6080/

# Check Ingress controller is running
kubectl get pods -n kube-system -l app.kubernetes.io/name=traefik

# Check Ingress status
kubectl describe ingress -n octolab-labs octobox-beta-novnc
```

### Container Restarts Frequently

**Symptoms:** Pod shows high restart count

```bash
# Check restart count
kubectl get pod -n octolab-labs -l app=octobox-beta

# Check previous container logs (if crashed)
kubectl logs -n octolab-labs $POD_NAME -c octobox-beta --previous
kubectl logs -n octolab-labs $POD_NAME -c novnc --previous

# Check resource limits
kubectl describe pod -n octolab-labs -l app=octobox-beta | grep -A 5 "Limits:"

# Check OOMKilled events
kubectl describe pod -n octolab-labs -l app=octobox-beta | grep -i oom
```

## Limitations / TODOs

**MVP Hacks:**
- Hardcoded VNC password (`octo123`) stored in Secret (will be per-lab generated later)
- No NetworkPolicies (all pods can communicate)
- Single static instance (not per-lab)
- HTTP only (no TLS) by default
- Sidecar image pinned to tag (not digest) - consider pinning to digest for supply chain security

**Future Enhancements (G3+):**
- Per-lab OctoBox instances with dynamic creation
- Secrets-based VNC password management
- NetworkPolicies to restrict access
- TLS via cert-manager (commented in ingress.yaml)
- Backend API integration for connection management
- Authentication layer in front of noVNC (OAuth2 proxy, Traefik auth middleware)

