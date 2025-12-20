> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# OctoLab Kubernetes Architecture

High-level architecture for the OctoLab platform running on Kubernetes.

## Overview

OctoLab runs on a **single-node k3s cluster** (expandable to multi-node in production) with a namespace-based architecture separating system components from lab workloads.

## Namespaces

### `octolab-system`

System-level components that are long-lived and shared across all users:

- **Ingress Controller** (Traefik)
  - Routes external traffic to services
  - Handles TLS termination
  - Provides WebSocket support for Guacamole

- **cert-manager**
  - Manages TLS certificates (self-signed for dev, Let's Encrypt for production)
  - Automatic certificate renewal

- **Guacamole** (future: G1 slice)
  - `guacamole-web`: Web application (Deployment + Service)
  - `guacd`: Guacamole daemon (Deployment + Service)
  - `guacamole-db`: PostgreSQL database (StatefulSet)

- **OctoLab Backend** (future: G2 slice)
  - `backend-api`: FastAPI application (Deployment + Service)
  - `backend-db`: PostgreSQL database (StatefulSet)

- **Monitoring** (future)
  - Prometheus, Grafana for observability

### `octolab-labs`

Lab workloads that are ephemeral and created per-user:

- **OctoBox Pods**
  - One pod per active lab
  - SSH/RDP accessible via Guacamole
  - Command logging via `octolog-shell` to evidence PVC

- **Lab Target Pods**
  - Vulnerable services per lab (e.g., Apache, WordPress)
  - Isolated per lab via NetworkPolicies

- **Lab Gateway Pods**
  - Network gateway with PCAP capture
  - Routes traffic between OctoBox and targets
  - Writes network logs to evidence PVC

- **Evidence Storage**
  - PVCs per lab (e.g., `lab-{lab-id}-evidence`)
  - Shared between OctoBox and Gateway pods
  - Contains: `commands.log`, `commands.time`, `network.json`

## Network Flows

### External Access

```
Browser
  ↓ (HTTPS)
Traefik Ingress (octolab-system)
  ├─→ /api/* → backend-api Service → FastAPI Pod
  ├─→ /guacamole/* → guacamole-web Service → Guacamole Web Pod
  └─→ / (root) → guacamole-web (default)
```

### Guacamole to OctoBox

```
Guacamole Web (octolab-system)
  ↓ (internal k8s network)
guacd Service (octolab-system)
  ↓ (RDP/SSH protocol)
OctoBox Pod Service (octolab-labs, per-lab)
  ↓
OctoBox Pod (octolab-labs)
```

### Evidence Collection

```
OctoBox Pod (octolab-labs)
  ↓ (writes to shared PVC)
lab-{lab-id}-evidence PVC
  ↑ (reads from shared PVC)
Lab Gateway Pod (octolab-labs)
```

## Component Relationships

### Database Placement

Both databases live in `octolab-system`:

- **Guacamole DB**: Stores Guacamole connection configurations
- **Backend DB**: Stores OctoLab users, labs, recipes, evidence metadata

**Rationale**: System-level, long-lived, benefit from namespace isolation and shared backup strategies.

### Lab Isolation

Each lab gets:

- Dedicated namespace (future: `octolab-labs-{lab-id}`) OR
- Label-based isolation within `octolab-labs` namespace

**Network Policies** (future):
- OctoBox pods can only reach their lab's target pods
- Gateway pods can only reach their lab's OctoBox and targets
- No cross-lab communication

## Current State (G0)

In **G0 (this slice)**, we only set up:

- ✅ k3s cluster (single-node)
- ✅ Traefik ingress controller
- ✅ cert-manager with self-signed issuer
- ✅ Base namespaces (`octolab-system`, `octolab-labs`)

**Not yet deployed:**
- ❌ Guacamole (G1 slice)
- ❌ Backend API (G2 slice)
- ❌ Lab workloads (G3 slice)

## Future Enhancements

### Multi-Node Support

- Add k3s agent nodes for horizontal scaling
- Separate control plane from worker nodes
- Node affinity for lab workloads

### Storage

- Migrate from `local-path` to external storage (NFS, cloud EBS)
- Evidence retention via object storage (S3-compatible)
- Database backups to external storage

### Security

- RBAC: ServiceAccounts with minimal permissions
- NetworkPolicies: Strict pod-to-pod communication rules
- Pod Security Standards: Enforce security contexts
- TLS: Let's Encrypt certificates for production

### Observability

- Prometheus for metrics collection
- Grafana for dashboards
- Centralized logging (Loki, ELK stack)

## Design Principles

1. **Separation of Concerns**: System components vs. lab workloads
2. **Ephemeral Labs**: Labs are created and destroyed dynamically
3. **Evidence Isolation**: Each lab's evidence is stored in a dedicated PVC
4. **Future-Proof**: Architecture supports multi-node, external storage, production TLS

