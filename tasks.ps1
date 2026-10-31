<# 
.SYNOPSIS
    PowerShell task runner for Paint Shop Management System (equivalent to Makefile)

.DESCRIPTION
    Provides the same targets as the Makefile for Windows users without make.
#>

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet('install', 'run', 'test', 'lint', 'migrate', 'seed', 'db-up', 'db-down', 'db-logs', 'backend-install', 'frontend-install', 'run-backend', 'run-frontend', 'backend-lint', 'frontend-lint', 'makemigrations', 'help')]
    [string]$Target = 'help'
)

function Write-Help {
    Write-Host "Available targets:" -ForegroundColor Cyan
    Write-Host "  install          - Install backend & frontend dependencies"
    Write-Host "  run              - Start backend (Django) and frontend (Vite)"
    Write-Host "  test             - Run backend tests"
    Write-Host "  lint             - Lint backend (ruff) and frontend (eslint)"
    Write-Host "  migrate          - Run Django migrations"
    Write-Host "  seed             - Load seed data"
    Write-Host "  db-up            - Start PostgreSQL database"
    Write-Host "  db-down          - Stop PostgreSQL database"
    Write-Host "  db-logs          - Show database logs"
    Write-Host "  backend-install  - Install backend dependencies only"
    Write-Host "  frontend-install - Install frontend dependencies only"
    Write-Host "  run-backend      - Start Django development server"
    Write-Host "  run-frontend     - Start Vite development server"
    Write-Host "  backend-lint     - Lint backend with ruff"
    Write-Host "  frontend-lint    - Lint frontend with eslint"
    Write-Host "  makemigrations   - Create Django migrations"
    Write-Host "  help             - Show this help"
}

function Invoke-BackendInstall {
    Write-Host "Installing backend dependencies..." -ForegroundColor Green
    Set-Location "backend"
    if (-not (Test-Path "venv")) {
        python -m venv venv
    }
    & ".\venv\Scripts\Activate.ps1"
    pip install -r requirements.txt
    Set-Location ".."
}

function Invoke-FrontendInstall {
    Write-Host "Installing frontend dependencies..." -ForegroundColor Green
    Set-Location "frontend"
    npm install
    Set-Location ".."
}

function Invoke-Test {
    Write-Host "Running backend tests..." -ForegroundColor Green
    Set-Location "backend"
    & ".\venv\Scripts\Activate.ps1"
    python -m pytest -v
    Set-Location ".."
}

function Invoke-Lint {
    Write-Host "Linting backend..." -ForegroundColor Green
    Set-Location "backend"
    & ".\venv\Scripts\Activate.ps1"
    ruff check .
    ruff format --check .
    Set-Location ".."
    
    Write-Host "Linting frontend..." -ForegroundColor Green
    Set-Location "frontend"
    npm run lint
    Set-Location ".."
}

function Invoke-Migrate {
    Write-Host "Running Django migrations..." -ForegroundColor Green
    Set-Location "backend"
    & ".\venv\Scripts\Activate.ps1"
    python manage.py migrate
    Set-Location ".."
}

function Invoke-Seed {
    Write-Host "Loading seed data..." -ForegroundColor Green
    Set-Location "backend"
    & ".\venv\Scripts\Activate.ps1"
    python manage.py seed
    Set-Location ".."
}

function Invoke-DbUp {
    Write-Host "Starting PostgreSQL database..." -ForegroundColor Green
    docker compose up -d db
}

function Invoke-DbDown {
    Write-Host "Stopping PostgreSQL database..." -ForegroundColor Green
    docker compose down
}

function Invoke-DbLogs {
    Write-Host "Showing database logs..." -ForegroundColor Green
    docker compose logs -f db
}

function Invoke-RunBackend {
    Write-Host "Starting Django development server..." -ForegroundColor Green
    Set-Location "backend"
    & ".\venv\Scripts\Activate.ps1"
    python manage.py runserver
    Set-Location ".."
}

function Invoke-RunFrontend {
    Write-Host "Starting Vite development server..." -ForegroundColor Green
    Set-Location "frontend"
    npm run dev
    Set-Location ".."
}

function Invoke-MakeMigrations {
    Write-Host "Creating Django migrations..." -ForegroundColor Green
    Set-Location "backend"
    & ".\venv\Scripts\Activate.ps1"
    python manage.py makemigrations
    Set-Location ".."
}

# Main dispatch
switch ($Target) {
    'help' { Write-Help }
    'install' { 
        Invoke-BackendInstall
        Invoke-FrontendInstall 
    }
    'backend-install' { Invoke-BackendInstall }
    'frontend-install' { Invoke-FrontendInstall }
    'test' { Invoke-Test }
    'lint' { Invoke-Lint }
    'backend-lint' { 
        Set-Location "backend"
        & ".\venv\Scripts\Activate.ps1"
        ruff check .
        ruff format --check .
        Set-Location ".."
    }
    'frontend-lint' { 
        Set-Location "frontend"
        npm run lint
        Set-Location ".."
    }
    'migrate' { Invoke-Migrate }
    'seed' { Invoke-Seed }
    'db-up' { Invoke-DbUp }
    'db-down' { Invoke-DbDown }
    'db-logs' { Invoke-DbLogs }
    'run-backend' { Invoke-RunBackend }
    'run-frontend' { Invoke-RunFrontend }
    'makemigrations' { Invoke-MakeMigrations }
    'run' {
        Write-Host "Run '.\tasks.ps1 run-backend' and '.\tasks.ps1 run-frontend' in separate terminals" -ForegroundColor Yellow
    }
    default { Write-Help }
}