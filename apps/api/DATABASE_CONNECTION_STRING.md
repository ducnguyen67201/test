# Database Connection String for ZeroZero Project

## Full Connection String
```
postgres://postgres:postgres@localhost:5432/zerozero?sslmode=disable
```

## Connection Details Breakdown

### For DBeaver / GUI Tools
```
Protocol: PostgreSQL
Host: localhost
Port: 5432
Database: zerozero
Username: postgres
Password: postgres
SSL Mode: disable
```

### For psql Command Line
```bash
psql postgres://postgres:postgres@localhost:5432/zerozero
```

Or using separate parameters:
```bash
psql -h localhost -p 5432 -U postgres -d zerozero
```

### For Docker Direct Access
```bash
docker exec -it zerozero-postgres psql -U postgres -d zerozero
```

## Environment Variables (from .env)
```env
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=postgres
DB_NAME=zerozero
DB_SSL_MODE=disable

# Or as single connection string
DATABASE_URL=postgres://postgres:postgres@localhost:5432/zerozero?sslmode=disable
```

## For Different Tools

### DBeaver
1. New Connection → PostgreSQL
2. Main Tab:
   - Host: `localhost`
   - Port: `5432`
   - Database: `zerozero` ⬅️ IMPORTANT!
   - Username: `postgres`
   - Password: `postgres`
3. PostgreSQL Tab:
   - Show all databases: ✅ (optional)
   - Use SSL: ❌

### pgAdmin
1. Create Server
2. Connection Tab:
   - Host name/address: `localhost`
   - Port: `5432`
   - Maintenance database: `zerozero`
   - Username: `postgres`
   - Password: `postgres`

### VS Code PostgreSQL Extension
```json
{
  "host": "localhost",
  "port": 5432,
  "database": "zerozero",
  "user": "postgres",
  "password": "postgres",
  "ssl": false
}
```

### Go Application (pgx)
```go
connString := "postgres://postgres:postgres@localhost:5432/zerozero?sslmode=disable"

pool, err := pgxpool.New(context.Background(), connString)
```

### Node.js (pg library)
```javascript
const { Pool } = require('pg');

const pool = new Pool({
  host: 'localhost',
  port: 5432,
  database: 'zerozero',
  user: 'postgres',
  password: 'postgres',
  ssl: false
});
```

## Quick Test Commands

### Test Connection
```bash
# Using psql
psql postgres://postgres:postgres@localhost:5432/zerozero -c "SELECT current_database();"

# Using Docker
docker exec -it zerozero-postgres psql -U postgres -d zerozero -c "SELECT current_database();"
```

### List All Tables
```bash
docker exec -it zerozero-postgres psql -U postgres -d zerozero -c "\dt"
```

### Count Records in Users Table
```bash
docker exec -it zerozero-postgres psql -U postgres -d zerozero -c "SELECT COUNT(*) FROM users;"
```

## Important Notes

⚠️ **DATABASE NAME MATTERS!**
- ❌ WRONG: `postgres` (this is the default PostgreSQL system database)
- ✅ CORRECT: `zerozero` (this is your application database)

🔐 **Security Note:**
These are development credentials. For production:
- Use strong passwords
- Enable SSL/TLS
- Use environment variables
- Restrict access by IP
- Use role-based access control

## Troubleshooting

### Can't Connect?
```bash
# Check if PostgreSQL container is running
docker ps | findstr postgres

# Start if not running
docker-compose up -d postgres
```

### Connected but No Tables?
You're probably in the wrong database. Make sure you're connected to `zerozero`, not `postgres`.

Run this to verify:
```sql
SELECT current_database();
-- Should return: zerozero
```

## Migration Commands (Using This Connection)

```powershell
# Apply migrations
.\scripts\migrate.ps1 up

# Check version
.\scripts\migrate.ps1 version

# Create new migration
.\scripts\migrate.ps1 create -Name "migration_name"
```

The connection string is defined in `scripts/migrate.ps1` at line 17.
