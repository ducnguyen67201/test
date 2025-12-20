"""Tests for evidence state reconciliation on GET /labs/{id}.

SECURITY tests included:
- Reconciliation only runs for terminal labs (finished/failed)
- Reconciliation only runs once (idempotent via evidence_finalized_at)
- Authorization unchanged (cannot trigger reconcile on other user's lab)
- No file paths exposed to non-admin users
- Fail-safe: reconciliation errors don't crash GET endpoint
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lab import Lab, LabStatus, EvidenceState
from app.services.lab_service import (
    reconcile_evidence_state_if_needed,
    TERMINAL_STATUSES,
    _enumish_to_str,
)


# =============================================================================
# reconcile_evidence_state_if_needed unit tests
# =============================================================================


class TestReconcileEvidenceStateIfNeeded:
    """Unit tests for reconcile_evidence_state_if_needed function."""

    @pytest.mark.asyncio
    async def test_skips_non_terminal_lab(self):
        """Should skip reconciliation for non-terminal labs."""
        lab = MagicMock(spec=Lab)
        lab.id = uuid4()
        lab.status = LabStatus.READY  # Not terminal
        lab.evidence_state = EvidenceState.COLLECTING.value
        lab.evidence_finalized_at = None

        session = AsyncMock(spec=AsyncSession)

        with patch("app.services.lab_service.finalize_evidence_state") as mock_finalize:
            result = await reconcile_evidence_state_if_needed(lab, session)

        assert result is False
        mock_finalize.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_provisioning_lab(self):
        """Should skip reconciliation for provisioning labs."""
        lab = MagicMock(spec=Lab)
        lab.id = uuid4()
        lab.status = LabStatus.PROVISIONING
        lab.evidence_state = EvidenceState.COLLECTING.value
        lab.evidence_finalized_at = None

        session = AsyncMock(spec=AsyncSession)

        with patch("app.services.lab_service.finalize_evidence_state") as mock_finalize:
            result = await reconcile_evidence_state_if_needed(lab, session)

        assert result is False
        mock_finalize.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_already_finalized_lab(self):
        """Should skip reconciliation when evidence_finalized_at is set."""
        lab = MagicMock(spec=Lab)
        lab.id = uuid4()
        lab.status = LabStatus.FINISHED
        lab.evidence_state = EvidenceState.COLLECTING.value
        lab.evidence_finalized_at = datetime.now(timezone.utc)  # Already finalized

        session = AsyncMock(spec=AsyncSession)

        with patch("app.services.lab_service.finalize_evidence_state") as mock_finalize:
            result = await reconcile_evidence_state_if_needed(lab, session)

        assert result is False
        mock_finalize.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_already_computed_state(self):
        """Should skip reconciliation when evidence_state is not 'collecting'."""
        lab = MagicMock(spec=Lab)
        lab.id = uuid4()
        lab.status = LabStatus.FINISHED
        lab.evidence_state = EvidenceState.READY.value  # Already computed
        lab.evidence_finalized_at = None

        session = AsyncMock(spec=AsyncSession)

        with patch("app.services.lab_service.finalize_evidence_state") as mock_finalize:
            result = await reconcile_evidence_state_if_needed(lab, session)

        assert result is False
        mock_finalize.assert_not_called()

    @pytest.mark.asyncio
    async def test_reconciles_terminal_collecting_lab(self):
        """Should reconcile a terminal lab stuck in 'collecting' state."""
        lab = MagicMock(spec=Lab)
        lab.id = uuid4()
        lab.status = LabStatus.FINISHED
        lab.evidence_state = EvidenceState.COLLECTING.value
        lab.evidence_finalized_at = None

        session = AsyncMock(spec=AsyncSession)

        with patch("app.services.lab_service.finalize_evidence_state") as mock_finalize:
            mock_finalize.return_value = EvidenceState.READY.value
            result = await reconcile_evidence_state_if_needed(lab, session)

        assert result is True
        # Now uses commit=False to avoid MissingGreenlet
        mock_finalize.assert_called_once_with(lab, session, commit=False)

    @pytest.mark.asyncio
    async def test_reconciles_failed_lab(self):
        """Should reconcile a failed lab stuck in 'collecting' state."""
        lab = MagicMock(spec=Lab)
        lab.id = uuid4()
        lab.status = LabStatus.FAILED
        lab.evidence_state = EvidenceState.COLLECTING.value
        lab.evidence_finalized_at = None

        session = AsyncMock(spec=AsyncSession)

        with patch("app.services.lab_service.finalize_evidence_state") as mock_finalize:
            mock_finalize.return_value = EvidenceState.PARTIAL.value
            result = await reconcile_evidence_state_if_needed(lab, session)

        assert result is True
        # Now uses commit=False to avoid MissingGreenlet
        mock_finalize.assert_called_once_with(lab, session, commit=False)

    @pytest.mark.asyncio
    async def test_handles_finalize_error(self):
        """Should set unavailable state on finalize error."""
        lab = MagicMock(spec=Lab)
        lab.id = uuid4()
        lab.status = LabStatus.FINISHED
        lab.evidence_state = EvidenceState.COLLECTING.value
        lab.evidence_finalized_at = None

        session = AsyncMock(spec=AsyncSession)

        with patch("app.services.lab_service.finalize_evidence_state") as mock_finalize:
            mock_finalize.side_effect = IOError("Volume not found")
            result = await reconcile_evidence_state_if_needed(lab, session)

        assert result is True
        assert lab.evidence_state == EvidenceState.UNAVAILABLE.value
        assert lab.evidence_finalized_at is not None
        # Now uses flush instead of commit to avoid MissingGreenlet
        session.flush.assert_called_once()


class TestReconcileTerminalStatuses:
    """Test that TERMINAL_STATUSES is correctly defined (as lowercase strings)."""

    def test_terminal_statuses_includes_finished(self):
        """TERMINAL_STATUSES should include 'finished'."""
        assert "finished" in TERMINAL_STATUSES

    def test_terminal_statuses_includes_failed(self):
        """TERMINAL_STATUSES should include 'failed'."""
        assert "failed" in TERMINAL_STATUSES

    def test_terminal_statuses_excludes_active(self):
        """TERMINAL_STATUSES should exclude active states."""
        assert "provisioning" not in TERMINAL_STATUSES
        assert "ready" not in TERMINAL_STATUSES
        assert "ending" not in TERMINAL_STATUSES

    def test_terminal_statuses_are_lowercase_strings(self):
        """TERMINAL_STATUSES should be a set of lowercase strings."""
        for status in TERMINAL_STATUSES:
            assert isinstance(status, str)
            assert status == status.lower()


# =============================================================================
# _enumish_to_str helper tests
# =============================================================================


class TestEnumishToStr:
    """Tests for _enumish_to_str helper function."""

    def test_converts_string_to_lowercase(self):
        """Should convert plain strings to lowercase."""
        assert _enumish_to_str("FINISHED") == "finished"
        assert _enumish_to_str("Ready") == "ready"
        assert _enumish_to_str("collecting") == "collecting"

    def test_converts_enum_with_value(self):
        """Should extract .value from enum-like objects."""
        assert _enumish_to_str(LabStatus.FINISHED) == "finished"
        assert _enumish_to_str(LabStatus.FAILED) == "failed"
        assert _enumish_to_str(EvidenceState.COLLECTING) == "collecting"

    def test_handles_none_gracefully(self):
        """Should convert None to 'none' string without crashing."""
        result = _enumish_to_str(None)
        assert result == "none"

    def test_handles_weird_objects(self):
        """Should not crash on unusual objects."""
        # Object with weird .value
        class WeirdObj:
            value = 123  # Not a string

        result = _enumish_to_str(WeirdObj())
        # Should convert to string somehow without crashing
        assert isinstance(result, str)


# =============================================================================
# String vs Enum status handling tests
# =============================================================================


class TestReconcileStatusTypes:
    """Tests for handling both string and enum status values."""

    @pytest.mark.asyncio
    async def test_string_status_does_not_crash(self):
        """String status 'finished' should work without AttributeError."""
        lab = MagicMock(spec=Lab)
        lab.id = uuid4()
        lab.status = "finished"  # Plain string, not Enum
        lab.evidence_state = "collecting"  # Plain string
        lab.evidence_finalized_at = None

        session = AsyncMock(spec=AsyncSession)

        with patch("app.services.lab_service.finalize_evidence_state") as mock_finalize:
            mock_finalize.return_value = "ready"
            # This should NOT raise AttributeError: 'str' object has no attribute 'value'
            result = await reconcile_evidence_state_if_needed(lab, session)

        assert result is True
        mock_finalize.assert_called_once()

    @pytest.mark.asyncio
    async def test_enum_status_still_works(self):
        """Enum status LabStatus.FINISHED should also work."""
        lab = MagicMock(spec=Lab)
        lab.id = uuid4()
        lab.status = LabStatus.FINISHED  # Enum
        lab.evidence_state = EvidenceState.COLLECTING  # Enum (not .value)
        lab.evidence_finalized_at = None

        session = AsyncMock(spec=AsyncSession)

        with patch("app.services.lab_service.finalize_evidence_state") as mock_finalize:
            mock_finalize.return_value = EvidenceState.READY.value
            result = await reconcile_evidence_state_if_needed(lab, session)

        assert result is True
        mock_finalize.assert_called_once()

    @pytest.mark.asyncio
    async def test_mixed_string_enum_works(self):
        """Should handle mix of string status and enum evidence_state."""
        lab = MagicMock(spec=Lab)
        lab.id = uuid4()
        lab.status = "failed"  # String
        lab.evidence_state = EvidenceState.COLLECTING  # Enum
        lab.evidence_finalized_at = None

        session = AsyncMock(spec=AsyncSession)

        with patch("app.services.lab_service.finalize_evidence_state") as mock_finalize:
            result = await reconcile_evidence_state_if_needed(lab, session)

        assert result is True


# =============================================================================
# Fail-safe behavior tests
# =============================================================================


class TestReconcileFailSafe:
    """Tests for fail-safe behavior (never crash GET endpoint)."""

    @pytest.mark.asyncio
    async def test_outer_exception_swallowed(self):
        """Exceptions in reconcile logic should be swallowed, returning False."""
        lab = MagicMock(spec=Lab)
        lab.id = uuid4()
        # Simulate an object that raises on attribute access
        lab.status = property(lambda self: 1/0)  # Would raise ZeroDivisionError

        # Actually, let's make status raise when accessed
        class BadLab:
            id = uuid4()
            evidence_finalized_at = None

            @property
            def status(self):
                raise RuntimeError("Simulated DB error")

            @property
            def evidence_state(self):
                return "collecting"

        bad_lab = BadLab()
        session = AsyncMock(spec=AsyncSession)

        # Should NOT raise, should return False
        result = await reconcile_evidence_state_if_needed(bad_lab, session)
        assert result is False

    @pytest.mark.asyncio
    async def test_finalize_exception_sets_unavailable(self):
        """finalize_evidence_state exceptions should set state to unavailable."""
        lab = MagicMock(spec=Lab)
        lab.id = uuid4()
        lab.status = "finished"
        lab.evidence_state = "collecting"
        lab.evidence_finalized_at = None

        session = AsyncMock(spec=AsyncSession)

        with patch("app.services.lab_service.finalize_evidence_state") as mock_finalize:
            mock_finalize.side_effect = RuntimeError("Volume extraction failed")
            result = await reconcile_evidence_state_if_needed(lab, session)

        # Should return True (state was updated to unavailable)
        assert result is True
        assert lab.evidence_state == EvidenceState.UNAVAILABLE.value
        assert lab.evidence_finalized_at is not None
        # Now uses flush instead of commit to avoid MissingGreenlet
        session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_none_evidence_state_handled(self):
        """Should handle None evidence_state without crashing."""
        lab = MagicMock(spec=Lab)
        lab.id = uuid4()
        lab.status = "finished"
        lab.evidence_state = None  # Not set
        lab.evidence_finalized_at = None

        session = AsyncMock(spec=AsyncSession)

        with patch("app.services.lab_service.finalize_evidence_state") as mock_finalize:
            # Should not crash, should skip (None != "collecting")
            result = await reconcile_evidence_state_if_needed(lab, session)

        assert result is False
        mock_finalize.assert_not_called()


# =============================================================================
# Integration tests (endpoint behavior)
# =============================================================================


class TestReconcileOnGetEndpoint:
    """Tests for reconciliation behavior in GET /labs/{id} endpoint."""

    @pytest.mark.skip(reason="Requires HTTP client fixtures (integration test)")
    @pytest.mark.asyncio
    async def test_get_lab_triggers_reconcile_for_terminal_collecting(self):
        """GET /labs/{id} should trigger reconcile for terminal lab in collecting state."""
        # Would test:
        # 1. Create lab with status=finished, evidence_state=collecting, finalized_at=None
        # 2. Call GET /labs/{id}
        # 3. Assert response evidence_state != 'collecting'
        # 4. Assert DB evidence_finalized_at is set
        pass

    @pytest.mark.skip(reason="Requires HTTP client fixtures (integration test)")
    @pytest.mark.asyncio
    async def test_get_lab_does_not_reconcile_for_running_lab(self):
        """GET /labs/{id} should NOT trigger reconcile for running labs."""
        # Would test:
        # 1. Create lab with status=ready, evidence_state=collecting
        # 2. Call GET /labs/{id}
        # 3. Assert evidence_state still 'collecting' (not modified)
        pass

    @pytest.mark.skip(reason="Requires HTTP client fixtures (integration test)")
    @pytest.mark.asyncio
    async def test_reconcile_is_idempotent(self):
        """Reconcile should only run once (idempotent via finalized_at)."""
        # Would test:
        # 1. Create lab with status=finished, evidence_state=collecting
        # 2. Call GET /labs/{id} twice
        # 3. Assert finalize_evidence_state called only once
        pass

    @pytest.mark.skip(reason="Requires HTTP client fixtures (integration test)")
    @pytest.mark.asyncio
    async def test_auth_scoping_unchanged(self):
        """User cannot trigger reconcile on another user's lab."""
        # Would test:
        # 1. Create lab owned by user A
        # 2. Authenticate as user B
        # 3. Call GET /labs/{lab_id}
        # 4. Assert 404 (not 200 with reconcile)
        pass


# =============================================================================
# Security tests
# =============================================================================


class TestReconcileSecurity:
    """Security tests for reconciliation."""

    @pytest.mark.asyncio
    async def test_no_file_paths_in_response(self):
        """Reconciliation should not expose file paths to non-admin users."""
        # The reconcile function updates lab.evidence_state but the API
        # response (LabResponse) does not include file lists or paths.
        # This is verified by the schema definition.
        from app.schemas.lab import LabResponse

        # Check that LabResponse doesn't have file path fields
        fields = LabResponse.model_fields
        assert 'file_paths' not in fields
        assert 'file_list' not in fields
        assert 'found_rel' not in fields
        assert 'missing_rel' not in fields

    @pytest.mark.asyncio
    async def test_only_terminal_labs_trigger_disk_check(self):
        """Only terminal labs should trigger filesystem access."""
        # Verify that non-terminal labs never call finalize_evidence_state
        for status in [LabStatus.PROVISIONING, LabStatus.READY, LabStatus.ENDING]:
            lab = MagicMock(spec=Lab)
            lab.id = uuid4()
            lab.status = status
            lab.evidence_state = EvidenceState.COLLECTING.value
            lab.evidence_finalized_at = None

            session = AsyncMock(spec=AsyncSession)

            with patch("app.services.lab_service.finalize_evidence_state") as mock_finalize:
                result = await reconcile_evidence_state_if_needed(lab, session)

            assert result is False, f"Non-terminal status {status} should not trigger reconcile"
            mock_finalize.assert_not_called()
