"""Database schema drift detection and guardrails.

Prevents runtime failures caused by code expecting DB columns that don't exist
because Alembic migrations haven't been applied.

SECURITY: Never log DB passwords or full connection URLs.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Backend directory (parent of app/)
BACKEND_DIR = Path(__file__).resolve().parents[2]


class SchemaStatus(TypedDict):
    """Schema synchronization status."""

    db_revision: str | None
    code_revision: str | None
    in_sync: bool
    reason: str


async def get_db_revision(session: "AsyncSession") -> str | None:
    """
    Get the current database revision from alembic_version table.

    Args:
        session: Async database session

    Returns:
        Current revision string, or None if table doesn't exist
    """
    try:
        result = await session.execute(
            text("SELECT version_num FROM alembic_version LIMIT 1")
        )
        row = result.fetchone()
        if row:
            return row[0]
        return None
    except Exception as e:
        # Table doesn't exist or other DB error
        error_type = type(e).__name__
        if "UndefinedTable" in error_type or "does not exist" in str(e).lower():
            return None
        # Log error type only, not full message (might contain sensitive info)
        logger.warning(f"Error querying alembic_version: {error_type}")
        return None


def get_code_head_revision() -> str | None:
    """
    Get the current head revision from Alembic migration scripts.

    Uses Alembic's ScriptDirectory to find the head revision without
    requiring a database connection.

    Returns:
        Head revision string, or None if unable to determine
    """
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        # Create Alembic config pointing to our alembic.ini
        alembic_ini = BACKEND_DIR / "alembic.ini"
        if not alembic_ini.exists():
            logger.warning(f"alembic.ini not found at {alembic_ini}")
            return None

        config = Config(str(alembic_ini))
        # Ensure script_location points to backend/alembic in case working dir differs
        config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))

        # Get script directory
        script_dir = ScriptDirectory.from_config(config)

        # Get current head(s) - usually just one
        heads = script_dir.get_heads()
        if not heads:
            logger.warning("No Alembic head revisions found")
            return None

        # Return first head (most repos have a single linear history)
        return heads[0]

    except ImportError:
        logger.warning("Alembic not installed - cannot determine code revision")
        return None
    except Exception as e:
        logger.warning(f"Error determining code head revision: {type(e).__name__}")
        return None


async def check_schema_in_sync(session: "AsyncSession") -> SchemaStatus:
    """
    Check if database schema is in sync with code.

    Args:
        session: Async database session

    Returns:
        SchemaStatus dict with db_revision, code_revision, in_sync, and reason
    """
    db_revision = await get_db_revision(session)
    code_revision = get_code_head_revision()

    # Determine sync status and reason
    if db_revision is None and code_revision is None:
        return SchemaStatus(
            db_revision=None,
            code_revision=None,
            in_sync=False,
            reason="Cannot determine either revision (check Alembic setup)",
        )

    if db_revision is None:
        return SchemaStatus(
            db_revision=None,
            code_revision=code_revision,
            in_sync=False,
            reason="alembic_version table missing - migrations likely never ran",
        )

    if code_revision is None:
        return SchemaStatus(
            db_revision=db_revision,
            code_revision=None,
            in_sync=False,
            reason="Cannot determine code head revision",
        )

    if db_revision == code_revision:
        return SchemaStatus(
            db_revision=db_revision,
            code_revision=code_revision,
            in_sync=True,
            reason="Database schema matches code",
        )

    # Revisions don't match - try to determine direction
    # Note: We can't easily determine if DB is ahead or behind without
    # walking the revision history, so we just report mismatch
    return SchemaStatus(
        db_revision=db_revision,
        code_revision=code_revision,
        in_sync=False,
        reason=f"Schema mismatch: DB at {db_revision[:8]}..., code at {code_revision[:8]}...",
    )


async def ensure_schema_in_sync() -> None:
    """
    Check schema synchronization and fail fast if not in sync.

    Called during application startup. Raises RuntimeError if schema
    is out of sync, unless ALLOW_PENDING_MIGRATIONS=1 is set.

    Raises:
        RuntimeError: If schema is not in sync and override not set
    """
    from app.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        status = await check_schema_in_sync(session)

    if status["in_sync"]:
        logger.info(
            f"Database schema in sync (revision: {status['db_revision'][:8] if status['db_revision'] else 'none'}...)"
        )
        return

    # Schema not in sync
    allow_pending = os.environ.get("ALLOW_PENDING_MIGRATIONS", "").lower() in (
        "1",
        "true",
        "yes",
    )

    message = (
        f"Database schema is not in sync with code.\n"
        f"  DB revision:   {status['db_revision'] or '(none)'}\n"
        f"  Code revision: {status['code_revision'] or '(none)'}\n"
        f"  Reason: {status['reason']}\n"
        f"\n"
        f"To fix, run from backend/:\n"
        f"  alembic upgrade head\n"
    )

    if allow_pending:
        logger.warning(
            f"Schema drift detected but ALLOW_PENDING_MIGRATIONS=1 is set. "
            f"DB: {status['db_revision']}, Code: {status['code_revision']}"
        )
        return

    raise RuntimeError(message)
