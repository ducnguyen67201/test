"""CVE Alias Resolution Service.

Resolves user input (CVE IDs or common names) to cached CVE Dockerfiles.
"""

import re
import logging
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cve_dockerfile import CVEDockerfile

logger = logging.getLogger(__name__)


async def resolve_cve_reference(user_input: str, db: AsyncSession) -> dict:
    """
    Resolve user input to a cached CVE Dockerfile.

    Args:
        user_input: User's search term (CVE ID or alias like "log4shell")
        db: Database session

    Returns:
        {"found": True, "cve_id": "...", "dockerfile": "...", ...}
        or {"found": False, "reason": "..."}
    """
    user_input = user_input.strip().lower()

    if not user_input:
        return {"found": False, "reason": "Empty input"}

    # 1. Try direct CVE ID match
    cve_match = re.search(r"cve-\d{4}-\d{4,}", user_input, re.I)
    if cve_match:
        cve_id = cve_match.group().upper()
        result = await db.execute(
            select(CVEDockerfile).where(CVEDockerfile.cve_id == cve_id)
        )
        entry = result.scalar_one_or_none()
        if entry:
            logger.info(f"Resolved CVE ID '{cve_id}' directly")
            return _entry_to_dict(entry)

    # 2. Try alias match (case-insensitive)
    # PostgreSQL: WHERE 'log4shell' = ANY(lower(aliases::text)::text[])
    # Using array containment with lower-cased comparison
    result = await db.execute(
        select(CVEDockerfile).where(
            func.array_position(
                func.array(
                    select(func.lower(func.unnest(CVEDockerfile.aliases)))
                ),
                user_input,
            ).isnot(None)
        )
    )
    entry = result.scalar_one_or_none()

    if not entry:
        # Fallback: simpler query using ILIKE on array elements
        # This is less efficient but more compatible
        result = await db.execute(
            select(CVEDockerfile).where(
                CVEDockerfile.aliases.any(user_input)
            )
        )
        entry = result.scalar_one_or_none()

    if entry:
        logger.info(f"Resolved alias '{user_input}' to CVE {entry.cve_id}")
        return _entry_to_dict(entry)

    # 3. Not found
    logger.debug(f"No CVE found for reference '{user_input}'")
    return {
        "found": False,
        "reason": f"Unknown reference '{user_input}'. Please provide CVE ID (e.g., CVE-2021-44228).",
    }


def _entry_to_dict(entry: CVEDockerfile) -> dict:
    """Convert CVEDockerfile entry to response dict."""
    return {
        "found": True,
        "cve_id": entry.cve_id,
        "dockerfile": entry.dockerfile,
        "source_files": entry.source_files or [],
        "base_image": entry.base_image,
        "exposed_ports": entry.exposed_ports or [],
        "exploit_hint": entry.exploit_hint,
        "aliases": entry.aliases or [],
        "status": entry.status.value if entry.status else None,
        "confidence_score": entry.confidence_score,
    }


async def add_alias(cve_id: str, alias: str, db: AsyncSession) -> bool:
    """
    Add an alias to a CVE entry.

    Args:
        cve_id: The CVE ID
        alias: The alias to add
        db: Database session

    Returns:
        True if added successfully, False if CVE not found
    """
    alias = alias.strip().lower()
    if not alias:
        return False

    result = await db.execute(
        select(CVEDockerfile).where(CVEDockerfile.cve_id == cve_id.upper())
    )
    entry = result.scalar_one_or_none()

    if not entry:
        return False

    # Add alias if not already present
    current_aliases = entry.aliases or []
    if alias not in [a.lower() for a in current_aliases]:
        entry.aliases = current_aliases + [alias]
        await db.commit()
        logger.info(f"Added alias '{alias}' to CVE {cve_id}")

    return True


async def set_aliases(cve_id: str, aliases: list[str], db: AsyncSession) -> bool:
    """
    Set all aliases for a CVE entry (replaces existing).

    Args:
        cve_id: The CVE ID
        aliases: List of aliases to set
        db: Database session

    Returns:
        True if set successfully, False if CVE not found
    """
    # Clean and dedupe aliases
    clean_aliases = list(set(a.strip().lower() for a in aliases if a.strip()))

    result = await db.execute(
        select(CVEDockerfile).where(CVEDockerfile.cve_id == cve_id.upper())
    )
    entry = result.scalar_one_or_none()

    if not entry:
        return False

    entry.aliases = clean_aliases
    await db.commit()
    logger.info(f"Set aliases for CVE {cve_id}: {clean_aliases}")

    return True
