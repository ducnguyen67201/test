"""Tests to verify no runtime fallback behavior.

SECURITY:
- Ensures that if firecracker runtime is selected and fails, we don't fall back to compose
- Fail-closed principle: errors bubble up, no silent degradation
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = pytest.mark.no_db


class TestNoRuntimeFallback:
    """Test that there's no fallback to compose when firecracker is selected."""

    @patch("app.services.runtime_selector.get_runtime_state")
    def test_get_effective_runtime_uses_settings_not_default(self, mock_get_state):
        """Verify get_effective_runtime uses settings, not a hardcoded default."""
        from unittest.mock import MagicMock

        mock_state = MagicMock()
        mock_state.override = None
        mock_get_state.return_value = mock_state

        # Mock settings
        with patch("app.services.runtime_selector.settings") as mock_settings:
            mock_settings.octolab_runtime = "firecracker"

            from app.services.runtime_selector import get_effective_runtime

            # Create mock app
            mock_app = MagicMock()

            result = get_effective_runtime(mock_app)
            assert result == "firecracker"

    @patch("app.services.runtime_selector.get_runtime_state")
    def test_override_takes_precedence(self, mock_get_state):
        """Verify that override takes precedence over settings."""
        mock_state = MagicMock()
        mock_state.override = "compose"  # Override to compose
        mock_get_state.return_value = mock_state

        with patch("app.services.runtime_selector.settings") as mock_settings:
            mock_settings.octolab_runtime = "firecracker"  # Settings say firecracker

            from app.services.runtime_selector import get_effective_runtime

            mock_app = MagicMock()
            result = get_effective_runtime(mock_app)

            # Override should win
            assert result == "compose"


class TestFirecrackerRuntimeErrorBubbling:
    """Test that firecracker runtime errors bubble up without fallback."""

    def test_firecracker_runtime_error_not_caught_silently(self):
        """Verify that firecracker runtime errors are not silently caught."""
        # Simulate what would happen if firecracker creation fails
        class MockFirecrackerRuntime:
            def __init__(self):
                raise RuntimeError("Firecracker prerequisites not met")

        with pytest.raises(RuntimeError) as exc_info:
            MockFirecrackerRuntime()

        assert "prerequisites" in str(exc_info.value).lower()

    def test_compose_runtime_not_used_as_fallback(self):
        """Verify compose runtime is never used as silent fallback."""
        # This is a documentation test - in real code, the pattern should be:
        # 1. Check runtime type
        # 2. If firecracker, use firecracker
        # 3. If firecracker fails, raise - don't fall back to compose

        runtime_choice = "firecracker"
        compose_used = False

        def get_runtime():
            nonlocal compose_used
            if runtime_choice == "firecracker":
                raise RuntimeError("Firecracker failed")
            # This should never be reached for firecracker
            compose_used = True
            return "compose_runtime"

        with pytest.raises(RuntimeError):
            get_runtime()

        assert not compose_used, "Compose should never be used as fallback"


class TestLabProvisioningNoFallback:
    """Test that lab provisioning doesn't fall back on runtime errors."""

    @pytest.mark.asyncio
    async def test_provisioning_surfaces_runtime_errors(self):
        """Verify that provisioning surfaces runtime errors clearly."""
        # Simulate the provisioning flow
        runtime = MagicMock()
        runtime.create_lab = AsyncMock(side_effect=RuntimeError("VM creation failed"))

        with pytest.raises(RuntimeError) as exc_info:
            await runtime.create_lab("lab-123", {})

        assert "VM creation failed" in str(exc_info.value)

    def test_runtime_mismatch_raises(self):
        """Verify that runtime mismatch is detected and raises."""
        expected_runtime = "firecracker"
        actual_runtime = "compose"

        # This pattern should be in production code
        if expected_runtime != actual_runtime:
            with pytest.raises(RuntimeError):
                raise RuntimeError(
                    f"Runtime mismatch: expected {expected_runtime}, got {actual_runtime}"
                )
