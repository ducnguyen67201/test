# Fix Migration State Script
# This script resets the migration state and reapplies all migrations

param(
    [Parameter(Mandatory=$false)]
    [switch]$Force
)

$DATABASE_URL = "postgres://postgres:postgres@localhost:5432/zerozero?sslmode=disable"
$MIGRATIONS_PATH = "./migrations"

Write-Host ""
Write-Host "=== Migration State Fix Tool ===" -ForegroundColor Cyan
Write-Host ""

# Check current state
Write-Host "Current migration version:" -ForegroundColor Yellow
migrate -database $DATABASE_URL -path $MIGRATIONS_PATH version
$currentVersion = $LASTEXITCODE

Write-Host ""
Write-Host "This script will:" -ForegroundColor Yellow
Write-Host "  1. Force migration version to 0 (reset state)"
Write-Host "  2. Re-apply all migrations from scratch"
Write-Host ""

if (-not $Force) {
    $confirm = Read-Host "Continue? (yes/no)"
    if ($confirm -ne "yes") {
        Write-Host "Cancelled" -ForegroundColor Yellow
        exit 0
    }
}

Write-Host ""
Write-Host "Step 1: Resetting migration state to version 0..." -ForegroundColor Cyan
migrate -database $DATABASE_URL -path $MIGRATIONS_PATH force 0

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to reset migration state" -ForegroundColor Red
    Write-Host ""
    Write-Host "Alternative: Try dropping the schema_migrations table manually:" -ForegroundColor Yellow
    Write-Host "  docker exec -it zerozero-postgres psql -U postgres -d zerozero -c 'DROP TABLE IF EXISTS schema_migrations CASCADE;'"
    exit 1
}

Write-Host "✅ Migration state reset to version 0" -ForegroundColor Green
Write-Host ""

Write-Host "Step 2: Applying all migrations..." -ForegroundColor Cyan
migrate -database $DATABASE_URL -path $MIGRATIONS_PATH up

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ All migrations applied successfully!" -ForegroundColor Green
} else {
    Write-Host "❌ Migration failed" -ForegroundColor Red
    Write-Host ""
    Write-Host "Check the error above. Common issues:" -ForegroundColor Yellow
    Write-Host "  - Database connection failed"
    Write-Host "  - Database doesn't exist"
    Write-Host "  - Invalid SQL in migration files"
    exit 1
}

Write-Host ""
Write-Host "Verifying final state..." -ForegroundColor Cyan
migrate -database $DATABASE_URL -path $MIGRATIONS_PATH version

Write-Host ""
Write-Host "✅ Migration fix complete!" -ForegroundColor Green
Write-Host ""
