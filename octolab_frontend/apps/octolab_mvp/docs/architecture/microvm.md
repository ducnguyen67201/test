# MicroVM Architecture

This document describes OctoLab's Firecracker-based microVM architecture, including the data flow, security model, and threat analysis.

## Overview

OctoLab uses Firecracker microVMs to provide strong isolation between labs. Each lab runs inside its own VM, with Docker Compose running inside the VM to orchestrate the actual lab containers.

```
┌─────────────────────────────────────────────────────────────────────┐
│                           Host (Hetzner/WSL)                        │
│                                                                     │
│  ┌─────────────────┐    ┌──────────────────┐                       │
│  │  Backend API    │    │  microvm-netd    │ ← Root process        │
│  │  (unprivileged) │    │  (network setup) │                       │
│  │  port 8000      │    │  Unix socket     │                       │
│  └────────┬────────┘    └────────┬─────────┘                       │
│           │                      │                                  │
│           │ vsock (control)      │ ip link add/del                  │
│           │                      │ (bridge + TAP)                   │
│           ▼                      ▼                                  │
│  ┌──────────────────────────────────────────────────────┐          │
│  │                  Firecracker VM                       │          │
│  │                                                       │          │
│  │  ┌─────────────────┐    ┌──────────────────┐         │          │
│  │  │  Guest Agent    │    │  Docker Daemon   │         │          │
│  │  │  (Python)       │    │  (dockerd)       │         │          │
│  │  │  vsock:5000     │    └────────┬─────────┘         │          │
│  │  └─────────────────┘             │                   │          │
│  │           │                      │ docker compose    │          │
│  │           │ upload bundle        │                   │          │
│  │           ▼                      ▼                   │          │
│  │  ┌──────────────────────────────────────────────┐   │          │
│  │  │           Lab Containers                      │   │          │
│  │  │  ┌──────────────┐   ┌───────────────────┐    │   │          │
│  │  │  │ Attacker Box │   │ Vulnerable Target │    │   │          │
│  │  │  │ (OctoBox)    │   │ (recipe-defined)  │    │   │          │
│  │  │  └──────────────┘   └───────────────────┘    │   │          │
│  │  └──────────────────────────────────────────────┘   │          │
│  │                                                       │          │
│  │  Network: TAP → Bridge → NAT → Host                  │          │
│  └──────────────────────────────────────────────────────┘          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Components

### Backend API (Unprivileged)

The FastAPI backend orchestrates lab lifecycle but runs without elevated privileges.

**Responsibilities:**
- User authentication and authorization
- Lab state management
- Recipe loading
- VM lifecycle orchestration (via vsock)
- Evidence collection

**Does NOT:**
- Create network interfaces (delegates to netd)
- Run with root privileges
- Access other users' resources

### microvm-netd (Privileged)

A minimal root process that creates and destroys network resources.

**Protocol:**
```json
// Create network for lab
{"op": "create", "lab_id": "uuid-string"}
→ {"ok": true, "result": {"bridge": "obr<10hex>", "tap": "otp<10hex>"}}

// Destroy network
{"op": "destroy", "lab_id": "uuid-string"}
→ {"ok": true, "result": {"bridge_deleted": "...", "tap_deleted": "..."}}

// Ping (health check)
{"op": "ping"}
→ {"ok": true, "result": {"status": "ok", "version": "1.0"}}
```

**Security model:**
- Socket at `/run/octolab/microvm-netd.sock`
- Group `octolab` can read/write (mode 0660)
- ALL interface names derived from lab_id (never from client input)
- Validates UUID format strictly
- Idempotent operations (safe retries)

### Guest Agent (In-VM)

A Python agent running inside each VM, communicating via vsock.

**Responsibilities:**
- Receive project bundle (compose.yml + env)
- Run `docker compose up/down`
- Report status back to host
- Stream logs/evidence on request

**Protocol (vsock port 5000):**
```json
{"op": "ping"} → {"ok": true}
{"op": "upload_project", "bundle": "<base64>"} → {"ok": true}
{"op": "compose_up"} → {"ok": true, "status": "running"}
{"op": "compose_down"} → {"ok": true}
{"op": "status"} → {"ok": true, "containers": [...]}
```

## Lab Lifecycle

### 1. Lab Creation Request

```
User → POST /api/labs
       {recipe_id: "...", intent: "..."}
```

### 2. Network Setup

```
Backend → netd: {"op": "create", "lab_id": "abc123..."}
netd → ip link add obr_abc123... type bridge
netd → ip tuntap add otp_abc123... mode tap
netd → (configure NAT rules)
netd → Backend: {"ok": true, "bridge": "obr_abc123...", "tap": "otp_abc123..."}
```

### 3. VM Boot

```
Backend → firecracker --api-sock /path/to/sock --config-file /path/to/config.json
Backend → (wait for vsock agent on port 5000)
```

### 4. Project Upload

```
Backend → vsock: {"op": "upload_project", "bundle": "<base64 tarball>"}
Agent → (extract to /var/lib/octolab/project/)
Agent → vsock: {"ok": true}
```

### 5. Compose Up

```
Backend → vsock: {"op": "compose_up"}
Agent → docker compose up -d
Agent → vsock: {"ok": true, "containers": ["attacker", "target"]}
```

### 6. Lab Ready

```
Backend → DB: UPDATE labs SET status='ready'
User → (connect via noVNC/Guacamole)
```

### 7. Teardown

```
Backend → vsock: {"op": "compose_down"}
Backend → (SIGTERM to firecracker)
Backend → netd: {"op": "destroy", "lab_id": "..."}
Backend → (cleanup state directory)
```

## Networking

### Interface Naming

All interface names are deterministically derived from lab_id:

```
lab_id = "12345678-1234-1234-1234-123456789abc"
hex_part = "1234567812"  # First 10 hex chars (no dashes)
bridge = "obr" + hex_part = "obr1234567812"  # 13 chars
tap = "otp" + hex_part = "otp1234567812"     # 13 chars
```

This ensures:
- Names fit in IFNAMSIZ (15 chars)
- No client can influence interface names
- Deterministic cleanup is possible

### Network Topology

```
┌─────────────────────────────────────────────────────────┐
│                        Host                              │
│                                                          │
│   eth0 (public IP)                                       │
│     │                                                    │
│     │ NAT (iptables MASQUERADE)                         │
│     │                                                    │
│   obr_<lab_id> (bridge, 10.x.x.1/24)                    │
│     │                                                    │
│   otp_<lab_id> (tap, connected to bridge)               │
│     │                                                    │
└─────┼────────────────────────────────────────────────────┘
      │
      │ virtio-net
      │
┌─────┼────────────────────────────────────────────────────┐
│     │                    Firecracker VM                  │
│     │                                                    │
│   eth0 (10.x.x.2/24)                                    │
│     │                                                    │
│   docker0 (172.17.0.1/16)                               │
│     ├── attacker (172.17.0.2)                           │
│     └── target (172.17.0.3)                             │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

## Security Model

### Threat Model

We assume **hostile tenants**:
- Users may attempt to escape their lab
- Users may attempt to access other users' labs
- Users may attempt to DoS the platform
- Users may attempt to exfiltrate data

### Isolation Layers

1. **VM Boundary** (Firecracker)
   - Hardware-backed isolation via KVM
   - Minimal attack surface (no BIOS, no USB, minimal devices)
   - seccomp filters on hypervisor

2. **Network Isolation**
   - Each lab gets its own bridge/TAP
   - No direct host access from VM
   - NAT for outbound (controlled egress)

3. **Resource Limits**
   - CPU: Limited vCPUs per VM
   - Memory: Bounded at VM creation
   - Disk: Ephemeral rootfs, bounded size
   - Network: Rate limiting possible

4. **Identity Isolation**
   - All resources tagged with lab_id
   - Backend enforces owner_id checks
   - No cross-tenant resource access

### What We Prevent

| Threat | Mitigation |
|--------|------------|
| VM escape | Firecracker + KVM |
| Cross-lab access | Separate VMs, network isolation |
| Host filesystem access | VM has no host mounts |
| Privilege escalation | Backend is unprivileged |
| DoS via resource exhaustion | Per-lab limits |
| Network sniffing | Separate bridges per lab |

### What We Don't Prevent

| Threat | Reason | Mitigation |
|--------|--------|------------|
| Outbound attack | Lab may need internet | Egress filtering, logging |
| In-VM DoS | User owns their lab | Timeouts, quotas |
| Malware in lab | Intentional (CVE rehearsal) | Contained to VM |

## Failure Modes

### netd Unavailable

```
Backend startup → doctor checks netd socket
                → FATAL if socket missing/unresponsive
                → Backend refuses to start
```

**No fallback to compose.** This is intentional.

### VM Boot Failure

```
Lab creation → firecracker starts
            → vsock agent doesn't respond in timeout
            → Lab marked FAILED
            → Cleanup triggered
```

### Network Creation Failure

```
Lab creation → netd create returns error
            → Lab creation fails immediately
            → No VM started
```

## Monitoring

### Health Endpoints

```
GET /health                    # Basic health
GET /admin/microvm/doctor      # Full diagnostics
GET /admin/microvm/smoke       # Run smoke test
```

### Key Metrics

- Labs by state (requested, provisioning, ready, ending, failed)
- VM boot time (p50, p95, p99)
- netd operations/second
- Evidence collection success rate

### Log Locations

| Component | Location |
|-----------|----------|
| Backend | `journalctl -u octolab-backend` |
| netd | `journalctl -u microvm-netd` |
| netd (WSL) | `/run/octolab/microvm-netd.log` |
| Firecracker | `<state_dir>/<lab_id>/firecracker.log` |
| Guest agent | Inside VM at `/var/log/guest-agent.log` |

## Development Notes

### WSL Limitations

1. **No jailer**: Jailer requires cgroups v1 setup not available in WSL
   - Use `DEV_UNSAFE_ALLOW_NO_JAILER=true`
   - Fine for development, NOT for production

2. **No systemd by default**: Run netd manually
   - `sudo infra/microvm/netd/run_netd.sh --daemon`

3. **Nested virtualization required**: Enable in `.wslconfig`
   ```ini
   [wsl2]
   nestedVirtualization=true
   ```

### Testing Without VMs

Use `OCTOLAB_RUNTIME=compose` for development without Firecracker:

```bash
octolabctl enable-runtime compose
```

This runs labs directly in Docker, without VM isolation. **Not for production.**
