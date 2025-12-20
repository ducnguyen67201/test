# Copilot Instructions for OctoLab

## Project Overview
OctoLab is a CVE rehearsal platform for penetration testers and red teams. It provisions isolated labs (attacker-box + vulnerable target) for exploit rehearsal and generates evidence reports. The platform is **not** for generic training or production safety.

When in doubt, prefer security, isolation, and explicitness over “convenience”.

## Architecture & Key Components
- **Backend:** Python 3.11, FastAPI, SQLAlchemy 2.x, Pydantic v2, PostgreSQL, Alembic
  - `app/main.py`: FastAPI app entry
  - `app/models/`: SQLAlchemy models (UUID PKs via `Mapped[...]` / `mapped_column`)
  - `app/schemas/`: Pydantic v2 schemas
  - `app/api/routes/`: FastAPI routers (thin, domain-grouped)
  - `app/services/`: Business logic (lab orchestration, evidence, LLM adapter)
- **Frontend:** React + TypeScript (Vite) in `frontend/`
- **Infra (clustered):** Kubernetes (k3s / managed), one namespace per lab, strict NetworkPolicy isolation
- **Lab runtime:** OctoBox attacker pod + one or more vulnerable target pods/containers + logging / LabGateway

## Developer Workflows
- **Backend dev:**
  - Run: `uvicorn app.main:app --reload`
  - Test: `pytest` or `uv run pytest`
  - DB migrations:
    - Model changes → update SQLAlchemy models
    - Generate migration: `alembic revision --autogenerate`
    - Apply: `alembic upgrade head`
- **Frontend dev:**
  - Run: `npm install && npm run dev` in `frontend/`
  - Build: `npm run build`
- **Cluster bootstrap (k3s or similar):**
  - `sudo bash infra/cluster/install-k3s.sh`
  - `bash infra/cluster/verify-cluster.sh`
- **Infra deployments:**
  - Traefik: Helm install via `infra/base/ingress/values-traefik.yaml`
  - cert-manager: Helm install via `infra/base/cert-manager/values-cert-manager.yaml`
  - Guacamole/OctoBox and other apps: `kubectl apply -k infra/apps/<app>/`

## Project-Specific Patterns & Rules

### Backend patterns
- Prefer **async FastAPI endpoints** and async DB access.
- SQLAlchemy 2.0 style (`Mapped[...]`, `mapped_column`, `select()`).
- Never trust client-supplied tenant or owner identifiers.

### Multi-tenancy & Auth
- Each lab is owned by a user (and later possibly an org/team).
- Always derive `owner_id` / tenant context from the authenticated user (JWT / session), **never** from request payload.
- All lab queries must be filtered by `owner_id = current_user.id` (or stricter tenant key if introduced).
- On access to a lab that does not belong to the current tenant:
  - Return **404** (not 403) to avoid leaking existence.
- No unauthenticated lab or recipe modification endpoints.
- Authorization checks belong in services or dedicated auth helpers, not scattered inline.

### Evidence
- Evidence is always tied to the correct Lab ID and tenant.
- Never expose logs or artifacts across users/tenants.
- Evidence formats: text/JSON/Markdown/HTML; artifacts are packaged into ZIPs per lab.
- Do not log secrets or full tokens; scrub sensitive values before logging.

### Kubernetes / Lab Isolation
- Each lab = dedicated namespace (or equivalent strong isolation unit).
- Attacker-box can only:
  - Talk to its own target(s).
  - Reach LabGateway / logging endpoints as needed.
- No cross-namespace communication.
- No outbound Internet by default from lab namespaces unless explicitly required and documented.
- Prefer:
  - Non-root containers.
  - Read-only root filesystems where possible.
  - Minimal Linux capabilities and least-privilege ServiceAccounts.
  - NetworkPolicies that default-deny and explicitly allow required traffic.

### HackVM / Docker Runtime (non-k8s labs)
- OctoBox/HackVM containers must:
  - Run as non-root, no `--privileged`, minimal exposed ports.
  - Respect the two-network model: `lab_net` (internal) and `egress_net` (controlled uplink) where applicable.
- Evidence isolation:
  - Only LabGateway captures `/pcap` and other logs.
  - Attacker/target containers cannot directly read or tamper with evidence volumes.
- No shell logging or command recording baked into Dockerfiles unless explicitly requested (this may be added via runtime hooks later).

### LLM / AI Adapter
- Use an adapter layer (e.g. `app/services/llm_adapter.py`) for all LLM calls.
- Provider is pluggable via config/env, not hard-coded.
- Handle failures/timeouts gracefully; do not block core lab lifecycle on non-essential LLM calls.
- Never send secrets, private keys, or full pcap content to the LLM.

## Testing & Quality
- When changing behavior, **add or update pytest tests** in `tests/`.
- Prefer focused unit tests in `tests/unit/` and higher-level flow tests in `tests/integration/` (if present).
- For security-sensitive logic (auth, tenant isolation, evidence access), always add explicit negative tests (access from wrong tenant, etc.).

## References
- See `docs/`, `infra/`, and `images/octobox-beta/README.md` for infra and evidence details.
- See `.cursor/rules/index.mdc` for older architecture and security rules; keep new rules aligned or explicitly supersede them.

---

**Always follow these rules. For complex or cross-cutting changes, first propose a short plan in the chat, then implement it step by step.**
