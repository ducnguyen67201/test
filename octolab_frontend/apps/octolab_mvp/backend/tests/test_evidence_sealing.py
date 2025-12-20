"""Tests for authoritative evidence sealing.

Verifies:
1. Canonical JSON serialization is deterministic
2. HMAC signing and verification work correctly
3. OctoBox cannot mount authoritative evidence volume (security invariant)
4. Evidence verification rejects tampered manifests
"""

import base64
import hashlib
import hmac
import json
import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4


# ============================================================================
# Unit tests for canonical JSON serialization
# ============================================================================

def test_canonical_json_sorted_keys():
    """Test that canonical JSON sorts keys for deterministic output."""
    from app.services.evidence_sealing import _canonical_json

    # Keys in reverse order
    obj = {"z": 1, "a": 2, "m": 3}
    result = _canonical_json(obj)
    decoded = result.decode("utf-8")

    # Keys should be sorted: a, m, z
    assert decoded == '{"a":2,"m":3,"z":1}'


def test_canonical_json_no_whitespace():
    """Test that canonical JSON has no extra whitespace."""
    from app.services.evidence_sealing import _canonical_json

    obj = {"key": "value", "nested": {"inner": 123}}
    result = _canonical_json(obj)
    decoded = result.decode("utf-8")

    # No spaces after colons or commas
    assert " " not in decoded
    assert '{"key":"value","nested":{"inner":123}}' == decoded


def test_canonical_json_deterministic():
    """Test that same input always produces same output."""
    from app.services.evidence_sealing import _canonical_json

    obj = {"lab_id": "test-123", "files": {"a.txt": "abc123", "b.log": "def456"}}

    # Run multiple times
    results = [_canonical_json(obj) for _ in range(5)]

    # All should be identical
    assert len(set(results)) == 1


def test_canonical_json_nested_sorting():
    """Test that nested dicts are also sorted."""
    from app.services.evidence_sealing import _canonical_json

    obj = {"outer": {"z_key": 1, "a_key": 2}, "files": {"z.txt": "hash1", "a.txt": "hash2"}}
    result = _canonical_json(obj)
    decoded = result.decode("utf-8")

    # Both outer and inner keys should be sorted
    assert '"files":{"a.txt":"hash2","z.txt":"hash1"}' in decoded
    assert '"outer":{"a_key":2,"z_key":1}' in decoded


# ============================================================================
# Unit tests for HMAC signing and verification
# ============================================================================

def test_hmac_compute_returns_base64():
    """Test that HMAC computation returns base64-encoded signature."""
    from app.services.evidence_sealing import _compute_hmac

    secret = b"test-secret"
    data = b"test data"
    result = _compute_hmac(secret, data)

    # Should be valid base64
    decoded = base64.b64decode(result)
    assert len(decoded) == 32  # SHA256 is 32 bytes


def test_hmac_verify_valid_signature():
    """Test that valid HMAC signature verifies correctly."""
    from app.services.evidence_sealing import _compute_hmac, _verify_hmac

    secret = b"test-secret"
    data = b"important data"

    signature = _compute_hmac(secret, data)
    assert _verify_hmac(secret, data, signature) is True


def test_hmac_verify_invalid_signature():
    """Test that tampered signature is rejected."""
    from app.services.evidence_sealing import _compute_hmac, _verify_hmac

    secret = b"test-secret"
    data = b"important data"

    signature = _compute_hmac(secret, data)

    # Tamper with signature
    tampered = signature[:-1] + ("A" if signature[-1] != "A" else "B")

    assert _verify_hmac(secret, data, tampered) is False


def test_hmac_verify_wrong_data():
    """Test that signature doesn't verify with different data."""
    from app.services.evidence_sealing import _compute_hmac, _verify_hmac

    secret = b"test-secret"
    original_data = b"original data"
    tampered_data = b"tampered data"

    signature = _compute_hmac(secret, original_data)
    assert _verify_hmac(secret, tampered_data, signature) is False


def test_hmac_verify_wrong_secret():
    """Test that signature doesn't verify with different secret."""
    from app.services.evidence_sealing import _compute_hmac, _verify_hmac

    secret1 = b"secret-one"
    secret2 = b"secret-two"
    data = b"some data"

    signature = _compute_hmac(secret1, data)
    assert _verify_hmac(secret2, data, signature) is False


def test_hmac_verify_malformed_signature():
    """Test that malformed signatures are handled gracefully."""
    from app.services.evidence_sealing import _verify_hmac

    secret = b"test-secret"
    data = b"data"

    # Not valid base64
    assert _verify_hmac(secret, data, "not-base64!!!") is False

    # Empty signature
    assert _verify_hmac(secret, data, "") is False


# ============================================================================
# Tests for volume naming
# ============================================================================

def test_volume_names_deterministic():
    """Test that volume names are deterministic from lab ID."""
    from app.services.evidence_sealing import get_evidence_volume_names

    lab = MagicMock()
    lab.id = uuid4()

    auth1, user1 = get_evidence_volume_names(lab)
    auth2, user2 = get_evidence_volume_names(lab)

    assert auth1 == auth2
    assert user1 == user2


def test_volume_names_unique_per_lab():
    """Test that different labs get different volume names."""
    from app.services.evidence_sealing import get_evidence_volume_names

    lab1 = MagicMock()
    lab1.id = uuid4()

    lab2 = MagicMock()
    lab2.id = uuid4()

    auth1, user1 = get_evidence_volume_names(lab1)
    auth2, user2 = get_evidence_volume_names(lab2)

    assert auth1 != auth2
    assert user1 != user2


def test_volume_names_format():
    """Test that volume names follow expected format."""
    from app.services.evidence_sealing import get_evidence_volume_names

    lab = MagicMock()
    lab.id = uuid4()

    auth_vol, user_vol = get_evidence_volume_names(lab)

    # Format: octolab_<lab_id>_evidence_auth
    assert auth_vol == f"octolab_{lab.id}_evidence_auth"
    assert user_vol == f"octolab_{lab.id}_evidence_user"


# ============================================================================
# Security invariant tests: OctoBox cannot mount auth volume
# ============================================================================

def test_octobox_service_does_not_mount_evidence_auth_volume():
    """CRITICAL SECURITY TEST: OctoBox must NOT mount evidence_auth volume.

    This is the core security invariant of authoritative evidence.
    If OctoBox can write to auth volume, evidence is not authoritative.
    """
    compose_path = Path(__file__).parent.parent.parent / "octolab-hackvm" / "docker-compose.yml"

    if not compose_path.exists():
        pytest.skip(f"docker-compose.yml not found at {compose_path}")

    with open(compose_path) as f:
        compose_yaml = yaml.safe_load(f)

    octobox_service = compose_yaml.get("services", {}).get("octobox", {})
    octobox_volumes = octobox_service.get("volumes", [])

    # Convert to strings for checking
    volume_strs = [str(v) for v in octobox_volumes]

    # OctoBox must NOT have access to evidence_auth
    for vol in volume_strs:
        assert "evidence_auth" not in vol, (
            f"SECURITY VIOLATION: OctoBox service mounts evidence_auth volume: {vol}\n"
            f"This breaks the authoritative evidence security invariant.\n"
            f"OctoBox must only mount evidence_user volume."
        )


def test_octobox_mounts_evidence_user_volume():
    """Test that OctoBox correctly mounts the user evidence volume."""
    compose_path = Path(__file__).parent.parent.parent / "octolab-hackvm" / "docker-compose.yml"

    if not compose_path.exists():
        pytest.skip(f"docker-compose.yml not found at {compose_path}")

    with open(compose_path) as f:
        compose_yaml = yaml.safe_load(f)

    octobox_service = compose_yaml.get("services", {}).get("octobox", {})
    octobox_volumes = octobox_service.get("volumes", [])

    # Convert to strings
    volume_strs = [str(v) for v in octobox_volumes]

    # OctoBox SHOULD have evidence_user volume
    has_user_evidence = any("evidence_user" in v for v in volume_strs)
    assert has_user_evidence, (
        "OctoBox service should mount evidence_user volume for tlog/commands.log"
    )


def test_gateway_mounts_evidence_auth_volume():
    """Test that lab-gateway correctly mounts the auth evidence volume."""
    compose_path = Path(__file__).parent.parent.parent / "octolab-hackvm" / "docker-compose.yml"

    if not compose_path.exists():
        pytest.skip(f"docker-compose.yml not found at {compose_path}")

    with open(compose_path) as f:
        compose_yaml = yaml.safe_load(f)

    gateway_service = compose_yaml.get("services", {}).get("lab-gateway", {})
    gateway_volumes = gateway_service.get("volumes", [])

    # Convert to strings
    volume_strs = [str(v) for v in gateway_volumes]

    # Gateway SHOULD have evidence_auth volume
    has_auth_evidence = any("evidence_auth" in v for v in volume_strs)
    assert has_auth_evidence, (
        "lab-gateway service should mount evidence_auth volume for network captures"
    )


def test_gateway_does_not_mount_evidence_user_volume():
    """Test that lab-gateway does NOT mount user evidence volume.

    Gateway should only write to auth volume, not user volume.
    This ensures gateway evidence cannot be mixed with user-controlled data.
    """
    compose_path = Path(__file__).parent.parent.parent / "octolab-hackvm" / "docker-compose.yml"

    if not compose_path.exists():
        pytest.skip(f"docker-compose.yml not found at {compose_path}")

    with open(compose_path) as f:
        compose_yaml = yaml.safe_load(f)

    gateway_service = compose_yaml.get("services", {}).get("lab-gateway", {})
    gateway_volumes = gateway_service.get("volumes", [])

    # Convert to strings
    volume_strs = [str(v) for v in gateway_volumes]

    # Gateway should NOT mount evidence_user
    for vol in volume_strs:
        assert "evidence_user" not in vol, (
            f"lab-gateway should not mount evidence_user volume: {vol}"
        )


def test_evidence_volumes_declared():
    """Test that both evidence volumes are declared in compose."""
    compose_path = Path(__file__).parent.parent.parent / "octolab-hackvm" / "docker-compose.yml"

    if not compose_path.exists():
        pytest.skip(f"docker-compose.yml not found at {compose_path}")

    with open(compose_path) as f:
        compose_yaml = yaml.safe_load(f)

    volumes = compose_yaml.get("volumes", {})

    assert "evidence_auth" in volumes, "evidence_auth volume should be declared"
    assert "evidence_user" in volumes, "evidence_user volume should be declared"


def test_evidence_volumes_no_explicit_names():
    """Test that evidence volumes don't have explicit names (would cause collisions)."""
    compose_path = Path(__file__).parent.parent.parent / "octolab-hackvm" / "docker-compose.yml"

    if not compose_path.exists():
        pytest.skip(f"docker-compose.yml not found at {compose_path}")

    with open(compose_path) as f:
        compose_yaml = yaml.safe_load(f)

    volumes = compose_yaml.get("volumes", {})

    for vol_name in ["evidence_auth", "evidence_user"]:
        vol_config = volumes.get(vol_name)

        if vol_config is None:
            # Empty config is fine (project-scoped)
            continue

        if isinstance(vol_config, dict):
            assert "name" not in vol_config, (
                f"Volume '{vol_name}' has explicit name: {vol_config.get('name')}\n"
                f"This causes cross-lab collisions (security issue)."
            )
            assert not vol_config.get("external"), (
                f"Volume '{vol_name}' is external - would be shared across labs"
            )


# ============================================================================
# Integration-style tests for seal verification
# ============================================================================

def test_manifest_verification_roundtrip():
    """Test that we can create and verify a manifest in memory."""
    from app.services.evidence_sealing import _canonical_json, _compute_hmac, _verify_hmac

    secret = b"test-hmac-secret"

    # Create manifest
    manifest = {
        "lab_id": str(uuid4()),
        "sealed_at": "2024-01-01T00:00:00Z",
        "evidence_version": "4.0",
        "seal_version": 1,
        "files": {
            "auth/network/network.json": "abcd1234" * 8,
            "auth/logs/compose.log": "efgh5678" * 8,
        }
    }

    # Seal it
    canonical = _canonical_json(manifest)
    signature = _compute_hmac(secret, canonical)

    # Verify it
    assert _verify_hmac(secret, canonical, signature) is True

    # Modify manifest and verify it fails
    manifest["files"]["auth/network/network.json"] = "tampered!"
    tampered_canonical = _canonical_json(manifest)
    assert _verify_hmac(secret, tampered_canonical, signature) is False


def test_file_hash_computation():
    """Test SHA256 hash computation for files."""
    import tempfile
    from app.services.evidence_sealing import _compute_file_hash

    # Create temp file with known content
    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(b"Hello, World!")
        temp_path = Path(f.name)

    try:
        result = _compute_file_hash(temp_path)

        # Known SHA256 of "Hello, World!"
        expected = hashlib.sha256(b"Hello, World!").hexdigest()
        assert result == expected
    finally:
        temp_path.unlink()


def test_file_hash_deterministic():
    """Test that file hashing is deterministic."""
    import tempfile
    from app.services.evidence_sealing import _compute_file_hash

    content = b"Test content for hashing\n" * 100

    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(content)
        temp_path = Path(f.name)

    try:
        # Hash multiple times
        hashes = [_compute_file_hash(temp_path) for _ in range(3)]
        assert len(set(hashes)) == 1, "File hash should be deterministic"
    finally:
        temp_path.unlink()


# ============================================================================
# Model field tests
# ============================================================================

def test_evidence_seal_status_enum_values():
    """Test that EvidenceSealStatus enum has expected values."""
    from app.models.lab import EvidenceSealStatus

    assert EvidenceSealStatus.NONE.value == "none"
    assert EvidenceSealStatus.SEALED.value == "sealed"
    assert EvidenceSealStatus.FAILED.value == "failed"


def test_lab_model_has_evidence_fields():
    """Test that Lab model has evidence seal fields."""
    from app.models.lab import Lab

    # Check column names exist
    columns = [c.name for c in Lab.__table__.columns]

    assert "evidence_auth_volume" in columns
    assert "evidence_user_volume" in columns
    assert "evidence_seal_status" in columns
    assert "evidence_sealed_at" in columns
    assert "evidence_manifest_sha256" in columns
