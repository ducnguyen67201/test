"""Authorization tests for evidence status endpoint.

Tests ensure:
1. Non-owned labs return 404 (no enumeration)
2. Owned labs return 200 with status
3. Wrong status labs return 409
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import uuid4
from datetime import datetime, timezone, timedelta

# Mark all tests as not requiring database
pytestmark = pytest.mark.no_db


class MockUser:
    """Mock user for testing."""

    def __init__(self, user_id=None):
        self.id = user_id or uuid4()


class MockLab:
    """Mock lab model for testing."""

    def __init__(
        self,
        lab_id=None,
        owner_id=None,
        status="ready",
        evidence_expires_at=None,
    ):
        from app.models.lab import LabStatus

        self.id = lab_id or uuid4()
        self.owner_id = owner_id or uuid4()
        self.status = getattr(LabStatus, status.upper())
        self.evidence_expires_at = evidence_expires_at


class TestEvidenceStatusEndpointAuthz:
    """Authorization tests for GET /labs/{lab_id}/evidence/status."""

    @pytest.mark.asyncio
    async def test_non_owned_lab_returns_404(self):
        """Non-owned lab returns 404 to prevent enumeration."""
        from app.api.routes.labs import get_evidence_status
        from fastapi import HTTPException

        user = MockUser()
        lab_id = uuid4()

        # Mock get_lab_for_user to return None (not found or not owned)
        with patch("app.api.routes.labs.get_lab_for_user", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            mock_db = MagicMock()

            with pytest.raises(HTTPException) as exc_info:
                await get_evidence_status(lab_id, user, mock_db)

            assert exc_info.value.status_code == 404
            assert "not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_nonexistent_lab_returns_404(self):
        """Nonexistent lab returns 404."""
        from app.api.routes.labs import get_evidence_status
        from fastapi import HTTPException

        user = MockUser()
        lab_id = uuid4()

        with patch("app.api.routes.labs.get_lab_for_user", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            mock_db = MagicMock()

            with pytest.raises(HTTPException) as exc_info:
                await get_evidence_status(lab_id, user, mock_db)

            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_provisioning_lab_returns_409(self):
        """Lab in PROVISIONING status returns 409."""
        from app.api.routes.labs import get_evidence_status
        from fastapi import HTTPException

        user = MockUser()
        lab = MockLab(owner_id=user.id, status="provisioning")

        with patch("app.api.routes.labs.get_lab_for_user", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = lab

            mock_db = MagicMock()

            with pytest.raises(HTTPException) as exc_info:
                await get_evidence_status(lab.id, user, mock_db)

            assert exc_info.value.status_code == 409
            assert "ready or finished" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_ending_lab_returns_409(self):
        """Lab in ENDING status returns 409."""
        from app.api.routes.labs import get_evidence_status
        from fastapi import HTTPException

        user = MockUser()
        lab = MockLab(owner_id=user.id, status="ending")

        with patch("app.api.routes.labs.get_lab_for_user", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = lab

            mock_db = MagicMock()

            with pytest.raises(HTTPException) as exc_info:
                await get_evidence_status(lab.id, user, mock_db)

            assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_expired_evidence_returns_404(self):
        """Expired evidence returns 404."""
        from app.api.routes.labs import get_evidence_status
        from fastapi import HTTPException

        user = MockUser()
        lab = MockLab(
            owner_id=user.id,
            status="finished",
            evidence_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        with patch("app.api.routes.labs.get_lab_for_user", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = lab

            mock_db = MagicMock()

            with pytest.raises(HTTPException) as exc_info:
                await get_evidence_status(lab.id, user, mock_db)

            assert exc_info.value.status_code == 404
            assert "not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_ready_lab_returns_200(self):
        """READY lab returns 200 with status."""
        from app.api.routes.labs import get_evidence_status
        from app.schemas.lab import EvidenceStatusResponse, EvidenceArtifacts, ArtifactStatus

        user = MockUser()
        lab = MockLab(owner_id=user.id, status="ready")

        mock_status = {
            "lab_id": lab.id,
            "generated_at": datetime.now(timezone.utc),
            "artifacts": EvidenceArtifacts(
                terminal_logs=ArtifactStatus(present=False, reason="No logs"),
                pcap=ArtifactStatus(present=False, reason="No capture"),
                guac_recordings=ArtifactStatus(present=False, reason="Not enabled"),
            ),
            "notes": [],
        }

        with patch("app.api.routes.labs.get_lab_for_user", new_callable=AsyncMock) as mock_get, \
             patch("app.api.routes.labs.build_evidence_status", new_callable=AsyncMock) as mock_status_fn:

            mock_get.return_value = lab
            mock_status_fn.return_value = mock_status

            mock_db = MagicMock()

            result = await get_evidence_status(lab.id, user, mock_db)

            assert result.lab_id == lab.id
            assert result.artifacts.terminal_logs.present is False

    @pytest.mark.asyncio
    async def test_finished_lab_returns_200(self):
        """FINISHED lab returns 200 with status."""
        from app.api.routes.labs import get_evidence_status
        from app.schemas.lab import EvidenceArtifacts, ArtifactStatus

        user = MockUser()
        lab = MockLab(owner_id=user.id, status="finished")

        mock_status = {
            "lab_id": lab.id,
            "generated_at": datetime.now(timezone.utc),
            "artifacts": EvidenceArtifacts(
                terminal_logs=ArtifactStatus(present=True, files=["evidence/commands.log"], bytes=100),
                pcap=ArtifactStatus(present=True, files=["pcap/capture.pcap"], bytes=500),
                guac_recordings=ArtifactStatus(present=False, reason="Not enabled"),
            ),
            "notes": [],
        }

        with patch("app.api.routes.labs.get_lab_for_user", new_callable=AsyncMock) as mock_get, \
             patch("app.api.routes.labs.build_evidence_status", new_callable=AsyncMock) as mock_status_fn:

            mock_get.return_value = lab
            mock_status_fn.return_value = mock_status

            mock_db = MagicMock()

            result = await get_evidence_status(lab.id, user, mock_db)

            assert result.lab_id == lab.id
            assert result.artifacts.terminal_logs.present is True
            assert result.artifacts.pcap.present is True


class TestEvidenceStatusTenantIsolation:
    """Ensure strict tenant isolation."""

    @pytest.mark.asyncio
    async def test_user_a_cannot_see_user_b_lab_status(self):
        """User A cannot see status of User B's lab."""
        from app.api.routes.labs import get_evidence_status
        from fastapi import HTTPException

        user_a = MockUser()
        user_b = MockUser()
        lab = MockLab(owner_id=user_b.id, status="ready")

        # Simulate get_lab_for_user filtering by owner_id
        # User A queries but lab is owned by User B
        with patch("app.api.routes.labs.get_lab_for_user", new_callable=AsyncMock) as mock_get:
            # get_lab_for_user returns None because owner_id doesn't match
            mock_get.return_value = None

            mock_db = MagicMock()

            with pytest.raises(HTTPException) as exc_info:
                await get_evidence_status(lab.id, user_a, mock_db)

            assert exc_info.value.status_code == 404
            # Must NOT reveal that lab exists but belongs to someone else
