# Kronos NSE — Developer Makefile
# Usage: make <target>
#   make help          Show this help
#   make dev           Start full dev stack (DB + Redis + API + TUI)
#   make dev-api       Start only API server (requires DB/Redis running)
#   make dev-tui       Start only TUI (requires API running)
#   make db-up         Start TimescaleDB + Redis via Docker Compose
#   make db-down       Stop TimescaleDB + Redis
#   make db-reset      Stop, remove volumes, start fresh
#   make migrate       Run DB migrations
#   make test          Run all tests
#   make test-unit     Run unit tests only
#   make test-int      Run integration tests only
#   make lint          Run ruff + mypy
#   make fmt           Format code with ruff
#   make clean         Clean up build artifacts

.PHONY: help dev dev-api dev-tui db-up db-down db-reset migrate test test-unit test-int lint fmt clean

# Default target
help:
	@echo "Kronos NSE — Developer Commands"
	@echo ""
	@echo "  make dev           Start full dev stack (DB + Redis + API + TUI)"
	@echo "  make dev-api       Start only API server (requires DB/Redis)"
	@echo "  make dev-tui       Start only TUI (requires API running)"
	@echo "  make db-up         Start TimescaleDB + Redis via Docker Compose"
	@echo "  make db-down       Stop TimescaleDB + Redis"
	@echo "  make db-reset      Stop, remove volumes, start fresh"
	@echo "  make migrate       Run DB migrations"
	@echo "  make test          Run all tests"
	@echo "  make test-unit     Run unit tests only"
	@echo "  make test-int      Run integration tests only"
	@echo "  make lint          Run ruff + mypy"
	@echo "  make fmt           Format code with ruff"
	@echo "  make clean         Clean up build artifacts"
	@echo ""

# ─── Docker Compose ──────────────────────────────────────────────
db-up:
	docker compose -f docker-compose.yml up -d timescaledb redis
	@echo "Waiting for DB to be ready..."
	@until docker compose exec -T timescaledb pg_isready -U postgres -d kronos_nse 2>/dev/null; do sleep 1; done
	@echo "TimescaleDB ready on port 5434"
	@echo "Redis ready on port 6379"

db-down:
	docker compose -f docker-compose.yml down

db-reset:
	docker compose -f docker-compose.yml down -v
	$(MAKE) db-up

migrate: db-up
	.venv-linux/bin/python -m scripts.bootstrap_db

# ─── Development Servers ─────────────────────────────────────────
dev-api: db-up
	@echo "Starting API server on http://localhost:8000"
	@echo "Docs: http://localhost:8000/docs"
	APP_MODE=VISUAL .venv-linux/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload --log-level info

dev-tui:
	@echo "Starting TUI (connects to API at ws://localhost:8000)"
	KRONOS_DEFAULT_SYMBOL=RELIANCE .venv-linux/bin/python scripts/tui_v2.py

# Full stack: DB + API + TUI (runs in background, use Ctrl+C to stop)
dev: db-up
	@echo "Starting full dev stack..."
	@echo "API: http://localhost:8000 (docs at /docs)"
	@echo "TUI: will launch in 3 seconds..."
	@sleep 3
	@APP_MODE=VISICAL .venv-linux/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000 --log-level info & \
	API_PID=$$!; \
	sleep 3; \
	KRONOS_DEFAULT_SYMBOL=RELIANCE .venv-linux/bin/python scripts/tui_v2.py; \
	kill $$API_PID 2>/dev/null || true

# ─── Testing ─────────────────────────────────────────────────────
test:
	.venv-linux/bin/python -m pytest tests/ -v --tb=short --ignore=tests/unit/test_training.py

test-unit:
	.venv-linux/bin/python -m pytest tests/unit/ -v --tb=short

test-int:
	.venv-linux/bin/python -m pytest tests/integration/ -v --tb=short

test-variance:
	.venv-linux/bin/python -m pytest variance/tests/ -v --tb=short

# ─── Code Quality ────────────────────────────────────────────────
lint:
	.venv-linux/bin/ruff check .
	.venv-linux/bin/mypy --ignore-missing-imports api/ model/ data/ variance/ headless/ scripts/ training/ backtest/ 2>&1 | head -50

fmt:
	.venv-linux/bin/ruff format .
	.venv-linux/bin/ruff check --fix .

# ─── Cleanup ─────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache 2>/dev/null || true
	rm -rf htmlcov 2>/dev/null || true

# ─── Setup ───────────────────────────────────────────────────────
setup:
	@echo "Setting up development environment..."
	@if [ ! -d .venv-linux ]; then \
		python3 -m venv .venv-linux; \
	fi
	.venv-linux/bin/pip install --upgrade pip
	.venv-linux/bin/pip install -e ".[dev]"
	@echo "Creating .env from example..."
	@if [ ! -f .env ]; then cp .env.example .env; fi
	@echo "Setup complete. Run 'make db-up' to start database."

# ─── Shortcuts ───────────────────────────────────────────────────
up: db-up
down: db-down
logs: db-up; docker compose logs -f timescaledb redis
