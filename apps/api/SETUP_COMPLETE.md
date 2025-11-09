# ✅ Migration Setup Complete!

## What Was Done

1. ✅ **Installed golang-migrate CLI**
   - Location: `C:\Users\P16\go\bin\migrate.exe`
   - Version: `dev`

2. ✅ **Created migration infrastructure**
   - Directory: `apps/api/migrations/`
   - PowerShell script: `apps/api/scripts/migrate.ps1`
   - Makefile: `apps/api/Makefile`

3. ✅ **Created first migration**
   - `000001_create_users_table.up.sql` - Creates users table
   - `000001_create_users_table.down.sql` - Rollback users table

4. ✅ **Applied migration to database**
   - Current version: **1**
   - Users table created with indexes

## Current Database Schema

```sql
users table:
├── id (UUID, primary key)
├── clerk_id (VARCHAR, unique, indexed)
├── email (VARCHAR, unique, indexed)
├── first_name (VARCHAR, nullable)
├── last_name (VARCHAR, nullable)
├── avatar_url (TEXT, nullable)
├── created_at (TIMESTAMP)
└── updated_at (TIMESTAMP)

Indexes:
- idx_users_clerk_id
- idx_users_email
- idx_users_created_at
```

---

## How to Use Going Forward

### For PowerShell Users (You!)

**If the error persists**, try opening a **new PowerShell window** (the PATH might not be refreshed in your current session).

Then use these commands:

```powershell
cd D:\START_UP\zeroZero\apps\api

# Create a new migration
.\scripts\migrate.ps1 create -Name add_user_preferences

# Apply all pending migrations
.\scripts\migrate.ps1 up

# Check current version
.\scripts\migrate.ps1 version

# Rollback last migration
.\scripts\migrate.ps1 down
```

### Alternative: Use CLI Directly

If the PowerShell script still doesn't work, use the CLI directly:

```powershell
cd D:\START_UP\zeroZero\apps\api

# Create migration
migrate create -ext sql -dir ./migrations -seq add_user_preferences

# Apply migrations
migrate -database "postgres://postgres:postgres@localhost:5432/zerozero?sslmode=disable" -path ./migrations up

# Check version
migrate -database "postgres://postgres:postgres@localhost:5432/zerozero?sslmode=disable" -path ./migrations version
```

---

## Typical Workflow

### Creating a New Feature with Database Changes

```powershell
# 1. Create migration
.\scripts\migrate.ps1 create -Name add_user_roles

# 2. Edit the migration files
# migrations/000002_add_user_roles.up.sql
# migrations/000002_add_user_roles.down.sql

# 3. Apply migration
.\scripts\migrate.ps1 up

# 4. Update your Go code to use the new schema

# 5. Test your app

# 6. Commit everything
git add migrations/
git add internal/
git commit -m "Add user roles feature"
```

### Pulling New Code from Teammates

```powershell
# 1. Pull latest
git pull

# 2. Apply any new migrations
.\scripts\migrate.ps1 up

# 3. Run your app
go run cmd/server/main.go
```

---

## What Files Were Created

```
apps/api/
├── migrations/
│   ├── 000001_create_users_table.up.sql   ✅ Applied
│   ├── 000001_create_users_table.down.sql
│   └── README.md
├── scripts/
│   └── migrate.ps1
├── Makefile
├── MIGRATION_QUICK_START.md
├── MIGRATION_COMMANDS.md
└── SETUP_COMPLETE.md (this file)
```

---

## Troubleshooting

### PowerShell Says "migrate not found"

**Solution 1: Open a new PowerShell window**
Your current session might not have the updated PATH.

**Solution 2: Use full path in the script**

Edit `scripts/migrate.ps1` and replace `migrate` with the full path:

```powershell
# Change this line:
migrate -database $DATABASE_URL -path $MIGRATIONS_PATH up

# To this:
& "C:\Users\P16\go\bin\migrate.exe" -database $DATABASE_URL -path $MIGRATIONS_PATH up
```

**Solution 3: Use CLI directly** (see examples above)

### Database Connection Failed

Make sure PostgreSQL is running:
```powershell
# Check if PostgreSQL is running
pg_isready

# If not, start the service (Windows Services app)
```

### "Dirty database" Error

A migration failed halfway. Fix it:
```powershell
# Check what version it's stuck on
.\scripts\migrate.ps1 version

# Force to last known good version
.\scripts\migrate.ps1 force -Version 1

# Try again
.\scripts\migrate.ps1 up
```

---

## Next Steps

### Recommended: Update Your App to Auto-run Migrations

You can optionally make your app automatically run migrations on startup (good for development):

```go
// In cmd/server/main.go (after database connection)

// Run migrations automatically in development
if cfg.App.Environment == "development" {
    if err := runMigrations(dbPool, "./migrations"); err != nil {
        appLogger.Fatal("Failed to run migrations", logger.Error(err))
    }
    appLogger.Info("Migrations applied successfully")
}
```

This way you don't have to manually run migrations every time.

---

## Summary

✅ **Everything is set up and working!**

You can now:
1. Create migrations easily
2. Apply/rollback migrations
3. Keep database schema in version control
4. Collaborate with your team

**Main command to remember:**
```powershell
.\scripts\migrate.ps1 up
```

This applies all pending migrations automatically! 🚀

---

## Resources

- [Migration Quick Start](./MIGRATION_QUICK_START.md) - Beginner guide
- [Migration Commands](./MIGRATION_COMMANDS.md) - Command reference
- [migrations/README.md](./migrations/README.md) - Detailed docs
- [golang-migrate Docs](https://github.com/golang-migrate/migrate)

Happy migrating! 🎉
