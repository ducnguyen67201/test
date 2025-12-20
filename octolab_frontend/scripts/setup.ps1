# Setup script for ZeroZero monorepo (Windows PowerShell)

Write-Host "🚀 Setting up ZeroZero monorepo..." -ForegroundColor Green

# Check for required tools
function Check-Tool {
    param($tool)
    if (!(Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Host "❌ $tool is not installed. Please install it first." -ForegroundColor Red
        exit 1
    }
    Write-Host "✅ $tool is installed" -ForegroundColor Green
}

Write-Host "Checking required tools..."
Check-Tool "node"
Check-Tool "go"
Check-Tool "docker"

# Install Node dependencies
Write-Host "Installing Node dependencies..."
npm install

# Install Go dependencies
Write-Host "Installing Go dependencies..."
Set-Location apps/api
go mod download
Set-Location ../..

# Install buf CLI
Write-Host "Installing buf CLI..."
npm install -g @bufbuild/buf

# Install migrate CLI
Write-Host "Installing migrate CLI..."
go install -tags 'postgres' github.com/golang-migrate/migrate/v4/cmd/migrate@latest

# Copy environment file
if (!(Test-Path .env.local)) {
    Write-Host "Creating .env.local file..."
    Copy-Item .env.example .env.local
    Write-Host "⚠️  Please update .env.local with your actual values" -ForegroundColor Yellow
}

# Start Docker services
Write-Host "Starting Docker services..."
docker-compose up -d postgres redis

# Wait for PostgreSQL to be ready
Write-Host "Waiting for PostgreSQL to be ready..."
Start-Sleep -Seconds 5

# Run migrations
Write-Host "Running database migrations..."
$env:DATABASE_URL = "postgres://postgres:postgres@localhost:5432/zerozero?sslmode=disable"
migrate -path db/migrations -database $env:DATABASE_URL up

# Generate protobuf files
Write-Host "Generating protobuf files..."
Set-Location proto
buf generate
Set-Location ..

# Generate sqlc files
Write-Host "Generating sqlc files..."
Set-Location db
sqlc generate
Set-Location ..

Write-Host "✅ Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "To start the development environment, run:"
Write-Host "  In terminal 1: cd apps/api && go run cmd/server/main.go"
Write-Host "  In terminal 2: cd apps/web && npm run dev"