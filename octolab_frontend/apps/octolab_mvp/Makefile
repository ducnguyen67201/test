# OctoLab Development Makefile
#
# This Makefile provides convenient targets for local development.
# All paths are Linux/WSL-relative (no Windows mounts).

.PHONY: help dev-up dev dev-down dev-status dev-doctor dev-provenance dev-rebuild-octobox dev-octobox-up dev-octobox-down dev-verify-make-targets guac-up guac-down guac-status guac-reset guac-reset-db guac-smoketest guac-verify db-migrate k3d-up k3d-down k3d-smoke k3d-import-image test test-verbose db-status db-upgrade e2e-verify e2e-register-verify e2e-evidence-verify dev-evidence-smoke snapshot gc verify-cmdlog dev-cmdlog-verify

# Default target
help:
	@echo "OctoLab Development Targets"
	@echo ""
	@echo "Development Workflow (recommended):"
	@echo "  dev-up              - Bootstrap dev environment (env, guac, db)"
	@echo "  dev                 - Start FastAPI development server"
	@echo "  dev-down            - Stop all dev services"
	@echo "  dev-status          - Show status of dev services"
	@echo "  dev-doctor          - Health check for dev environment"
	@echo "  dev-provenance      - Verify OctoBox image provenance & cmdlog wiring"
	@echo "  dev-rebuild-octobox - Rebuild OctoBox with cmdlog cache bust"
	@echo "  dev-octobox-up      - Start OctoBox for local testing (uses default password)"
	@echo "  dev-octobox-down    - Stop local OctoBox"
	@echo ""
	@echo "Guacamole Stack:"
	@echo "  guac-up             - Start Guacamole stack (with smoketest)"
	@echo "  guac-down           - Stop Guacamole stack"
	@echo "  guac-status         - Show Guacamole status"
	@echo "  guac-smoketest      - Run Guacamole preflight smoketest"
	@echo "  guac-verify         - Run Guacamole E2E verification"
	@echo "  guac-reset          - Full reset: nuke and recreate (if ERROR page)"
	@echo "  guac-reset-db       - Reset Guac DB only (DESTRUCTIVE!)"
	@echo ""
	@echo "Database:"
	@echo "  db-migrate          - Run Alembic migrations (via run_with_env.py)"
	@echo "  db-status           - Show current Alembic migration status"
	@echo "  db-upgrade          - Apply pending Alembic migrations (legacy)"
	@echo ""
	@echo "k3d Cluster Management:"
	@echo "  k3d-up              - Create k3d cluster"
	@echo "  k3d-down            - Delete k3d cluster"
	@echo "  k3d-smoke           - Verify cluster health"
	@echo "  k3d-import-image    - Import local image (requires IMAGE=name:tag)"
	@echo ""
	@echo "Testing:"
	@echo "  test                - Run backend tests with test database"
	@echo "  test-verbose        - Run tests with verbose output"
	@echo "  e2e-verify          - Run E2E verification (Guac+VNC+evidence)"
	@echo "  e2e-register-verify - Run registration E2E verification"
	@echo "  e2e-evidence-verify - Run evidence collection E2E verification"
	@echo "  dev-evidence-smoke  - Smoke test evidence bundle with tlog extraction"
	@echo "  verify-cmdlog       - Verify cmdlog cache-busting works"
	@echo "  dev-cmdlog-verify   - Verify PROMPT_COMMAND hook and commands.tsv logging"
	@echo ""
	@echo "Maintenance:"
	@echo "  gc                  - Garbage collect expired labs and old evidence"
	@echo ""
	@echo "Debugging:"
	@echo "  snapshot            - Capture system state snapshot (git, docker, health)"
	@echo ""
	@echo "Quick Start:"
	@echo "  make dev-up         # Bootstrap environment"
	@echo "  make dev            # Start dev server"
	@echo ""

# ============================================================================
# Development Workflow Targets
# ============================================================================

# Bootstrap dev environment (idempotent)
dev-up:
	@echo "==> Bootstrapping development environment..."
	@echo ""
	@echo "Step 1/3: Ensuring .env.local exists..."
	@python3 dev/scripts/ensure_env_local.py
	@echo ""
	@echo "Step 2/3: Starting Guacamole stack..."
	@./dev/guac_up.sh
	@echo ""
	@echo "Step 3/3: Running database migrations..."
	@./dev/db_migrate.sh upgrade head
	@echo ""
	@echo "==> Dev environment ready! Run 'make dev' to start the server."

# Start FastAPI development server
dev:
	@echo "==> Starting FastAPI development server..."
	@if command -v docker >/dev/null 2>&1; then \
		if ! docker compose -f infra/guacamole/docker-compose.yml ps >/dev/null 2>&1; then \
			echo "NOTE: Unable to check Guacamole stack status (docker compose unavailable)"; \
		elif [ -z "$$(docker compose -f infra/guacamole/docker-compose.yml ps -q 2>/dev/null)" ]; then \
			echo "NOTE: Dev dependencies appear down (run 'make dev-up' to start Guacamole/DB)"; \
		fi; \
	else \
		echo "NOTE: docker not available; skipping dependency check."; \
	fi
	@python3 backend/scripts/run_with_env.py \
		--env backend/.env \
		--env backend/.env.local \
		-- python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --app-dir backend

# Stop all dev services
dev-down:
	@echo "==> Stopping development services..."
	@./dev/guac_down.sh

# Show dev services status
dev-status:
	@echo "==> Tooling versions"
	@if command -v docker >/dev/null 2>&1; then docker --version; else echo "docker: not installed"; fi
	@if command -v docker >/dev/null 2>&1; then docker compose version; else echo "docker compose: not available"; fi
	@echo ""
	@echo "==> OctoLab lab compose status"
	@if command -v docker >/dev/null 2>&1; then \
		cd octolab-hackvm && LAB_ID=devstatus VNC_PASSWORD=dummy VNC_PASSWORD_ALLOW_DEFAULT=1 docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Health}}"; \
	else \
		echo "docker not available; skipping"; \
	fi
	@echo ""
	@echo "==> Guacamole stack status"
	@if command -v docker >/dev/null 2>&1; then \
		cd infra/guacamole && docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Health}}"; \
	else \
		echo "docker not available; skipping"; \
	fi
	@echo ""
	@printf 'Backend compose template: '
	@PYTHONPATH=backend python3 -c "from app.runtime import _resolve_compose_path; print(_resolve_compose_path())"
	@echo "Guac compose manifest: $$(pwd)/infra/guacamole/docker-compose.yml"
	@echo "Tip: use 'make guac-status' for detailed Guacamole diagnostics."

# Health check for dev environment
dev-doctor:
	@./dev/doctor.sh

# Verify OctoBox image provenance and cmdlog wiring
# Builds image, starts container, verifies build markers and scripts, cleans up
dev-provenance:
	@./dev/scripts/dev_provenance.sh

# Rebuild OctoBox image with cmdlog cache bust (forces cmdlog layer rebuild)
# Use when cmdlog scripts change and you want to test without full rebuild
dev-rebuild-octobox:
	@echo "==> Rebuilding OctoBox with CMDLOG_BUST=$(shell date +%s)..."
	@CMDLOG_BUST=$(shell date +%s) BUILD_TIMESTAMP=$(shell date -Iseconds) \
		VNC_PASSWORD_ALLOW_DEFAULT=1 \
		docker compose -f octolab-hackvm/docker-compose.yml build octobox
	@echo "==> Done. New image ready."

# Start OctoBox stack for local testing (dev convenience, uses default VNC password)
# NOTE: Backend-provisioned labs always use server-generated passwords
dev-octobox-up:
	@echo "==> Starting OctoBox for local dev (default VNC password)..."
	@VNC_PASSWORD_ALLOW_DEFAULT=1 VNC_PASSWORD=devpassword \
		docker compose -f octolab-hackvm/docker-compose.yml up -d octobox
	@echo "==> OctoBox started. noVNC: http://localhost:6080"

dev-octobox-down:
	@echo "==> Stopping OctoBox..."
	@VNC_PASSWORD_ALLOW_DEFAULT=1 VNC_PASSWORD=devpassword \
		docker compose -f octolab-hackvm/docker-compose.yml down

# Verify make targets (dry-run and actual up)
dev-verify-make-targets:
	@echo "==> Dry-run 'make dev':"
	@make -n dev
	@echo ""
	@echo "==> Dry-run 'make dev-up':"
	@make -n dev-up
	@echo ""
	@echo "==> Running 'make dev-up'..."
	@make dev-up
	@echo ""
	@echo "==> Checking services..."
	@VNC_PASSWORD_ALLOW_DEFAULT=1 VNC_PASSWORD=devpassword \
		docker compose -f octolab-hackvm/docker-compose.yml ps


# ============================================================================
# Guacamole Stack Targets
# ============================================================================

guac-up:
	@./dev/guac_up.sh

guac-down:
	@./dev/guac_down.sh

guac-status:
	@./dev/guac_status.sh

guac-reset-db:
	@./dev/guac_reset_db.sh

# Full Guacamole reset (nuke and pave) - use when GUI shows ERROR
# Usage: make guac-reset YES=1  (non-interactive)
guac-reset:
	@if [ "$(YES)" = "1" ]; then ./dev/guac_reset.sh --yes; else ./dev/guac_reset.sh; fi

# Guacamole smoketest - exercises preflight check
guac-smoketest:
	@echo "==> Running Guacamole smoketest..."
	@python3 backend/scripts/run_with_env.py \
		--env backend/.env \
		--env backend/.env.local \
		-- python3 dev/guac_smoketest.py

# Guacamole end-to-end verification
guac-verify:
	@echo "==> Running Guacamole E2E verification..."
	@python3 backend/scripts/run_with_env.py \
		--env backend/.env \
		--env backend/.env.local \
		-- python3 dev/verify_guac_e2e.py

# ============================================================================
# Database Migration (via run_with_env.py)
# ============================================================================

db-migrate:
	@./dev/db_migrate.sh

# ============================================================================
# k3d Cluster Management
# ============================================================================

k3d-up:
	@echo "==> Creating k3d cluster..."
	@infra/k3d/create_cluster.sh

k3d-down:
	@echo "==> Deleting k3d cluster..."
	@infra/k3d/delete_cluster.sh

k3d-smoke:
	@echo "==> Running cluster smoke tests..."
	@infra/k3d/smoke_test.sh

k3d-import-image:
ifndef IMAGE
	@echo "ERROR: IMAGE parameter is required"
	@echo "Usage: make k3d-import-image IMAGE=name:tag"
	@echo "Example: make k3d-import-image IMAGE=octolab-backend:latest"
	@exit 1
endif
	@echo "==> Importing image $(IMAGE) into k3d cluster..."
	@k3d image import $(IMAGE) -c octolab-dev

# Testing targets
test:
	@echo "==> Running backend tests with test database..."
	@backend/scripts/test.sh

test-verbose:
	@echo "==> Running backend tests (verbose)..."
	@backend/scripts/test.sh -v

# Cmdlog cache-bust verification (builds image, checks build-id, cleans up)
verify-cmdlog:
	@./dev/scripts/verify_cmdlog_build.sh

# Interactive cmdlog verification (verifies PROMPT_COMMAND hook works and logs commands.tsv)
dev-cmdlog-verify:
	@./dev/scripts/verify_cmdlog.sh

# Database migration targets
db-status:
	@echo "==> Checking Alembic migration status..."
	@cd backend && alembic current
	@echo ""
	@echo "==> Available head revision(s):"
	@cd backend && alembic heads

db-upgrade:
	@echo "==> Applying pending Alembic migrations..."
	@cd backend && alembic upgrade head
	@echo "==> Done. Current revision:"
	@cd backend && alembic current

# ============================================================================
# E2E Verification
# ============================================================================

e2e-verify:
	@echo "==> Running E2E verification (Guac+VNC+evidence)..."
	@python3 backend/scripts/run_with_env.py \
		--env backend/.env \
		--env backend/.env.local \
		-- python3 dev/scripts/e2e_verify.py

e2e-register-verify:
	@echo "==> Running registration E2E verification..."
	@python3 dev/scripts/e2e_register_verify.py

e2e-evidence-verify:
	@echo "==> Running evidence E2E verification..."
	@python3 backend/scripts/run_with_env.py \
		--env backend/.env \
		--env backend/.env.local \
		-- python3 dev/scripts/e2e_evidence_verify.py

dev-evidence-smoke:
	@echo "==> Running evidence bundle smoke test..."
	@./dev/scripts/dev_evidence_smoke.sh

# ============================================================================
# Debugging / Snapshots
# ============================================================================

snapshot:
	@echo "==> Capturing system state snapshot..."
	@python3 dev/scripts/snapshot_state.py

# ============================================================================
# Maintenance
# ============================================================================

gc:
	@echo "==> Running garbage collection (expired labs, old evidence)..."
	@python3 backend/scripts/run_with_env.py \
		--env backend/.env \
		--env backend/.env.local \
		-- python3 dev/scripts/gc.py
