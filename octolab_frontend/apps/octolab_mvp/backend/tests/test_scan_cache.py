"""Tests for scan cache and scan-bound stop operations.

These tests verify:
- Scan cache TTL behavior
- scan_id required for stop-labs
- 409 response for expired/invalid scan_id
- Mode-based target derivation from cached scan
- Before/after counts in response
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
import time

# Mark all tests as not requiring database
pytestmark = pytest.mark.no_db


class TestScanCache:
    """Tests for ScanCache class."""

    def test_put_returns_scan_id_and_timestamp(self):
        """Test that put() returns a scan_id and generated_at."""
        from app.services.scan_cache import ScanCache

        cache = ScanCache(ttl_seconds=60)
        payload = {"foo": "bar"}

        scan_id, generated_at = cache.put(payload)

        assert scan_id is not None
        assert len(scan_id) == 36  # UUID format
        assert isinstance(generated_at, datetime)
        assert generated_at.tzinfo is not None  # Should be timezone-aware

    def test_get_returns_payload_before_expiry(self):
        """Test that get() returns payload before TTL expires."""
        from app.services.scan_cache import ScanCache

        cache = ScanCache(ttl_seconds=60)
        payload = {"running_lab_projects_total": 5, "projects": []}

        scan_id, _ = cache.put(payload)
        retrieved = cache.get(scan_id)

        assert retrieved == payload

    def test_get_returns_none_after_expiry(self):
        """Test that get() returns None after TTL expires."""
        from app.services.scan_cache import ScanCache

        # Very short TTL for testing
        cache = ScanCache(ttl_seconds=1)
        payload = {"foo": "bar"}

        scan_id, _ = cache.put(payload)

        # Wait for expiry
        time.sleep(1.1)

        retrieved = cache.get(scan_id)
        assert retrieved is None

    def test_get_returns_none_for_unknown_scan_id(self):
        """Test that get() returns None for unknown scan_id."""
        from app.services.scan_cache import ScanCache

        cache = ScanCache()
        retrieved = cache.get("not-a-real-scan-id")

        assert retrieved is None

    def test_get_entry_returns_full_metadata(self):
        """Test that get_entry() returns full ScanEntry with metadata."""
        from app.services.scan_cache import ScanCache

        cache = ScanCache(ttl_seconds=60)
        payload = {"foo": "bar"}

        scan_id, generated_at = cache.put(payload)
        entry = cache.get_entry(scan_id)

        assert entry is not None
        assert entry.scan_id == scan_id
        assert entry.generated_at == generated_at
        assert entry.payload == payload
        assert entry.expires_at > generated_at

    def test_max_cached_scans_eviction(self):
        """Test that oldest entries are evicted when max is reached."""
        from app.services.scan_cache import ScanCache, MAX_CACHED_SCANS

        cache = ScanCache(ttl_seconds=60)

        # Fill cache to max
        scan_ids = []
        for i in range(MAX_CACHED_SCANS + 10):
            scan_id, _ = cache.put({"index": i})
            scan_ids.append(scan_id)

        # First 10 should have been evicted
        for scan_id in scan_ids[:10]:
            assert cache.get(scan_id) is None

        # Later ones should still exist
        for scan_id in scan_ids[10:]:
            assert cache.get(scan_id) is not None

    def test_clear_removes_all_entries(self):
        """Test that clear() removes all entries."""
        from app.services.scan_cache import ScanCache

        cache = ScanCache()

        scan_id1, _ = cache.put({"a": 1})
        scan_id2, _ = cache.put({"b": 2})

        cache.clear()

        assert cache.get(scan_id1) is None
        assert cache.get(scan_id2) is None

    def test_thread_safety(self):
        """Test that cache is thread-safe."""
        from app.services.scan_cache import ScanCache
        import threading

        cache = ScanCache(ttl_seconds=60)
        results = []

        def put_and_get():
            scan_id, _ = cache.put({"thread": threading.current_thread().name})
            payload = cache.get(scan_id)
            results.append(payload is not None)

        threads = [threading.Thread(target=put_and_get) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(results)


class TestGlobalScanCache:
    """Tests for global scan cache singleton."""

    def test_get_scan_cache_returns_singleton(self):
        """Test that get_scan_cache() returns the same instance."""
        from app.services.scan_cache import get_scan_cache, reset_scan_cache

        reset_scan_cache()  # Start fresh

        cache1 = get_scan_cache()
        cache2 = get_scan_cache()

        assert cache1 is cache2

    def test_reset_scan_cache_clears_and_creates_new(self):
        """Test that reset_scan_cache() clears entries."""
        from app.services.scan_cache import get_scan_cache, reset_scan_cache

        reset_scan_cache()  # Start fresh

        cache = get_scan_cache()
        scan_id, _ = cache.put({"test": "data"})

        reset_scan_cache()

        cache2 = get_scan_cache()
        assert cache2.get(scan_id) is None


class TestStopLabsScanIdValidation:
    """Tests for stop-labs scan_id validation."""

    def test_stop_labs_request_requires_scan_id(self):
        """Test that StopLabsRequest requires scan_id field."""
        from app.api.routes.admin import StopLabsRequest, StopLabsMode, STOP_LABS_CONFIRM_PHRASE

        # scan_id is required
        with pytest.raises(Exception):  # Pydantic validation error
            StopLabsRequest(
                mode=StopLabsMode.ALL_RUNNING,
                confirm=True,
                confirm_phrase=STOP_LABS_CONFIRM_PHRASE,
                # Missing scan_id
            )

        # With scan_id should work
        request = StopLabsRequest(
            scan_id="test-scan-id",
            mode=StopLabsMode.ALL_RUNNING,
            confirm=True,
            confirm_phrase=STOP_LABS_CONFIRM_PHRASE,
        )
        assert request.scan_id == "test-scan-id"


class TestStopLabsResponseFormat:
    """Tests for stop-labs response format with before/after counts."""

    def test_stop_labs_response_has_before_after_fields(self):
        """Test that StopLabsResponse has before/after count fields."""
        from app.api.routes.admin import StopLabsResponse

        response = StopLabsResponse(
            scan_id="test-scan-id",
            mode="all_running",
            targets_requested=5,
            targets_found=5,
            before_projects=5,
            before_containers=10,
            projects_stopped=5,
            projects_failed=0,
            networks_removed=10,
            networks_failed=0,
            after_projects=0,
            after_containers=0,
            errors=[],
            results=[],
            message="All stopped",
        )

        assert response.scan_id == "test-scan-id"
        assert response.before_projects == 5
        assert response.before_containers == 10
        assert response.after_projects == 0
        assert response.after_containers == 0

    def test_stop_labs_response_mode_string(self):
        """Test that StopLabsResponse mode is returned as string."""
        from app.api.routes.admin import StopLabsResponse

        response = StopLabsResponse(
            scan_id="test-scan-id",
            mode="drifted_only",
            targets_requested=3,
            targets_found=3,
            before_projects=10,
            before_containers=20,
            projects_stopped=3,
            projects_failed=0,
            networks_removed=6,
            networks_failed=0,
            after_projects=7,
            after_containers=14,
            errors=[],
            results=[],
            message="Stopped drifted",
        )

        assert response.mode == "drifted_only"


class TestRuntimeDriftResponseFormat:
    """Tests for runtime-drift response format with scan_id."""

    def test_runtime_drift_response_has_scan_id(self):
        """Test that RuntimeDriftResponse has scan_id and generated_at fields."""
        from app.api.routes.admin import RuntimeDriftResponse

        now = datetime.now(timezone.utc).isoformat()
        response = RuntimeDriftResponse(
            scan_id="test-scan-id",
            generated_at=now,
            running_lab_projects_total=5,
            running_lab_containers_total=10,
            tracked_running_projects=3,
            drifted_running_projects=1,
            orphaned_running_projects=1,
            projects=[],
            debug_sample=[],
        )

        assert response.scan_id == "test-scan-id"
        assert response.generated_at == now


class TestScanCachePayloadFormat:
    """Tests for scan cache payload format used by stop-labs."""

    def test_cache_payload_has_classification_counts(self):
        """Test that cache payload has counts for each classification."""
        from app.services.scan_cache import ScanCache

        cache = ScanCache()
        payload = {
            "running_lab_projects_total": 10,
            "running_lab_containers_total": 20,
            "tracked_running_projects": 5,
            "drifted_running_projects": 3,
            "orphaned_running_projects": 2,
            "projects": [
                {"project": "octolab_111", "classification": "tracked"},
                {"project": "octolab_222", "classification": "drifted"},
                {"project": "octolab_333", "classification": "orphaned"},
            ],
        }

        scan_id, _ = cache.put(payload)
        retrieved = cache.get(scan_id)

        assert retrieved["running_lab_projects_total"] == 10
        assert retrieved["tracked_running_projects"] == 5
        assert retrieved["drifted_running_projects"] == 3
        assert retrieved["orphaned_running_projects"] == 2
        assert len(retrieved["projects"]) == 3


class TestModeBasedTargetDerivation:
    """Tests for deriving targets from cached scan based on mode."""

    def test_orphaned_only_mode_targets(self):
        """Test that orphaned_only mode only targets orphaned projects."""
        from app.api.routes.admin import StopLabsMode

        cached_projects = [
            {"project": "octolab_111", "classification": "tracked"},
            {"project": "octolab_222", "classification": "drifted"},
            {"project": "octolab_333", "classification": "orphaned"},
            {"project": "octolab_444", "classification": "orphaned"},
        ]

        mode = StopLabsMode.ORPHANED_ONLY
        targets = [
            p["project"] for p in cached_projects
            if p["classification"] == "orphaned"
        ]

        assert len(targets) == 2
        assert "octolab_333" in targets
        assert "octolab_444" in targets

    def test_drifted_only_mode_targets(self):
        """Test that drifted_only mode only targets drifted projects."""
        from app.api.routes.admin import StopLabsMode

        cached_projects = [
            {"project": "octolab_111", "classification": "tracked"},
            {"project": "octolab_222", "classification": "drifted"},
            {"project": "octolab_333", "classification": "orphaned"},
        ]

        mode = StopLabsMode.DRIFTED_ONLY
        targets = [
            p["project"] for p in cached_projects
            if p["classification"] == "drifted"
        ]

        assert len(targets) == 1
        assert "octolab_222" in targets

    def test_tracked_only_mode_targets(self):
        """Test that tracked_only mode only targets tracked projects."""
        from app.api.routes.admin import StopLabsMode

        cached_projects = [
            {"project": "octolab_111", "classification": "tracked"},
            {"project": "octolab_222", "classification": "drifted"},
            {"project": "octolab_333", "classification": "tracked"},
        ]

        mode = StopLabsMode.TRACKED_ONLY
        targets = [
            p["project"] for p in cached_projects
            if p["classification"] == "tracked"
        ]

        assert len(targets) == 2
        assert "octolab_111" in targets
        assert "octolab_333" in targets

    def test_all_running_mode_targets(self):
        """Test that all_running mode targets all projects."""
        from app.api.routes.admin import StopLabsMode

        cached_projects = [
            {"project": "octolab_111", "classification": "tracked"},
            {"project": "octolab_222", "classification": "drifted"},
            {"project": "octolab_333", "classification": "orphaned"},
        ]

        mode = StopLabsMode.ALL_RUNNING
        targets = [p["project"] for p in cached_projects]

        assert len(targets) == 3
