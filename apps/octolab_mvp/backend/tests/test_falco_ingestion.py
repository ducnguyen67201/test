"""Tests for Falco event ingestion endpoint.

Tests cover:
- Token validation (401 without/with invalid token)
- Rate limiting per lab
- Deduplication via event hash
- Container name parsing (lab-{uuid}-{role})
- Event storage in database
- Size limit middleware
"""

import hashlib
import time
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.api.routes.internal import (
    CONTAINER_NAME_PATTERN,
    check_dedup,
    check_rate_limit,
    compute_event_hash,
    extract_lab_id,
    FalcoEvent,
    _dedup_cache,
    _rate_limit_cache,
)


@pytest.mark.no_db
class TestContainerNameParsing:
    """Tests for container name to lab ID extraction."""

    def test_valid_container_name(self):
        """Valid lab container names should extract UUID."""
        lab_id = uuid4()
        container_name = f"lab-{lab_id}-octobox"

        extracted = extract_lab_id(container_name)

        assert extracted == lab_id

    def test_valid_container_name_different_roles(self):
        """Various role names should be accepted."""
        lab_id = uuid4()

        for role in ["octobox", "target", "gateway", "web", "db"]:
            container_name = f"lab-{lab_id}-{role}"
            extracted = extract_lab_id(container_name)
            assert extracted == lab_id, f"Failed for role: {role}"

    def test_invalid_container_name_no_prefix(self):
        """Container names without 'lab-' prefix should return None."""
        assert extract_lab_id("container-abc123-role") is None
        assert extract_lab_id("my-container") is None
        assert extract_lab_id("octobox") is None

    def test_invalid_container_name_invalid_uuid(self):
        """Container names with invalid UUIDs should return None."""
        assert extract_lab_id("lab-not-a-uuid-role") is None
        assert extract_lab_id("lab-123-role") is None
        assert extract_lab_id("lab-abc-role") is None

    def test_invalid_container_name_no_role(self):
        """Container names missing role should return None."""
        lab_id = uuid4()
        # Missing role suffix
        assert extract_lab_id(f"lab-{lab_id}") is None

    def test_container_name_pattern_regex(self):
        """Verify regex pattern matches expected format."""
        lab_id = uuid4()

        # Valid patterns
        assert CONTAINER_NAME_PATTERN.match(f"lab-{lab_id}-role") is not None
        assert CONTAINER_NAME_PATTERN.match(f"lab-{lab_id}-a") is not None

        # Invalid patterns
        assert CONTAINER_NAME_PATTERN.match("lab-invalid-uuid-role") is None
        assert CONTAINER_NAME_PATTERN.match("notlab-{lab_id}-role") is None


@pytest.mark.no_db
class TestRateLimiting:
    """Tests for rate limiting functionality."""

    def setup_method(self):
        """Clear rate limit cache before each test."""
        _rate_limit_cache.clear()

    def test_first_event_allowed(self):
        """First event for a lab should be allowed."""
        lab_id = str(uuid4())

        result = check_rate_limit(lab_id)

        assert result is True
        assert lab_id in _rate_limit_cache
        assert _rate_limit_cache[lab_id]["count"] == 1

    def test_within_limit_allowed(self):
        """Events within rate limit should be allowed."""
        lab_id = str(uuid4())

        # Send multiple events up to limit
        with patch("app.api.routes.internal.settings") as mock_settings:
            mock_settings.falco_rate_limit_per_lab = 10

            for i in range(10):
                result = check_rate_limit(lab_id)
                assert result is True, f"Event {i+1} should be allowed"

    def test_exceeds_limit_rejected(self):
        """Events exceeding rate limit should be rejected."""
        lab_id = str(uuid4())

        with patch("app.api.routes.internal.settings") as mock_settings:
            mock_settings.falco_rate_limit_per_lab = 5

            # Exhaust limit
            for _ in range(5):
                check_rate_limit(lab_id)

            # 6th event should be rejected
            result = check_rate_limit(lab_id)
            assert result is False

    def test_window_reset(self):
        """Rate limit window should reset after timeout."""
        lab_id = str(uuid4())

        with patch("app.api.routes.internal.settings") as mock_settings:
            mock_settings.falco_rate_limit_per_lab = 5

            # Exhaust limit
            for _ in range(5):
                check_rate_limit(lab_id)

            # Manually age the window
            _rate_limit_cache[lab_id]["window_start"] = time.time() - 61

            # Should be allowed again
            result = check_rate_limit(lab_id)
            assert result is True
            assert _rate_limit_cache[lab_id]["count"] == 1

    def test_separate_limits_per_lab(self):
        """Each lab should have independent rate limits."""
        lab_id_1 = str(uuid4())
        lab_id_2 = str(uuid4())

        with patch("app.api.routes.internal.settings") as mock_settings:
            mock_settings.falco_rate_limit_per_lab = 5

            # Exhaust limit for lab 1
            for _ in range(5):
                check_rate_limit(lab_id_1)

            # Lab 2 should still be allowed
            result = check_rate_limit(lab_id_2)
            assert result is True

            # Lab 1 should be blocked
            result = check_rate_limit(lab_id_1)
            assert result is False


@pytest.mark.no_db
class TestDeduplication:
    """Tests for event deduplication."""

    def setup_method(self):
        """Clear dedup cache before each test."""
        _dedup_cache.clear()

    def test_new_event_not_duplicate(self):
        """New events should not be flagged as duplicates."""
        event_hash = hashlib.sha256(b"unique-event").hexdigest()

        with patch("app.api.routes.internal.settings") as mock_settings:
            mock_settings.falco_dedup_ttl_seconds = 60

            result = check_dedup(event_hash)
            assert result is False  # Not a duplicate

    def test_repeated_event_is_duplicate(self):
        """Repeated events within TTL should be flagged as duplicates."""
        event_hash = hashlib.sha256(b"duplicate-event").hexdigest()

        with patch("app.api.routes.internal.settings") as mock_settings:
            mock_settings.falco_dedup_ttl_seconds = 60

            # First occurrence
            result1 = check_dedup(event_hash)
            assert result1 is False  # Not a duplicate

            # Second occurrence
            result2 = check_dedup(event_hash)
            assert result2 is True  # Is a duplicate

    def test_expired_entry_not_duplicate(self):
        """Events with expired TTL should not be flagged as duplicates."""
        event_hash = hashlib.sha256(b"expired-event").hexdigest()

        with patch("app.api.routes.internal.settings") as mock_settings:
            mock_settings.falco_dedup_ttl_seconds = 60

            # Add to cache with past expiry
            _dedup_cache[event_hash] = time.time() - 1

            # Should not be flagged (expired)
            result = check_dedup(event_hash)
            assert result is False

    def test_different_events_not_duplicates(self):
        """Different events should not be flagged as duplicates of each other."""
        hash1 = hashlib.sha256(b"event-1").hexdigest()
        hash2 = hashlib.sha256(b"event-2").hexdigest()

        with patch("app.api.routes.internal.settings") as mock_settings:
            mock_settings.falco_dedup_ttl_seconds = 60

            check_dedup(hash1)
            result = check_dedup(hash2)
            assert result is False  # Different event, not a duplicate


@pytest.mark.no_db
class TestEventHashComputation:
    """Tests for event hash computation."""

    def test_command_event_hash(self):
        """Command events should hash consistently."""
        lab_id = uuid4()
        event = FalcoEvent(
            type="command",
            timestamp="2025-12-05T10:00:00Z",
            container=f"lab-{lab_id}-octobox",
            cmdline="ls -la",
            cwd="/home/user",
        )

        hash1 = compute_event_hash(lab_id, event)
        hash2 = compute_event_hash(lab_id, event)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex

    def test_network_event_hash(self):
        """Network events should hash consistently."""
        lab_id = uuid4()
        event = FalcoEvent(
            type="network",
            timestamp="2025-12-05T10:00:00Z",
            container=f"lab-{lab_id}-octobox",
            dst_ip="192.168.1.100",
            dst_port=80,
            proto="tcp",
        )

        hash1 = compute_event_hash(lab_id, event)
        hash2 = compute_event_hash(lab_id, event)

        assert hash1 == hash2

    def test_file_read_event_hash(self):
        """File read events should hash consistently."""
        lab_id = uuid4()
        event = FalcoEvent(
            type="file_read",
            timestamp="2025-12-05T10:00:00Z",
            container=f"lab-{lab_id}-octobox",
            file="/etc/passwd",
        )

        hash1 = compute_event_hash(lab_id, event)
        hash2 = compute_event_hash(lab_id, event)

        assert hash1 == hash2

    def test_different_events_different_hash(self):
        """Different events should produce different hashes."""
        lab_id = uuid4()
        event1 = FalcoEvent(
            type="command",
            timestamp="2025-12-05T10:00:00Z",
            container=f"lab-{lab_id}-octobox",
            cmdline="ls -la",
            cwd="/home/user",
        )
        event2 = FalcoEvent(
            type="command",
            timestamp="2025-12-05T10:00:00Z",
            container=f"lab-{lab_id}-octobox",
            cmdline="pwd",  # Different command
            cwd="/home/user",
        )

        hash1 = compute_event_hash(lab_id, event1)
        hash2 = compute_event_hash(lab_id, event2)

        assert hash1 != hash2

    def test_different_labs_different_hash(self):
        """Same event for different labs should produce different hashes."""
        lab_id_1 = uuid4()
        lab_id_2 = uuid4()
        event = FalcoEvent(
            type="command",
            timestamp="2025-12-05T10:00:00Z",
            container="lab-placeholder-octobox",  # Will be ignored for hash
            cmdline="ls -la",
            cwd="/home/user",
        )

        hash1 = compute_event_hash(lab_id_1, event)
        hash2 = compute_event_hash(lab_id_2, event)

        assert hash1 != hash2


@pytest.mark.no_db
class TestFalcoEventModel:
    """Tests for FalcoEvent Pydantic model."""

    def test_command_event_valid(self):
        """Valid command event should parse correctly."""
        event = FalcoEvent(
            type="command",
            timestamp="2025-12-05T10:00:00Z",
            container="lab-12345678-1234-1234-1234-123456789012-octobox",
            user="pentester",
            uid=1000,
            cmdline="nmap -sV 192.168.1.1",
            cwd="/home/pentester",
            ppid=1,
            pname="bash",
        )

        assert event.type == "command"
        assert event.cmdline == "nmap -sV 192.168.1.1"

    def test_network_event_valid(self):
        """Valid network event should parse correctly."""
        event = FalcoEvent(
            type="network",
            timestamp="2025-12-05T10:00:00Z",
            container="lab-12345678-1234-1234-1234-123456789012-octobox",
            proto="tcp",
            src_ip="10.0.0.1",
            src_port=54321,
            dst_ip="192.168.1.100",
            dst_port=80,
        )

        assert event.type == "network"
        assert event.dst_ip == "192.168.1.100"
        assert event.dst_port == 80

    def test_file_read_event_valid(self):
        """Valid file_read event should parse correctly."""
        event = FalcoEvent(
            type="file_read",
            timestamp="2025-12-05T10:00:00Z",
            container="lab-12345678-1234-1234-1234-123456789012-octobox",
            user="root",
            file="/etc/shadow",
            cmdline="cat /etc/shadow",
        )

        assert event.type == "file_read"
        assert event.file == "/etc/shadow"

    def test_minimal_event(self):
        """Event with only required fields should be valid."""
        event = FalcoEvent(
            type="command",
            timestamp="2025-12-05T10:00:00Z",
            container="lab-12345678-1234-1234-1234-123456789012-octobox",
        )

        assert event.type == "command"
        assert event.user is None
        assert event.cmdline is None

    def test_event_model_dump(self):
        """Event should serialize correctly with model_dump."""
        event = FalcoEvent(
            type="command",
            timestamp="2025-12-05T10:00:00Z",
            container="lab-12345678-1234-1234-1234-123456789012-octobox",
            cmdline="ls",
        )

        dumped = event.model_dump(exclude_none=True)

        assert dumped["type"] == "command"
        assert dumped["cmdline"] == "ls"
        assert "user" not in dumped  # None values excluded
