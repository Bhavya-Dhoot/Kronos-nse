#!/usr/bin/env bash
# Kronos NSE - One-command launch for TUI
# Starts DB, Redis, API server, and TUI automatically

set -euo pipefail

PROJECT_ROOT="/mnt/f/wsl/work/kronos-nse"
cd "$PROJECT_ROOT"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log() { echo -e "${GREEN}[Kronos]${NC} $*"; }
warn() { echo -e "${YELLOW}[Warn]${NC} $*"; }
err() { echo -e "${RED}[Error]${NC} $*"; }

# Cleanup function
cleanup() {
    log "Shutting down..."
    if [[ -n "${API_PID:-}" ]]; then
        kill "$API_PID" 2>/dev/null || true
        wait "$API_PID" 2>/dev/null || true
    fi
    if [[ -n "${DB_COMPOSE_UP:-}" ]]; then
        docker compose -f docker-compose.yml down >/dev/null 2>&1 || true
    fi
    exit 0
}
trap cleanup INT TERM EXIT

log "Starting Kronos NSE..."

# 1. Start Docker services (TimescaleDB + Redis)
log "Starting TimescaleDB and Redis..."
docker compose -f docker-compose.yml up -d timescaledb redis
DB_COMPOSE_UP=1

# Wait for DB to be ready
log "Waiting for TimescaleDB..."
until docker compose -f docker-compose.yml exec -T timescaledb pg_isready -U postgres -d kronos_nse >/dev/null 2>&1; do
    sleep 1
done
log "TimescaleDB ready"

# 2. Run migrations
log "Running database migrations..."
.venv-linux/bin/python -m scripts.bootstrap_db

# 3. Start API server in background
log "Starting API server on http://localhost:8000..."
APP_MODE=VISUAL .venv-linux/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000 --log-level info &
API_PID=$!

# Wait for API to be ready
log "Waiting for API server..."
until curl -sf http://localhost:8000/health >/dev/null 2>&1; do
    sleep 1
done
log "API server ready"

# 4. Launch TUI
log "Launching TUI..."
log "Press 'q' to quit, 'h' for help"
KRONOS_DEFAULT_SYMBOL=RELIANCE .venv-linux/bin/python scripts/tui_v2.py