"""In-memory TTL cache for runtime drift scans.

This module provides a simple per-process cache for storing runtime drift
scan results with a TTL. This allows stop operations to be bound to a
specific, recent scan rather than operating on stale or arbitrary data.

For MVP, this is in-memory. For multi-replica deployments, consider Redis.

SECURITY:
- Scans are server-generated only (never from client)
- scan_id is a random UUID, not guessable
- TTL prevents acting on very stale scans
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# Default TTL for scan entries (60 seconds)
DEFAULT_SCAN_TTL_SECONDS = 60

# Maximum number of cached scans (to prevent memory bloat)
MAX_CACHED_SCANS = 100


@dataclass
class ScanEntry:
    """A cached scan entry with metadata."""

    scan_id: str
    generated_at: datetime
    expires_at: datetime
    payload: dict[str, Any]


@dataclass
class RuntimeScanPayload:
    """Payload stored for a runtime drift scan.

    Contains all information needed to execute a stop operation
    without re-scanning runtime state.
    """

    running_lab_projects_total: int = 0
    running_lab_containers_total: int = 0
    tracked_running_projects: int = 0
    drifted_running_projects: int = 0
    orphaned_running_projects: int = 0

    # List of projects with their classification and container count
    # Each entry: {"project": str, "lab_id": str, "classification": str, "db_status": str|None, "container_count": int}
    projects: list[dict[str, Any]] = field(default_factory=list)


class ScanCache:
    """Thread-safe in-memory TTL cache for runtime scans.

    Usage:
        cache = ScanCache()
        scan_id = cache.put(payload)
        payload = cache.get(scan_id)  # Returns None if expired/missing
    """

    def __init__(self, ttl_seconds: int = DEFAULT_SCAN_TTL_SECONDS):
        self._lock = threading.Lock()
        self._cache: dict[str, ScanEntry] = {}
        self._ttl_seconds = ttl_seconds

    def put(self, payload: dict[str, Any]) -> tuple[str, datetime]:
        """Store a scan payload and return (scan_id, generated_at).

        Args:
            payload: The scan payload to cache

        Returns:
            Tuple of (scan_id, generated_at)
        """
        scan_id = str(uuid4())
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self._ttl_seconds)

        entry = ScanEntry(
            scan_id=scan_id,
            generated_at=now,
            expires_at=expires_at,
            payload=payload,
        )

        with self._lock:
            # Purge expired entries and enforce max size
            self._purge_expired_unsafe()

            if len(self._cache) >= MAX_CACHED_SCANS:
                # Remove oldest entries to make room
                sorted_entries = sorted(
                    self._cache.items(),
                    key=lambda x: x[1].generated_at,
                )
                to_remove = len(self._cache) - MAX_CACHED_SCANS + 1
                for key, _ in sorted_entries[:to_remove]:
                    del self._cache[key]

            self._cache[scan_id] = entry
            logger.debug(f"Cached scan {scan_id}, expires at {expires_at.isoformat()}")

        return scan_id, now

    def get(self, scan_id: str) -> dict[str, Any] | None:
        """Retrieve a scan payload by ID.

        Returns None if the scan doesn't exist or has expired.

        Args:
            scan_id: The scan ID to look up

        Returns:
            The scan payload, or None if expired/missing
        """
        with self._lock:
            entry = self._cache.get(scan_id)

            if entry is None:
                logger.debug(f"Scan {scan_id} not found in cache")
                return None

            now = datetime.now(timezone.utc)
            if now > entry.expires_at:
                # Expired - remove it
                del self._cache[scan_id]
                logger.debug(f"Scan {scan_id} expired at {entry.expires_at.isoformat()}")
                return None

            return entry.payload

    def get_entry(self, scan_id: str) -> ScanEntry | None:
        """Retrieve the full scan entry (including metadata).

        Returns None if the scan doesn't exist or has expired.

        Args:
            scan_id: The scan ID to look up

        Returns:
            The ScanEntry, or None if expired/missing
        """
        with self._lock:
            entry = self._cache.get(scan_id)

            if entry is None:
                return None

            now = datetime.now(timezone.utc)
            if now > entry.expires_at:
                del self._cache[scan_id]
                return None

            return entry

    def _purge_expired_unsafe(self) -> int:
        """Purge all expired entries. Must be called with lock held.

        Returns:
            Number of entries purged
        """
        now = datetime.now(timezone.utc)
        expired = [
            scan_id
            for scan_id, entry in self._cache.items()
            if now > entry.expires_at
        ]

        for scan_id in expired:
            del self._cache[scan_id]

        if expired:
            logger.debug(f"Purged {len(expired)} expired scan entries")

        return len(expired)

    def clear(self) -> None:
        """Clear all cached entries. Useful for testing."""
        with self._lock:
            self._cache.clear()


# Global singleton instance for the application
_scan_cache: ScanCache | None = None


def get_scan_cache() -> ScanCache:
    """Get the global scan cache singleton.

    Returns:
        The global ScanCache instance
    """
    global _scan_cache
    if _scan_cache is None:
        _scan_cache = ScanCache()
    return _scan_cache


def reset_scan_cache() -> None:
    """Reset the global scan cache. Useful for testing."""
    global _scan_cache
    if _scan_cache is not None:
        _scan_cache.clear()
    _scan_cache = None
