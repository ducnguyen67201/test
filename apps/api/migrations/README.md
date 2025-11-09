# Database Migrations

This directory contains database migration files managed by [golang-migrate](https://github.com/golang-migrate/migrate).

## Quick Start

### 1. Install golang-migrate CLI

```bash
go install -tags 'postgres' github.com/golang-migrate/migrate/v4/cmd/migrate@latest
```

### 2. Create a new migration

**Option A: Using Makefile (Linux/Mac/WSL)**
```bash
make migrate-create name=create_users_table
```

**Option B: Using PowerShell script (Windows)**
```powershell
.\scripts\migrate.ps1 create -Name create_users_table
```

**Option C: Using CLI directly**
```bash
migrate create -ext sql -dir ./migrations -seq create_users_table
```

This creates two files:
- `000001_create_users_table.up.sql` - Apply the migration
- `000001_create_users_table.down.sql` - Rollback the migration

### 3. Write your SQL

**000001_create_users_table.up.sql:**
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

**000001_create_users_table.down.sql:**
```sql
DROP TABLE IF EXISTS users;
```

### 4. Apply migrations

**Option A: Makefile**
```bash
make migrate-up
```

**Option B: PowerShell**
```powershell
.\scripts\migrate.ps1 up
```

**Option C: CLI**
```bash
migrate -database "postgres://localhost:5432/zerozero?sslmode=disable" -path ./migrations up
```

## Common Commands

### Check migration status
```bash
# Makefile
make migrate-version

# PowerShell
.\scripts\migrate.ps1 version

# CLI
migrate -database $DATABASE_URL -path ./migrations version
```

### Rollback last migration
```bash
# Makefile
make migrate-down

# PowerShell
.\scripts\migrate.ps1 down

# CLI
migrate -database $DATABASE_URL -path ./migrations down 1
```

### Force a specific version (use with caution!)
```bash
# Makefile
make migrate-force version=1

# PowerShell
.\scripts\migrate.ps1 force -Version 1

# CLI
migrate -database $DATABASE_URL -path ./migrations force 1
```

## Migration File Naming

Migrations are automatically numbered sequentially:

```
migrations/
├── 000001_create_users_table.up.sql
├── 000001_create_users_table.down.sql
├── 000002_create_products_table.up.sql
├── 000002_create_products_table.down.sql
├── 000003_add_avatar_url_to_users.up.sql
└── 000003_add_avatar_url_to_users.down.sql
```

## Best Practices

### ✅ DO:
- Always write both `.up.sql` and `.down.sql` files
- Test your migrations locally before committing
- Use descriptive migration names
- Run migrations before deploying your application
- Keep migrations simple and focused
- Add indexes for foreign keys and frequently queried columns

### ❌ DON'T:
- Never modify existing migration files that have been applied to production
- Don't skip migration numbers
- Don't use `DROP TABLE` without `IF EXISTS` in down migrations
- Don't put data changes and schema changes in the same migration

## Example Migration Flow

```bash
# 1. Create migration
make migrate-create name=add_user_role

# 2. Edit the files
# migrations/000002_add_user_role.up.sql
# migrations/000002_add_user_role.down.sql

# 3. Test locally
make migrate-up

# 4. Test rollback
make migrate-down

# 5. Re-apply
make migrate-up

# 6. Commit to git
git add migrations/
git commit -m "Add user role migration"
```

## Troubleshooting

### Migration fails with "dirty database"

This happens when a migration fails halfway through. Fix it with:

```bash
# Check which version is dirty
make migrate-version

# Force to a known good version
make migrate-force version=<last_good_version>

# Or force to 0 to start fresh (development only!)
make migrate-force version=0
```

### Can't connect to database

Make sure:
1. PostgreSQL is running
2. Database exists: `createdb zerozero`
3. Connection string is correct in Makefile or script

### Migration already applied

If you need to re-run a migration:
1. Rollback: `make migrate-down`
2. Re-apply: `make migrate-up`

## Environment Variables

Override the default database URL:

```bash
# Makefile
DATABASE_URL=postgres://user:pass@host:5432/dbname make migrate-up

# PowerShell (edit script or set env var)
$env:DATABASE_URL = "postgres://user:pass@host:5432/dbname"
.\scripts\migrate.ps1 up
```

## CI/CD Integration

### GitHub Actions Example

```yaml
# .github/workflows/deploy.yml
- name: Run migrations
  run: |
    migrate -database "${{ secrets.DATABASE_URL }}" \
            -path ./apps/api/migrations \
            up
```

### Docker Example

```dockerfile
# Run migrations before starting the app
RUN migrate -database "${DATABASE_URL}" -path /migrations up
CMD ["./server"]
```

## Resources

- [golang-migrate Documentation](https://github.com/golang-migrate/migrate)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Migration Best Practices](https://github.com/golang-migrate/migrate/blob/master/MIGRATIONS.md)
