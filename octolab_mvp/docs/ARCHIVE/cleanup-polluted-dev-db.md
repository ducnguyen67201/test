> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# Cleaning Up Polluted Development Database

If your development database has been polluted with test data (e.g., random `r-<uuid>` recipes showing up in the UI), this guide provides safe cleanup options.

## ⚠️ Important Safety Notes

- **DO NOT** run these commands on production databases
- **Backup first** if you have any data you want to keep
- **Verify** you're connected to the correct database before running any DROP/DELETE commands
- Test isolation should now prevent this issue going forward (see Test Database Isolation section)

## Option 1: Reset Database (Recommended for Fresh Start)

This completely wipes the database and recreates all tables from scratch.

```bash
# Stop any running backend services
# Kill background pytest processes if any

# Connect to PostgreSQL
psql -U octolab

# Drop and recreate database
DROP DATABASE IF EXISTS octolab;
CREATE DATABASE octolab;

# Exit psql
\q

# Run Alembic migrations to recreate tables
cd backend
alembic upgrade head
```

## Option 2: Selective Cleanup (Keep Some Data)

If you want to keep certain data (like a specific user), selectively delete test data.

### Identify Test Data

Test data typically has:
- UUIDs with no meaningful names
- Recipes named `r-<uuid>`
- Labs with generic or test-related names
- Created recently (during test runs)

### Clean Up Test Recipes

```sql
-- Connect to database
psql -U octolab -d octolab

-- Find test recipes (those with random UUID-like names)
SELECT id, name, software, created_at
FROM recipes
WHERE name LIKE 'r-%'
ORDER BY created_at DESC;

-- Review the list, then delete if confirmed
DELETE FROM recipes WHERE name LIKE 'r-%';
```

### Clean Up Test Labs

```sql
-- Find labs associated with test recipes or test users
SELECT l.id, l.status, l.created_at, u.email
FROM labs l
JOIN users u ON l.owner_id = u.id
WHERE u.email LIKE '%@example.com'  -- Test emails
   OR l.recipe_id IN (SELECT id FROM recipes WHERE name LIKE 'r-%')
ORDER BY l.created_at DESC;

-- Delete test labs
DELETE FROM labs
WHERE owner_id IN (SELECT id FROM users WHERE email LIKE '%@example.com')
   OR recipe_id IN (SELECT id FROM recipes WHERE name LIKE 'r-%');
```

### Clean Up Test Users

```sql
-- Find test users
SELECT id, email, created_at
FROM users
WHERE email LIKE '%@example.com'
   OR email LIKE 'test-%'
ORDER BY created_at DESC;

-- Delete test users (this will cascade to their labs due to FK constraints)
DELETE FROM users
WHERE email LIKE '%@example.com'
   OR email LIKE 'test-%';
```

## Option 3: Admin Script (Future Enhancement)

For convenience, an admin script could be added:

```bash
# backend/scripts/cleanup_test_data.sh (to be implemented)
./backend/scripts/cleanup_test_data.sh --dry-run  # Preview
./backend/scripts/cleanup_test_data.sh            # Execute
```

This script would:
1. Identify test data patterns
2. Show what would be deleted (dry-run)
3. Require confirmation before deleting
4. Create a backup before cleanup

## Test Database Isolation (Preventing Future Pollution)

The new test isolation ensures this won't happen again:

### How It Works

1. **Separate test database**: Tests use `octolab_test` database
2. **Environment marker**: `APP_ENV=test` required for tests
3. **Hard guardrails**: `conftest.py` refuses to run tests against dev DB
4. **Test runner**: `backend/scripts/test.sh` enforces test env

### Running Tests Correctly

```bash
# From repository root
make test

# Or directly
./backend/scripts/test.sh

# Verbose output
./backend/scripts/test.sh -v
```

### Creating Test Database

```bash
# Create test database (one-time setup)
psql -U octolab -c "CREATE DATABASE octolab_test;"

# Run migrations on test database
cd backend
export DATABASE_URL="postgresql+asyncpg://octolab:octolab_password@localhost:5432/octolab_test"
alembic upgrade head
```

### What Tests Will Reject

Tests will refuse to run if:
- `APP_ENV` is not set to "test"
- `DATABASE_URL` doesn't end with "_test"
- Database host is not localhost (unless explicitly allowed)

### Checking Test Isolation

```bash
# This should FAIL (protecting dev DB)
export APP_ENV=development
python3 -m pytest backend/tests/

# This should SUCCEED (test DB)
make test
```

## Verification

After cleanup, verify your database is clean:

```sql
-- Check recipe count
SELECT COUNT(*) FROM recipes;

-- Check lab count
SELECT COUNT(*) FROM labs;

-- Check user count
SELECT COUNT(*) FROM users;

-- List remaining recipes
SELECT id, name, software, is_active FROM recipes;
```

## Prevention Checklist

- ✅ Test database `octolab_test` created
- ✅ Always use `make test` or `./backend/scripts/test.sh` for tests
- ✅ Never set `DATABASE_URL` to dev DB when running pytest
- ✅ Check that `APP_ENV=test` is set in test environment
- ✅ Review `.env` vs `.env.test` to understand the difference

## Need Help?

If you're unsure about any cleanup operation:

1. **Backup first**: `pg_dump -U octolab octolab > backup.sql`
2. **Ask for review**: Share the SQL commands before executing
3. **Test on copy**: Create a database copy and test cleanup there first

```sql
-- Create a copy for testing cleanup
CREATE DATABASE octolab_copy WITH TEMPLATE octolab;

-- Test cleanup on copy
\c octolab_copy
-- Run your DELETE commands here

-- If satisfied, repeat on real DB
\c octolab
-- Run your DELETE commands here
```
