# CLAUDE.md

### When to Score Confidence
You MUST calculate and explicitly state your confidence score (0-100%) for:
- Any code modification or suggestion
- Architecture decisions
- API endpoint usage
- Data structure interpretations
- Bug fixes or feature implementations

### Confidence Calculation Factors
Consider these factors when calculating confidence:
- API documentation availability and clarity (30%)
- Similar patterns in existing codebase (25%)
- Understanding of data flow and dependencies (20%)
- Complexity of the requested change (15%)
- Potential impact on other systems (10%)

### Confidence Thresholds
- 95-100%: Proceed with implementation
- 90-94%: Implement but explicitly note uncertainties
- Below 90%: STOP and ask clarifying questions

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workspace Structure (CRITICAL)

This workspace contains two separate projects with **non-obvious paths**:

```
~/apps/
├── octolab_mvp/           ← BACKEND PROJECT
│   ├── backend/           ← Python FastAPI (edit this)
│   └── frontend/          ← OLD, UNUSED - DO NOT EDIT
│
└── octolab_frontend/      ← FRONTEND PROJECT
    └── apps/octo-web/     ← Next.js App Router (edit this)
```

| Component | Correct Path | Notes |
|-----------|--------------|-------|
| Backend | `octolab_mvp/backend/` | Python/FastAPI |
| Frontend | `octolab_frontend/apps/octo-web/` | Next.js 15 |
| ~~Old Frontend~~ | ~~`octolab_mvp/frontend/`~~ | **NEVER EDIT** |

---

## Backend (`octolab_mvp/backend/`)

CVE rehearsal platform that spins up isolated labs (attacker-box + vulnerable targets) for exploit practice with evidence collection.

### Quick Start

```bash
cd octolab_mvp
source backend/.venv/bin/activate
make dev-up      # Bootstrap: Guacamole, migrations
make dev         # Start FastAPI server (localhost:8000)
```

### Testing

```bash
make test                                    # All tests
./backend/scripts/test.sh -k test_name       # Specific test by name
./backend/scripts/test.sh -v tests/test_file.py::TestClass::test_method
```

Tests require `APP_ENV=test` and database name ending in `_test`. Use `@pytest.mark.no_db` for tests that don't need database access.

### Database

```bash
make db-migrate      # Run pending migrations
make db-status       # Show current revision
./dev/db_migrate.sh revision --autogenerate -m "description"
```

### Guacamole (Remote Desktop)

```bash
make guac-up         # Start stack
make guac-down       # Stop stack
make guac-reset      # Full reset (if ERROR page in browser)
```

### Architecture

- **Structure**: `backend/app/` - FastAPI with SQLAlchemy 2.x async, Pydantic v2
- **Runtimes**: Docker Compose (dev), Firecracker microVMs (prod), Kubernetes
- **Evidence**: Command logs, network captures, sealed with HMAC
- **Remote desktop**: Apache Guacamole integration

**Lab Network Isolation:**
- Each lab runs inside a Firecracker microVM
- **OctoBox** (attacker container) is the user's entry point via VNC/Guacamole
- **Target** (vulnerable container with CVE) is only accessible from OctoBox
- OctoBox and Target share a Docker network inside the VM - hostname `target` should resolve to the vulnerable container
- The host/internet cannot directly reach the Target container (isolated by design)

### CVE Rehearsal Platform Philosophy

**OctoLab is a REHEARSAL platform, not a training platform.**

Users are pentesters who:
1. Have a real engagement target (e.g., client's Apache 2.4.49 server)
2. Want to practice the exploit in a safe environment BEFORE running against production
3. Spin up a lab expecting it to behave like a properly vulnerable system
4. Run the exploit, confirm it works, gain confidence
5. Execute against the real target

**If our lab is misconfigured and the exploit fails:**
- User thinks: "My exploit syntax is wrong" or "This CVE isn't exploitable"
- User moves on, doesn't report the vulnerability to their client
- Client's system remains vulnerable to real attackers

**A broken lab Dockerfile can lead to a real breach.**

**Requirements for CVE labs:**
- Every CVE Dockerfile MUST faithfully reproduce a vulnerable configuration
- The documented exploit technique MUST work against the lab
- "It builds successfully" is not enough - the CVE must be exploitable
- CVE labs need automated smoke tests: spawn → run exploit → verify success

**When a CVE exploit fails in a lab, ask:**
1. Is our Dockerfile configured correctly for this CVE's requirements?
2. What conditions does this CVE need to be exploitable?
3. Does our configuration match those conditions?

Do NOT assume the user needs to "figure it out" - this is rehearsal, not training.

### Backend Patterns

- Async FastAPI endpoints and async DB access
- SQLAlchemy 2.0 style: `Mapped[...]`, `mapped_column`, `select()`
- Pydantic v2 for all schemas
- Thin routers, business logic in `services/`
- UUIDs for all primary keys

### Environment Files

| File | Purpose | Committed |
|------|---------|-----------|
| `backend/.env` | All configuration (secrets included) | No |
| `backend/.env.example` | Template for new setups | Yes |
| `backend/.env.test` | Test configuration | Yes |

**Setup**: Copy `backend/.env.example` to `backend/.env` and fill in secrets. Run `chmod 600 backend/.env` to protect.

---

## Frontend (`octolab_frontend/apps/octo-web/`)

Next.js 15 App Router with tRPC, Prisma, and NextAuth.

### Quick Start

```bash
cd octolab_frontend/apps/octo-web
docker compose -f docker-compose.dev.yml up -d  # Start frontend container
```

### Commands

```bash
npm run type-check      # TypeScript checking
npm run lint            # ESLint
npm run build           # Production build

# Database (Prisma)
npm run db:generate     # Generate Prisma client
npm run db:push         # Push schema to database
npm run db:migrate      # Run migrations
npm run db:studio       # Open Prisma Studio
```

### Architecture

- **Framework**: Next.js 15 (App Router, Turbopack), React 19
- **API**: tRPC v11 for type-safe internal calls
- **Database**: PostgreSQL + Prisma 6
- **Auth**: NextAuth v5 (JWT strategy)
- **UI**: shadcn/ui + Tailwind CSS

### Frontend Patterns

- Server Components by default, `"use client"` only when necessary
- tRPC via `api.*` hooks (client) or `await api()` caller (server)
- shadcn/ui for all UI components: `npx shadcn@latest add [component]`
- File naming: kebab-case files, PascalCase components

### tRPC Usage

**Client Components:**
```tsx
"use client";
import { api } from "@/lib/trpc/react";

function MyComponent() {
  const { data } = api.user.me.useQuery();
  const mutation = api.user.updateProfile.useMutation();
}
```

**Server Components:**
```tsx
import { api } from "@/lib/trpc/server";

export default async function Page() {
  const caller = await api();
  const user = await caller.user.me();
}
```

---

## Shared Rules

### Type Safety

- **NO `any` types** - use `unknown` with proper type narrowing
- Create named types for unions instead of inline types
- Use explicit return types for functions

### Multi-Tenancy & Security

- All lab queries must filter by `owner_id = current_user.id`
- Return 404 (not 403) for resources not owned by current user
- Derive owner_id from JWT, never from request payload
- Never log secrets or full tokens

### Logging & Error Handling

**Backend (Python/FastAPI):**
- Use verbose logging with `logger.info/warning/debug` at key decision points
- Include context tags like `[test-build]`, `[sandbox]` for easy filtering
- Log detailed errors server-side for debugging

**Frontend (Next.js/tRPC):**
- Keep detailed errors in `console.log/console.error` (server-side logs only)
- **NEVER expose detailed errors to the client** - this leaks implementation details to attackers
- Return generic user-friendly messages in thrown errors/responses

**Example:**
```typescript
// BAD - exposes backend details to client
throw new TRPCError({
  message: errorData.detail || "Build failed: missing MPM module",
});

// GOOD - log details server-side, return generic message to client
console.error("[deploy] Build failed:", errorData.detail);
throw new TRPCError({
  message: "Deployment failed. Please try again.",
});
```

### Development Notes

- Do NOT run build/lint/type-check after finishing work - user runs these separately
- Backend uses single `backend/.env` file (not committed, contains secrets)
- Frontend uses Turbopack (enabled by default)

---

## Security-First Troubleshooting

**CRITICAL: Never weaken security to fix connectivity issues.**

### Principles

1. **Understand before changing**: Diagnose the actual problem before modifying any configuration
2. **Security over convenience**: If a fix involves exposing services, it's the wrong fix
3. **Check the full path**: Network issues have multiple components—verify each one

### Common Mistakes to Avoid

| Wrong Fix | Why It's Dangerous | Right Approach |
|-----------|-------------------|----------------|
| Bind service to `0.0.0.0` | Exposes to all networks including internet | Check why client can't reach localhost |
| Disable authentication | Opens service to unauthorized access | Fix credential/token configuration |
| Open firewall ports | Increases attack surface | Use internal networking or proxies |
| Skip TLS verification | Enables MITM attacks | Fix certificate configuration |

### Diagnosing Connectivity Issues

Before changing any service binding or firewall rules:

1. **Check container network mode**: `docker inspect <container> --format '{{.HostConfig.NetworkMode}}'`
   - `host` mode: Container shares host network, can use `localhost`
   - `bridge` mode: Container has separate network, needs docker bridge IP or container name

2. **Check where service is listening**: `ss -tlnp | grep <port>` or check systemd service config
   - `127.0.0.1:8000` = localhost only (secure)
   - `0.0.0.0:8000` = all interfaces (usually wrong)

3. **Check environment variables**: Container env vars may be stale from creation time
   - `docker inspect <container> --format '{{json .Config.Env}}'`
   - Restart won't update env vars set at creation—must recreate container

4. **Check how container was created**:
   - `docker compose down` only manages containers it created
   - Containers created with `docker run` must be removed manually first

### Example: Frontend Can't Reach Backend

**Symptom**: "fetch failed" from frontend container to backend

**Wrong approach**: Change backend from `--host 127.0.0.1` to `--host 0.0.0.0`

**Right approach**:
1. Check frontend container network mode (`docker inspect`)
2. If `host` mode, frontend can use `localhost:8000`
3. Check frontend's env var for backend URL
4. If env var is wrong (e.g., `172.17.0.1` instead of `localhost`), fix the env var
5. Recreate container if env var was set at creation time

---

## Execution Efficiency

Minimize round-trips and avoid unnecessary operations:

### Parallelize File Operations
- Read multiple related files in a single parallel call
- Don't read files sequentially when they're independent

### Batch Edits
- Make larger, combined edits instead of many small ones
- Group related changes across files

### Start Implementing Early
- After reading 2-3 key files, begin implementing
- Don't over-investigate by reading every tangentially related file

### Skip Redundant Verification
- Don't grep/read files immediately after editing them to "verify"
- Trust your edits unless there's a specific reason to doubt them

---

## Testing Efficiency

### Get Credentials Right First
- Check systemd service files for `EnvironmentFile=` to find production credentials
- Don't guess passwords from multiple `.env` files

### Use Direct Solutions
- If a tool (alembic, migrations) has complex setup, use direct SQL instead
- `psql` with direct SQL is faster than debugging migration tooling

### Test the Critical Path Only
- Identify what actually needs testing
- Skip frontend build if backend is the critical path

---

## Debugging Guidelines

### 1. Verify Data Flow Before Assuming Component Failure
When a value shows as `null`/`None`, check the entire data path:
- Is the source producing the value?
- Is the schema capturing the field?
- Is the parsing code extracting it correctly?

### 2. Check Schema/Dataclass Completeness First
When adding new response fields:
- Add fields to the response dataclass/schema
- Update parsing code to extract them
- Missing fields with `getattr(obj, "field", None)` fail silently

### 3. Follow Existing Patterns—Don't Invent New Ones
Before implementing a feature:
- Find how similar features work in the codebase
- Copy the existing pattern exactly
- Only diverge when there's a clear technical reason

### 4. Distinguish Symptoms from Root Causes
Common misdirections:
- "Service X isn't starting" → Check if monitoring/reporting is broken first
- "Value is null" → Check if the value exists but isn't being captured
- "Connection failed" → Check network path, not just the endpoint

### 5. Trace Errors Upstream Before Fixing Downstream
When logs show an error, follow it to the source before fixing anything:

**Wrong approach:**
```
Log: "Lab status DEGRADED"
→ Frontend shows "Deploying..."
→ Fix frontend status mapping
→ Then ask "why DEGRADED?"
→ Then investigate container
→ Then find root cause
```

**Right approach:**
```
Log: "Target container crash-looping"
→ Why? Check container logs/Dockerfile
→ Find: httpd.conf missing Listen directive
→ Why not caught earlier? Sandbox timing issue
→ Fix root cause first
```

**The principle:** The first error in the log is usually closest to the root cause. Fix upstream before downstream—otherwise you're patching symptoms while the disease spreads.

### 6. Search for Alternative Code Paths When Behavior Doesn't Match
When timing or behavior contradicts what you expect from a known code path, immediately search for duplicate or alternative paths:

**Symptom:** test-build was called at 13:33:39, but lab failed at 13:32:40 (test happened AFTER failure)

**Wrong approach:**
```
→ Verify test-build code is deployed
→ Test the endpoint manually
→ Check authentication
→ Debug the endpoint itself
```

**Right approach:**
```
→ "Why was test-build called AFTER deployment failed?"
→ grep for ALL places that generate Dockerfiles
→ Find: deploy() has its own inline generation that bypasses test-build
→ Fix the duplicate code path
```

**The principle:** When timing doesn't match expectations, there's likely a different code path being executed. Search for duplicates (`grep -n "pattern" file`) before debugging the path you expect. Duplicate code that diverges over time is a common source of bugs.

### 7. Verify Configuration Before Changing It
Before assuming infrastructure is broken:
- Check actual runtime state first (`docker inspect`, `env`, config files)
- Don't change settings based on assumptions—verify the current state

### 8. Search Codebase Before Answering Questions About It
Never make claims about what the codebase does or doesn't do without verifying first:

**Wrong approach:**
```
User: "Does the notification cover exploitability?"
→ Assume based on recently read files (notification_service.py)
→ Answer: "No, only build validity"
→ User asks: "Didn't we already do exploit verification?"
→ Search codebase, find cve_smoke_test.py
→ Realize answer was wrong
```

**Right approach:**
```
User: "Does the notification cover exploitability?"
→ Search: grep -r "exploit.*verif\|verify.*exploit" backend/
→ Find: cve_smoke_test.py, nightly_cve_verification.py
→ Read the actual code
→ Answer based on what the code actually does
```

**The principle:** Your memory of "what we built" is unreliable. The codebase is the source of truth. Before answering questions about functionality:
1. Search for relevant files (`grep`, `find`)
2. Read the actual implementation
3. Then answer based on code, not assumptions

This applies especially to questions like:
- "Does X support Y?"
- "What does the Z feature do?"
- "Did we already implement W?"

### 9. Use Examples Over Instructions for LLMs
When an LLM keeps making the same mistake despite instructions:
- Don't add more instructions—add a working example
- LLMs are good at pattern matching, bad at following complex rules
- One few-shot example beats five paragraphs of guidance

**Wrong approach:**
```
→ Add instruction: "Use official Docker images"
→ Still fails, add: "Don't COPY httpd.conf"
→ Still fails, add: "Use sed to modify config"
→ Still fails after 3 rounds of instructions
```

**Right approach:**
```
→ Add one working example that the LLM can copy
→ Works on first try
```

### 10. Write Scripts to Files, Don't Inline Complex Commands
When shell commands get complex (quotes, loops, variables):
- Write to a file first, then execute
- Avoids escaping hell and makes debugging easier
- Use service tokens directly to backend instead of fighting frontend auth

### 11. Check Endpoint Paths Before Guessing
Before calling an API endpoint:
- Check the router file for the actual path prefix
- Don't assume `/api/v1/...` - verify with `grep -n "router\|prefix"`

### 12. Clean Up Test Artifacts Immediately
After testing:
- Delete test labs, containers, images
- Remove temp scripts and data files
- Don't leave resources running that will be forgotten

---

## Implementation Efficiency

### 1. Extend, Don't Rewrite
- Add to existing functions/modules rather than rewriting as classes
- New abstractions must justify their complexity

### 2. Match Effort to Value
- Simple fix → simple implementation
- Don't create abstractions for one-off checks
- A working 10-line function beats an "elegant" 50-line class

### 3. Copy, Don't Improvise
When creating new files similar to existing ones:
- Find the closest existing example
- Copy imports, structure, and patterns exactly
- Don't guess import paths or invent new patterns

### 4. Check Runtime Config for Credentials
When database/service connections fail:
- Check `cat /etc/systemd/system/<service>.service`
- Look for `EnvironmentFile=` to find real credentials
- Production often uses different credentials than dev `.env` files

### 5. Plan the Complete Solution Before Executing
Before starting a multi-step task, map out ALL dependencies and changes:

**Wrong approach (iterative discovery):**
```
→ Build kernel with netfilter
→ Deploy and test
→ Discover: iptables uses nftables backend, kernel lacks nf_tables
→ Switch to iptables-legacy, remount rootfs
→ Discover: Docker config still has iptables:false
→ Update Docker config, remount rootfs again
→ Test again
```

**Right approach (upfront analysis):**
```
→ Check kernel config: what netfilter options exist?
→ Check rootfs: which iptables binary? (nft vs legacy)
→ Check rootfs: what's in Docker daemon.json?
→ Plan: build kernel with X, update rootfs with Y and Z
→ Execute all rootfs changes in ONE mount cycle
→ Test once
```

**The principle:** 10 minutes of upfront analysis saves 30 minutes of iterative fixing. Before executing:
- Identify ALL components that need to change
- Check the current state of each component
- Make all related changes together (single mount, single deploy, single test)
- Use the simplest tool for the job (psql over complex API auth)

### 6. Verify Actual State, Not Just Code

Code describes intent. Runtime state is reality. Before modifying infrastructure or runtime code:

**Check what's actually deployed/built:**
```
→ What images are pre-loaded in rootfs? (not what compose says to use)
→ What binaries are installed? (not what Dockerfile says to install)
→ What's the actual response format? (not what you assume it returns)
→ What functions actually exist? (not what imports expect)
```

**Wrong approach:**
```
→ Read compose template, see it uses image X
→ Assume image X is available
→ Deploy, discover image X isn't pre-loaded
→ Fix, redeploy, discover wrong image tag format
→ Fix, redeploy, discover feature still broken
```

**Right approach:**
```
→ Check rootfs: docker images (what's actually pre-loaded?)
→ Check agent code: what does docker_build actually return?
→ Check imports: does the function actually exist?
→ THEN write the code that matches reality
```

**The principle:** Don't trust that code matches reality. Infrastructure has layers (rootfs, agent, runtime, compose) - verify each layer's actual state before writing code that depends on it.

---

## Feature Implementation Checklist

### Phase 1: Check Before Building
- [ ] Does this already exist? (`grep` for similar code)
- [ ] Is there a simpler solution?
- [ ] What patterns does the codebase use?

### Phase 2: Implement Minimally
- [ ] Follow existing patterns exactly
- [ ] No unnecessary abstractions
- [ ] Register new routes/models appropriately

### Phase 3: Database Changes
- [ ] Check systemd service for `EnvironmentFile=` to find real credentials
- [ ] Create migration or use direct SQL via `psql`
- [ ] Restart backend: `sudo systemctl restart octolab-backend`

### Phase 4: Test Critical Paths
- [ ] Happy path works
- [ ] Auth required endpoints protected
- [ ] Error cases return appropriate status codes

### Phase 5: Cleanup
- [ ] No debug print statements
- [ ] Test data removed
- [ ] Services running: `systemctl is-active octolab-backend`

---

## Dockerfile Validation Pipeline

### What Makes a Dockerfile "Good"?

The `sandbox_build.py` service validates Dockerfiles through a **full build and run test**:

| Step | Duration | What It Catches |
|------|----------|-----------------|
| 1. Docker build | 30-60s | Syntax errors, missing packages, invalid base images |
| 2. Container start | ~1s | Entrypoint failures, missing binaries |
| 3. Stabilization wait | 10s | Crash-loops, services that die after startup |
| 4. State check | ~1s | Container still running + not restarting |

The 10-second wait is critical for catching **crash-loops** - services that appear to start successfully but fail shortly after (like Apache with missing MPM module).

### Validation Flow

```
generateDockerfile (frontend)
    ↓
    Loop up to 5 iterations:
        ├── LLM generates Dockerfile
        ├── POST /api/v1/labs/test-build (with Dockerfile)
        │       ↓
        │   sandbox_build_dockerfile()
        │       ├── docker build
        │       ├── docker run -d
        │       ├── sleep 10  ← catches crash-loops
        │       └── check State.Running && RestartCount == 0
        │
        ├── If PASS → save Dockerfile, exit loop
        └── If FAIL → feed error back to LLM, retry
```

### Spawn ≠ Guaranteed Success

**Important:** The `deploy` procedure does NOT re-validate the Dockerfile. It sends the saved Dockerfile directly to the backend. This means:

- A Dockerfile that passed test-build in Docker may fail in Firecracker
- Environment differences (network, resources) can cause runtime failures
- "Can spawn" only means "passed 5 iterations of test-build"

### Faster Validation Options (Trade-offs)

| Method | Time | Misses |
|--------|------|--------|
| Syntax-only (Dockerfile lint) | ~instant | Build failures, runtime errors |
| Build-only (skip run) | 30-60s | Crash-loops, entrypoint issues |
| **Current (build + run 10s)** | 40-70s | Late-stage crashes (>10s) |
| Run 30s | 60-90s | Crashes after 30s |

Current approach balances speed vs reliability. Most crash-loops manifest within 10 seconds.
