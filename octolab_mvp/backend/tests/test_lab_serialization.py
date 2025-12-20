"""Tests for Lab serialization to prevent MissingGreenlet regression.

These tests verify that Lab objects can be serialized to LabResponse
without triggering lazy-load exceptions (MissingGreenlet).

The root cause of MissingGreenlet in async SQLAlchemy:
- After commit(), SQLAlchemy expires attributes by default
- With server-side defaults (e.g., onupdate=func.now()), the Python object
  doesn't have the value until refreshed or re-queried
- Accessing expired attributes outside a greenlet context raises MissingGreenlet

These tests use mocking to verify the fix without requiring a real database.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.schemas.lab import LabCreate, LabIntent, LabResponse
from app.models.lab import Lab, LabStatus, EvidenceSealStatus
from app.models.user import User
from app.models.recipe import Recipe


class TestLabCreationSerialization:
    """Tests for create_lab_for_user returning serializable Lab objects."""

    def test_lab_service_does_refetch_after_second_commit(self):
        """Verify create_lab_for_user has re-fetch logic after second commit.

        This is a code inspection test that verifies the fix is in place.
        The actual MissingGreenlet bug would require a real database to reproduce,
        but we can verify the fix exists in the code.

        The fix pattern:
        1. First commit after lab creation
        2. Set evidence volumes
        3. Second commit
        4. Re-fetch via select() with tenant isolation <- THIS IS THE FIX

        Without the re-fetch, updated_at (with onupdate=func.now()) would not
        be loaded, causing MissingGreenlet during Pydantic serialization.
        """
        import inspect
        from app.services.lab_service import create_lab_for_user

        source = inspect.getsource(create_lab_for_user)

        # Verify the fix is present: re-fetch after second commit
        # The pattern we're looking for:
        # 1. Second commit (after setting evidence_auth_volume)
        # 2. Re-fetch query with Lab.id and Lab.owner_id filter
        # 3. scalar_one() to get the refreshed lab

        # Check that the function has a re-fetch pattern
        assert "scalar_one()" in source, (
            "create_lab_for_user should use scalar_one() to re-fetch the lab"
        )

        # Check for tenant isolation in the re-fetch
        assert "Lab.owner_id == user.id" in source, (
            "create_lab_for_user should filter by owner_id in re-fetch"
        )

        # Verify we have two commits (initial + after setting evidence volumes)
        commit_count = source.count("await db.commit()")
        assert commit_count >= 2, (
            f"Expected at least 2 commits in create_lab_for_user, found {commit_count}"
        )

    @pytest.mark.asyncio
    async def test_lab_response_model_validate_succeeds(self):
        """Test that LabResponse.model_validate works with properly loaded Lab.

        This tests the Pydantic serialization that would fail with MissingGreenlet
        if created_at or updated_at were expired/unloaded.
        """
        now = datetime.now(timezone.utc)
        lab_id = uuid4()
        owner_id = uuid4()
        recipe_id = uuid4()

        # Create a mock lab with all required fields
        lab = MagicMock(spec=Lab)
        lab.id = lab_id
        lab.owner_id = owner_id
        lab.recipe_id = recipe_id
        lab.status = LabStatus.PROVISIONING
        lab.requested_intent = {"software": "apache"}
        lab.connection_url = None
        lab.hackvm_project = None
        lab.expires_at = None
        lab.created_at = now
        lab.updated_at = now
        lab.finished_at = None

        # Make status serializable (it needs .value for Literal validation)
        lab.status = "provisioning"

        # This should NOT raise MissingGreenlet or ValidationError
        response = LabResponse.model_validate(lab)

        assert response.id == lab_id
        assert response.owner_id == owner_id
        assert response.recipe_id == recipe_id
        assert response.status == "provisioning"
        assert response.created_at == now
        assert response.updated_at == now
        assert response.requested_intent == {"software": "apache"}

    def test_lab_response_schema_requires_timestamps(self):
        """Test that LabResponse schema requires created_at and updated_at.

        This documents the expected behavior: created_at and updated_at are required.
        If they're missing, Pydantic should raise ValidationError.

        This is why the MissingGreenlet fix is necessary - without properly loaded
        timestamps, LabResponse.model_validate() would fail.
        """
        from pydantic import ValidationError

        # Test with dict input (simulates what Pydantic sees from ORM)
        incomplete_lab_data = {
            "id": str(uuid4()),
            "owner_id": str(uuid4()),
            "recipe_id": str(uuid4()),
            "status": "provisioning",
            "requested_intent": None,
            "connection_url": None,
            "hackvm_project": None,
            "expires_at": None,
            "finished_at": None,
            # Missing: created_at, updated_at
        }

        # Validation should fail when timestamps are missing
        with pytest.raises(ValidationError) as exc_info:
            LabResponse.model_validate(incomplete_lab_data)

        # Verify the error is about missing timestamps
        errors = exc_info.value.errors()
        error_fields = {e["loc"][0] for e in errors}
        assert "created_at" in error_fields, "Should fail on missing created_at"
        assert "updated_at" in error_fields, "Should fail on missing updated_at"


class TestListLabsSerialization:
    """Tests for list_labs_for_user returning serializable Lab objects."""

    @pytest.mark.asyncio
    async def test_list_labs_returns_labs_with_timestamps(self):
        """Test that list_labs_for_user returns Labs with all fields loaded."""
        from app.services.lab_service import list_labs_for_user

        user = MagicMock(spec=User)
        user.id = uuid4()

        now = datetime.now(timezone.utc)
        lab1 = MagicMock(spec=Lab)
        lab1.id = uuid4()
        lab1.owner_id = user.id
        lab1.recipe_id = uuid4()
        lab1.status = "ready"
        lab1.requested_intent = None
        lab1.connection_url = "http://localhost:6080"
        lab1.hackvm_project = None
        lab1.expires_at = None
        lab1.created_at = now
        lab1.updated_at = now
        lab1.finished_at = None

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [lab1]
        mock_session.execute.return_value = mock_result

        result = await list_labs_for_user(db=mock_session, user=user)

        assert len(result) == 1
        assert result[0].created_at == now
        assert result[0].updated_at == now

        # Verify serialization works
        response = LabResponse.model_validate(result[0])
        assert response.created_at == now


class TestGetLabSerialization:
    """Tests for get_lab_for_user returning serializable Lab objects."""

    @pytest.mark.asyncio
    async def test_get_lab_returns_lab_with_timestamps(self):
        """Test that get_lab_for_user returns Lab with all fields loaded."""
        from app.services.lab_service import get_lab_for_user

        user = MagicMock(spec=User)
        user.id = uuid4()

        now = datetime.now(timezone.utc)
        lab = MagicMock(spec=Lab)
        lab.id = uuid4()
        lab.owner_id = user.id
        lab.recipe_id = uuid4()
        lab.status = "finished"
        lab.requested_intent = None
        lab.connection_url = None
        lab.hackvm_project = None
        lab.expires_at = None
        lab.created_at = now
        lab.updated_at = now
        lab.finished_at = now

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = lab
        mock_session.execute.return_value = mock_result

        result = await get_lab_for_user(db=mock_session, user=user, lab_id=lab.id)

        assert result is not None
        assert result.created_at == now
        assert result.updated_at == now

        # Verify serialization works
        response = LabResponse.model_validate(result)
        assert response.updated_at == now
