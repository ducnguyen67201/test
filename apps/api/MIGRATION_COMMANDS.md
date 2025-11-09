# Migration Commands - Quick Reference

## 🎯 Apply All Pending Migrations (Auto-run new migrations)

This command applies **ALL migrations** that haven't been run yet. If you have 5 migration files but only 2 have been applied, it will run the remaining 3.

### PowerShell (Windows) - **Recommended**
```powershell
cd apps\api
.\scripts\migrate.ps1 up
```

### Makefile (Linux/Mac/WSL)
```bash
cd apps/api
make migrate-up
```

### CLI Directly
```bash
cd apps/api
migrate -database "postgres://postgres:postgres@localhost:5432/zerozero?sslmode=disable" -path ./migrations up
```

---

## 📋 How It Works

The `up` command is **smart**:
- ✅ Tracks which migrations have been applied
- ✅ Only runs new/pending migrations
- ✅ Runs migrations in order (000001, 000002, 000003...)
- ✅ Stops if a migration fails
- ✅ Safe to run multiple times (idempotent)

### Example:

```
Current state:
✅ 000001_create_users.sql        (already applied)
✅ 000002_create_products.sql     (already applied)
❌ 000003_add_avatar_url.sql      (not applied yet)
❌ 000004_create_orders.sql       (not applied yet)

Run: .\scripts\migrate.ps1 up

Result:
✅ 000001_create_users.sql        (skipped - already applied)
✅ 000002_create_products.sql     (skipped - already applied)
✅ 000003_add_avatar_url.sql      (APPLIED ✨)
✅ 000004_create_orders.sql       (APPLIED ✨)

Done! 2 new migrations applied.
```

---

## 🔄 Common Workflow

### Development Workflow:

```powershell
# 1. Pull latest code
git pull

# 2. Check if there are new migrations
.\scripts\migrate.ps1 version

# 3. Apply any new migrations
.\scripts\migrate.ps1 up

# 4. Start your app
go run cmd/server/main.go
```

### Creating & Testing a New Migration:

```powershell
# 1. Create migration
.\scripts\migrate.ps1 create -Name add_user_role

# 2. Edit the .up.sql and .down.sql files
# migrations/000005_add_user_role.up.sql
# migrations/000005_add_user_role.down.sql

# 3. Apply the migration
.\scripts\migrate.ps1 up

# 4. Test your app with the new schema

# 5. Test rollback (optional)
.\scripts\migrate.ps1 down

# 6. Re-apply
.\scripts\migrate.ps1 up

# 7. Commit to git
git add migrations/
git commit -m "Add user role migration"
```

---

## 📊 All Available Commands

| Command | PowerShell | Purpose |
|---------|-----------|---------|
| **Apply all pending** | `.\scripts\migrate.ps1 up` | Run all new migrations |
| **Rollback last** | `.\scripts\migrate.ps1 down` | Undo last migration |
| **Check version** | `.\scripts\migrate.ps1 version` | See current migration version |
| **Create new** | `.\scripts\migrate.ps1 create -Name <name>` | Create migration files |
| **Force version** | `.\scripts\migrate.ps1 force -Version <num>` | Force set version (careful!) |

---

## 🚨 Important Notes

### ✅ Safe Operations:
- `up` - Always safe, only applies new migrations
- `version` - Read-only, just shows status
- `create` - Just creates files, doesn't modify database

### ⚠️ Careful Operations:
- `down` - Rollback (test locally first!)
- `force` - Can break migration tracking (use only if stuck)

### The `up` Command is Idempotent:
```powershell
# Run it once
PS> .\scripts\migrate.ps1 up
✅ Applied migrations 1, 2, 3

# Run it again
PS> .\scripts\migrate.ps1 up
✅ No new migrations to apply (nothing happens)

# Run it a third time
PS> .\scripts\migrate.ps1 up
✅ No new migrations to apply (still nothing happens)
```

**It's safe to run multiple times!** It won't re-apply migrations.

---

## 🎓 Examples

### Scenario 1: New Developer Joins Team

```powershell
# Clone repo
git clone <repo>
cd apps/api

# Create database
createdb zerozero

# Apply all migrations (sets up entire schema)
.\scripts\migrate.ps1 up

# Start working!
```

### Scenario 2: Teammate Added New Migrations

```powershell
# Pull latest code
git pull

# You have new migration files
# migrations/000010_new_feature.up.sql
# migrations/000010_new_feature.down.sql

# Apply them
.\scripts\migrate.ps1 up

# Done! Your database is up to date.
```

### Scenario 3: Testing a Migration

```powershell
# Apply it
.\scripts\migrate.ps1 up

# Oh no, something wrong!
# Rollback
.\scripts\migrate.ps1 down

# Fix the .sql file
# Re-apply
.\scripts\migrate.ps1 up
```

---

## 🔍 Checking Migration Status

### See current version:
```powershell
PS> .\scripts\migrate.ps1 version
4
```
This means migrations 1, 2, 3, 4 have been applied.

### See what's pending:
```bash
# List all migration files
ls migrations/

# Compare with current version
# If you're at version 4 and see 000005_*.sql files,
# that migration is pending
```

---

## 💡 Pro Tips

### 1. Run migrations before starting your app
```powershell
# Good workflow
.\scripts\migrate.ps1 up
go run cmd/server/main.go

# Or automate it (we can add this later)
```

### 2. Always check migration status after pulling code
```powershell
git pull
.\scripts\migrate.ps1 version
.\scripts\migrate.ps1 up
```

### 3. Commit migrations with related code
```bash
git add migrations/
git add internal/domain/
git commit -m "Add user roles feature with migration"
```

---

## 🐛 Troubleshooting

### "No migration found"
You're already up to date! No pending migrations.

### "Dirty database"
A migration failed halfway. Fix with:
```powershell
# Check current version
.\scripts\migrate.ps1 version

# Force to last known good version
.\scripts\migrate.ps1 force -Version <last_good_number>

# Try again
.\scripts\migrate.ps1 up
```

### "Connection refused"
Make sure PostgreSQL is running:
```bash
# Windows: Start PostgreSQL service
# Or check if it's running
pg_isready
```

---

## 🎉 Summary

**The command you want is:**

```powershell
.\scripts\migrate.ps1 up
```

This will:
- ✅ Apply all pending migrations
- ✅ Skip already-applied migrations
- ✅ Run in correct order
- ✅ Be safe to run multiple times
- ✅ Stop on errors

**Use it every time you:**
- Pull new code
- Create a new migration
- Set up a fresh database
- Want to ensure your schema is up to date

Easy! 🚀
