#!/bin/bash
set -e

# ═══════════════════════════════════════════════════════════════════════════════
# HVAC Bot - Deploy Script
# ═══════════════════════════════════════════════════════════════════════════════
#
# Usage:
#   ./scripts/deploy.sh [command]
#
# Commands:
#   local     - Start all services locally (default)
#   build     - Build Docker images
#   stop      - Stop all services
#   logs      - View logs
#   backup    - Create Qdrant backup
#   status    - Show service status
#
# ═══════════════════════════════════════════════════════════════════════════════

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_env() {
    if [ ! -f "backend/.env" ]; then
        log_error "backend/.env not found!"
        log_info "Copy backend/.env.example to backend/.env and add your API keys"
        exit 1
    fi
    
    # Source env for docker-compose
    export $(grep -v '^#' backend/.env | xargs)
}

start_local() {
    log_info "Starting HVAC Bot locally..."
    check_env
    
    # Start infrastructure
    log_info "Starting Docker services..."
    docker-compose up -d postgres redis qdrant
    
    # Wait for services
    log_info "Waiting for services to be ready..."
    sleep 5
    
    # Check health
    if ! docker-compose ps | grep -q "healthy\|Up"; then
        log_error "Some services failed to start"
        docker-compose ps
        exit 1
    fi
    
    log_success "Infrastructure ready!"
    echo ""
    echo "Services running:"
    echo "  • PostgreSQL: localhost:5432"
    echo "  • Redis:      localhost:6379"
    echo "  • Qdrant:     localhost:6333"
    echo ""
    echo "To start the backend:"
    echo "  cd backend && source .venv/bin/activate && uvicorn main:app --reload"
    echo ""
    echo "To start the frontend:"
    echo "  cd frontend && npm run dev"
    echo ""
}

start_production() {
    log_info "Starting HVAC Bot in production mode..."
    check_env
    
    docker-compose up -d
    
    log_success "All services started!"
    docker-compose ps
}

build_images() {
    log_info "Building Docker images..."
    check_env
    
    docker-compose build
    
    log_success "Build complete!"
}

stop_services() {
    log_info "Stopping services..."
    docker-compose down
    log_success "All services stopped"
}

show_logs() {
    local service=${1:-}
    if [ -n "$service" ]; then
        docker-compose logs -f "$service"
    else
        docker-compose logs -f
    fi
}

create_backup() {
    log_info "Creating backup..."
    "$SCRIPT_DIR/backup-qdrant.sh"
}

show_status() {
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "  HVAC Bot - Service Status"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    
    # Docker services
    log_info "Docker services:"
    docker-compose ps 2>/dev/null || echo "  (not running)"
    echo ""
    
    # Qdrant check
    log_info "Qdrant collection:"
    QDRANT_INFO=$(curl -s http://localhost:6333/collections/hvac_manuals 2>/dev/null)
    if [ $? -eq 0 ] && echo "$QDRANT_INFO" | jq -e '.result' > /dev/null 2>&1; then
        POINTS=$(echo "$QDRANT_INFO" | jq -r '.result.points_count // 0')
        echo "  Collection: hvac_manuals"
        echo "  Points: $POINTS"
    else
        echo "  (not available)"
    fi
    echo ""
    
    # Disk usage
    log_info "Disk usage:"
    docker system df 2>/dev/null | head -5 || echo "  (docker not running)"
    echo ""
}

print_usage() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  local      Start infrastructure for local development (default)"
    echo "  prod       Start all services in production mode"
    echo "  build      Build Docker images"
    echo "  stop       Stop all services"
    echo "  logs       View logs (optionally: logs <service>)"
    echo "  backup     Create Qdrant backup"
    echo "  status     Show service status"
    echo ""
}

# Main
case ${1:-local} in
    local|dev)
        start_local
        ;;
    prod|production)
        start_production
        ;;
    build)
        build_images
        ;;
    stop)
        stop_services
        ;;
    logs)
        show_logs "$2"
        ;;
    backup)
        create_backup
        ;;
    status)
        show_status
        ;;
    help|--help|-h)
        print_usage
        ;;
    *)
        log_error "Unknown command: $1"
        print_usage
        exit 1
        ;;
esac


