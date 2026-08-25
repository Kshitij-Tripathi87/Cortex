# Cortex Backend — Development Commands

## Setup

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Lint

```powershell
ruff check .
ruff format --check .
```

## Typecheck

```powershell
mypy app
```

## Test

```powershell
pytest tests/ -v --tb=short
```

## Run Dev Server

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Database Migrations

```powershell
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Downgrade
alembic downgrade -1
```

## Environment Variables

Create `.env` in the backend folder:

```
CORTEX_ENV=dev
CORTEX_DB_DSN=postgresql+asyncpg://localhost/cortex
CORTEX_REDIS_URL=redis://localhost:6379/0
CORTEX_S3_ENDPOINT=http://localhost:9000
CORTEX_S3_BUCKET=cortex-uploads
CORTEX_S3_REGION=us-east-1
CORTEX_S3_ACCESS_KEY=minioadmin
CORTEX_S3_SECRET_KEY=minioadmin
CORTEX_S3_USE_PATH_STYLE=true
```