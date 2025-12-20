"""FastAPI application entry point."""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# =============================================================================
# Logging Configuration (DEBUG level for diagnostics)
# =============================================================================
# Configure root logger BEFORE any app imports to capture all module logs.
# Key areas to watch:
#   - app.services.firecracker_manager: VM creation, vsock, agent communication
#   - app.services.microvm_net_client: TAP/bridge allocation via netd
#   - app.runtime.firecracker_runtime: Lab lifecycle orchestration
#   - app.services.teardown_worker: Lab cleanup
#
# To reduce noise later, change level to logging.INFO or logging.WARNING.
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
    force=True,  # Override any existing config
)

# Reduce noise from third-party libraries
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.INFO)  # Keep access logs at INFO

from app.api.routes import admin, auth, cve_registry, dockerfile_review_queue, evidence, health, internal, labs, recipes
from app.config import settings
from app.db import engine
from app.middleware.size_limit import SizeLimitMiddleware
from app.services.db_schema_guard import ensure_schema_in_sync
from app.services.runtime_selector import RuntimeState
from app.services.teardown_worker import teardown_worker_loop
from app.services.firecracker_cleanup import cleanup_orphaned_firecracker_resources
from app.services.lab_cleanup import watchdog_cleanup, cleanup_orphaned_nat_rules
from app.utils.tmp_janitor import startup_cleanup

logger = logging.getLogger(__name__)

# Watchdog interval in seconds (5 minutes)
WATCHDOG_INTERVAL_SECONDS = 300


async def _watchdog_loop() -> None:
    """Background task that periodically cleans up orphaned resources.

    Runs every WATCHDOG_INTERVAL_SECONDS to catch orphans from:
    - Server crashes/restarts
    - Failed cleanups
    - Race conditions

    SECURITY: Only cleans resources for labs that are terminated or don't exist.
    """
    logger.info(f"Watchdog loop started (interval={WATCHDOG_INTERVAL_SECONDS}s)")

    while True:
        try:
            await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
            result = await watchdog_cleanup()
            if result["orphans_found"] > 0:
                logger.info(
                    f"Watchdog: cleaned {result['orphans_cleaned']}/{result['orphans_found']} orphans"
                )
        except asyncio.CancelledError:
            logger.info("Watchdog loop cancelled")
            break
        except Exception as e:
            logger.error(f"Watchdog loop error: {type(e).__name__}")
            # Continue running despite errors


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

    # Clean up orphaned Firecracker resources (TAPs, bridges, VM dirs) from previous runs
    if settings.octolab_runtime == "firecracker":
        await cleanup_orphaned_firecracker_resources()

        # Clean up orphaned NAT rules at startup
        logger.info("Cleaning up orphaned NAT rules...")
        try:
            nat_result = await cleanup_orphaned_nat_rules()
            if nat_result["rules_cleaned"] > 0:
                logger.info(
                    f"Cleaned {nat_result['rules_cleaned']} orphaned NAT rules"
                )
        except Exception as e:
            logger.warning(f"NAT rules cleanup failed: {type(e).__name__}")

    # Check database schema is in sync with code (fail fast if not)
    logger.info("Checking database schema synchronization...")
    await ensure_schema_in_sync()

    # Start background teardown worker
    worker_task = asyncio.create_task(teardown_worker_loop())

    # Start watchdog for orphan cleanup (only for Firecracker runtime)
    watchdog_task = None
    if settings.octolab_runtime == "firecracker":
        watchdog_task = asyncio.create_task(_watchdog_loop())

    yield

    # Shutdown
    # Cancel worker gracefully
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass  # Expected during shutdown

    # Cancel watchdog gracefully
    if watchdog_task:
        watchdog_task.cancel()
        try:
            await watchdog_task
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

# CORS middleware
# Origins can be extended via CORS_ORIGINS env var (comma-separated)
_cors_origins = [
    "http://localhost:5173",   # Vite dev server
    "http://localhost:3000",   # Next.js dev server
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]
# Add custom origins from environment (e.g., "http://34.151.112.15:3000,http://34.151.112.15")
if os.environ.get("CORS_ORIGINS"):
    _cors_origins.extend(os.environ["CORS_ORIGINS"].split(","))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(labs.router)
app.include_router(recipes.router)
app.include_router(cve_registry.router)
app.include_router(dockerfile_review_queue.router)
app.include_router(internal.router)
app.include_router(evidence.router)
app.include_router(admin.router)

