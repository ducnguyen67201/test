# Database Migration Helper Script for Windows
# Requires: golang-migrate CLI
# Install: go install -tags 'postgres' github.com/golang-migrate/migrate/v4/cmd/migrate@latest

param(
    [Parameter(Mandatory=$false)]
    [string]$Command,

    [Parameter(Mandatory=$false)]
    [string]$Name,

    [Parameter(Mandatory=$false)]
    [int]$Version
)

# Configuration
$DATABASE_URL = "postgres://postgres:postgres@localhost:5432/zerozero?sslmode=disable"
$MIGRATIONS_PATH = "./migrations"

function Show-Help {
    Write-Host ""
    Write-Host "Database Migration Commands" -ForegroundColor Cyan
    Write-Host "============================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Usage:" -ForegroundColor Yellow
    Write-Host "  .\scripts\migrate.ps1 <command> [options]"
    Write-Host ""
    Write-Host "Commands:" -ForegroundColor Yellow
    Write-Host "  create -Name <name>     Create new migration files"
    Write-Host "  up                      Apply all pending migrations"
    Write-Host "  down                    Rollback last migration"
    Write-Host "  version                 Show current migration version"
    Write-Host "  force -Version <num>    Force set migration version (use with caution!)"
    Write-Host ""
    Write-Host "Examples:" -ForegroundColor Green
    Write-Host "  .\scripts\migrate.ps1 create -Name create_users_table"
    Write-Host "  .\scripts\migrate.ps1 up"
    Write-Host "  .\scripts\migrate.ps1 down"
    Write-Host "  .\scripts\migrate.ps1 version"
    Write-Host ""
}

function Create-Migration {
    param([string]$MigrationName)

    if ([string]::IsNullOrWhiteSpace($MigrationName)) {
        Write-Host "Error: Migration name is required" -ForegroundColor Red
        Write-Host "Usage: .\scripts\migrate.ps1 create -Name <migration_name>" -ForegroundColor Yellow
        exit 1
    }

    Write-Host "Creating migration: $MigrationName" -ForegroundColor Cyan
    migrate create -ext sql -dir $MIGRATIONS_PATH -seq $MigrationName

    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Migration files created successfully!" -ForegroundColor Green
        Write-Host "Edit the files in: $MIGRATIONS_PATH\" -ForegroundColor Yellow
    } else {
        Write-Host "❌ Failed to create migration" -ForegroundColor Red
        exit 1
    }
}

function Migrate-Up {
    Write-Host "Applying migrations..." -ForegroundColor Cyan
    migrate -database $DATABASE_URL -path $MIGRATIONS_PATH up

    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Migrations applied successfully!" -ForegroundColor Green
    } else {
        Write-Host "❌ Migration failed" -ForegroundColor Red
        exit 1
    }
}

function Migrate-Down {
    Write-Host "Rolling back last migration..." -ForegroundColor Cyan
    migrate -database $DATABASE_URL -path $MIGRATIONS_PATH down 1

    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Rolled back successfully!" -ForegroundColor Green
    } else {
        Write-Host "❌ Rollback failed" -ForegroundColor Red
        exit 1
    }
}

function Get-Version {
    Write-Host "Current migration version:" -ForegroundColor Cyan
    migrate -database $DATABASE_URL -path $MIGRATIONS_PATH version
}

function Force-Version {
    param([int]$VersionNumber)

    if ($VersionNumber -eq 0) {
        Write-Host "Error: Version number is required" -ForegroundColor Red
        Write-Host "Usage: .\scripts\migrate.ps1 force -Version <version_number>" -ForegroundColor Yellow
        exit 1
    }

    Write-Host "⚠️  WARNING: Forcing migration version to $VersionNumber" -ForegroundColor Yellow
    $confirm = Read-Host "Are you sure? Type 'yes' to confirm"

    if ($confirm -ne "yes") {
        Write-Host "Cancelled" -ForegroundColor Yellow
        exit 0
    }

    migrate -database $DATABASE_URL -path $MIGRATIONS_PATH force $VersionNumber

    if ($LASTEXITCODE -eq 0) {
        Write-Host "⚠️  Forced version to: $VersionNumber" -ForegroundColor Yellow
    } else {
        Write-Host "❌ Failed to force version" -ForegroundColor Red
        exit 1
    }
}

# Main script logic
switch ($Command.ToLower()) {
    "create" { Create-Migration -MigrationName $Name }
    "up" { Migrate-Up }
    "down" { Migrate-Down }
    "version" { Get-Version }
    "force" { Force-Version -VersionNumber $Version }
    "help" { Show-Help }
    default {
        if ([string]::IsNullOrWhiteSpace($Command)) {
            Show-Help
        } else {
            Write-Host "Unknown command: $Command" -ForegroundColor Red
            Show-Help
            exit 1
        }
    }
}
