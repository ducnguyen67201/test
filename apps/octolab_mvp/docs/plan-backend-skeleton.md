# Backend Skeleton Setup Plan

## Directory Structure

```
octolab_mvp/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app, router registration
│   │   ├── db.py                    # SQLAlchemy engine, session, base
│   │   ├── config.py                # Configuration from environment
│   │   ├── models/
│   │   │   ├── __init__.py          # Export all models
│   │   │   ├── base.py               # Base declarative model
│   │   │   ├── user.py               # User model (placeholder)
│   │   │   ├── lab.py                # Lab model (placeholder)
│   │   │   └── recipe.py             # Recipe model (placeholder)
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── health.py             # Health/version response schemas
│   │   │   ├── user.py               # User schemas (placeholder)
│   │   │   ├── lab.py                # Lab schemas (placeholder)
│   │   │   └── recipe.py             # Recipe schemas (placeholder)
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── routes/
│   │   │       ├── __init__.py
│   │   │       ├── health.py         # /health and /version endpoints
│   │   │       ├── auth.py           # Auth routes (placeholder)
│   │   │       ├── labs.py           # Lab routes (placeholder)
│   │   │       └── recipes.py        # Recipe routes (placeholder)
│   │   └── services/
│   │       ├── __init__.py
│   │       └── (placeholder for future services)
│   ├── alembic/
│   │   ├── versions/                # Migration files
│   │   ├── env.py                   # Alembic environment config
│   │   ├── script.py.mako           # Migration template
│   │   └── README
│   ├── alembic.ini                   # Alembic configuration
│   ├── tests/                        # Test directory structure
│   │   ├── __init__.py
│   │   ├── conftest.py               # Pytest fixtures
│   │   └── test_health.py            # Test for health endpoints
│   ├── .env.example                  # Example environment variables
│   ├── pyproject.toml                # Python project config (or requirements.txt)
│   └── README.md
├── frontend/                         # Placeholder directory
│   └── README.md                     # "Frontend coming soon"
├── infra/                            # Placeholder directory
│   └── README.md                     # "Infrastructure coming soon"
├── recipes/                          # Placeholder directory (for recipe definitions)
│   └── README.md                     # "Recipe definitions coming soon"
├── .gitignore
└── README.md
```

## Files to Create

### 1. Core Application Files

**`backend/app/main.py`**
- FastAPI app instance
- Include routers from `app/api/routes/`
- Startup/shutdown hooks for DB connection management
- CORS middleware (placeholder for frontend)
- Exception handlers

**`backend/app/db.py`**
- SQLAlchemy 2.x async engine creation
- Async session factory
- Base declarative model
- Dependency function for getting DB session in routes
- Connection string from config

**`backend/app/config.py`**
- Pydantic Settings for environment variables
- Database URL construction
- App metadata (name, version)
- Logging configuration

### 2. Models Package (`backend/app/models/`)

**`backend/app/models/base.py`**
- Base declarative class using SQLAlchemy 2.0 `DeclarativeBase`
- Common mixins (timestamps, UUID primary key)

**`backend/app/models/user.py`**
- User model with UUID primary key
- Email, password_hash fields
- Relationship to Labs (one-to-many)
- Timestamps

**`backend/app/models/recipe.py`**
- Recipe model with UUID primary key
- Fields: name, description, software, version_constraint, exploit_family, is_active
- Timestamps
- Relationship to Labs (one-to-many)

**`backend/app/models/lab.py`**
- Lab model with UUID primary key
- Foreign keys: owner_id → User, recipe_id → Recipe
- Status field (Enum: requested, provisioning, ready, ending, finished, failed)
- requested_intent (JSON field)
- Timestamps: created_at, updated_at, finished_at

**`backend/app/models/__init__.py`**
- Import and export all models
- Import Base for Alembic
- All models must be imported here so Alembic can discover them

### 3. Schemas Package (`backend/app/schemas/`)

**`backend/app/schemas/health.py`**
- HealthResponse schema
- VersionResponse schema

**`backend/app/schemas/user.py`**, **`backend/app/schemas/lab.py`**, **`backend/app/schemas/recipe.py`**
- Placeholder files with basic structure comments
- Will contain Pydantic v2 models for request/response

### 4. API Routes (`backend/app/api/routes/`)

**`backend/app/api/routes/health.py`**
- GET `/health` endpoint returning status
- GET `/version` endpoint returning app version
- No authentication required

**`backend/app/api/routes/auth.py`**, **`backend/app/api/routes/labs.py`**, **`backend/app/api/routes/recipes.py`**
- Placeholder files with router setup
- Will contain domain-specific endpoints later

**`backend/app/api/routes/__init__.py`**
- Export all routers

### 5. Alembic Setup

**`backend/alembic.ini`**
- Standard Alembic config
- Database URL from environment variable
- Script location: `alembic/`

**`backend/alembic/env.py`**
- Import `Base` from `app.models` (not `app.models.base`)
- Set `target_metadata = Base.metadata`
- Configure async engine if using async migrations (or sync for initial setup)
- Load database URL from config
- Ensure all models are imported via `app.models.__init__.py` so Alembic can discover them

**`backend/alembic/script.py.mako`**
- Standard migration template

### 6. Configuration Files

**`backend/pyproject.toml`** (or `requirements.txt`)
- FastAPI
- SQLAlchemy 2.x
- Pydantic v2
- Alembic
- asyncpg (PostgreSQL async driver)
- python-dotenv
- uvicorn[standard]
- pytest, pytest-asyncio (for tests)

**`backend/.env.example`**
- DATABASE_URL
- APP_NAME
- APP_VERSION
- LOG_LEVEL

**`.gitignore`** (root level)
- Python ignores
- .env file
- __pycache__
- .venv
- alembic versions (keep structure)

## Alembic Integration

1. **Base Model Import**: Alembic's `env.py` imports `Base` from `app.models` (which is exported from `app/models/__init__.py`)
2. **Metadata**: Set `target_metadata = Base.metadata` in `backend/alembic/env.py`
3. **Model Discovery**: All models must be imported in `app/models/__init__.py` so Alembic can auto-generate migrations
4. **Initial Migration**: Create initial migration after models are defined (not in this skeleton phase)

## Minimal Endpoints

**GET `/health`**
- Returns `{"status": "healthy"}` or `{"status": "unhealthy"}` with optional DB check
- Status code 200

**GET `/version`**
- Returns app name and version from config
- Status code 200

Both endpoints in `backend/app/api/routes/health.py` and registered in `backend/app/main.py`.

## Implementation Steps

1. Create directory structure
2. Create `backend/pyproject.toml` with dependencies
3. Create `backend/app/config.py` for environment-based configuration
4. Create `backend/app/db.py` with SQLAlchemy 2.x async setup
5. Create `backend/app/models/base.py` with Base and common mixins
6. Create placeholder model files (user, lab, recipe) with basic structure
7. Create `backend/app/models/__init__.py` exporting Base and all models
8. Create `backend/app/schemas/health.py` with response schemas
9. Create `backend/app/api/routes/health.py` with /health and /version endpoints
10. Create `backend/app/main.py` with FastAPI app and router registration
11. Create `backend/alembic.ini` and `backend/alembic/env.py` wired to `app.models`
12. Create `backend/.env.example`, `.gitignore`, `README.md`
13. Create placeholder directories (frontend/, infra/, recipes/)
14. Create basic test structure with `backend/tests/conftest.py` and `backend/tests/test_health.py`

