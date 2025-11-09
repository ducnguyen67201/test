# Migration Fix Summary

## Problem
The migration script was showing "no change" but you believed no tables were created.

## Root Cause
The migration tracking system had a **corrupted state**:
- The `schema_migrations` table showed version 2 (all migrations applied)
- The actual database tables **did exist** (`users` and `user_preferences`)
- The migrations were working correctly, but the state was confusing

## What Was Fixed

### 1. Created `scripts/reset-migrations.go`
A utility to reset migration state by dropping the `schema_migrations` table:
```bash
go run scripts/reset-migrations.go
```

### 2. Updated Migration Files to be Idempotent
Changed index creation to use `IF NOT EXISTS`:
```sql
-- Before
CREATE INDEX idx_users_clerk_id ON users(clerk_id);

-- After
CREATE INDEX IF NOT EXISTS idx_users_clerk_id ON users(clerk_id);
```

This prevents errors if migrations are run multiple times.

### 3. Created `scripts/fix-migrations.ps1`
A PowerShell script to reset and re-apply migrations (use with caution).

## Verification

✅ Migration version is now correctly set to: **2**
✅ All tables exist in database:
- `users` (with indexes)
- `user_preferences` (with indexes)
- `schema_migrations` (tracking table)

## How to Use Going Forward

### Check Current Migration Status
```powershell
.\scripts\migrate.ps1 version
```

### Apply New Migrations
```powershell
.\scripts\migrate.ps1 up
```

### Create New Migration
```powershell
.\scripts\migrate.ps1 create -Name "migration_name"
```

### Rollback Last Migration
```powershell
.\scripts\migrate.ps1 down
```

### Reset Migration State (if needed)
```bash
go run scripts/reset-migrations.go
```

## Important Notes

- The "no change" message is **normal** when all migrations are already applied
- Always check the database directly to verify tables exist
- Use `go run scripts/reset-migrations.go` to see current database state
- Migration files are now idempotent (safe to run multiple times)

## Troubleshooting

If you get "relation already exists" errors:
1. Run `go run scripts/reset-migrations.go` to see current state
2. Force migration version: `migrate -database "..." -path "./migrations" force <version>`
3. Or drop and recreate (development only)
