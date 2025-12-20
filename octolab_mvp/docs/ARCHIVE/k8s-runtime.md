> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# Kubernetes Runtime for OctoLab

## Overview

The Kubernetes runtime (`K8sLabRuntime`) enables OctoLab to provision labs on Kubernetes (k3s) instead of Docker Compose. Each lab gets its own namespace with isolated resources.

## Configuration

### Environment Variables

Set `OCTOLAB_RUNTIME=k8s` to enable the Kubernetes runtime:

```bash
export OCTOLAB_RUNTIME=k8s
```

### Kubernetes Configuration

Optional environment variables (via `.env` or environment):

- `OCTOLAB_K8S_KUBECONFIG`: Path to kubeconfig file (defaults to `~/.kube/config` or in-cluster config)
- `OCTOLAB_K8S_CONTEXT`: Kubernetes context name (optional)
- `OCTOLAB_K8S_INGRESS_ENABLED`: Enable Ingress creation for labs (default: `false`)
- `OCTOLAB_K8S_BASE_DOMAIN`: Base domain for Ingress hosts (default: `octolab.local`)

### Example `.env` Configuration

```bash
# Runtime selection
OCTOLAB_RUNTIME=k8s

# Kubernetes settings
OCTOLAB_K8S_KUBECONFIG=/home/user/.kube/config
OCTOLAB_K8S_CONTEXT=k3s-default
OCTOLAB_K8S_INGRESS_ENABLED=true
OCTOLAB_K8S_BASE_DOMAIN=octolab.local
```

## Prerequisites

1. **kubectl access**: The backend must have `kubectl` available and configured to access your k3s cluster
2. **Permissions**: The kubeconfig user/ServiceAccount must have permissions to:
   - Create/delete namespaces
   - Create/delete Deployments, Services, Ingress, Secrets, PVCs
   - Exec into pods (for evidence download)

3. **Attacker image**: The `octobox-beta:dev` image must be available in k3s (imported via `k3s ctr images import`)

## Lab Provisioning

When a lab is created via `POST /api/labs`, the runtime:

1. **Creates namespace**: `lab-{lab.id}` with labels for isolation
2. **Creates Secret**: Random VNC password stored in `octobox-{lab.id}-vnc-secret`
3. **Creates PVC**: `octobox-{lab.id}-evidence` for `/evidence` storage
4. **Creates Deployment**: OctoBox + noVNC sidecar containers
5. **Creates Service**: ClusterIP exposing port 6080 only (VNC port 5900 is NOT exposed)
6. **Creates Ingress** (if enabled): `lab-{lab.id}.{base_domain}` → Service:6080

### Resource Naming

All resources are named deterministically from the lab UUID:
- Namespace: `lab-{lab.id}`
- Deployment: `octobox-{lab.id}`
- Service: `octobox-{lab.id}-novnc`
- Secret: `octobox-{lab.id}-vnc-secret`
- PVC: `octobox-{lab.id}-evidence`

### Labels

All resources include labels for isolation and filtering:
- `app.octolab.io/lab-id: {lab.id}`
- `app.octolab.io/owner-id: {lab.owner_id}`

## Security

### Isolation

- **Per-lab namespaces**: Each lab runs in its own namespace, preventing cross-lab pod communication
- **Server-controlled naming**: All resource names derived from lab.id (UUID), not client input
- **Label verification**: Before deleting a namespace, labels are verified to match the lab

### VNC Security

- **Localhost-only**: VNC binds to `127.0.0.1:5900` inside the pod (via `VNC_LOCALHOST=1`)
- **No direct VNC exposure**: Port 5900 is never exposed via Service or Ingress
- **noVNC only**: Access is only through the noVNC sidecar on port 6080
- **Dynamic passwords**: Each lab gets a random VNC password (16 chars, URL-safe)

### Evidence Access

- **Tenant isolation**: Evidence download endpoint verifies `lab.owner_id == current_user.id` (returns 404 if not owner)
- **Pod access**: Uses `kubectl exec` with explicit namespace and pod name derived from lab.id
- **Streaming**: Evidence tar.gz is streamed directly without temp files on the API server

## Lab Termination

When a lab is deleted via `DELETE /api/labs/{lab_id}`, the runtime:

1. **Verifies namespace labels** match the lab (security check)
2. **Deletes namespace** (cascades to all resources: Deployment, Service, Ingress, Secret)
3. **PVC handling**: PVC is deleted with namespace (evidence is lost unless manually preserved)

### Evidence Preservation (Future)

For MVP, evidence is deleted with the namespace. Future enhancements could:
- Move PVC to a "graveyard" namespace before deleting lab namespace
- Implement evidence retention policies with TTL
- Export evidence to external storage before deletion

## Evidence Download

The evidence download endpoint (`GET /api/labs/{lab_id}/evidence`) automatically detects the runtime:

- **k8s runtime**: Uses `kubectl exec` to stream `tar -cz -C /evidence .` from the pod
- **compose runtime**: Uses Docker volume mounts (existing behavior)

The response is a streaming `tar.gz` containing:
- `commands.log`: Command transcript from `octolog-shell`
- `commands.time`: Timing data from `script`
- `metadata.json`: SHA256 checksums and metadata

## Accessing Labs

### With Ingress Enabled

If `OCTOLAB_K8S_INGRESS_ENABLED=true`, labs are accessible at:
```
http://lab-{lab.id}.{base_domain}/
```

Example: `http://lab-123e4567-e89b-12d3-a456-426614174000.octolab.local/`

### Without Ingress (Port-Forward)

If ingress is disabled, use `kubectl port-forward`:

```bash
# Get service name
SERVICE_NAME="octobox-{lab-id}-novnc"
NAMESPACE="lab-{lab-id}"

# Port forward
kubectl port-forward -n $NAMESPACE svc/$SERVICE_NAME 6080:6080

# Access at http://localhost:6080
```

## Troubleshooting

### Check Lab Resources

```bash
LAB_ID="your-lab-id"
NAMESPACE="lab-${LAB_ID}"

# List all resources
kubectl get all -n $NAMESPACE

# Check deployment status
kubectl rollout status deployment/octobox-${LAB_ID} -n $NAMESPACE

# View pod logs
kubectl logs -n $NAMESPACE -l app.octolab.io/lab-id=${LAB_ID} -c octobox-beta
kubectl logs -n $NAMESPACE -l app.octolab.io/lab-id=${LAB_ID} -c novnc
```

### Verify VNC Security

```bash
# Check VNC is localhost-only
POD_NAME=$(kubectl get pod -n $NAMESPACE -l app.octolab.io/lab-id=${LAB_ID} -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n $NAMESPACE $POD_NAME -c octobox-beta -- ss -tlnp | grep 5900
# Expected: 127.0.0.1:5900 (NOT 0.0.0.0:5900)

# Verify Service only exposes 6080
kubectl get svc octobox-${LAB_ID}-novnc -n $NAMESPACE -o yaml | grep -E "port:|targetPort:"
# Expected: port: 6080, targetPort: 6080 (no 5900)
```

### Check Evidence

```bash
# List evidence files in pod
kubectl exec -n $NAMESPACE $POD_NAME -c octobox-beta -- ls -la /evidence

# View commands.log
kubectl exec -n $NAMESPACE $POD_NAME -c octobox-beta -- cat /evidence/commands.log
```

## Differences from Compose Runtime

| Feature | Compose Runtime | k8s Runtime |
|---------|----------------|-------------|
| Isolation | Docker networks | Kubernetes namespaces |
| Resource naming | `octolab_{lab.id}` | `lab-{lab.id}` namespace |
| Evidence storage | Docker volumes | Kubernetes PVCs |
| Evidence download | Docker volume mount | `kubectl exec` tar stream |
| VNC password | Hardcoded (MVP) | Random per lab |
| Access method | Direct host port | Ingress or port-forward |

## Migration Notes

- **Existing labs**: Labs created with Compose runtime continue to work; runtime is per-lab at creation time
- **Evidence format**: Evidence format is identical (commands.log, commands.time, metadata.json)
- **Connection URL**: For k8s labs without ingress, `connection_url` may be `None` (port-forward required)

