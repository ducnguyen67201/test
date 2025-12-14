"""FastAPI application entry point."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import admin, auth, evidence, health, internal, labs, recipes
from app.config import settings
from app.db import engine
from app.middleware.size_limit import SizeLimitMiddleware
from app.services.db_schema_guard import ensure_schema_in_sync
from app.services.runtime_selector import RuntimeState
from app.services.teardown_worker import teardown_worker_loop
from app.utils.tmp_janitor import startup_cleanup

logger = logging.getLogger(__name__)


def _validate_runtime_selection() -> None:
    """Validate runtime selection at FastAPI startup.

    SECURITY:
    - Default is firecracker (production-safe)
    - Production environment ONLY allows firecracker/noop
    - Compose/k8s runtimes allowed only in dev/test
    - Firecracker triggers doctor checks to ensure prerequisites are met

    Raises:
        RuntimeError: If firecracker prerequisites fail
    """
    runtime = settings.octolab_runtime
    app_env = settings.app_env.lower()

    logger.info(f"Runtime selection: OCTOLAB_RUNTIME={runtime} (APP_ENV={app_env})")

    # Production check (redundant with config validator, but defense in depth)
    if app_env == "production" and runtime not in ("firecracker", "noop"):
        raise RuntimeError(
            f"Production requires OCTOLAB_RUNTIME=firecracker. "
            f"Got '{runtime}'. This is a security requirement."
        )

    # Firecracker/microvm requires additional validation
    if runtime == "firecracker":
        _validate_firecracker_prerequisites()


def _validate_firecracker_prerequisites() -> None:
    """Validate Firecracker runtime prerequisites at startup.

    Called when OCTOLAB_RUNTIME=firecracker is explicitly set.
    Fails hard with RuntimeError if doctor checks fail.

    SECURITY:
    - NO fallback to compose runtime - fails closed
    - Error messages are redacted (no full paths or secrets)
    - Prevents running labs with broken microvm config
    - Uses standalone microvm_doctor that doesn't require Settings for core checks
    """
    from app.services.microvm_doctor import run_checks, get_fatal_summary

    logger.info("OCTOLAB_RUNTIME=firecracker - running microVM doctor checks...")

    result = run_checks(debug=False)

    if not result["is_ok"]:
        # Build error message with redacted details
        fatal_count = result["summary"]["fatal"]
        error_msg = get_fatal_summary(result)

        logger.error(
            f"Firecracker runtime validation FAILED: {fatal_count} fatal issue(s)"
        )
        for check in result["checks"][:5]:  # Log first 5 failed checks
            if check["status"] == "FAIL" and check["severity"] == "fatal":
                hint = check.get("hint") or check.get("message", "")
                logger.error(f"  - {check['name']}: {hint[:100]}")

        raise RuntimeError(
            f"Cannot start with OCTOLAB_RUNTIME=firecracker: {error_msg}. "
            "Fix the issues above. NO FALLBACK to compose."
        )

    # Log warnings but continue
    warn_checks = [c for c in result["checks"] if c["status"] == "WARN"]
    if warn_checks:
        logger.warning(f"Firecracker runtime has {len(warn_checks)} warning(s):")
        for w in warn_checks:
            logger.warning(f"  - {w['name']}: {w['message'][:80]}")

    summary = result["summary"]
    logger.info(
        f"Firecracker runtime validation passed: OK={summary['ok']} WARN={summary['warn']}"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown events.
    """
    # Startup

    # FAIL-HARD: Validate runtime selection at startup (not at import time)
    # This allows Alembic to import config without OCTOLAB_RUNTIME set,
    # while ensuring the API itself cannot start without explicit runtime.
    _validate_runtime_selection()  # Raises RuntimeError if not set or firecracker fails

    # Initialize runtime state for dynamic runtime override
    # This is in-memory only (resets on restart) for dev safety
    app.state.runtime_state = RuntimeState()
    logger.info("Initialized runtime state")

    # Clean up any orphaned evidence temp directories from previous runs
    logger.info("Cleaning up orphaned evidence temp directories...")
    await startup_cleanup()

    # Check database schema is in sync with code (fail fast if not)
    logger.info("Checking database schema synchronization...")
    await ensure_schema_in_sync()

    # Start background teardown worker
    worker_task = asyncio.create_task(teardown_worker_loop())

    yield

    # Shutdown
    # Cancel worker gracefully
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass  # Expected during shutdown

    await engine.dispose()


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

# Size limit middleware for Falco ingestion (prevents DoS)
app.add_middleware(
    SizeLimitMiddleware,
    path_limits={
        "/internal/falco/ingest": 1 * 1024 * 1024,  # 1MB limit
    },
)

# CORS middleware (dev: only permit local frontend; tighten further for prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(labs.router)
app.include_router(recipes.router)
app.include_router(internal.router)
app.include_router(evidence.router)
app.include_router(admin.router)

