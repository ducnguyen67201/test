# Database Connection Verification Script
# Quick script to verify database connection and show current state

Write-Host ""
Write-Host "=== ZeroZero Database Connection Verification ===" -ForegroundColor Cyan
Write-Host ""

$DATABASE_URL = "postgres://postgres:postgres@localhost:5432/zerozero?sslmode=disable"

Write-Host "Connection String:" -ForegroundColor Yellow
Write-Host $DATABASE_URL
Write-Host ""

Write-Host "Connection Details:" -ForegroundColor Yellow
Write-Host "  Host: localhost"
Write-Host "  Port: 5432"
Write-Host "  Database: zerozero"
Write-Host "  Username: postgres"
Write-Host "  Password: postgres"
Write-Host ""

Write-Host "For DBeaver:" -ForegroundColor Green
Write-Host "  1. New Connection → PostgreSQL"
Write-Host "  2. Host: localhost"
Write-Host "  3. Port: 5432"
Write-Host "  4. Database: zerozero  <-- IMPORTANT!"
Write-Host "  5. Username: postgres"
Write-Host "  6. Password: postgres"
Write-Host ""

Write-Host "Checking Docker container..." -ForegroundColor Cyan
docker ps --filter "name=postgres" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
Write-Host ""

Write-Host "Checking database connection..." -ForegroundColor Cyan
$result = docker exec zerozero-postgres psql -U postgres -d zerozero -c "SELECT current_database();" 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Successfully connected to database!" -ForegroundColor Green
    Write-Host ""

    Write-Host "Tables in database:" -ForegroundColor Cyan
    docker exec zerozero-postgres psql -U postgres -d zerozero -c "\dt"
    Write-Host ""

    Write-Host "Table counts:" -ForegroundColor Cyan
    docker exec zerozero-postgres psql -U postgres -d zerozero -c "SELECT 'users' as table_name, COUNT(*) as count FROM users UNION ALL SELECT 'user_preferences', COUNT(*) FROM user_preferences;"
    Write-Host ""

    Write-Host "Migration version:" -ForegroundColor Cyan
    migrate -database $DATABASE_URL -path "./migrations" version
    Write-Host ""

    Write-Host "✅ Database is ready!" -ForegroundColor Green
} else {
    Write-Host "❌ Failed to connect to database" -ForegroundColor Red
    Write-Host ""
    Write-Host "Troubleshooting:" -ForegroundColor Yellow
    Write-Host "  1. Make sure Docker container is running:"
    Write-Host "     docker-compose up -d postgres"
    Write-Host ""
    Write-Host "  2. Check container logs:"
    Write-Host "     docker logs zerozero-postgres"
    Write-Host ""
    Write-Host "Error details:" -ForegroundColor Red
    Write-Host $result
}

Write-Host ""
