#!/bin/bash
# OctoLab Production Deployment Script
# =====================================
#
# This script deploys OctoLab to a production server.
#
# Prerequisites:
#   - Docker and Docker Compose installed
#   - backend/.env configured with secrets
#   - Node.js for frontend build
#   - netd service running on host (for Firecracker)
#
# Usage:
#   ./deploy.sh              # Full deployment
#   ./deploy.sh --skip-build # Skip frontend build
#   ./deploy.sh --down       # Stop all services
#   ./deploy.sh --logs       # View logs
#   ./deploy.sh --status     # Check service status

set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.prod.yml"
ENV_FILE="${SCRIPT_DIR}/backend/.env"
FRONTEND_DIR="${SCRIPT_DIR}/frontend"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# =============================================================================
# Helper Functions
# =============================================================================
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed"
        exit 1
    fi

    # Check Docker Compose
    if ! docker compose version &> /dev/null; then
        log_error "Docker Compose is not installed"
        exit 1
    fi

    # Check env file
    if [[ ! -f "$ENV_FILE" ]]; then
        log_error "backend/.env not found. Copy from template:"
        log_error "  cp backend/.env.example backend/.env"
        log_error "  # Edit backend/.env with your secrets"
        exit 1
    fi

    log_success "Prerequisites OK"
}

check_netd_service() {
    log_info "Checking microvm-netd service..."

    # Check if netd socket exists
    if [[ -S /run/octolab/microvm-netd.sock ]]; then
        log_success "microvm-netd socket exists"
    else
        log_warn "microvm-netd socket not found at /run/octolab/microvm-netd.sock"
        log_warn "Firecracker runtime requires netd. Start it with:"
        log_warn "  sudo systemctl start microvm-netd"
        log_warn "Or run manually:"
        log_warn "  sudo python3 ${SCRIPT_DIR}/infra/microvm/netd/microvm_netd.py"
    fi
}

build_frontend() {
    log_info "Building frontend..."

    if [[ ! -d "$FRONTEND_DIR" ]]; then
        log_error "Frontend directory not found: $FRONTEND_DIR"
        exit 1
    fi

    cd "$FRONTEND_DIR"

    # Install dependencies if needed
    if [[ ! -d "node_modules" ]]; then
        log_info "Installing frontend dependencies..."
        npm ci
    fi

    # Build for production
    log_info "Building React app..."

    # Set API URL for production build
    # Frontend will proxy through nginx, so use relative /api path
    VITE_API_URL="" npm run build

    if [[ ! -d "dist" ]]; then
        log_error "Frontend build failed - dist directory not created"
        exit 1
    fi

    cd "$SCRIPT_DIR"
    log_success "Frontend built successfully"
}

start_services() {
    log_info "Starting Docker services..."

    # Load env file and start compose
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --build

    log_success "Docker services started"
}

run_migrations() {
    log_info "Running database migrations..."

    # Wait for database to be ready
    log_info "Waiting for database to be healthy..."
    local max_attempts=30
    local attempt=1

    while [[ $attempt -le $max_attempts ]]; do
        if docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres pg_isready -U octolab -d octolab &> /dev/null; then
            log_success "Database is ready"
            break
        fi

        if [[ $attempt -eq $max_attempts ]]; then
            log_error "Database did not become ready in time"
            exit 1
        fi

        log_info "Waiting for database... (attempt $attempt/$max_attempts)"
        sleep 2
        ((attempt++))
    done

    # Run Alembic migrations
    log_info "Applying Alembic migrations..."
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T backend \
        /opt/venv/bin/alembic upgrade head

    log_success "Database migrations complete"
}

verify_deployment() {
    log_info "Verifying deployment..."

    # Wait for backend to be healthy
    local max_attempts=30
    local attempt=1

    while [[ $attempt -le $max_attempts ]]; do
        if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
            log_success "Backend health check passed"
            break
        fi

        if [[ $attempt -eq $max_attempts ]]; then
            log_error "Backend health check failed"
            log_error "Check logs with: ./deploy.sh --logs"
            exit 1
        fi

        log_info "Waiting for backend... (attempt $attempt/$max_attempts)"
        sleep 2
        ((attempt++))
    done

    # Check frontend
    if curl -sf http://localhost/ > /dev/null 2>&1; then
        log_success "Frontend is accessible"
    else
        log_warn "Frontend may not be accessible yet"
    fi

    log_success "Deployment verification complete"
}

show_status() {
    log_info "Service Status:"
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps

    echo ""
    log_info "Health Checks:"

    # Backend health
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        log_success "Backend: healthy"
    else
        log_error "Backend: unhealthy"
    fi

    # Frontend health
    if curl -sf http://localhost/ > /dev/null 2>&1; then
        log_success "Frontend: accessible"
    else
        log_warn "Frontend: not accessible"
    fi

    # netd socket
    if [[ -S /run/octolab/microvm-netd.sock ]]; then
        log_success "netd: socket exists"
    else
        log_warn "netd: socket not found"
    fi
}

stop_services() {
    log_info "Stopping services..."
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" down
    log_success "Services stopped"
}

show_logs() {
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" logs -f
}

# =============================================================================
# Main
# =============================================================================
main() {
    cd "$SCRIPT_DIR"

    case "${1:-}" in
        --down)
            stop_services
            ;;
        --logs)
            show_logs
            ;;
        --status)
            show_status
            ;;
        --skip-build)
            check_prerequisites
            check_netd_service
            start_services
            run_migrations
            verify_deployment
            ;;
        --help|-h)
            echo "OctoLab Production Deployment"
            echo ""
            echo "Usage: ./deploy.sh [OPTION]"
            echo ""
            echo "Options:"
            echo "  (no option)     Full deployment (build frontend, start services, run migrations)"
            echo "  --skip-build    Skip frontend build (use existing dist/)"
            echo "  --down          Stop all services"
            echo "  --logs          View service logs (follow mode)"
            echo "  --status        Check service status and health"
            echo "  --help, -h      Show this help message"
            echo ""
            echo "Prerequisites:"
            echo "  1. Copy backend/.env.example to backend/.env and configure secrets"
            echo "  2. Start netd service: sudo systemctl start microvm-netd"
            echo "  3. Ensure Firecracker assets are in /var/lib/octolab/firecracker/"
            ;;
        *)
            check_prerequisites
            check_netd_service
            build_frontend
            start_services
            run_migrations
            verify_deployment

            echo ""
            log_success "==================================="
            log_success "Deployment complete!"
            log_success "==================================="
            echo ""
            echo "Services:"
            echo "  Frontend: http://localhost/"
            echo "  Backend API: http://localhost:8000/"
            echo "  Health: http://localhost:8000/health"
            echo ""
            echo "Useful commands:"
            echo "  ./deploy.sh --logs     View logs"
            echo "  ./deploy.sh --status   Check status"
            echo "  ./deploy.sh --down     Stop services"
            ;;
    esac
}

main "$@"
