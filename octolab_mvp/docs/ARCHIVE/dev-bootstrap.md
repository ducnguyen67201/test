> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# OctoLab Development Bootstrap

This document explains how to set up and run the OctoLab development environment.

## Quick Start

```bash
# Bootstrap everything (idempotent, safe to re-run)
make dev-up

# Start the development server
make dev
```

## Prerequisites

- Python 3.11+
- Docker with Docker Compose v2
- PostgreSQL (or use Docker)

Check your environment:
```bash
make dev-doctor
```

## Environment Files

OctoLab uses a layered environment file approach:

| File | Purpose | Committed |
|------|---------|-----------|
| `backend/.env` | Non-secret defaults | Yes |
| `backend/.env.local` | Local secrets (auto-generated) | No |
| `backend/.env.local.example` | Template for reference | Yes |

### Automatic Setup

Running `make dev-up` automatically:
1. Creates `backend/.env.local` if missing
2. Generates `GUAC_ENC_KEY` (Fernet encryption key)
3. Sets file permissions to 600

### Manual Setup

```bash
# Copy template and customize
cp backend/.env.local.example backend/.env.local
chmod 600 backend/.env.local

# Or use the setup script directly
python3 dev/scripts/ensure_env_local.py
```

### Important: GUAC_ENC_KEY

The `GUAC_ENC_KEY` is a Fernet encryption key used to encrypt per-lab Guacamole passwords. **Do not change this key after labs have been created** or existing labs will be unable to decrypt their passwords.

## Makefile Targets

### Development Workflow

```bash
make dev-up      # Bootstrap: env, Guacamole, DB migrations
make dev         # Start FastAPI dev server (with hot reload)
make dev-down    # Stop all dev services
make dev-status  # Show status of dev services
make dev-doctor  # Health check for dev environment
```

### Dev Doctor Checks

The `make dev-doctor` command runs a comprehensive health check:

| Check | Description |
|-------|-------------|
| Python version | Verifies Python 3.11+ is installed |
| Docker daemon | Checks Docker is running |
| Docker Compose | Checks compose v2 is available |
| Environment files | Verifies `.env.local` exists with correct permissions |
| GUAC_ENC_KEY | Validates encryption key decodes to 32 bytes |
| Database | Tests PostgreSQL is reachable |
| **Alembic migrations** | **Verifies migrations are at head revision** |
| Guacamole | Checks Guacamole stack is healthy (if enabled) |

**Important:** The alembic check ensures your database schema matches the code. If migrations are behind:
```bash
make db-migrate  # Apply pending migrations
```

### Guacamole Stack

```bash
make guac-up        # Start Guacamole stack (includes smoketest)
make guac-down      # Stop Guacamole stack
make guac-status    # Show Guacamole status
make guac-reset YES=1  # Full reset: regenerate initdb.sql, nuke volumes, recreate
```

Or use the scripts directly:
```bash
./dev/guac_up.sh        # Start with smoketest
./dev/guac_down.sh
./dev/guac_status.sh
./dev/guac_reset.sh --yes  # Full nuke and pave (non-interactive)
./dev/guac_down.sh -v      # Also remove volumes (destructive!)
```

### Functional Health ("Truly Ready")

Guacamole is considered **functionally healthy** when BOTH conditions are met:

1. **GUI reachable**: `GET /guacamole/` returns HTTP 200
2. **API functional**: `POST /guacamole/api/tokens` returns HTTP 200 with an `authToken`

The smoketest verifies both conditions. If the API returns 5xx, the stack is NOT functional even if the GUI loads.

**Common 5xx causes:**
- Schema mismatch (initdb.sql doesn't match Guacamole image version)
- Missing schema (init script didn't run - check file permissions)
- Database credentials mismatch

### guac-reset: Deterministic Recovery

When you see an ERROR page or API 5xx errors:

```bash
make guac-reset YES=1
```

This command:
1. Regenerates `initdb.sql` from the pinned Guacamole image (1.5.5)
2. Destroys all Guacamole volumes (database data)
3. Recreates containers with fresh database
4. Waits for DB health + runs functional smoketest
5. Verifies API tokens endpoint returns 200

The `YES=1` flag is required for non-interactive execution (e.g., in scripts).

### Database

```bash
make db-migrate  # Run migrations (recommended)
make db-status   # Show current migration status
make db-upgrade  # Legacy: direct alembic upgrade
```

Or use the script directly:
```bash
./dev/db_migrate.sh                    # upgrade head (default)
./dev/db_migrate.sh current            # show current revision
./dev/db_migrate.sh revision -m "msg"  # create new migration
```

## Security Design

### No Shell Sourcing

The dev tools **never source or eval** environment files. This prevents:
- Command injection via `$(command)` in env values
- Shell expansion vulnerabilities
- Accidental secret exposure

Instead, `run_with_env.py` parses KEY=VALUE lines strictly:
- Rejects `export FOO=bar` syntax
- Rejects command substitution `$(...)` and backticks
- Validates key names (alphanumeric + underscore only)

### Secret Redaction

All tools redact sensitive values in output. Patterns like:
- `*PASSWORD*`
- `*SECRET*`
- `*_KEY`
- `DATABASE_URL`

Are automatically replaced with `****` in logs and error messages.

### File Permissions

The `ensure_env_local.py` script sets `.env.local` permissions to 600 (owner read/write only).

## Troubleshooting

### "python3 not found" or wrong version

```bash
# Check version
python3 --version  # Should be 3.11+

# On Ubuntu/Debian
sudo apt install python3.11
```

### "docker daemon not running"

```bash
# Start Docker service
sudo systemctl start docker

# Or on WSL, ensure Docker Desktop is running
```

### Guacamole DB Unhealthy

The Guac DB healthcheck may fail for several reasons. The `guac_up.sh` script will automatically diagnose common issues and suggest fixes.

**Common Causes:**

1. **Stale volume with different credentials**
   - Symptoms: "password authentication failed", "role does not exist"
   - Fix: `make guac-reset-db`

2. **PostgreSQL version mismatch**
   - Symptoms: "database files are incompatible"
   - Fix: `make guac-reset-db`

3. **Init SQL script error**
   - Symptoms: SQL syntax errors in logs
   - Fix: Check `infra/guacamole/init/initdb.sql` for errors

4. **Permission denied**
   - Symptoms: "Permission denied" on data directory
   - Fix: `make guac-reset-db` or check Docker volume permissions

**Resetting Guac DB:**

```bash
# Interactive reset (will prompt for confirmation)
make guac-reset-db

# Or directly:
./dev/guac_reset_db.sh

# Non-interactive (for scripts):
./dev/guac_reset_db.sh --yes
```

**Warning:** Resetting the DB deletes all Guacamole data including users, connections, and history.

### "Guacamole not healthy" (Web UI)

```bash
# Check logs
docker compose -f infra/guacamole/docker-compose.yml logs

# Restart stack
make guac-down && make guac-up
```

### Guacamole Shows "ERROR" Page

If you visit http://127.0.0.1:8081/guacamole/ and see a generic "ERROR" page instead of the login form, this usually means the database schema is corrupted or credentials are mismatched.

**Fix:**
```bash
make guac-reset    # Full nuke and recreate
make dev-up        # Re-bootstrap everything
```

The `guac-reset` command:
1. Stops and removes all Guacamole containers
2. Deletes all Guacamole volumes (database data)
3. Starts fresh with clean init SQL
4. Waits for health + runs smoketest

After reset, verify:
- http://127.0.0.1:8081/guacamole/ shows login page
- Default credentials: guacadmin / guacadmin

### Why Guac DB Has No Host Port

The Guacamole database (`guac-db`) deliberately does NOT publish port 5432 to the host. This is a security measure:

- **Reduced attack surface**: The DB is only accessible within the Docker network
- **No port conflicts**: Won't conflict with local PostgreSQL installations
- **Internal-only access**: Guacamole web connects via Docker DNS (`guac-db:5432`)

**If you need to debug the DB directly:**

```bash
# Option 1: Use docker exec
docker exec -it octolab-guac-db psql -U guacamole -d guacamole_db

# Option 2: Start with debug profile (exposes port 5433)
docker compose -f infra/guacamole/docker-compose.yml --profile debug up -d
psql -h localhost -p 5433 -U guacamole -d guacamole_db
```

### "DATABASE_URL not reachable"

```bash
# If using Docker PostgreSQL
docker ps | grep postgres

# Check connection
pg_isready -h localhost -p 5432
```

### GUAC_ENC_KEY issues

If you see decryption errors for existing labs:
1. **Do not regenerate the key** - this will break existing labs
2. Restore the key from backup if available
3. As a last resort, terminate affected labs and recreate

## Architecture

```
dev/
  guac_up.sh         # Start Guacamole (with smoketest)
  guac_down.sh       # Stop Guacamole
  guac_status.sh     # Check status
  guac_reset.sh      # Full nuke and pave (for ERROR page)
  guac_reset_db.sh   # Reset Guac DB only (destructive!)
  db_migrate.sh      # Run Alembic migrations
  doctor.sh          # Health check
  scripts/
    ensure_env_local.py  # Generate .env.local
    guac_diagnose.py     # Diagnose Guac DB failures
    guac_smoketest.py    # Verify Guac GUI + API functional
    redact_stream.py     # Redact secrets from output

backend/
  scripts/
    run_with_env.py  # Secure env loader
  app/services/
    guacamole_preflight.py  # Functional readiness checker
    guacamole_provisioner.py  # Lab provisioning
  .env               # Defaults (committed)
  .env.local         # Secrets (gitignored)
  .env.local.example # Template (committed)

infra/
  guacamole/
    docker-compose.yml  # Guacamole stack
    init/initdb.sql     # DB schema
```

## WSL Notes

If running on WSL:
- Keep the repo on the Linux filesystem (`/home/...`) not Windows mounts (`/mnt/c/...`)
- This significantly improves file I/O performance
- `make dev-doctor` will warn if repo is on a Windows mount

## How to Use (Quick Reference)

### Normal Development

```bash
make dev-up    # Bootstrap: env, guac, db migrations
make dev       # Start FastAPI server
# Visit http://localhost:8000/docs
```

### If Guacamole Shows ERROR Page

```bash
make guac-reset  # Full nuke and pave
make dev-up      # Re-bootstrap
make dev         # Start server
```

### Check Logs

```bash
# Guacamole stack logs
docker compose -f infra/guacamole/docker-compose.yml logs -f

# Follow specific service
docker compose -f infra/guacamole/docker-compose.yml logs -f guacamole
docker compose -f infra/guacamole/docker-compose.yml logs -f guac-db
```

### Verify Stack Health

```bash
make dev-doctor    # Full health check
make guac-status   # Guacamole-specific status
```
