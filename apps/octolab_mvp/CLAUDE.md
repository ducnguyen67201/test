# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OctoLab is a **CVE rehearsal platform** for penetration testers and red teams. Users describe a real engagement scenario, OctoLab spins up an isolated lab (attacker-box + vulnerable target), they rehearse payloads safely, and the platform generates an evidence report (commands, logs, summary). The goal is exploit rehearsal + evidence generation, not generic training.

## Tech Stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy 2.x (async), Pydantic v2, PostgreSQL, Alembic
- **Frontend**: React + TypeScript (Vite)
- **Infrastructure**: Kubernetes (k3s) with namespace-based isolation, or Docker Compose for local dev
- **Lab Runtime**: OctoBox attacker pod + vulnerable target pods + logging/evidence collection

## Common Commands

### Development Workflow (Recommended)
```bash
make dev-up          # Bootstrap: creates .env.local, starts Guacamole stack, runs migrations
make dev             # Start FastAPI dev server (loads .env and .env.local via run_with_env.py)
make dev-down        # Stop all dev services
make dev-doctor      # Health check for dev environment
make dev-status      # Show status of dev services
```

### Testing
```bash
make test                              # Run all tests (uses backend/.env.test)
make test-verbose                      # Run tests with verbose output
./backend/scripts/test.sh -k test_name # Run specific test by name
./backend/scripts/test.sh -v tests/test_file.py::TestClass::test_method  # Run single test
```

Tests require `APP_ENV=test` and `DATABASE_URL` ending in `_test`. The test harness (`conftest.py`) enforces:
- `APP_ENV=test` environment variable
- Database name ends with `_test`
- Database host is localhost or known test service (unless `ALLOW_REMOTE_TEST_DB=true`)

Use `@pytest.mark.no_db` to mark tests that don't need database access (skips all DB safety checks, allows running without DATABASE_URL).

### Database Migrations
```bash
make db-migrate                        # Run pending migrations (via run_with_env.py)
make db-status                         # Show current Alembic revision
./dev/db_migrate.sh revision --autogenerate -m "description"  # Generate new migration
```

### Guacamole Stack (Remote Desktop Gateway)
```bash
make guac-up          # Start Guacamole stack (includes smoketest)
make guac-down        # Stop Guacamole stack
make guac-status      # Show status
make guac-reset       # Full reset: nuke and recreate (if ERROR page in browser)
make guac-reset-db    # Reset Guac DB only (DESTRUCTIVE)
```

If Guacamole shows a generic "ERROR" page at http://127.0.0.1:8081/guacamole/, run `make guac-reset`.

### k3d Cluster (Local Kubernetes)
```bash
make k3d-up                            # Create k3d cluster
make k3d-down                          # Delete k3d cluster
make k3d-smoke                         # Verify cluster health
make k3d-import-image IMAGE=name:tag   # Import local image
```

### E2E Verification & Debugging
```bash
make e2e-verify                        # Full E2E test (Guac+VNC+evidence)
make e2e-register-verify               # Registration E2E verification
make e2e-evidence-verify               # Evidence collection E2E verification
make snapshot                          # Capture system state for debugging
make gc                                # Garbage collect expired labs and old evidence
```

### Firecracker Runtime (octolabctl)
```bash
sudo infra/octolabctl/octolabctl.sh install           # Install Firecracker + dependencies
sudo infra/octolabctl/octolabctl.sh netd start        # Start network daemon (required for VMs)
sudo infra/octolabctl/octolabctl.sh netd stop         # Stop network daemon
infra/octolabctl/octolabctl.sh doctor                 # Check all prerequisites
infra/octolabctl/octolabctl.sh smoke                  # Run smoke test (boots ephemeral VM)
infra/octolabctl/octolabctl.sh enable-runtime firecracker  # Switch to Firecracker runtime
infra/octolabctl/octolabctl.sh enable-runtime compose      # Switch back to Compose runtime
```

The `microvm-netd` daemon handles privileged network operations (bridges, TAPs) for Firecracker labs. It runs as root and communicates via `/run/octolab/microvm-netd.sock`. The backend user must be in the `octolab` group.

### Frontend Development
```bash
cd frontend
npm install && npm run dev             # Run dev server (localhost:5173)
npm run build                          # Production build
```

Frontend uses `VITE_API_URL` env var (defaults to `http://localhost:8000`). Auth tokens are stored in `localStorage` (`octolab_token`) and managed by `AuthProvider` in `src/hooks/useAuth.tsx`.

### Environment Setup
Backend uses a layered environment file approach:

| File | Purpose | Committed |
|------|---------|-----------|
| `backend/.env` | Non-secret defaults | Yes |
| `backend/.env.local` | Local secrets (auto-generated) | No |
| `backend/.env.local.example` | Template for reference | Yes |
| `backend/.env.test` | Test configuration | Yes |

Created by `make dev-up` or `python3 dev/scripts/ensure_env_local.py`.

**Important**: `GUAC_ENC_KEY` in `.env.local` encrypts per-lab Guacamole passwords. Do not regenerate this key after labs are created or existing labs will fail to decrypt their passwords.

## Architecture

### Backend Structure (`backend/app/`)
- `main.py` - FastAPI app, router registration, lifespan (teardown worker)
- `config.py` - Settings via pydantic-settings (env vars)
- `db.py` - SQLAlchemy async engine and session
- `models/` - SQLAlchemy models (User, Lab, Recipe, Evidence, PortReservation)
- `schemas/` - Pydantic v2 request/response schemas
- `api/routes/` - FastAPI routers (auth, labs, recipes, health, internal, admin, evidence)
- `services/` - Business logic:
  - `lab_service.py`, `lab_orchestrator.py`, `orchestrator_service.py` - Lab lifecycle management
  - `auth_service.py` - User authentication
  - `evidence_service.py`, `evidence_sealing.py` - Evidence collection and integrity
  - `teardown_worker.py` - Background lab cleanup
  - `guacamole_*.py` - Remote desktop integration (client, provisioner, preflight)
  - `port_allocator.py` - Dynamic port allocation for noVNC
  - `runtime_selector.py` - Runtime selection logic
  - `firecracker_*.py` - MicroVM runtime support
- `runtime/` - Lab provisioning backends (ComposeRuntime, K8sRuntime, NoopRuntime, FirecrackerRuntime)
- `helpers/` - Crypto utilities (password encryption, secure generation)

### Lab Runtime Abstraction
The `LabRuntime` protocol (`runtime/base.py`) defines `create_lab()`, `destroy_lab()`, `resources_exist_for_lab()`. Implementations:
- `ComposeLabRuntime` - Docker Compose for local dev (default)
- `K8sLabRuntime` - Kubernetes for large-scale deployments
- `FirecrackerRuntime` - MicroVM isolation (production recommended for hostile tenants)
- `NoopRuntime` - Testing/dry-run

Select via `OCTOLAB_RUNTIME` env var: `compose`, `k8s`, `firecracker`, or `noop`.

**Important**: No runtime fallback. If a runtime is configured and prerequisites fail, the backend refuses to start. This is intentional security design.

### Lab Lifecycle
Labs progress through states: `requested` → `provisioning` → `ready` → `ending` → `finished` (or `failed`).
- A background teardown worker (`teardown_worker.py`) processes labs in `ending` state
- noVNC readiness gating ensures VNC is accessible before marking lab `ready`
- Transitions must be explicit and persisted; never leave labs in undefined states
- `PortReservation` model manages noVNC host port allocation to prevent conflicts
- Labs have TTL via `expires_at`; expired labs are auto-terminated

### Multi-Tenancy
- All lab queries must filter by `owner_id = current_user.id`
- Return 404 (not 403) for labs not owned by current user to avoid leaking existence
- Derive owner_id from JWT, never from request payload

### Kubernetes Architecture
- `octolab-system` namespace: system components (ingress, cert-manager, backend)
- `octolab-labs` namespace: ephemeral lab pods with NetworkPolicy isolation
- Each lab gets dedicated evidence PVC

### Docker Runtime (Local Dev)
When using ComposeLabRuntime:
- Containers run as non-root, no `--privileged`, minimal exposed ports
- Two-network model: `lab_net` (internal) and `egress_net` (controlled uplink)
- Evidence volumes are isolated; only LabGateway captures pcap/logs

### Firecracker Runtime (Production)
When using FirecrackerRuntime:
- Each lab gets its own VM with dedicated Linux kernel (hardware-backed isolation via KVM)
- Guest agent communicates via vsock, receives compose bundles from backend
- Requires `/dev/kvm`, Firecracker binaries, kernel image (vmlinux), rootfs (ext4)
- `microvm-netd` creates per-lab bridge (`obr<hex>`) and TAP (`otp<hex>`) interfaces
- WSL: Requires nested virtualization enabled in `.wslconfig`

### Network Architecture (Production)

```
Browser → nginx (port 80)
              ├── /api/*        → backend:8000 (rewrite prefix)
              ├── /guacamole/*  → octolab-guacamole:8080 (WebSocket support)
              ├── /labs/*       → backend:8000
              └── /*            → frontend static files
```

**Important**: The nginx container must be connected to the `guacamole_guac-internal` Docker network to proxy `/guacamole/` requests. This is configured in `docker-compose.prod.yml` as an external network.

## Key Patterns

- **Async everywhere**: Use async FastAPI endpoints and async DB access
- **SQLAlchemy 2.0 style**: `Mapped[...]`, `mapped_column`, `select()`
- **Thin routers**: Move complex logic into `services/`
- **UUIDs for PKs**: All primary keys are UUIDs
- **Security first**: When in doubt between security and convenience, choose security
- **LLM adapter layer**: LLM calls should go through a dedicated adapter (pluggable provider via config), handle failures gracefully, never send secrets to LLM

## Evidence & Logging

Each Lab produces an evidence bundle that may include:
- Attacker-box shell transcript (e.g. `tty.log`)
- Command log (`commands.tsv`) via `PROMPT_COMMAND` hook
- Target-app logs (e.g. Apache access/error logs)
- Metadata: user, timestamps, recipe, software/version, exploit_family
- Falco events (commands, network, file reads) stored in `Evidence` model with deduplication via `event_hash`

Evidence lifecycle states: `collecting` → `ready`/`partial`/`unavailable`. Evidence can be sealed with HMAC signature for integrity verification.

Evidence is always tied to the correct Lab ID and tenant. Never expose logs from one Lab to a different user. Evidence collection uses container name patterns (`lab-{uuid}-{role}`) to route events to the correct lab.

## Dev Script Safety

Dev scripts in `dev/` and `backend/scripts/` follow these rules:
- **Never source env files directly** in production code paths; use `backend/scripts/run_with_env.py` for secure env loading
- **Never leak secrets** to terminal output; use redaction filters when piping output
- Commands that load env vars: `./dev/db_migrate.sh`, `make dev`

## Guacamole Integration

Guacamole provides remote desktop access to labs. Key components:
- `guacamole_preflight.py` - Validates GUI + API endpoints before provisioning
- `guacamole_provisioner.py` - Creates per-lab users/connections
- `guacamole_client.py` - REST API client for Guacamole

Preflight classifies failures into actionable categories:
- `BASE_URL_WRONG` - 404 on /api/tokens (URL misconfigured)
- `CREDS_WRONG` - 401/403 (check GUAC_ADMIN_USER/PASSWORD)
- `SERVER_5XX` - Check Guacamole container logs
- `NETWORK_DOWN` - Ensure stack is running (`make guac-up`)

To debug Guac DB directly:
```bash
docker exec -it octolab-guac-db psql -U guacamole -d guacamole_db
# Or expose port 5433 via debug profile:
docker compose -f infra/guacamole/docker-compose.yml --profile debug up -d
```

## OctoBox Image (`images/octobox-beta/`)

The OctoBox image is the attacker-box environment users connect to. Key aspects:
- VNC/noVNC for remote desktop access, integrated with Guacamole
- Command logging via `PROMPT_COMMAND` hook writes to `commands.tsv`
- `start-vnc-session.sh` launches the VNC server with password from environment
- Healthcheck endpoint via `octobox-healthcheck` script

Development commands:
```bash
make dev-rebuild-octobox    # Rebuild with cache bust for cmdlog changes
make dev-octobox-up         # Start for local testing (uses default password)
make dev-octobox-down       # Stop local OctoBox
make dev-provenance         # Verify build markers and cmdlog wiring
make verify-cmdlog          # Verify cmdlog cache-busting works
make dev-cmdlog-verify      # Verify PROMPT_COMMAND hook logs to commands.tsv
```

## Agent Safety Constraints

Safe to run:
- `pytest`, `make test`, `./backend/scripts/test.sh`
- `alembic upgrade head`, `make db-migrate`
- `uvicorn app.main:app --reload`, `make dev`
- `make guac-up`, `make guac-down`, `make guac-status`, `make guac-reset`

Avoid without explicit user request:
- `rm -rf`, `docker system prune`, unscoped `kubectl delete`
- Modifying production deployment configs
- Creating or modifying infrastructure secrets

## Debugging Guidelines

These principles prevent common debugging pitfalls:

### 1. Verify Data Flow Before Assuming Component Failure
When a value shows as `null`/`None`, check the entire data path:
- Is the source actually producing the value? (check logs/raw responses)
- Is the schema/dataclass capturing the field? (missing fields silently return None)
- Is the parsing code extracting it correctly?

**Example**: `docker_ready: null` looked like Docker wasn't starting, but Docker was fine—the `AgentResponse` dataclass simply lacked the field.

### 2. Check Schema/Dataclass Completeness First
When adding new response fields from external sources (APIs, guest agents, etc.):
- Add fields to the response dataclass/schema
- Update the parsing code to extract them
- Missing fields with `getattr(obj, "field", None)` fail silently

### 3. Verify External Dependencies Still Exist
Docker images, npm packages, and APIs can disappear or change:
- Check that referenced images exist on their registry
- Verify API endpoints haven't changed
- Pin versions when stability matters

### 4. Follow Existing Patterns—Don't Invent New Ones
Before implementing a feature:
- Find how similar features work in the codebase
- Copy the existing pattern exactly
- Only diverge when there's a clear technical reason

**Example**: Firecracker labs should use the same Guacamole flow as Docker Compose labs. Inventing a separate noVNC/nginx approach created unnecessary complexity.

### 5. Distinguish Symptoms from Root Causes
Common misdirections:
- "Service X isn't starting" → Check if monitoring/reporting is broken first
- "Value is null" → Check if the value exists but isn't being captured
- "Connection failed" → Check network path, not just the endpoint

### 6. Log Raw Data at Integration Points
When debugging cross-component issues:
- Log the raw response before parsing
- Compare what was sent vs what was received
- Check for field name mismatches (snake_case vs camelCase)

### 7. Test the Smallest Unit First
Before debugging a complex flow:
- Can the guest agent respond at all? (ping)
- Is the raw JSON correct? (diag with logging)
- Is one specific field missing? (targeted check)

Don't debug the whole lab lifecycle when the issue is one missing dataclass field.

## Current MVP Gaps

These are known limitations in the current implementation:

| Feature | Status | Notes |
|---------|--------|-------|
| Vulnerable targets | Placeholder | All labs use `httpd:2.4` regardless of recipe; recipe-specific images not yet built |
| Recipe → Image mapping | Not implemented | `Recipe.target_image` field needed to select per-vulnerability containers |
| LLM intent parsing | Stubbed | LLM adapter exists but no actual provider integration |
| K8s runtime | Partial | NetworkPolicies defined but not fully tested at scale |

The platform infrastructure (isolation, VNC, evidence, Guacamole) is complete. The "vulnerable target" aspect requires building CVE-specific Docker images and mapping them to recipes.
