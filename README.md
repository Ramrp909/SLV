# Paint Shop Management System

Monorepo for a single-owner paint and hardware shop management system.

## Stack

- **Backend**: Django 5 + Django REST Framework + PostgreSQL 16
- **Frontend**: React 18 + Vite
- **API**: REST `/api/v1`, JWT auth (single owner user)

## Prerequisites

- Docker & Docker Compose
- Python 3.12+ (for local development)
- Node.js 18+ (for frontend development)

## Quick Start (Docker)

```bash
# Start PostgreSQL database
docker compose up -d db

# Verify database is healthy
docker compose ps
```

## Local Development

### Backend

```bash
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1   # Windows PowerShell
# source venv/bin/activate    # Linux/macOS

pip install -r requirements.txt
cp ../.env.example .env
# Edit .env with your settings

python manage.py migrate
python manage.py runserver
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Makefile Targets (Windows: use `tasks.ps1`)

| Target | Description |
|--------|-------------|
| `make install` | Install backend & frontend dependencies |
| `make run` | Start backend (Django) and frontend (Vite) |
| `make test` | Run backend tests |
| `make lint` | Lint backend (ruff) and frontend (eslint) |
| `make migrate` | Run Django migrations |
| `make seed` | Load seed data |

## Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Required variables:
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` - Database credentials
- `DJANGO_SECRET_KEY` - Django secret key
- `DJANGO_DEBUG` - Set to `True` for development

## Project Structure

```
project-starter-kit/
├── backend/          # Django project (to be created)
├── frontend/         # React + Vite project (to be created)
├── docs/             # Blueprint documentation
├── docker-compose.yml
├── Makefile
├── tasks.ps1         # PowerShell equivalent of Makefile
├── .env.example
├── .gitignore
└── AGENTS.md         # AI coding assistant rules
```

## License

Internal use only.