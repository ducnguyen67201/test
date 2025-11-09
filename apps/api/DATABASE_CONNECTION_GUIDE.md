# How to Connect to Your Database

## ✅ Database Connection Details

```
Host:     localhost
Port:     5432
Database: zerozero  ← IMPORTANT!
Username: postgres
Password: postgres
```

---

## Common DB Clients & How to Connect

### 1. **pgAdmin** (Most Popular)

1. Open pgAdmin
2. Right-click "Servers" → "Create" → "Server"
3. **General Tab:**
   - Name: `ZeroZero Local`
4. **Connection Tab:**
   - Host: `localhost`
   - Port: `5432`
   - Maintenance database: `zerozero` ← IMPORTANT!
   - Username: `postgres`
   - Password: `postgres`
5. Click "Save"
6. Expand: **Servers** → **ZeroZero Local** → **Databases** → **zerozero** → **Schemas** → **public** → **Tables**

**You should see:**
- `schema_migrations`
- `users`
- `user_preferences`

---

### 2. **DBeaver**

1. Click "New Database Connection"
2. Select "PostgreSQL"
3. Fill in:
   - Host: `localhost`
   - Port: `5432`
   - Database: `zerozero` ← IMPORTANT!
   - Username: `postgres`
   - Password: `postgres`
4. Click "Test Connection"
5. Click "Finish"
6. Navigate: **zerozero** → **Schemas** → **public** → **Tables**

---

### 3. **DataGrip / IntelliJ Database Tools**

1. Click "+" → "Data Source" → "PostgreSQL"
2. Fill in:
   - Host: `localhost`
   - Port: `5432`
   - Database: `zerozero` ← IMPORTANT!
   - User: `postgres`
   - Password: `postgres`
3. Click "Test Connection"
4. Click "OK"
5. Expand: **zerozero** → **schemas** → **public** → **tables**

---

### 4. **VSCode with PostgreSQL Extension**

1. Install extension: "PostgreSQL" by Chris Kolkman
2. Click PostgreSQL icon in sidebar
3. Click "+" to add connection
4. Enter connection string:
   ```
   postgres://postgres:postgres@localhost:5432/zerozero
   ```
5. Expand the connection → **public** → **Tables**

---

### 5. **TablePlus**

1. Click "Create a new connection"
2. Select "PostgreSQL"
3. Fill in:
   - Name: `ZeroZero Local`
   - Host: `localhost`
   - Port: `5432`
   - Database: `zerozero` ← IMPORTANT!
   - User: `postgres`
   - Password: `postgres`
4. Click "Test" then "Connect"
5. See tables in left sidebar

---

### 6. **psql (Command Line)**

```bash
# Connect to the database
psql -h localhost -U postgres -d zerozero

# List all tables
\dt

# You should see:
#              List of relations
#  Schema |       Name        | Type  |  Owner
# --------+-------------------+-------+----------
#  public | schema_migrations | table | postgres
#  public | user_preferences  | table | postgres
#  public | users             | table | postgres
```

---

## 🔍 Troubleshooting

### Issue: "I only see other databases like 'postgres', 'template1'"

**Solution:** You're looking at the server, not the specific database!

1. Make sure you've created the `zerozero` database:
   ```sql
   CREATE DATABASE zerozero;
   ```

2. Connect specifically to `zerozero` database (not `postgres`)

---

### Issue: "I see the database but no tables"

**Common causes:**

#### A. Looking at wrong schema
- Make sure you're looking at schema: `public`
- Not: `pg_catalog`, `information_schema`, etc.

#### B. Need to refresh
- In most DB clients, right-click on "Tables" → "Refresh"
- Or press F5

#### C. Connected to wrong database
- Double-check you're connected to `zerozero` not `postgres`
- Check the database name in your client's status bar

---

### Issue: "Tables show up in one client but not another"

**Solution:** Different database instances running

Check if you have multiple PostgreSQL installations:
```bash
# Windows: Check services
services.msc
# Look for multiple "PostgreSQL" services

# Or check which port each is running on
netstat -ano | findstr :5432
```

---

## ✅ Quick Verification Script

Run this to verify tables exist:

```bash
cd D:\START_UP\zeroZero\apps\api
go run scripts/check_tables.go
```

**Expected output:**
```
Tables in database 'zerozero':
================================
1. schema_migrations
2. user_preferences
3. users

Total tables: 3
```

---

## 📋 Your Tables Schema

### `users` table:
```sql
id              UUID PRIMARY KEY
clerk_id        VARCHAR(255) UNIQUE NOT NULL
email           VARCHAR(255) UNIQUE NOT NULL
first_name      VARCHAR(255)
last_name       VARCHAR(255)
avatar_url      TEXT
created_at      TIMESTAMP
updated_at      TIMESTAMP
```

### `user_preferences` table:
```sql
id                      UUID PRIMARY KEY
user_id                 UUID (FK → users.id)
theme                   VARCHAR(50)
language                VARCHAR(10)
notifications_enabled   BOOLEAN
email_notifications     BOOLEAN
created_at              TIMESTAMP
updated_at              TIMESTAMP
```

### `schema_migrations` table:
```sql
version    BIGINT PRIMARY KEY
dirty      BOOLEAN
```
This tracks which migrations have been applied.

---

## 🎯 Recommended: pgAdmin

If you don't have a DB client yet, I recommend **pgAdmin**:

1. Download: https://www.pgadmin.org/download/
2. Install
3. Follow the pgAdmin connection steps above

---

## Connection String

For any tool that accepts a connection string:

```
postgres://postgres:postgres@localhost:5432/zerozero?sslmode=disable
```

Or for apps that don't like query params:

```
postgres://postgres:postgres@localhost:5432/zerozero
```

---

## Still Can't See Tables?

Run the verification script:
```bash
cd D:\START_UP\zeroZero\apps\api
go run scripts/check_tables.go
```

If it shows the 3 tables, then:
1. ✅ Tables exist in the database
2. ❌ Your DB client is connected to wrong database/schema

Check your DB client's connection settings again!

---

## Summary Checklist

- [ ] Database name is **exactly** `zerozero`
- [ ] Host is `localhost` (or `127.0.0.1`)
- [ ] Port is `5432`
- [ ] Username is `postgres`
- [ ] Password is `postgres`
- [ ] Looking at schema: `public`
- [ ] Refreshed the tables list (F5 / right-click refresh)
- [ ] Ran `go run scripts/check_tables.go` successfully

If all checked, you should see your tables! ✅
