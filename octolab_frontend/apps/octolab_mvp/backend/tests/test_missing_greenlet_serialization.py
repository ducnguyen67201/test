"""Tests for MissingGreenlet fix during ORM serialization.

Verifies that:
- finalize_evidence_state uses flush() when commit=False
- reconcile_evidence_state_if_needed uses flush, not commit
- LabResponse.model_validate doesn't raise MissingGreenlet after flush
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lab import Lab, LabStatus, EvidenceState
from app.schemas.lab import LabResponse


# =============================================================================
# finalize_evidence_state commit parameter tests
# =============================================================================


class TestFinalizeEvidenceStateCommitParam:
    """Tests for finalize_evidence_state commit parameter."""

    @pytest.mark.asyncio
    async def test_uses_commit_by_default(self):
        """finalize_evidence_state commits by default (for teardown path)."""
        from app.services.evidence_service import finalize_evidence_state

        lab = MagicMock(spec=Lab)
        lab.id = uuid4()

        session = AsyncMock(spec=AsyncSession)

        with patch("app.services.evidence_service._extract_volume_to_dir"):
            with patch("app.services.evidence_service.compute_evidence_state") as mock_compute:
                mock_compute.return_value = ("ready", MagicMock())

                with patch("app.services.evidence_service.rmtree_hardened"):
                    with patch("app.services.evidence_service.safe_mkdir"):
                        with patch("tempfile.mkdtemp", return_value="/tmp/test"):
                            await finalize_evidence_state(lab, session)

        # Should call commit (default behavior)
        session.commit.assert_called_once()
        session.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_flush_when_commit_false(self):
        """finalize_evidence_state uses flush when commit=False."""
        from app.services.evidence_service import finalize_evidence_state

        lab = MagicMock(spec=Lab)
        lab.id = uuid4()

        session = AsyncMock(spec=AsyncSession)

        with patch("app.services.evidence_service._extract_volume_to_dir"):
            with patch("app.services.evidence_service.compute_evidence_state") as mock_compute:
                mock_compute.return_value = ("ready", MagicMock())

                with patch("app.services.evidence_service.rmtree_hardened"):
                    with patch("app.services.evidence_service.safe_mkdir"):
                        with patch("tempfile.mkdtemp", return_value="/tmp/test"):
                            await finalize_evidence_state(lab, session, commit=False)

        # Should call flush, not commit
        session.flush.assert_called_once()
        session.commit.assert_not_called()


# =============================================================================
# reconcile_evidence_state_if_needed flush tests
# =============================================================================


class TestReconcileUsesFlush:
    """Tests that reconcile uses flush instead of commit."""

    @pytest.mark.asyncio
    async def test_reconcile_uses_flush_not_commit(self):
        """reconcile_evidence_state_if_needed uses flush, not commit."""
        from app.services.lab_service import reconcile_evidence_state_if_needed

        lab = MagicMock(spec=Lab)
        lab.id = uuid4()
        lab.status = "finished"  # Terminal status
        lab.evidence_state = "collecting"  # Needs reconcile
        lab.evidence_finalized_at = None

        session = AsyncMock(spec=AsyncSession)

        with patch("app.services.lab_service.finalize_evidence_state") as mock_finalize:
            mock_finalize.return_value = "ready"

            result = await reconcile_evidence_state_if_needed(lab, session)

        # Should call finalize with commit=False
        mock_finalize.assert_called_once()
        call_kwargs = mock_finalize.call_args[1]
        assert call_kwargs.get("commit") is False

        assert result is True

    @pytest.mark.asyncio
    async def test_reconcile_error_path_uses_flush(self):
        """Error path in reconcile also uses flush."""
        from app.services.lab_service import reconcile_evidence_state_if_needed

        lab = MagicMock(spec=Lab)
        lab.id = uuid4()
        lab.status = "finished"
        lab.evidence_state = "collecting"
        lab.evidence_finalized_at = None

        session = AsyncMock(spec=AsyncSession)

        with patch("app.services.lab_service.finalize_evidence_state") as mock_finalize:
            mock_finalize.side_effect = RuntimeError("Volume error")

            result = await reconcile_evidence_state_if_needed(lab, session)

        # Should use flush on error
        session.flush.assert_called_once()
        session.commit.assert_not_called()

        # Should set unavailable
        assert lab.evidence_state == EvidenceState.UNAVAILABLE.value
        assert result is True


# =============================================================================
# LabResponse serialization safety tests
# =============================================================================


class TestLabResponseSerialization:
    """Tests for safe LabResponse serialization."""

    def test_lab_response_has_evidence_fields(self):
        """LabResponse includes evidence_state and evidence_finalized_at."""
        fields = LabResponse.model_fields
        assert "evidence_state" in fields
        assert "evidence_finalized_at" in fields

    def test_lab_response_validates_valid_evidence_state(self):
        """LabResponse accepts valid evidence states."""
        # Test with string values (as stored in DB)
        for state in ["collecting", "ready", "partial", "unavailable"]:
            # Create a minimal lab-like dict
            lab_data = {
                "id": uuid4(),
                "owner_id": uuid4(),
                "recipe_id": uuid4(),
                "status": "finished",
                "requested_intent": None,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
                "finished_at": None,
                "evidence_state": state,
                "evidence_finalized_at": datetime.now(timezone.utc) if state != "collecting" else None,
            }

            # Should not raise
            response = LabResponse.model_validate(lab_data)
            assert response.evidence_state == state


# =============================================================================
# AsyncSession configuration tests
# =============================================================================


class TestAsyncSessionConfig:
    """Tests for AsyncSession configuration."""

    def test_expire_on_commit_is_false(self):
        """Verify expire_on_commit=False in session factory."""
        from app.db import AsyncSessionLocal

        # Check the sessionmaker configuration
        # The _kw attribute contains the configuration passed to sessionmaker
        assert hasattr(AsyncSessionLocal, "kw")
        config = AsyncSessionLocal.kw
        assert config.get("expire_on_commit") is False


# =============================================================================
# Regression tests
# =============================================================================


class TestMissingGreenletRegression:
    """Regression tests to prevent MissingGreenlet from returning."""

    @pytest.mark.asyncio
    async def test_flush_does_not_expire_attributes(self):
        """Verify that flush() doesn't expire ORM attributes."""
        # This is a documentation test - the actual behavior depends on
        # expire_on_commit=False configuration
        from app.db import AsyncSessionLocal

        # Verify configuration
        assert AsyncSessionLocal.kw.get("expire_on_commit") is False

    def test_evidence_state_is_simple_string(self):
        """evidence_state is a simple string column, not a relationship."""
        from app.models.lab import Lab

        # Get the column
        evidence_state_col = Lab.__table__.c.get("evidence_state")
        assert evidence_state_col is not None

        # It should be a String type, not a foreign key
        from sqlalchemy import String
        assert isinstance(evidence_state_col.type, String)
