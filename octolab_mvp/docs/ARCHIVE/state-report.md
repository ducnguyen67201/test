> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# OctoLab MVP State Report
**Generated:** 2025-11-28  
**Purpose:** Truthful snapshot of current implementation vs. gaps for multi-tenant isolation

---

## 1. Executive Summary

### What Works Today
- ✅ **Attacker image builds successfully**: `images/octobox-beta/Dockerfile` produces `octobox-beta:dev` with XFCE + VNC
- ✅ **VNC security**: VNC bound to `localhost:5900` inside pod (not exposed via Service/Ingress)
- ✅ **Evidence logging**: `octolog-shell` wrapper logs commands to `/evidence` PVC (1Gi, ReadWriteOnce)
- ✅ **Backend API**: FastAPI endpoints exist (`POST /labs`, `GET /labs/{id}/evidence`, `DELETE /labs/{id}`)
- ✅ **Database models**: User, Lab, Recipe models with tenant isolation via `owner_id` filtering
- ✅ **noVNC sidecar**: `bonigarcia/novnc:1.3.0` successfully bridges VNC to web (port 6080)
- ✅ **Deployment scripts**: `octobox-refresh.sh` automates build/import/deploy workflow for k3s

### What Is Currently Broken/Flaky
- ⚠️ **k3s API readiness**: Deployment fails if k3s API server not ready (transient "unable to handle request")
- ⚠️ **Backend-k8s disconnect**: Backend uses Docker Compose runtime (`ComposeLabRuntime`), not k8s/kubectl
- ⚠️ **Single shared namespace**: All labs share `octolab-labs` namespace (no per-lab isolation)
- ⚠️ **Hardcoded secrets**: VNC password `octo123` hardcoded in Secret (`secret-novnc.yaml`) and entrypoint script
- ⚠️ **NetworkPolicy enforcement**: Policy exists but k3s default flannel may not enforce it
- ⚠️ **No TLS**: Ingress is HTTP-only (TLS commented out, requires cert-manager)

### Biggest Security Risks
- 🔴 **CRITICAL: No per-lab namespace isolation** - All labs share `octolab-labs` namespace; pods can reach each other by default
- 🔴 **CRITICAL: Hardcoded VNC password** - Same password (`octo123`) for all labs, stored in plaintext Secret
- 🟡 **MEDIUM: NetworkPolicy may not enforce** - k3s flannel CNI may ignore NetworkPolicy rules
- 🟡 **MEDIUM: Backend cannot spawn k8s labs** - Backend uses Docker Compose, not kubectl; manual deployment required
- 🟡 **MEDIUM: No tenant-to-tenant network isolation** - Pods in same namespace can communicate unless NetworkPolicy enforced
- 🟢 **LOW: HTTP-only Ingress** - No TLS (acceptable for dev, production risk)

---

## 2. Current Architecture (As Implemented)

### Network Flow (Current Reality)
```
Browser
  ↓ (HTTP/WebSocket)
Traefik Ingress (octobox-beta.octolab.local:80)
  ↓ (port 6080)
Service: octobox-beta-novnc (ClusterIP)
  ↓ (targetPort 6080)
Pod: octobox-beta (2 containers)
  ├─ Container: novnc (bonigarcia/novnc:1.3.0)
  │   └─ Connects to: localhost:5900
  └─ Container: octobox-beta (octobox-beta:dev)
      ├─ Xtigervnc listening on 127.0.0.1:5900
      ├─ XFCE desktop session
      └─ octolog-shell → /evidence PVC (commands.log, commands.time)
```

### Components Present vs. Planned

| Component | Status | Location |
|-----------|--------|----------|
| **Attacker image** | ✅ Implemented | `images/octobox-beta/Dockerfile` |
| **VNC entrypoint** | ✅ Implemented | `images/octobox-beta/rootfs/usr/local/bin/start-vnc-session.sh` |
| **Evidence logging** | ✅ Implemented | `images/octobox-beta/rootfs/usr/local/bin/octolog-shell` |
| **k8s Deployment** | ✅ Implemented | `infra/apps/octobox-beta/deployment.yaml` |
| **noVNC sidecar** | ✅ Implemented | Sidecar in same pod |
| **Service (6080 only)** | ✅ Implemented | `infra/apps/octobox-beta/service-novnc.yaml` |
| **Ingress (Traefik)** | ✅ Implemented | `infra/apps/octobox-beta/ingress.yaml` |
| **PVC for evidence** | ✅ Implemented | `infra/apps/octobox-beta/pvc-evidence.yaml` |
| **NetworkPolicy** | ⚠️ Present but may not enforce | `infra/apps/octobox-beta/networkpolicy.yaml` |
| **Backend k8s integration** | ❌ Missing | Backend uses Docker Compose only |
| **Per-lab namespace** | ❌ Missing | All labs share `octolab-labs` |
| **Dynamic Secret generation** | ❌ Missing | Hardcoded in `secret-novnc.yaml` |
| **Guacamole integration** | ⚠️ Separate deployment | `infra/apps/guacamole/` (not connected to backend) |

---

## 3. Repo Inventory (With Pointers)

### Image Build Files

**`images/octobox-beta/Dockerfile`** (62 lines)
- Base: `debian:12-slim`
- Installs: XFCE4, tigervnc-standalone-server, tigervnc-tools, pentesting tools
- Creates user: `pentester` (password: `pentester123`, sudo NOPASSWD)
- Evidence dir: `/evidence` (owned by pentester)
- Entrypoint: `/usr/local/bin/start-vnc-session.sh`

**`images/octobox-beta/rootfs/usr/local/bin/start-vnc-session.sh`** (78 lines)
- Key config: `VNC_LOCALHOST=1` (binds VNC to 127.0.0.1:5900)
- Password: Hardcoded `octo123` (line 55)
- Starts: `Xtigervnc` + `startxfce4` as `pentester` user
- Pre-creates: `/tmp/.X11-unix`, `/tmp/.ICE-unix` with 1777 perms

**`images/octobox-beta/rootfs/usr/local/bin/octolog-shell`** (38 lines)
- Wrapper shell that logs all commands via `script` command
- Logs to: `/evidence/commands.log` and `/evidence/commands.time`
- Falls back to regular bash if `/evidence` not writable

### Kubernetes Manifests

**`infra/apps/octobox-beta/deployment.yaml`** (77 lines)
- Replicas: 1
- Containers:
  - `octobox-beta`: `octobox-beta:dev`, `imagePullPolicy: IfNotPresent`
  - `novnc`: `bonigarcia/novnc:1.3.0`, `imagePullPolicy: IfNotPresent`
- Env vars: `VNC_LOCALHOST=1`, `VNC_RFBPORT=5900`, `VNC_DISPLAY=:0`
- SecurityContext: `allowPrivilegeEscalation: false`, `capabilities.drop: ALL`
- Volume: `/evidence` → PVC `octobox-beta-evidence`

**`infra/apps/octobox-beta/service-novnc.yaml`** (16 lines)
- Type: ClusterIP
- Port: 6080 → targetPort 6080
- **Note**: Explicitly does NOT expose port 5900 (good)

**`infra/apps/octobox-beta/ingress.yaml`** (28 lines)
- Host: `octobox-beta.octolab.local`
- Path: `/` → Service `octobox-beta-novnc:6080`
- Annotations: WebSocket upgrade, 300s timeout
- **TLS**: Commented out (requires cert-manager)

**`infra/apps/octobox-beta/secret-novnc.yaml`** (13 lines)
- **Hardcoded**: `VNC_PASSWORD: "octo123"` (line 8)
- Namespace: `octolab-labs`
- **Security risk**: Same password for all labs

**`infra/apps/octobox-beta/networkpolicy.yaml`** (28 lines)
- Ingress: Only from Traefik pods in `kube-system` namespace
- Port: 6080 only
- **Limitation**: k3s default flannel may not enforce (line 13 comment)

**`infra/apps/octobox-beta/pvc-evidence.yaml`** (12 lines)
- Size: 1Gi
- AccessMode: ReadWriteOnce
- StorageClass: Default (local-path in k3s)

**`infra/apps/octobox-beta/kustomization.yaml`** (16 lines)
- Namespace: `octolab-labs` (shared by all labs)
- Resources: All manifests listed above

### Backend Orchestration

**`backend/app/api/routes/labs.py`** (289 lines)
- Endpoints:
  - `POST /labs` - Create lab (calls `provision_lab` in background)
  - `GET /labs` - List labs (filtered by `owner_id`)
  - `GET /labs/{id}` - Get lab (404 if not owned by user)
  - `DELETE /labs/{id}` - Trigger teardown (calls `terminate_lab` in background)
  - `GET /labs/{id}/evidence` - Download evidence tar.gz
- Security: All endpoints require `get_current_user` dependency
- Tenant isolation: Service layer filters by `owner_id` (returns 404, not 403)

**`backend/app/services/lab_service.py`** (321 lines)
- `create_lab_for_user()`: Creates Lab with `owner_id=user.id`, status=PROVISIONING
- `provision_lab()`: Calls `runtime.create_lab(lab, recipe)` (line 169)
- `terminate_lab()`: Calls `runtime.destroy_lab(lab)` (line 198)
- **Constraint**: One active lab per user (line 112-125)

**`backend/app/runtime/compose_runtime.py`** (82 lines)
- **Current runtime**: `ComposeLabRuntime` uses Docker Compose
- Project name: `octolab_{lab.id}` (line 33)
- **No k8s integration**: Uses `docker compose -p <project> up -d`
- **Gap**: Backend cannot spawn k8s labs

**`backend/app/runtime/__init__.py`** (37 lines)
- Factory: `get_runtime()` returns `ComposeLabRuntime` by default
- Configurable via `OCTOLAB_RUNTIME` env var (supports `noop` for testing)

**`backend/app/services/evidence_service.py`** (176 lines)
- `build_lab_network_evidence_tar()`: Creates tar.gz from Docker volume
- Assumes volume name: `octolab_{lab.id}_lab_evidence` (line 36)
- **Gap**: Assumes Docker Compose volumes, not k8s PVCs

**`backend/app/models/lab.py`** (94 lines)
- Fields: `id` (UUID), `owner_id` (FK to User), `recipe_id`, `status`, `connection_url`
- Status enum: REQUESTED, PROVISIONING, READY, ENDING, FINISHED, FAILED
- Index: `ix_labs_owner_id` for tenant isolation queries

---

## 4. Deployment Reality Check (k3s)

### Container Images Referenced
- **Attacker**: `octobox-beta:dev` (local build, `imagePullPolicy: IfNotPresent`)
- **Sidecar**: `bonigarcia/novnc:1.3.0` (Docker Hub, `imagePullPolicy: IfNotPresent`)

### Image Import Strategy
- **Current**: Manual import via `docker save | sudo k3s ctr images import -`
- **Scripts**: `scripts/octobox-build-import.sh` automates this
- **Freshness**: Script removes old image before re-import (ensures latest build)

### Port Exposure Analysis
- ✅ **Port 5900 (VNC)**: NOT exposed via Service or Ingress (bound to localhost in pod)
- ✅ **Port 6080 (noVNC)**: Exposed via ClusterIP Service and Traefik Ingress
- ✅ **Security check**: `octobox-deploy.sh` verifies Service doesn't expose 5900 (line 78-85)

### Namespace Usage
- **Current**: Single namespace `octolab-labs` for all labs
- **Namespace definition**: `infra/base/namespaces/octolab-labs.yaml`
- **Label**: `app.octolab.io/role: labs`
- **Risk**: All labs share same namespace; no isolation

### ReplicaSet Considerations
- **Replicas**: 1 (single instance)
- **Rollout**: Standard Deployment rollout (no canary/blue-green)
- **Issue**: If deployment updated, old ReplicaSet may persist (handled by reset script)

---

## 5. Isolation & Threat Model (Current State)

### Can One Lab Reach Another?
**Answer: YES, by default**
- All labs share `octolab-labs` namespace
- Pods can communicate via Service DNS names or pod IPs
- NetworkPolicy exists but may not be enforced (k3s flannel limitation)
- **Mitigation**: VNC bound to localhost (prevents direct VNC access), but pods can still reach each other's network services

### Namespace Usage
- **Current**: Single shared namespace (`octolab-labs`)
- **Per-lab namespace**: ❌ Not implemented
- **Backend integration**: ❌ Backend has no k8s namespace creation logic

### NetworkPolicy Enforcement
- **Policy exists**: `infra/apps/octobox-beta/networkpolicy.yaml`
- **Enforcement**: Unknown (k3s default flannel may ignore)
- **Scope**: Only restricts ingress to noVNC port (6080) from Traefik
- **Gap**: No egress restrictions, no inter-pod restrictions within namespace

### Secrets Handling
- **Current**: Hardcoded Secret `octobox-beta-novnc-secret` with password `octo123`
- **Per-lab secrets**: ❌ Not implemented
- **Backend generation**: ❌ Backend does not create k8s Secrets
- **Risk**: Same password for all labs, stored in plaintext

### Trust Client-Supplied IDs Anti-Patterns
- ✅ **Good**: Backend filters labs by `owner_id` (line 116 in `lab_service.py`)
- ✅ **Good**: Endpoints return 404 (not 403) if lab not owned by user
- ⚠️ **Risk**: If backend compromised, attacker could access any lab ID (but still filtered by `owner_id`)

---

## 6. Gaps to Reach "Isolation v1"

### Minimal Set of Repo Changes Needed

#### 6.1 Per-Lab Namespace Isolation
**Required changes:**
- Create namespace per lab: `lab-{lab.id}` (or `octolab-lab-{lab.id}`)
- Backend k8s client: Add kubectl/kubernetes Python client integration
- Namespace lifecycle: Create on lab creation, delete on lab termination
- **Files to modify:**
  - `backend/app/runtime/k8s_runtime.py` (new file)
  - `backend/app/runtime/__init__.py` (add k8s runtime option)
  - `backend/app/services/lab_service.py` (namespace creation logic)

#### 6.2 Dynamic Secret Generation
**Required changes:**
- Generate random VNC password per lab (e.g., 16-char alphanumeric)
- Create k8s Secret per lab in lab's namespace
- Update Deployment to reference lab-specific Secret
- **Files to modify:**
  - `backend/app/services/lab_service.py` (password generation)
  - `infra/apps/octobox-beta/deployment.yaml` (use Secret name from env var or ConfigMap)
  - `backend/app/runtime/k8s_runtime.py` (Secret creation)

#### 6.3 Gateway/No-Exposed-Target Pattern
**Current**: Targets (if any) would be in same namespace as attacker
**Required changes:**
- Deploy targets in separate namespace or isolated network
- Gateway/proxy pattern: Attacker → Gateway → Targets (for PCAP/logging)
- **Files to create:**
  - `infra/apps/gateway/` (new gateway deployment)
  - `backend/app/services/gateway_service.py` (gateway orchestration)

#### 6.4 Policy Enforcement Considerations
**Required changes:**
- Verify NetworkPolicy enforcement (test on k3s or migrate to CNI that enforces)
- Add egress NetworkPolicy: Restrict attacker pod egress to gateway only
- Add ingress NetworkPolicy: Deny inter-pod communication within namespace
- **Files to modify:**
  - `infra/apps/octobox-beta/networkpolicy.yaml` (add egress rules)
  - `infra/apps/octobox-beta/kustomization.yaml` (apply per-lab namespace)

#### 6.5 Backend-k8s Integration
**Required changes:**
- Replace Docker Compose runtime with k8s runtime (or add as option)
- kubectl/kubernetes client: Use `kubernetes` Python library or `kubectl` subprocess
- Template rendering: Use Jinja2 or kustomize to generate per-lab manifests
- **Files to create:**
  - `backend/app/runtime/k8s_runtime.py` (new k8s runtime implementation)
  - `backend/app/k8s/templates/` (kustomize overlays or Jinja2 templates)

---

## 7. Recommended Next Slice Options

### Option A: Docker Compose Per-Lab with Isolated Bridge Networks + Gateway

**Approach:**
- Keep current Docker Compose runtime
- Create isolated bridge network per lab: `octolab_{lab.id}_network`
- Deploy gateway container in each lab network (for PCAP/logging)
- Attacker and targets connect via gateway (no direct access)

**Pros:**
- ✅ Reuses existing `ComposeLabRuntime` (minimal backend changes)
- ✅ Docker bridge networks provide native isolation
- ✅ Lower complexity (no k8s namespace management)
- ✅ Faster iteration (Docker Compose is simpler than k8s)

**Cons:**
- ❌ Not k8s-native (doesn't leverage k3s investment)
- ❌ Requires Docker daemon on backend host (or Docker-in-Docker)
- ❌ Scaling limitations (single host)
- ❌ No k8s resource management (CPU/memory limits)

**Complexity:** Low-Medium  
**Cost:** Low (reuses existing Docker Compose infrastructure)  
**Reusable parts:**
- `backend/app/runtime/compose_runtime.py` (extend for network creation)
- `images/octobox-beta/` (attacker image)
- `backend/app/services/evidence_service.py` (Docker volume access)

**Files to modify:**
- `backend/app/runtime/compose_runtime.py` (add network creation)
- `octolab-hackvm/docker-compose.yml` (add gateway service, network config)
- `backend/app/services/gateway_service.py` (new gateway orchestration)

---

### Option B: k3s Path - Namespace-Per-Lab + Attacker/noVNC + Gateway + Best-Effort NetworkPolicy

**Approach:**
- Create namespace per lab: `lab-{lab.id}`
- Deploy attacker pod + noVNC sidecar in lab namespace
- Deploy gateway pod in lab namespace (for PCAP/logging)
- Deploy targets (if any) in separate namespace or isolated network
- Apply NetworkPolicy per namespace (best-effort enforcement)

**Pros:**
- ✅ Leverages k3s investment (k8s-native)
- ✅ Namespace isolation (stronger than Docker networks)
- ✅ Resource limits (CPU/memory via k8s)
- ✅ Scalable (multi-node k3s cluster possible)
- ✅ Reuses existing k8s manifests (extend for per-lab)

**Cons:**
- ❌ Higher complexity (k8s namespace/Secret/Deployment management)
- ❌ NetworkPolicy enforcement uncertain (k3s flannel limitation)
- ❌ Requires k8s client library or kubectl subprocess
- ❌ Slower iteration (k8s API calls vs. Docker Compose)

**Complexity:** Medium-High  
**Cost:** Medium (requires k8s client integration, template rendering)  
**Reusable parts:**
- `infra/apps/octobox-beta/` (all manifests, extend with kustomize overlays)
- `images/octobox-beta/` (attacker image)
- `scripts/octobox-*.sh` (deployment automation)

**Files to create:**
- `backend/app/runtime/k8s_runtime.py` (k8s runtime implementation)
- `backend/app/k8s/templates/` (kustomize overlays or Jinja2 templates)
- `infra/apps/octobox-beta/base/` (base kustomize resources)
- `infra/apps/octobox-beta/overlays/` (per-lab overlays)

**Files to modify:**
- `backend/app/runtime/__init__.py` (add k8s runtime option)
- `backend/app/services/lab_service.py` (namespace/Secret creation)
- `infra/apps/octobox-beta/deployment.yaml` (parameterize Secret name)

---

## 8. Security Recommendations (Immediate)

### Critical (Fix Before Multi-Tenant)
1. **Per-lab namespace**: Implement namespace-per-lab to prevent pod-to-pod communication
2. **Dynamic VNC passwords**: Generate random password per lab, store in lab-specific Secret
3. **Backend k8s integration**: Replace Docker Compose runtime with k8s runtime (or add as option)

### High Priority
4. **NetworkPolicy testing**: Verify NetworkPolicy enforcement on k3s (or migrate to CNI that enforces)
5. **Egress restrictions**: Add NetworkPolicy egress rules to restrict attacker pod outbound access
6. **TLS on Ingress**: Enable cert-manager and TLS for production

### Medium Priority
7. **Evidence access control**: Verify evidence endpoint enforces tenant isolation (currently relies on `owner_id` filtering)
8. **Secret rotation**: Implement VNC password rotation (if passwords are long-lived)

---

## 9. Conclusion

**Current State:** The repo has a working single-instance OctoBox deployment with noVNC access and evidence logging. The backend has a solid foundation (models, API endpoints, tenant isolation) but uses Docker Compose, not k8s, for lab provisioning.

**Biggest Gap:** No per-lab isolation. All labs share the same namespace, use the same VNC password, and can potentially reach each other's pods.

**Safest Next Step:** **Option A (Docker Compose)** is faster to implement and provides immediate isolation via Docker bridge networks. **Option B (k8s)** is more scalable but requires significant backend changes and NetworkPolicy enforcement verification.

**Recommendation:** Start with **Option A** to achieve isolation quickly, then migrate to **Option B** once k8s runtime is implemented and NetworkPolicy enforcement is verified.

---

**Report generated by:** Cursor Agent  
**Repository:** `/home/architect/octolab_mvp`  
**Key files inspected:** 30+ files across `backend/`, `infra/`, `images/`, `scripts/`

