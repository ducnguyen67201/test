# OctoLab Documentation

OctoLab is a **CVE rehearsal platform** for penetration testers and red teams. Users describe an engagement scenario, OctoLab spins up an isolated lab (attacker-box + vulnerable target), they rehearse payloads safely, and the platform generates an evidence report (commands, logs, summary).

**Goal**: Exploit rehearsal + evidence generation, not generic training.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture](#architecture)
3. [Runtimes & Isolation](#runtimes--isolation)
4. [MicroVM Networking & microvm-netd](#microvm-networking--microvm-netd)
5. [Developer Workflow](#developer-workflow)
6. [Operations & Housekeeping](#operations--housekeeping)
7. [Evidence & Logging](#evidence--logging)
8. [Additional Guides](#additional-guides)
9. [Documentation Policy](#documentation-policy)

---

## Quick Start

| Guide | Who | Description |
|-------|-----|-------------|
| [Dev Quickstart](dev/quickstart.md) | Developers | Single-machine dev setup (~30 min) |
| [Hetzner Deploy](ops/hetzner.md) | Operators | Fresh Ubuntu 24.04 production install |
| [Architecture](architecture/microvm.md) | Everyone | MicroVM flow + threat model (15 min read) |

### Fastest Path (Compose Runtime)

```bash
cd ~/apps/octolab_mvp

# Backend setup
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" && cd ..

# Bootstrap and run
make dev-up    # Creates .env.local, starts Guacamole, runs migrations
make dev       # Start FastAPI server

# Verify
curl http://localhost:8000/health
```

### Fastest Path (Firecracker Runtime)

```bash
# Install prerequisites (root required)
sudo infra/octolabctl/octolabctl.sh install

# Add yourself to octolab group, then re-login or:
newgrp octolab

# Start network daemon
sudo infra/octolabctl/octolabctl.sh netd start

# Verify setup
infra/octolabctl/octolabctl.sh doctor
infra/octolabctl/octolabctl.sh smoke

# Enable Firecracker runtime
infra/octolabctl/octolabctl.sh enable-runtime firecracker

# Then run backend as normal
make dev-up && make dev
```

---

## Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                           Host Machine                              │
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

### Components

| Component | Role |
|-----------|------|
| **Backend API** | FastAPI server (unprivileged), orchestrates lab lifecycle |
| **microvm-netd** | Root daemon that creates/destroys bridges and TAP devices |
| **Guest Agent** | Python agent inside VM, communicates via vsock |
| **OctoBox** | Attacker-box container with VNC desktop + command logging |
| **Lab Gateway** | Captures network traffic (pcap) for evidence |

### Lab Lifecycle

Labs progress through states: `requested` → `provisioning` → `ready` → `ending` → `finished` (or `failed`).

1. **Request**: User creates lab via `POST /api/labs`
2. **Network Setup**: netd creates bridge + TAP for the lab
3. **VM Boot**: Firecracker starts with vsock agent
4. **Project Upload**: Backend sends compose bundle via vsock
5. **Compose Up**: Guest agent runs `docker compose up`
6. **Ready**: Lab accessible via noVNC/Guacamole
7. **Teardown**: Compose down → VM kill → network destroy

A background teardown worker processes labs in `ending` state asynchronously, ensuring non-blocking API responses and self-healing on restart.

### Security Model

We assume **hostile tenants** who may attempt to:
- Escape their lab
- Access other users' labs
- DoS the platform
- Exfiltrate data

**Isolation layers:**

| Layer | Mechanism |
|-------|-----------|
| VM Boundary | Firecracker + KVM (hardware isolation) |
| Network | Per-lab bridge/TAP, no cross-lab traffic |
| Resources | Bounded vCPUs, memory, disk per VM |
| Identity | All resources tagged with lab_id, owner_id checks |

**Multi-tenancy rules:**
- All lab queries filter by `owner_id = current_user.id`
- Return 404 (not 403) for labs not owned by current user
- Derive owner_id from JWT, never from request payload

---

## Runtimes & Isolation

OctoLab supports multiple lab runtimes, selected via `OCTOLAB_RUNTIME`:

| Runtime | Description | Use Case |
|---------|-------------|----------|
| `firecracker` | MicroVM isolation | **Production**, hostile tenants |
| `compose` | Docker Compose | Development, simple deployments |
| `k8s` | Kubernetes | Large-scale deployments |
| `noop` | No-op (testing) | CI/test environments |

**Important**: No runtime fallback. If `OCTOLAB_RUNTIME=firecracker` is set and prerequisites fail, the backend refuses to start. This is intentional security design.

### Compose Runtime (Development)

The compose runtime runs labs directly in Docker containers on the host. Useful for development but provides weaker isolation than microVMs.

- Containers run as non-root, no `--privileged`
- Two-network model: `lab_net` (internal) and `egress_net` (controlled uplink)
- See [compose-runtime-ops.md](compose-runtime-ops.md) for operations guide

### Firecracker Runtime (Production)

The Firecracker runtime provides kernel-level isolation via microVMs:

- Each lab gets its own VM with dedicated Linux kernel
- Hardware-backed isolation via KVM
- Minimal attack surface (no BIOS, no USB, minimal devices)
- Guest agent communicates via vsock

**Requirements:**
- `/dev/kvm` available and accessible
- Firecracker + jailer binaries installed
- Kernel image (vmlinux) and rootfs (ext4)
- microvm-netd running

### Runtime Selection

```bash
# Switch runtime
infra/octolabctl/octolabctl.sh enable-runtime firecracker
infra/octolabctl/octolabctl.sh enable-runtime compose

# Check current runtime
grep OCTOLAB_RUNTIME backend/.env.local

# Always restart backend after switching
```

---

## MicroVM Networking & microvm-netd

The `microvm-netd` daemon handles privileged network operations for Firecracker labs. It runs as root and creates/destroys Linux bridges and TAP devices.

### What microvm-netd Does

1. Creates per-lab bridge (`obr<10hex>`) and TAP (`otp<10hex>`) interfaces
2. Configures NAT rules for VM egress
3. Provides RPC socket for backend to request network operations
4. Cleans up interfaces on lab teardown

**Security model:**
- Socket at `/run/octolab/microvm-netd.sock` (mode 0660, group `octolab`)
- Interface names derived from lab_id (never from client input)
- Validates UUID format strictly
- Idempotent operations (safe retries)

### Paths and Permissions

| Path | Owner | Mode | Description |
|------|-------|------|-------------|
| `/run/octolab/` | root:octolab | 0750 | Runtime directory |
| `/run/octolab/microvm-netd.sock` | root:octolab | 0660 | RPC socket |
| `/run/octolab/microvm-netd.pid` | root | 0644 | PID file |
| `/var/log/octolab/microvm-netd.log` | root:octolab | 0640 | Log file |

### WSL (No Systemd)

WSL doesn't have systemd by default, so netd must be managed manually:

```bash
# Start/stop/restart
sudo ./infra/octolabctl/octolabctl.sh netd start
sudo ./infra/octolabctl/octolabctl.sh netd stop
sudo ./infra/octolabctl/octolabctl.sh netd restart

# Check status (exit codes: 0=running, 1=stopped, 2=degraded)
./infra/octolabctl/octolabctl.sh netd status

# View logs (redacted by default)
./infra/octolabctl/octolabctl.sh netd logs
./infra/octolabctl/octolabctl.sh netd logs -f        # Follow
./infra/octolabctl/octolabctl.sh netd logs -n 50     # Last 50 lines
./infra/octolabctl/octolabctl.sh netd logs --no-redact  # Unredacted (admin only)
```

**WSL-specific notes:**
- No jailer support (use `DEV_UNSAFE_ALLOW_NO_JAILER=true` for dev only)
- Enable nested virtualization in `.wslconfig`:
  ```ini
  [wsl2]
  nestedVirtualization=true
  ```
- Restart WSL after group changes: `wsl --terminate <distro>`

### Linux with Systemd

```bash
# Install systemd unit
sudo infra/octolabctl/octolabctl.sh netd install

# Manage via systemctl
sudo systemctl start microvm-netd
sudo systemctl status microvm-netd
sudo systemctl enable microvm-netd

# View logs
journalctl -u microvm-netd -f
```

### Group Membership

The backend user must be in the `octolab` group to connect to the socket:

```bash
sudo usermod -aG octolab $USER

# Apply immediately (opens new shell)
newgrp octolab

# Or log out and back in
```

### octolabctl Commands

```bash
# Check all prerequisites
infra/octolabctl/octolabctl.sh doctor

# Install Firecracker + dependencies
sudo infra/octolabctl/octolabctl.sh install

# Run smoke test (boots ephemeral VM)
infra/octolabctl/octolabctl.sh smoke

# Configure backend runtime
infra/octolabctl/octolabctl.sh enable-runtime firecracker
```

---

## Developer Workflow

### Directory Structure

```
octolab_mvp/
├── backend/           # FastAPI backend
│   ├── app/          # Application code
│   │   ├── api/routes/   # HTTP endpoints
│   │   ├── models/       # SQLAlchemy models
│   │   ├── schemas/      # Pydantic schemas
│   │   ├── services/     # Business logic
│   │   └── runtime/      # Lab runtime implementations
│   ├── alembic/      # Database migrations
│   └── tests/        # Test suite
├── frontend/          # React frontend (Vite)
├── infra/             # Infrastructure
│   ├── octolabctl/   # Management tool
│   ├── microvm/      # MicroVM setup + netd
│   ├── firecracker/  # VM assets + guest agent
│   └── guacamole/    # Remote desktop gateway
├── images/            # Docker images (OctoBox)
└── docs/              # Documentation (you are here)
```

### Environment Files

| File | Purpose | Committed |
|------|---------|-----------|
| `backend/.env` | Non-secret defaults | Yes |
| `backend/.env.local` | Local secrets (auto-generated) | No |
| `backend/.env.local.example` | Template for reference | Yes |
| `backend/.env.test` | Test configuration | Yes |

**Important**: `GUAC_ENC_KEY` in `.env.local` encrypts per-lab Guacamole passwords. Do not regenerate after labs are created.

### Common Commands

```bash
# Development workflow
make dev-up          # Bootstrap environment
make dev             # Start FastAPI server
make dev-down        # Stop services
make dev-doctor      # Health check
make dev-status      # Show service status

# Testing
make test            # Run all tests
make test-verbose    # Verbose output
./backend/scripts/test.sh -k test_name  # Specific test

# Database
make db-migrate      # Run migrations
make db-status       # Check migration status

# Guacamole
make guac-up         # Start Guacamole stack
make guac-down       # Stop Guacamole stack
make guac-status     # Show status
make guac-reset      # Full reset (if ERROR page)

# OctoBox image
make dev-rebuild-octobox   # Rebuild with cache bust
make dev-provenance        # Verify image build
```

### Testing

Tests require `APP_ENV=test` and `DATABASE_URL` ending in `_test`:

```bash
# Run all tests
make test

# Run specific test
./backend/scripts/test.sh -k test_name
./backend/scripts/test.sh -v tests/test_file.py::TestClass::test_method

# Mark test as not needing database
@pytest.mark.no_db
```

### Frontend

```bash
cd frontend
npm install && npm run dev   # Dev server at localhost:5173
npm run build               # Production build
```

Uses `VITE_API_URL` env var (defaults to `http://localhost:8000`).

---

## Operations & Housekeeping

### Log Locations

| Component | Linux (systemd) | WSL (manual) |
|-----------|-----------------|--------------|
| Backend | `journalctl -u octolab-backend` | Terminal output |
| netd | `journalctl -u microvm-netd` | `/run/octolab/microvm-netd.log` |
| Firecracker | `<state_dir>/<lab_id>/firecracker.log` | Same |
| Guacamole | `docker logs octolab-guac-web` | Same |

State directory is typically `/var/lib/octolab/microvm/`.

### Garbage Collection

```bash
# Garbage collect expired labs and old evidence
make gc

# Dry-run mode
python3 backend/scripts/run_with_env.py \
  --env backend/.env --env backend/.env.local \
  -- python3 dev/scripts/gc.py --dry-run
```

### Admin Access

Admin endpoints require email in `OCTOLAB_ADMIN_EMAILS`:

```bash
# In backend/.env.local
OCTOLAB_ADMIN_EMAILS=admin@example.com,ops@example.com
```

See [admin-allowlist.md](admin-allowlist.md) for details.

### Health Checks

```bash
# API health
curl http://localhost:8000/health

# DB schema sync
curl http://localhost:8000/health/db

# Full doctor check
infra/octolabctl/octolabctl.sh doctor

# Smoke test (boots ephemeral VM)
infra/octolabctl/octolabctl.sh smoke
```

---

## Evidence & Logging

Each lab produces an evidence bundle containing:

| File | Description |
|------|-------------|
| `commands.log` | Terminal I/O transcript (script PTY format) |
| `commands.time` | Timing data for replay |
| `commands.tsv` | Parsed commands via PROMPT_COMMAND hook |
| `network.json` | Network traffic logs (TShark JSON) |
| `metadata.json` | Lab metadata + SHA256 checksums |

### Evidence Lifecycle

Evidence states: `collecting` → `ready`/`partial`/`unavailable`

- Evidence tied to lab_id and owner_id (tenant isolation)
- Evidence can be sealed with HMAC signature for integrity
- Retention period configurable (default: 72 hours)

### Download Evidence

```bash
# Via API
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/labs/{id}/evidence > evidence.tar.gz

# Extract and verify
tar -xzf evidence.tar.gz
sha256sum commands.log  # Compare with metadata.json

# Replay terminal session
scriptreplay commands.time commands.log
```

See [evidence-collection.md](evidence-collection.md) for technical details.

---

## Additional Guides

These documents provide detailed information for specific topics:

| Document | Description |
|----------|-------------|
| [architecture/microvm.md](architecture/microvm.md) | MicroVM architecture, threat model, protocols |
| [dev/quickstart.md](dev/quickstart.md) | Full developer setup guide |
| [ops/hetzner.md](ops/hetzner.md) | Production deployment on Hetzner |
| [troubleshooting.md](troubleshooting.md) | Common errors and solutions |
| [compose-runtime-ops.md](compose-runtime-ops.md) | Compose runtime operations (network cleanup, etc.) |
| [evidence-collection.md](evidence-collection.md) | Evidence format and collection details |
| [admin-allowlist.md](admin-allowlist.md) | Admin access configuration |

### Archived Documentation

Historical planning documents, investigation reports, and superseded docs are in [ARCHIVE/](ARCHIVE/). These are kept for reference but may be outdated.

---

## Documentation Policy

**This README.md is the primary documentation file.** All key information should be consolidated here.

### When Adding Documentation

1. **First choice**: Add to an existing section in this README
2. **Detailed guides**: Use `dev/`, `ops/`, or `architecture/` subdirectories
3. **Last resort**: Create a new file only if content truly cannot fit elsewhere

### Guidelines

- Keep docs up to date with the microVM-first reality
- Compose runtime is legacy/development-only
- Never scatter docs across many small files
- Link new docs from the "Additional Guides" section above
- Archive obsolete docs rather than deleting (in case of reference)

---

## Getting Help

1. Check [Troubleshooting](troubleshooting.md)
2. Run `octolabctl doctor` for diagnostics
3. Review logs (see Log Locations above)
4. File an issue with:
   - Doctor output
   - Relevant logs (redact secrets!)
   - Steps to reproduce
