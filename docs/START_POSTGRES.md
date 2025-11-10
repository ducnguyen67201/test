# 🚨 PostgreSQL Not Running - How to Start

## The Problem

PostgreSQL database server is **not running**. That's why:
- ❌ Can't see tables
- ❌ Migrations appear to fail
- ❌ Can't connect with DB clients

---

## ✅ Solution: Start PostgreSQL

### Method 1: Windows Services GUI (Easiest)

1. Press `Win + R` keys
2. Type: `services.msc`
3. Press Enter
4. Scroll down to find **"PostgreSQL"** or **"postgresql-x64-XX"**
5. Right-click on it
6. Click **"Start"**
7. Wait for status to show **"Running"**

**Optional:** Set it to start automatically:
- Right-click → Properties
- Startup type: **"Automatic"**
- Click OK

---

### Method 2: Command Line (Faster)

**Open PowerShell as Administrator:**
1. Right-click Start menu
2. Click "Windows PowerShell (Admin)" or "Terminal (Admin)"

**Run this command:**
```powershell
# Try each one until you find the right service name
net start postgresql-x64-16
# or
net start postgresql-x64-15
# or
net start postgresql-x64-14
# or just
net start postgresql
```

**Expected output:**
```
The postgresql-x64-16 service is starting.
The postgresql-x64-16 service was started successfully.
```

---

### Method 3: pg_ctl Command

If PostgreSQL is installed but not as a service:

```powershell
# Find your PostgreSQL data directory
# Usually: C:\Program Files\PostgreSQL\16\data

pg_ctl -D "C:\Program Files\PostgreSQL\16\data" start
```

---

## 🔍 Verify PostgreSQL is Running

After starting, verify it's running:

```powershell
# Check if postgres process is running
Get-Process -Name postgres

# Or try to connect
psql --version
```

---

## 🎯 Once Started, Re-run Migrations

```powershell
cd D:\START_UP\zeroZero\apps\api

# Create the database (if not exists)
createdb zerozero

# Run migrations
migrate -database "postgres://postgres:postgres@localhost:5432/zerozero?sslmode=disable" -path ./migrations up

# Verify tables
go run scripts/check_tables.go
```

---

## Common PostgreSQL Service Names

Depending on your PostgreSQL version, the service name might be:

- `postgresql-x64-16` (PostgreSQL 16)
- `postgresql-x64-15` (PostgreSQL 15)
- `postgresql-x64-14` (PostgreSQL 14)
- `postgresql` (generic)

---

## Can't Find PostgreSQL Service?

### Check if PostgreSQL is Installed

```powershell
# Check if psql command exists
where.exe psql

# Check PostgreSQL version
psql --version

# Check if PostgreSQL is installed
Test-Path "C:\Program Files\PostgreSQL"
```

### If Not Installed

Download and install PostgreSQL:
1. Go to: https://www.postgresql.org/download/windows/
2. Download installer
3. Run installer
4. During installation:
   - Set password for `postgres` user: `postgres`
   - Port: `5432`
   - Check "Start server on startup"

---

## After Starting PostgreSQL

### 1. Verify Connection

```powershell
cd D:\START_UP\zeroZero\apps\api
go run scripts/check_tables.go
```

**Should now show:**
```
Tables in database 'zerozero':
================================
1. schema_migrations
2. user_preferences
3. users
```

### 2. Connect with DB Client

Now you can connect with pgAdmin, DBeaver, etc.:
```
Host:     localhost
Port:     5432
Database: zerozero
Username: postgres
Password: postgres
```

### 3. Start Your App

```powershell
cd D:\START_UP\zeroZero\apps\api
go run cmd/server/main.go
```

---

## 🔄 Auto-Start PostgreSQL on Boot

To avoid this issue in the future:

1. Open `services.msc`
2. Find PostgreSQL service
3. Right-click → Properties
4. Startup type: **"Automatic"**
5. Click Apply → OK

Now PostgreSQL will start automatically when Windows starts!

---

## Still Having Issues?

### Check PostgreSQL logs:

```powershell
# Logs are usually in:
C:\Program Files\PostgreSQL\16\data\log\

# Open latest log file
notepad "C:\Program Files\PostgreSQL\16\data\log\postgresql-*.log"
```

### Check what's using port 5432:

```powershell
netstat -ano | findstr :5432
```

If nothing shows, PostgreSQL definitely isn't running.

---

## Summary

**The issue:** PostgreSQL wasn't running ❌

**The fix:** Start PostgreSQL service ✅

**Commands to run after starting:**
```powershell
# 1. Verify it's running
Get-Process -Name postgres

# 2. Run migrations
cd D:\START_UP\zeroZero\apps\api
migrate -database "postgres://postgres:postgres@localhost:5432/zerozero?sslmode=disable" -path ./migrations up

# 3. Check tables
go run scripts/check_tables.go
```

You should now see your tables! 🎉
