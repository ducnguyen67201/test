# Database Migration Commands
# Requires: golang-migrate CLI
# Install: go install -tags 'postgres' github.com/golang-migrate/migrate/v4/cmd/migrate@latest

# Configuration
DATABASE_URL ?= postgres://postgres:postgres@localhost:5432/zerozero?sslmode=disable
MIGRATIONS_PATH := ./migrations

.PHONY: help migrate-create migrate-up migrate-down migrate-force migrate-version migrate-drop

# Show available commands
help:
	@echo "Available migration commands:"
	@echo "  make migrate-create name=<migration_name>  - Create new migration files"
	@echo "  make migrate-up                            - Apply all pending migrations"
	@echo "  make migrate-down                          - Rollback last migration"
	@echo "  make migrate-version                       - Show current migration version"
	@echo "  make migrate-force version=<version>       - Force set migration version"
	@echo "  make migrate-drop                          - Drop all tables (DANGEROUS!)"
	@echo ""
	@echo "Example:"
	@echo "  make migrate-create name=create_users_table"

# Create new migration files
migrate-create:
ifndef name
	@echo "Error: name parameter is required"
	@echo "Usage: make migrate-create name=<migration_name>"
	@echo "Example: make migrate-create name=create_users_table"
	@exit 1
endif
	@migrate create -ext sql -dir $(MIGRATIONS_PATH) -seq $(name)
	@echo "✅ Created migration files for: $(name)"
	@echo "Edit the files in: $(MIGRATIONS_PATH)/"

# Apply all pending migrations
migrate-up:
	@echo "Applying migrations..."
	@migrate -database "$(DATABASE_URL)" -path $(MIGRATIONS_PATH) up
	@echo "✅ Migrations applied successfully"

# Rollback last migration
migrate-down:
	@echo "Rolling back last migration..."
	@migrate -database "$(DATABASE_URL)" -path $(MIGRATIONS_PATH) down 1
	@echo "✅ Rolled back successfully"

# Force set migration version (use with caution!)
migrate-force:
ifndef version
	@echo "Error: version parameter is required"
	@echo "Usage: make migrate-force version=<version_number>"
	@echo "Example: make migrate-force version=1"
	@exit 1
endif
	@migrate -database "$(DATABASE_URL)" -path $(MIGRATIONS_PATH) force $(version)
	@echo "⚠️  Forced migration version to: $(version)"

# Show current migration version
migrate-version:
	@migrate -database "$(DATABASE_URL)" -path $(MIGRATIONS_PATH) version

# Drop all tables (DANGEROUS - use only in development!)
migrate-drop:
	@echo "⚠️  WARNING: This will drop all tables!"
	@read -p "Are you sure? Type 'yes' to confirm: " confirm && [ "$$confirm" = "yes" ] || exit 1
	@migrate -database "$(DATABASE_URL)" -path $(MIGRATIONS_PATH) drop -f
	@echo "🗑️  All tables dropped"

# Development helpers
.PHONY: dev-reset dev-seed

# Reset database (drop + migrate up)
dev-reset: migrate-drop migrate-up
	@echo "✅ Database reset complete"

# Run migrations and seed data (if seed script exists)
dev-seed: migrate-up
	@if [ -f "./scripts/seed.sql" ]; then \
		psql "$(DATABASE_URL)" -f ./scripts/seed.sql; \
		echo "✅ Seed data inserted"; \
	else \
		echo "ℹ️  No seed file found at ./scripts/seed.sql"; \
	fi
