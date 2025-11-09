# DBeaver Connection Fix - Why You Can't See Tables

## The Problem
Tables exist in PostgreSQL but DBeaver shows nothing when you connect.

## Confirmed Database State ✅
Your tables **DO EXIST** in the database:
- ✅ `users` table
- ✅ `user_preferences` table

## Root Cause
You're likely connected to the **wrong database** in DBeaver. PostgreSQL has multiple databases, and you need to connect to the specific `zerozero` database, not the default `postgres` database.

## Step-by-Step Fix

### 1. Check Your Current DBeaver Connection

In DBeaver, look at your connection settings:

**Current Connection (WRONG):**
```
Host: localhost
Port: 5432
Database: postgres  ⬅️ THIS IS THE PROBLEM
Username: postgres
Password: postgres
```

**Correct Connection (RIGHT):**
```
Host: localhost
Port: 5432
Database: zerozero  ⬅️ CONNECT TO THIS DATABASE
Username: postgres
Password: postgres
```

### 2. Fix Your DBeaver Connection

#### Option A: Edit Existing Connection
1. Right-click your PostgreSQL connection in DBeaver
2. Select **"Edit Connection"**
3. In the "Main" tab, change:
   - Database: `postgres` → `zerozero`
4. Click **"Test Connection"** to verify
5. Click **"OK"** to save

#### Option B: Create New Connection
1. Click **Database** → **New Database Connection**
2. Select **PostgreSQL**
3. Configure:
   ```
   Host: localhost
   Port: 5432
   Database: zerozero
   Username: postgres
   Password: postgres
   ```
4. Click **"Test Connection"**
5. Click **"Finish"**

### 3. Verify in DBeaver

After connecting to the `zerozero` database:

1. Expand the connection: `zerozero` → `Schemas` → `public` → `Tables`
2. You should see:
   - ✅ `users`
   - ✅ `user_preferences`
   - ✅ `schema_migrations`

### 4. Refresh the Schema

If you still don't see tables:
1. Right-click on the connection
2. Select **"Invalidate/Reconnect"**
3. Or press **F5** to refresh

## Understanding PostgreSQL Databases

PostgreSQL has multiple databases in one server:
```
PostgreSQL Server (localhost:5432)
├── postgres (default system database) ⬅️ You're probably looking here
├── template0 (template database)
├── template1 (template database)
└── zerozero (your app database) ⬅️ Tables are HERE
    └── public schema
        ├── users
        ├── user_preferences
        └── schema_migrations
```

## Quick Verification Script

Run this to see all databases:
```powershell
docker exec -it zerozero-postgres psql -U postgres -c "\l"
```

Run this to see tables in zerozero database:
```powershell
docker exec -it zerozero-postgres psql -U postgres -d zerozero -c "\dt"
```

## Common DBeaver Mistakes

### Mistake 1: Connected to Wrong Database
- ❌ Connected to `postgres` database
- ✅ Should connect to `zerozero` database

### Mistake 2: Looking at Wrong Schema
- ❌ Looking at `pg_catalog` or other system schemas
- ✅ Should look at `public` schema

### Mistake 3: Not Refreshing
- After creating tables, DBeaver needs a refresh
- Right-click connection → **"Invalidate/Reconnect"**

## Visual Guide

**What you should see in DBeaver:**
```
📁 zerozero
  📁 Schemas
    📁 public
      📁 Tables
        📄 users (3 rows visible after refresh)
        📄 user_preferences (0 rows)
        📄 schema_migrations (1 row)
      📁 Indexes
        📄 idx_users_clerk_id
        📄 idx_users_email
        📄 idx_users_created_at
        📄 idx_user_preferences_user_id
```

## Still Not Working?

### Check Docker Container
```powershell
# Verify container is running
docker ps | findstr postgres

# Connect directly to verify tables exist
docker exec -it zerozero-postgres psql -U postgres -d zerozero -c "SELECT tablename FROM pg_tables WHERE schemaname='public';"
```

### Check Connection from DBeaver
1. In DBeaver, open **SQL Editor** (F3)
2. Make sure you're connected to `zerozero` database (check bottom status bar)
3. Run:
```sql
-- Check current database
SELECT current_database();

-- Should return: zerozero

-- List all tables
SELECT tablename FROM pg_tables WHERE schemaname = 'public';

-- Should show: users, user_preferences, schema_migrations
```

## Quick Fix Commands

### See what database you're connected to:
```sql
SELECT current_database();
```

### Connect to correct database:
```sql
\c zerozero
```

### List all tables:
```sql
\dt
```

Or:
```sql
SELECT * FROM pg_tables WHERE schemaname = 'public';
```

## After Fixing

Once connected to the correct database, you should see:
- ✅ 3 tables in the `public` schema
- ✅ Ability to run queries against `users` and `user_preferences`
- ✅ Schema migrations tracking table

The tables ARE there - you just need to look in the right place! 🎯
