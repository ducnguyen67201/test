# Migration Quick Start Guide

## 🚀 Yes! Go has scripts to create migration files

You have **3 ways** to create migration files:

---

## Option 1: PowerShell Script (Recommended for Windows)

```powershell
# Create migration files
.\scripts\migrate.ps1 create -Name create_users_table

# Apply migrations
.\scripts\migrate.ps1 up

# Rollback
.\scripts\migrate.ps1 down

# Check status
.\scripts\migrate.ps1 version
```

---

## Option 2: Makefile (Linux/Mac/WSL)

```bash
# Create migration files
make migrate-create name=create_users_table

# Apply migrations
make migrate-up

# Rollback
make migrate-down

# Check status
make migrate-version
```

---

## Option 3: golang-migrate CLI Directly

```bash
# Create migration files
migrate create -ext sql -dir ./migrations -seq create_users_table

# Apply migrations
migrate -database "postgres://localhost:5432/zerozero?sslmode=disable" -path ./migrations up

# Rollback
migrate -database "postgres://localhost:5432/zerozero?sslmode=disable" -path ./migrations down 1
```

---

## 📦 Setup (One-time)

### 1. Install golang-migrate CLI

```bash
go install -tags 'postgres' github.com/golang-migrate/migrate/v4/cmd/migrate@latest
```

### 2. Add to your Go project

```bash
cd apps/api
go get -u github.com/golang-migrate/migrate/v4
go get -u github.com/golang-migrate/migrate/v4/database/postgres
go get -u github.com/golang-migrate/migrate/v4/source/file
```

✅ **Done!** The `migrations/` directory is already created.

---

## 🎯 Usage Example

### Step 1: Create migration

```powershell
.\scripts\migrate.ps1 create -Name create_users_table
```

This creates:
```
migrations/
├── 000001_create_users_table.up.sql    ← Write SQL here
└── 000001_create_users_table.down.sql  ← Write rollback SQL here
```

### Step 2: Write SQL

**`000001_create_users_table.up.sql`**
```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clerk_id VARCHAR(255) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    avatar_url TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_users_clerk_id ON users(clerk_id);
CREATE INDEX idx_users_email ON users(email);
```

**`000001_create_users_table.down.sql`**
```sql
DROP TABLE IF EXISTS users;
```

### Step 3: Apply migration

```powershell
.\scripts\migrate.ps1 up
```

Output:
```
Applying migrations...
✅ Migrations applied successfully!
```

### Step 4: Test rollback (optional)

```powershell
.\scripts\migrate.ps1 down
```

---

## 📁 What You Have Now

```
apps/api/
├── migrations/               ← Migration files go here
│   └── README.md            ← Full documentation
├── scripts/
│   └── migrate.ps1          ← PowerShell helper script
├── Makefile                 ← Make commands
└── MIGRATION_QUICK_START.md ← This file
```

---

## 🎓 Quick Reference

| Task | PowerShell | Makefile |
|------|-----------|----------|
| Create migration | `.\scripts\migrate.ps1 create -Name <name>` | `make migrate-create name=<name>` |
| Apply all | `.\scripts\migrate.ps1 up` | `make migrate-up` |
| Rollback one | `.\scripts\migrate.ps1 down` | `make migrate-down` |
| Check version | `.\scripts\migrate.ps1 version` | `make migrate-version` |
| Force version | `.\scripts\migrate.ps1 force -Version 1` | `make migrate-force version=1` |

---

## ✅ Best Practices

1. **Always write both `.up.sql` and `.down.sql`**
2. **Never modify existing migrations** (create new ones instead)
3. **Test migrations locally before committing**
4. **Commit migration files to Git**
5. **Run migrations before deploying code**

---

## 🆘 Troubleshooting

### "migrate: command not found"

Install the CLI:
```bash
go install -tags 'postgres' github.com/golang-migrate/migrate/v4/cmd/migrate@latest
```

### "connection refused"

Make sure PostgreSQL is running:
```bash
# Check if running
pg_isready

# Start if not running (Windows)
# Start PostgreSQL service from Services app
```

### "database doesn't exist"

Create the database:
```bash
createdb zerozero
```

Or connect to PostgreSQL and run:
```sql
CREATE DATABASE zerozero;
```

---

## 🎉 You're Ready!

Now you can:
1. ✅ Create migration files with one command
2. ✅ Apply/rollback migrations easily
3. ✅ Keep database schema in version control
4. ✅ Collaborate with your team

**Next step:** Create your first migration!

```powershell
.\scripts\migrate.ps1 create -Name create_users_table
```

Happy migrating! 🚀
