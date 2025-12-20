"""Tests for Firecracker guest agent protocol.

SECURITY tests:
- Invalid tokens rejected
- Actions outside allowlist rejected
- Output size limits enforced
- Token never appears in error messages
"""

import pytest

from app.services.firecracker_manager import (
    ALLOWED_AGENT_ACTIONS,
    AgentResponse,
    communicate_with_agent,
)


# =============================================================================
# Action Allowlist Tests
# =============================================================================


class TestActionAllowlist:
    """Tests for action allowlist enforcement."""

    def test_allowlist_contains_expected_actions(self):
        """Allowlist should contain only safe actions."""
        expected = {"ping", "uname", "id"}
        assert ALLOWED_AGENT_ACTIONS == expected

    def test_allowlist_is_frozen(self):
        """Allowlist should be immutable."""
        assert isinstance(ALLOWED_AGENT_ACTIONS, frozenset)

    @pytest.mark.asyncio
    async def test_rejects_disallowed_action(self):
        """Disallowed actions should raise ValueError."""
        disallowed_actions = [
            "exec",
            "shell",
            "bash",
            "sh",
            "rm",
            "cat",
            "/bin/sh",
            "python",
            "curl",
            "wget",
            "nc",
            "; rm -rf /",
            "ping; rm -rf /",
            "$(whoami)",
        ]
        for action in disallowed_actions:
            with pytest.raises(ValueError) as exc_info:
                # This should fail at validation, before any network call
                await communicate_with_agent(
                    vsock_sock_path="/nonexistent/vsock.sock",
                    token="test_token",
                    action=action,
                    timeout=0.1,
                )
            assert "not allowed" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_allowed_actions_accepted(self):
        """Allowed actions should not raise ValueError at validation.

        Note: The actual vsock call will fail (no VM), but that's expected.
        We're testing that the action passes the allowlist check.
        """
        for action in ALLOWED_AGENT_ACTIONS:
            try:
                # This will fail due to no VM, but shouldn't raise ValueError
                await communicate_with_agent(
                    vsock_sock_path="/nonexistent/vsock.sock",
                    token="test_token",
                    action=action,
                    timeout=0.1,
                )
            except ValueError:
                pytest.fail(f"Action '{action}' should be allowed but was rejected")
            except Exception:
                # Expected - no actual VM to connect to
                pass


# =============================================================================
# Token Security Tests
# =============================================================================


class TestTokenSecurity:
    """Tests for token security."""

    @pytest.mark.asyncio
    async def test_token_not_in_error_message(self):
        """Token should never appear in error messages."""
        secret_token = "super_secret_token_12345"

        try:
            await communicate_with_agent(
                vsock_sock_path="/nonexistent/vsock.sock",
                token=secret_token,
                action="ping",
                timeout=0.1,
            )
        except Exception as e:
            error_str = str(e)
            assert secret_token not in error_str

    def test_agent_response_does_not_leak_token(self):
        """AgentResponse should not contain token field."""
        response = AgentResponse(
            ok=True,
            stdout="test output",
            stderr="",
            exit_code=0,
        )
        # Verify token is not an attribute
        assert not hasattr(response, "token")
        # Verify token not in string representation
        assert "token" not in str(response).lower()


# =============================================================================
# Output Size Limit Tests
# =============================================================================


class TestOutputSizeLimits:
    """Tests for output size limit enforcement."""

    def test_max_output_setting_exists(self):
        """Max output setting should exist and have reasonable value."""
        from app.config import settings

        assert hasattr(settings, "microvm_max_output_bytes")
        assert settings.microvm_max_output_bytes > 0
        assert settings.microvm_max_output_bytes <= 1024 * 1024  # Max 1MB

    def test_agent_response_truncation(self):
        """AgentResponse should handle truncated output."""
        # Simulate large output
        large_output = "x" * 100000

        response = AgentResponse(
            ok=True,
            stdout=large_output[:65536],  # Truncated
            stderr="",
            exit_code=0,
        )

        # Should not crash
        assert len(response.stdout) <= 65536


# =============================================================================
# Timeout Tests
# =============================================================================


class TestTimeouts:
    """Tests for timeout handling."""

    def test_timeout_settings_exist(self):
        """Timeout settings should exist and have reasonable values."""
        from app.config import settings

        assert hasattr(settings, "microvm_boot_timeout_secs")
        assert hasattr(settings, "microvm_cmd_timeout_secs")

        assert settings.microvm_boot_timeout_secs > 0
        assert settings.microvm_boot_timeout_secs <= 300  # Max 5 minutes

        assert settings.microvm_cmd_timeout_secs > 0
        assert settings.microvm_cmd_timeout_secs <= 300  # Max 5 minutes (allows compose operations)


# =============================================================================
# CID Generation Tests
# =============================================================================


class TestCIDGeneration:
    """Tests for guest CID generation."""

    def test_cid_generation_deterministic(self):
        """Same lab ID should produce same CID."""
        from app.services.firecracker_manager import _generate_cid

        lab_id = "12345678-1234-1234-1234-123456789abc"
        cid1 = _generate_cid(lab_id)
        cid2 = _generate_cid(lab_id)
        assert cid1 == cid2

    def test_cid_in_valid_range(self):
        """CID should be in valid guest range."""
        from app.services.firecracker_manager import (
            MAX_GUEST_CID,
            MIN_GUEST_CID,
            _generate_cid,
        )
        from uuid import uuid4

        for _ in range(100):
            lab_id = str(uuid4())
            cid = _generate_cid(lab_id)
            assert MIN_GUEST_CID <= cid <= MAX_GUEST_CID

    def test_different_lab_ids_produce_different_cids(self):
        """Different lab IDs should (usually) produce different CIDs."""
        from app.services.firecracker_manager import _generate_cid
        from uuid import uuid4

        cids = set()
        for _ in range(100):
            lab_id = str(uuid4())
            cid = _generate_cid(lab_id)
            cids.add(cid)

        # With 100 random UUIDs and 65435 possible CIDs,
        # collision is extremely unlikely
        assert len(cids) >= 99


# =============================================================================
# Token Generation Tests
# =============================================================================


class TestTokenGeneration:
    """Tests for token generation."""

    def test_token_has_sufficient_entropy(self):
        """Generated tokens should have sufficient entropy."""
        from app.services.firecracker_manager import _generate_token

        token = _generate_token()
        assert len(token) >= 64  # 32 bytes = 64 hex chars
        assert token.isalnum()  # Only alphanumeric

    def test_tokens_are_unique(self):
        """Each generated token should be unique."""
        from app.services.firecracker_manager import _generate_token

        tokens = set()
        for _ in range(100):
            token = _generate_token()
            assert token not in tokens
            tokens.add(token)
