.PHONY: install run test lint migrate seed db-up db-down db-logs help

# Default target
help:
	@echo "Available targets:"
	@echo "  install   - Install backend & frontend dependencies"
	@echo "  run       - Start backend (Django) and frontend (Vite)"
	@echo "  test      - Run backend tests"
	@echo "  lint      - Lint backend (ruff) and frontend (eslint)"
	@echo "  migrate   - Run Django migrations"
	@echo "  seed      - Load seed data"
	@echo "  db-up     - Start PostgreSQL database"
	@echo "  db-down   - Stop PostgreSQL database"
	@echo "  db-logs   - Show database logs"

# Install dependencies
install: backend-install frontend-install

backend-install:
	cd backend && python -m venv venv && . venv/bin/activate && pip install -r requirements.txt

frontend-install:
	cd frontend && npm install

# Run development servers
run:
	@echo "Starting backend and frontend..."
	@echo "Run 'make run-backend' and 'make run-frontend' in separate terminals"

run-backend:
	cd backend && . venv/bin/activate && python manage.py runserver

run-frontend:
	cd frontend && npm run dev

# Run tests
test:
	cd backend && . venv/bin/activate && python -m pytest -v

# Lint code
lint: backend-lint frontend-lint

backend-lint:
	cd backend && . venv/bin/activate && ruff check . && ruff format --check .

frontend-lint:
	cd frontend && npm run lint

# Database migrations
migrate:
	cd backend && . venv/bin/activate && python manage.py migrate

makemigrations:
	cd backend && . venv/bin/activate && python manage.py makemigrations

# Seed data
seed:
	cd backend && . venv/bin/activate && python manage.py seed

# Database management
db-up:
	docker compose up -d db

db-down:
	docker compose down

db-logs:
	docker compose logs -f db

# Full stack up/down
up: db-up
	@echo "Database started. Run 'make run-backend' and 'make run-frontend' separately."

down: db-down