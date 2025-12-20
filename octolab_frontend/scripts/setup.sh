#!/bin/bash

# Setup script for ZeroZero monorepo

set -e

echo "🚀 Setting up ZeroZero monorepo..."

# Check for required tools
check_tool() {
    if ! command -v $1 &> /dev/null; then
        echo "❌ $1 is not installed. Please install it first."
        exit 1
    fi
    echo "✅ $1 is installed"
}

echo "Checking required tools..."
check_tool "node"
check_tool "go"
check_tool "docker"
check_tool "make"

# Install Node dependencies
echo "Installing Node dependencies..."
npm install

# Install Go dependencies
echo "Installing Go dependencies..."
cd apps/api && go mod download && cd ../..

# Install buf CLI
echo "Installing buf CLI..."
npm install -g @bufbuild/buf

# Install migrate CLI
echo "Installing migrate CLI..."
go install -tags 'postgres' github.com/golang-migrate/migrate/v4/cmd/migrate@latest

# Copy environment file
if [ ! -f .env.local ]; then
    echo "Creating .env.local file..."
    cp .env.example .env.local
    echo "⚠️  Please update .env.local with your actual values"
fi

# Start Docker services
echo "Starting Docker services..."
docker-compose up -d postgres redis

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL to be ready..."
sleep 5

# Run migrations
echo "Running database migrations..."
make migrate-up

# Generate protobuf files
echo "Generating protobuf files..."
make proto-generate

# Generate sqlc files
echo "Generating sqlc files..."
make sqlc-generate

echo "✅ Setup complete!"
echo ""
echo "To start the development environment, run:"
echo "  make dev"
echo ""
echo "Or start services individually:"
echo "  cd apps/api && go run cmd/server/main.go"
echo "  cd apps/web && npm run dev"