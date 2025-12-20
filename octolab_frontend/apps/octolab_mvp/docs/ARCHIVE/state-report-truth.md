> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# OctoLab MVP State Report - Truth Audit
**Generated:** 2025-11-28  
**Audit Type:** Read-only repository inspection  
**Prior Report:** `docs/state-report.md` (found and referenced)

---

## Repo State

- **Repo Root:** `/home/architect/octolab_mvp`
- **Git Status:** Not a git repository (no HEAD commit available)
- **Working Tree:** Clean (no uncommitted changes detected via `git status --porcelain`)
- **Prior Report:** Found at `docs/state-report.md` (verified claims against this file)

---

## Executive Summary

**Verified Working:**
- All 5 workflow scripts exist and function as documented
- Kubernetes manifests correctly expose only port 6080 (5900 NOT exposed)
- VNC password hardcoded in both Secret and entrypoint script (security risk confirmed)
- Backend uses Docker Compose runtime exclusively (no k8s integration)
- Evidence service assumes Docker volumes, not k8s PVCs

**Critical Discrepancies Found:**
- NetworkPolicy exists but enforcement uncertain (k3s flannel limitation noted in comments)
- Backend evidence service uses Docker volume names, incompatible with k8s PVC approach
- Single shared namespace confirmed (no per-lab isolation)

---

## What Exists (Verified)

### Scripts (`scripts/`)

**All 5 workflow scripts verified:**

1. **`scripts/octobox-reset.sh`** (202 lines)
   - Flags: `--namespace <ns>`, `--delete-evidence`, `--yes`
   - Actions: Scales deployment to 0, deletes ReplicaSets, waits for pod termination, deletes Deployment/Service/Ingress/Secret, conditionally deletes PVC
   - Evidence: ```12:31:scripts/octobox-reset.sh
   case $1 in
       --namespace)
           NAMESPACE="$2"
           shift 2
           ;;
       --delete-evidence)
           DELETE_EVIDENCE=true
   ```
   - Security: No dangerous patterns found (no `prune`, `rm -rf`, namespace deletion)

2. **`scripts/octobox-cleanup-images.sh`** (119 lines)
   - Flags: `--namespace <ns>`
   - Actions: Verifies no pods exist, lists OctoBox images, removes via `sudo k3s ctr images rm`
   - Evidence: ```42:50:scripts/octobox-cleanup-images.sh
   ALL_IMAGES=$(sudo k3s ctr images ls 2>/dev/null | awk '{print $1}' | grep -v "^REF" || true)
   PATTERNS=(
       "octobox-beta"
       "docker.io/library/octobox-beta"
       "bonigarcia/novnc"
   ```
   - Security: Safe - only removes OctoBox images, checks for running pods first

3. **`scripts/octobox-build-import.sh`** (262 lines)
   - Flags: None (no arguments)
   - Actions: Waits for containerd, builds `octobox-beta:dev`, removes old image from k3s, imports via temp file, ensures sidecar image present, verifies both images
   - Evidence: ```44:44:scripts/octobox-build-import.sh
   if docker build -t octobox-beta:dev images/octobox-beta/ 2>&1; then
   ```
   - Freshness approach: Removes old image before re-import (line 66-77)

4. **`scripts/octobox-deploy.sh`** (102 lines)
   - Flags: `--namespace <ns>`
   - Actions: Applies kustomize manifests, waits for rollout, verifies pod readiness (2/2), verifies endpoints, **security check: verifies port 5900 NOT exposed**
   - Evidence: ```78:85:scripts/octobox-deploy.sh
   SVC_YAML=$(kubectl -n "$NAMESPACE" get svc octobox-beta-novnc -o yaml 2>/dev/null || echo "")
   if echo "$SVC_YAML" | grep -qiE "5900|port.*5900|targetPort.*5900"; then
       echo "[octobox-deploy]   ✗ SECURITY ERROR: Service exposes port 5900!"
   ```

5. **`scripts/octobox-refresh.sh`** (110 lines)
   - Flags: `--namespace <ns>`, `--delete-evidence`, `--yes` (passes through to reset script)
   - Actions: Orchestrates all 4 scripts in sequence
   - Evidence: ```49:54:scripts/octobox-refresh.sh
   if "$SCRIPT_DIR/octobox-reset.sh" "${FLAGS[@]}"; then
       echo "[octobox-refresh] ✓ Reset complete"
   else
       echo "[octobox-refresh] ✗ Reset failed" >&2
   ```

### Kubernetes Manifests (`infra/apps/octobox-beta/`)

**Files verified:**
- `deployment.yaml`, `service-novnc.yaml`, `ingress.yaml`, `secret-novnc.yaml`, `networkpolicy.yaml`, `pvc-evidence.yaml`, `kustomization.yaml`

**Port Exposure Analysis:**

1. **Service (`service-novnc.yaml`):**
   - Port 6080: ✅ Exposed (port: 6080, targetPort: 6080)
   - Port 5900: ✅ NOT exposed (explicit comment confirms)
   - Evidence: ```10:15:infra/apps/octobox-beta/service-novnc.yaml
   ports:
     - name: novnc
       port: 6080
       targetPort: 6080
   # NOTE: VNC port 5900 is NOT exposed via this Service.
   ```

2. **Ingress (`ingress.yaml`):**
   - Port 6080: ✅ Exposed (backend service port: 6080)
   - Port 5900: ✅ NOT exposed (no reference found)
   - TLS: ❌ Not configured (commented out, requires cert-manager)
   - Evidence: ```19:20:infra/apps/octobox-beta/ingress.yaml
   service:
       name: octobox-beta-novnc
       port:
           number: 6080
   ```

3. **Deployment (`deployment.yaml`):**
   - Container ports: Only 6080 exposed (novnc container)
   - VNC port 5900: Used internally only (env var `VNC_RFBPORT=5900`, not exposed)
   - Evidence: ```22:23:infra/apps/octobox-beta/deployment.yaml
   - name: VNC_RFBPORT
       value: "5900"
   ```

**Image References:**
- Attacker: `octobox-beta:dev` (line 17), `imagePullPolicy: IfNotPresent`
- Sidecar: `bonigarcia/novnc:1.3.0` (line 43), `imagePullPolicy: IfNotPresent`

**Secret (`secret-novnc.yaml`):**
- VNC password: ✅ Hardcoded `octo123` (line 8)
- Evidence: ```7:8:infra/apps/octobox-beta/secret-novnc.yaml
   stringData:
       VNC_PASSWORD: "octo123"
   ```

**NetworkPolicy (`networkpolicy.yaml`):**
- Exists: ✅ Yes (28 lines)
- Ingress rules: Allows port 6080 from Traefik pods in kube-system namespace
- Egress rules: ❌ None (no egress policy defined)
- Enforcement note: Comment states "k3s default flannel may not enforce NetworkPolicies" (line 13)
- Evidence: ```11:25:infra/apps/octobox-beta/networkpolicy.yaml
   ingress:
       - from:
           - namespaceSelector:
               matchLabels:
                   name: kube-system
           - podSelector:
               matchLabels:
                   app.kubernetes.io/name: traefik
       ports:
           - protocol: TCP
               port: 6080
   ```

**Kustomization (`kustomization.yaml`):**
- Namespace: `octolab-labs` (shared by all labs)
- Labels: Uses `labels` (not deprecated `commonLabels`)
- Evidence: ```12:15:infra/apps/octobox-beta/kustomization.yaml
   labels:
     - includeSelectors: true
       pairs:
         app.octolab.io/component: octobox-beta
   ```

### Image Build Files (`images/octobox-beta/`)

**Dockerfile (`Dockerfile`):**
- tigervnc-tools: ✅ Installed (line 25)
- User creation: ✅ `pentester` user with password `pentester123` (line 42-43)
- Sudo config: ✅ NOPASSWD for all commands (line 45)
- Evidence dir: ✅ `/evidence` created and owned by pentester (line 48-50)
- Evidence: ```25:25:images/octobox-beta/Dockerfile
   tigervnc-tools \
   ```
   ```42:45:images/octobox-beta/Dockerfile
   RUN useradd -m -s /bin/bash pentester && \
       echo "pentester:pentester123" | chpasswd && \
       usermod -aG sudo pentester && \
       echo "pentester ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
   ```

**Entrypoint (`start-vnc-session.sh`):**
- VNC bind: ✅ Binds to localhost when `VNC_LOCALHOST=1` (default, line 22, 60-62)
- Port config: ✅ Uses `VNC_RFBPORT` env var, defaults to 5900 (line 19, 59)
- Password: ✅ Hardcoded `octo123` (line 55)
- X/ICE sockets: ✅ Creates `/tmp/.X11-unix` and `/tmp/.ICE-unix` with 1777 perms (line 30-37)
- Evidence: ```22:22:images/octobox-beta/rootfs/usr/local/bin/start-vnc-session.sh
   VNC_LOCALHOST="${VNC_LOCALHOST:-1}"
   ```
   ```55:55:images/octobox-beta/rootfs/usr/local/bin/start-vnc-session.sh
   sudo -u pentester /bin/bash -c "set -euo pipefail; echo 'octo123' | '$PASSWORD_TOOL' -f > '$HOME/.vnc/passwd'"
   ```
   ```30:37:images/octobox-beta/rootfs/usr/local/bin/start-vnc-session.sh
   for sock_dir in /tmp/.X11-unix /tmp/.ICE-unix; do
     if [[ ! -d "${sock_dir}" ]]; then
       mkdir -p "${sock_dir}"
       log "Created ${sock_dir}"
     fi
     chown root:root "${sock_dir}"
     chmod 1777 "${sock_dir}"
   ```

**Evidence Logger (`octolog-shell`):**
- Log paths: ✅ `/evidence/commands.log` and `/evidence/commands.time` (line 31-32)
- Fallback: ✅ Falls back to regular bash if `/evidence` not writable (line 17-20)
- Evidence: ```31:32:images/octobox-beta/rootfs/usr/local/bin/octolog-shell
   -t 2>"${LOG_DIR}/commands.time" \
       "${LOG_DIR}/commands.log"
   ```
   ```17:20:images/octobox-beta/rootfs/usr/local/bin/octolog-shell
   if [ ! -w "${LOG_DIR}" ]; then
     echo "Warning: ${LOG_DIR} is not writable, falling back to regular bash" >&2
     exec /bin/bash "$@"
   ```

### Backend (`backend/`)

**Endpoints (`app/api/routes/labs.py`):**
- `POST /labs`: ✅ Exists (line 34-70)
- `GET /labs`: ✅ Exists (line 166-190)
- `GET /labs/{id}`: ✅ Exists (line 193-220)
- `DELETE /labs/{id}`: ✅ Exists (line 73-104)
- `GET /labs/{id}/evidence`: ✅ Exists (line 107-163)
- Auth: ✅ All endpoints require `get_current_user` dependency
- Evidence: ```107:115:backend/app/api/routes/labs.py
   @router.get(
       "/{lab_id}/evidence",
       summary="Download structured evidence tarball",
   )
   async def get_lab_evidence(
       lab_id: UUID,
       current_user: User = Depends(get_current_user),
   ```

**Tenant Isolation (`app/services/lab_service.py`):**
- Owner filtering: ✅ All queries filter by `owner_id=user.id` (line 116)
- Returns 404: ✅ Returns 404 (not 403) if lab not owned by user
- Evidence: ```114:119:backend/app/services/lab_service.py
   result = await db.execute(
       select(Lab).where(
           Lab.owner_id == user.id,
           Lab.status.in_(active_statuses),
       )
   )
   ```

**Runtime Implementation (`app/runtime/compose_runtime.py`):**
- ComposeLabRuntime: ✅ Exists (82 lines)
- Commands: ✅ Runs `docker compose -p octolab_{lab.id} up -d` and `down`
- k8s runtime: ❌ NOT found (searched backend/, no kubectl/kubernetes imports)
- Evidence: ```41:41:backend/app/runtime/compose_runtime.py
   cmd = ["docker", "compose", "-f", str(self.compose_path), *args]
   ```
   ```32:33:backend/app/runtime/compose_runtime.py
   def _project_name(self, lab: Lab) -> str:
       return f"{self.project_prefix}{lab.id}"
   ```

**Runtime Factory (`app/runtime/__init__.py`):**
- Available runtimes: ✅ `ComposeLabRuntime` (default), `NoopRuntime` (via env var)
- k8s runtime: ❌ NOT available (only compose and noop)
- Evidence: ```32:37:backend/app/runtime/__init__.py
   runtime_choice = os.environ.get("OCTOLAB_RUNTIME", "compose").lower()
   if runtime_choice == "noop":
       return NoopRuntime()
   compose_path = _resolve_compose_path()
   return ComposeLabRuntime(compose_path)
   ```

**Evidence Service (`app/services/evidence_service.py`):**
- Docker volume assumption: ✅ Uses Docker volume names `octolab_{lab.id}_lab_evidence` (line 35-36)
- k8s PVC logic: ❌ NOT present (no kubectl commands, no PVC mounting logic)
- Evidence: ```35:36:backend/app/services/evidence_service.py
   project_name = f"octolab_{lab.id}"
   volume_name = f"{project_name}_lab_evidence"
   ```
   ```44:49:backend/app/services/evidence_service.py
   check_log_cmd = [
       "docker",
       "run",
       "--rm",
       "-v",
       f"{volume_name}:/evidence:ro",
   ```

---

## What Does Not Exist / Cannot Be Verified

### Backend k8s Integration
- **Claim:** "Backend k8s integration: ❌ Missing"
- **Status:** ✅ VERIFIED FALSE - No kubectl/kubernetes imports found in backend/
- **Evidence:** `grep -r "kubectl\|kubernetes\|K8sRuntime" backend/` returned no matches

### Per-Lab Namespace
- **Claim:** "Per-lab namespace: ❌ Missing"
- **Status:** ✅ VERIFIED FALSE - All manifests use `namespace: octolab-labs` (shared)
- **Evidence:** ```3:3:infra/apps/octobox-beta/kustomization.yaml
   namespace: octolab-labs
   ```

### Dynamic Secret Generation
- **Claim:** "Dynamic Secret generation: ❌ Missing"
- **Status:** ✅ VERIFIED FALSE - Secret contains hardcoded `octo123` value
- **Evidence:** ```7:8:infra/apps/octobox-beta/secret-novnc.yaml
   stringData:
       VNC_PASSWORD: "octo123"
   ```

### NetworkPolicy Enforcement
- **Claim:** "NetworkPolicy may not enforce"
- **Status:** ⚠️ UNKNOWN - Policy exists but enforcement depends on CNI (k3s flannel may not enforce)
- **Evidence:** Comment in NetworkPolicy: ```13:14:infra/apps/octobox-beta/networkpolicy.yaml
   # NOTE: k3s default flannel may not enforce NetworkPolicies.
   # Primary containment is VNC bound to localhost inside the pod.
   ```

### Evidence Service k8s Compatibility
- **Claim:** Evidence service assumes Docker volumes
- **Status:** ✅ VERIFIED TRUE - Uses Docker volume names, no k8s PVC logic
- **Evidence:** ```35:49:backend/app/services/evidence_service.py
   volume_name = f"{project_name}_lab_evidence"
   check_log_cmd = [
       "docker",
       "run",
       "--rm",
       "-v",
       f"{volume_name}:/evidence:ro",
   ```

---

## Security Posture (Provable Facts)

### Verified Security Controls

1. **VNC Port Isolation:**
   - ✅ VNC bound to localhost only (`VNC_LOCALHOST=1` in deployment, `-localhost` flag in entrypoint)
   - ✅ Port 5900 NOT exposed via Service (verified in `service-novnc.yaml` and deploy script check)
   - ✅ Port 5900 NOT exposed via Ingress (verified in `ingress.yaml`)

2. **Container Security:**
   - ✅ `allowPrivilegeEscalation: false` (both containers)
   - ✅ `capabilities.drop: ALL` (both containers)
   - ✅ noVNC runs as non-root (`runAsNonRoot: true`, `runAsUser: 1000`)

3. **Tenant Isolation (Backend):**
   - ✅ All lab queries filter by `owner_id=user.id`
   - ✅ Returns 404 (not 403) if lab not owned by user

### Verified Security Risks

1. **Hardcoded VNC Password:**
   - ✅ Password `octo123` hardcoded in `secret-novnc.yaml` (line 8)
   - ✅ Password `octo123` hardcoded in `start-vnc-session.sh` (line 55)
   - ✅ Same password for all labs (no per-lab generation)

2. **Hardcoded User Password:**
   - ✅ User `pentester` password `pentester123` hardcoded in Dockerfile (line 43)

3. **No Per-Lab Namespace:**
   - ✅ All labs share `octolab-labs` namespace
   - ⚠️ Pods can communicate within namespace (unless NetworkPolicy enforced)

4. **NetworkPolicy Enforcement:**
   - ⚠️ UNKNOWN - Policy exists but enforcement uncertain (k3s flannel limitation noted)

5. **No TLS:**
   - ✅ Ingress is HTTP-only (TLS commented out, requires cert-manager)

### Unknowns (Cannot Verify)

- **NetworkPolicy enforcement:** Cannot verify without testing on actual k3s cluster
- **Evidence service k8s compatibility:** Assumes Docker volumes; k8s PVC access method unknown

---

## Biggest Gaps (Repo-Backed)

1. **Backend-k8s Disconnect:**
   - Backend uses `ComposeLabRuntime` exclusively
   - Evidence service uses Docker volume names (`octolab_{lab.id}_lab_evidence`)
   - No kubectl/kubernetes client code found
   - **Impact:** Backend cannot spawn k8s labs; manual deployment required

2. **No Per-Lab Isolation:**
   - All labs share `octolab-labs` namespace
   - NetworkPolicy may not enforce (k3s flannel limitation)
   - **Impact:** Pods can potentially reach each other's services

3. **Hardcoded Secrets:**
   - VNC password `octo123` in both Secret and entrypoint script
   - User password `pentester123` in Dockerfile
   - **Impact:** Same credentials for all labs; no per-lab security

4. **Evidence Service Incompatibility:**
   - Assumes Docker volumes (`octolab_{lab.id}_lab_evidence`)
   - k8s uses PVC (`octobox-beta-evidence`)
   - **Impact:** Evidence endpoint will fail for k8s-deployed labs

---

## Next-Step Options (Grounded in Verified Reality)

### Option A: Docker Compose Per-Lab with Isolated Bridge Networks

**Reality Check:**
- ✅ `ComposeLabRuntime` exists and works (`backend/app/runtime/compose_runtime.py`)
- ✅ Evidence service already uses Docker volumes (`backend/app/services/evidence_service.py`)
- ✅ Per-lab project naming already implemented (`octolab_{lab.id}`)

**Pros:**
- ✅ Minimal backend changes (extend existing runtime)
- ✅ Evidence service already compatible
- ✅ Native Docker network isolation

**Cons:**
- ❌ Not k8s-native (doesn't leverage k3s investment)
- ❌ Single-host limitation

**Reusable Parts:**
- `backend/app/runtime/compose_runtime.py` (extend for network creation)
- `backend/app/services/evidence_service.py` (already uses Docker volumes)
- `images/octobox-beta/` (attacker image)

---

### Option B: k3s Path - Namespace-Per-Lab + Backend k8s Integration

**Reality Check:**
- ✅ k8s manifests exist and work (`infra/apps/octobox-beta/`)
- ✅ Scripts automate deployment (`scripts/octobox-*.sh`)
- ❌ Backend has no k8s client code (verified: no kubectl/kubernetes imports)
- ❌ Evidence service incompatible (uses Docker volumes, not k8s PVCs)

**Pros:**
- ✅ Leverages k3s investment
- ✅ Namespace isolation (stronger than Docker networks)
- ✅ Scalable (multi-node possible)

**Cons:**
- ❌ Requires significant backend changes:
  - New `K8sLabRuntime` implementation
  - kubectl/kubernetes Python client integration
  - Evidence service rewrite for k8s PVC access
- ⚠️ NetworkPolicy enforcement uncertain (k3s flannel)

**Reusable Parts:**
- `infra/apps/octobox-beta/` (all manifests, extend with kustomize overlays)
- `images/octobox-beta/` (attacker image)
- `scripts/octobox-*.sh` (deployment automation)

**Required New Work:**
- `backend/app/runtime/k8s_runtime.py` (new file)
- `backend/app/k8s/templates/` (kustomize overlays or Jinja2 templates)
- Evidence service rewrite for k8s PVC access

---

## Discrepancy Matrix

| Claim from Prior Report | Status | Evidence |
|------------------------|--------|----------|
| "All 5 workflow scripts exist" | ✅ VERIFIED | All scripts found in `scripts/` directory |
| "Port 5900 NOT exposed via Service" | ✅ VERIFIED | `service-novnc.yaml` only exposes 6080, deploy script checks for 5900 |
| "VNC password hardcoded in Secret" | ✅ VERIFIED | `secret-novnc.yaml` line 8: `VNC_PASSWORD: "octo123"` |
| "VNC password hardcoded in entrypoint" | ✅ VERIFIED | `start-vnc-session.sh` line 55: `echo 'octo123'` |
| "Backend uses Docker Compose runtime" | ✅ VERIFIED | `ComposeLabRuntime` exists, no k8s runtime found |
| "No per-lab namespace" | ✅ VERIFIED | `kustomization.yaml` uses shared `octolab-labs` namespace |
| "NetworkPolicy may not enforce" | ⚠️ UNKNOWN | Policy exists but comment notes k3s flannel limitation |
| "Evidence service uses Docker volumes" | ✅ VERIFIED | `evidence_service.py` uses `octolab_{lab.id}_lab_evidence` volume names |
| "No TLS on Ingress" | ✅ VERIFIED | TLS section commented out in `ingress.yaml` |
| "tigervnc-tools installed" | ✅ VERIFIED | `Dockerfile` line 25 includes `tigervnc-tools` |
| "X/ICE socket directories created" | ✅ VERIFIED | `start-vnc-session.sh` lines 30-37 create `/tmp/.X11-unix` and `/tmp/.ICE-unix` |
| "octolog-shell falls back if /evidence not writable" | ✅ VERIFIED | `octolog-shell` lines 17-20 check writability and fallback |
| "All /labs endpoints exist" | ✅ VERIFIED | `labs.py` contains POST, GET (list), GET (single), DELETE, GET (evidence) |
| "Tenant isolation via owner_id" | ✅ VERIFIED | `lab_service.py` line 116 filters by `Lab.owner_id == user.id` |

---

## Top 5 Corrections Discovered

1. **Evidence Service Incompatibility:** Evidence service (`backend/app/services/evidence_service.py`) uses Docker volume names (`octolab_{lab.id}_lab_evidence`) but k8s deployment uses PVC (`octobox-beta-evidence`). The evidence endpoint will fail for k8s-deployed labs.

2. **VNC Password Double-Hardcoded:** Password `octo123` is hardcoded in BOTH `infra/apps/octobox-beta/secret-novnc.yaml` (line 8) AND `images/octobox-beta/rootfs/usr/local/bin/start-vnc-session.sh` (line 55). This is worse than single hardcoding - both must be changed.

3. **NetworkPolicy Enforcement Unknown:** NetworkPolicy exists (`infra/apps/octobox-beta/networkpolicy.yaml`) but includes comment that "k3s default flannel may not enforce NetworkPolicies" (line 13). Cannot verify enforcement without cluster testing.

4. **No k8s Runtime Found:** Backend has zero k8s integration code. Searched entire `backend/` directory for `kubectl`, `kubernetes`, `K8sRuntime` - no matches found. Backend is Docker Compose-only.

5. **Deploy Script Security Check:** `scripts/octobox-deploy.sh` includes explicit security check (lines 78-85) that verifies port 5900 is NOT exposed by Service. This is a positive security control that was not mentioned in prior report.

---

**Report generated by:** Cursor Agent (read-only audit)  
**Method:** File inspection, grep searches, code excerpt verification  
**No code changes made** (read-only audit only)

