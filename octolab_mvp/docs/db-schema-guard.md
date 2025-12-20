# Database Schema Drift Guard

This document describes the database schema drift detection system that prevents runtime failures caused by code-database mismatches.

## Problem

When code is updated but Alembic migrations aren't applied, the application crashes with errors like:

```
psycopg.errors.UndefinedColumn: column labs.evidence_auth_volume does not exist
```

This happens because the code expects database columns that don't exist yet.

## Solution

The backend now checks database schema synchronization on startup and fails fast with a clear, actionable message if migrations are pending.

## How It Works

1. **Startup Check**: When the FastAPI app starts, it queries the `alembic_version` table to get the current DB revision and compares it to the code's head revision.

2. **Fail Fast**: If revisions don't match, the app raises a `RuntimeError` with instructions:
   ```
   Database schema is not in sync with code.
     DB revision:   old_revision_123
     Code revision: new_revision_456
     Reason: Schema mismatch

   To fix, run from backend/:
     alembic upgrade head
   ```

3. **Override**: Set `ALLOW_PENDING_MIGRATIONS=1` to skip the check (useful for debugging).

## Endpoints

### GET /health/db

Returns schema synchronization status without authentication:

```bash
curl -s http://127.0.0.1:8000/health/db | jq
```

Response:
```json
{
  "db_revision": "a1b2c3d4e5f6",
  "code_revision": "a1b2c3d4e5f6",
  "in_sync": true,
  "reason": "Database schema matches code"
}
```

## Makefile Targets

```bash
# Check current migration status
make db-status

# Apply pending migrations
make db-upgrade
```

## Manual Commands

From the `backend/` directory:

```bash
# Check current DB revision
alembic current

# Check code head revision
alembic heads

# Apply all pending migrations
alembic upgrade head

# Create a new migration
alembic revision --autogenerate -m "description"
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ALLOW_PENDING_MIGRATIONS` | Set to `1` to skip schema check | Not set (check enabled) |

## Security Notes

- The `/health/db` endpoint only exposes revision hashes, not connection details
- Database URLs and passwords are never logged
- The startup check doesn't auto-run migrations (requires explicit action)
