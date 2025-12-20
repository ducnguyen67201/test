# Production-ready Monorepo Makefile

.PHONY: help dev build test clean proto migrate docker-up docker-down

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# Development
dev: ## Start all services in development mode
	@echo "Starting development environment..."
	@$(MAKE) -s docker-up
	@$(MAKE) -s migrate-up
	@$(MAKE) -s proto-generate
	@echo "Starting API server..."
	@cd apps/api && go run cmd/server/main.go &
	@echo "Starting web app..."
	@cd apps/web && npm run dev &
	@echo "Development environment ready!"
	@echo "API: http://localhost:8080"
	@echo "Web: http://localhost:3000"
	@wait

# Build
build: ## Build all applications
	@echo "Building applications..."
	@$(MAKE) -s proto-generate
	@cd apps/api && go build -o bin/server cmd/server/main.go
	@cd apps/web && npm run build
	@echo "Build complete!"

# Testing
test: ## Run all tests
	@echo "Running tests..."
	@cd apps/api && go test ./...
	@cd apps/web && npm test
	@echo "Tests complete!"

# Protocol Buffers
proto-generate: ## Generate protobuf code
	@echo "Generating protobuf code..."
	@cd proto && buf generate
	@echo "Protobuf generation complete!"

proto-lint: ## Lint protobuf files
	@cd proto && buf lint

proto-breaking: ## Check for breaking changes
	@cd proto && buf breaking --against '.git#branch=main'

# Database
migrate-up: ## Run database migrations
	@echo "Running migrations..."
	@cd db && migrate -path migrations -database "postgres://postgres:postgres@localhost:5432/zerozero?sslmode=disable" up

migrate-down: ## Rollback database migrations
	@cd db && migrate -path migrations -database "postgres://postgres:postgres@localhost:5432/zerozero?sslmode=disable" down 1

migrate-create: ## Create new migration (usage: make migrate-create name=create_users)
	@cd db && migrate create -ext sql -dir migrations -seq $(name)

sqlc-generate: ## Generate sqlc code
	@cd db && sqlc generate

# Docker
docker-up: ## Start docker services
	@docker-compose up -d postgres redis

docker-down: ## Stop docker services
	@docker-compose down

docker-clean: ## Clean docker volumes
	@docker-compose down -v

# Installation
install: ## Install dependencies
	@echo "Installing dependencies..."
	@npm install
	@cd apps/api && go mod download
	@cd apps/web && npm install
	@echo "Dependencies installed!"

# Cleanup
clean: ## Clean generated files and build artifacts
	@echo "Cleaning..."
	@rm -rf apps/api/bin
	@rm -rf apps/web/.next
	@rm -rf apps/web/out
	@rm -rf proto/gen
	@echo "Clean complete!"

# CI/CD
ci-test: ## Run CI tests
	@$(MAKE) proto-lint
	@$(MAKE) test

ci-build: ## Run CI build
	@$(MAKE) build
	@docker build -f apps/api/Dockerfile -t zerozero-api .
	@docker build -f apps/web/Dockerfile -t zerozero-web .