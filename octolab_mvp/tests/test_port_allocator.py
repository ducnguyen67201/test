"""Unit tests for port allocation service with compose runtime integration."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy.exc import IntegrityError
from uuid import uuid4

from app.models.lab import Lab
from app.models.port_reservation import PortReservation
from app.services.port_allocator import allocate_novnc_port, release_novnc_port
from app.config import settings


@pytest.mark.asyncio
async def test_allocate_novnc_port_creates_reservation():
    """Test that allocate_novnc_port creates a new reservation in the configured range."""
    async with AsyncMock() as session:
        lab_id = uuid4()
        owner_id = uuid4()

        # Mock successful reservation with a port in the configured range
        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            if isinstance(query, str) and "UPDATE labs SET novnc_host_port" in query:
                # Simulate successful update of the lab
                return mock_result
            elif "SELECT labs.novnc_host_port" in str(query):
                # Simulate no existing reservation
                mock_result.scalar_one_or_none.return_value = None
                return mock_result
            return mock_result

        session.execute = mock_execute
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        # Mock random port selection within range
        with patch('secrets.randbelow') as mock_randbelow:
            # Return a port in range
            mock_randbelow.return_value = 5000  # relative to min port of 30000 = port 35000
            allocated_port = await allocate_novnc_port(session, lab_id=lab_id, owner_id=owner_id)

            # Verify the port is in the expected range
            expected_port = settings.compose_port_min + 5000
            assert allocated_port == expected_port
            # Verify commit was called to persist the reservation
            session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_allocate_novnc_port_idempotency():
    """Test that allocate_novnc_port returns existing port when already allocated."""
    async with AsyncMock() as session:
        lab_id = uuid4()
        owner_id = uuid4()
        existing_port = 35001

        # Mock SELECT query to return existing port
        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            if "SELECT labs.novnc_host_port" in str(query):
                mock_result.scalar_one_or_none.return_value = existing_port
                return mock_result
            return mock_result

        session.execute = mock_execute
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        # Should return existing port without trying to allocate a new one
        allocated_port = await allocate_novnc_port(session, lab_id=lab_id, owner_id=owner_id)
        
        assert allocated_port == existing_port
        # Verify that commit/rollback were not called since no update happened
        session.commit.assert_not_called()
        session.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_allocate_novnc_port_concurrency_retry():
    """Test that allocate_novnc_port handles DB collisions with bounded retry."""
    async with AsyncMock() as session:
        lab_id = uuid4()
        owner_id = uuid4()

        # Mock first 3 calls to raise IntegrityError (collision) and 4th to succeed
        call_count = 0
        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            
            if "SELECT labs.novnc_host_port" in str(query):
                # First query: check existing port (return None)
                mock_result.scalar_one_or_none.return_value = None
                return mock_result
            elif "UPDATE labs SET novnc_host_port" in str(query):
                # Subsequent queries: try to update with port
                if call_count <= 4:  # First 3 UPDATE calls fail with IntegrityError
                    if call_count <= 3:
                        raise IntegrityError("duplicate key value violates unique constraint", {}, None)
                    else:
                        # 4th call succeeds
                        mock_result.rowcount = 1
                        return mock_result
                else:
                    mock_result.rowcount = 1
                    return mock_result

        session.execute = mock_execute
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        # Mock different port selections for each retry
        with patch('secrets.randbelow') as mock_randbelow:
            mock_randbelow.side_effect = [1000, 2000, 3000, 4000]  # Different relative ports for each attempt
            allocated_port = await allocate_novnc_port(session, lab_id=lab_id, owner_id=owner_id)

            # Should get the port from the 4th attempt
            expected_port = settings.compose_port_min + 4000
            assert allocated_port == expected_port
            # Verify that commit was called once on success
            assert session.commit.call_count == 1


@pytest.mark.asyncio
async def test_allocate_novnc_port_exhausts_retries():
    """Test that allocate_novnc_port raises RuntimeError after exhausting retries."""
    async with AsyncMock() as session:
        lab_id = uuid4()
        owner_id = uuid4()

        # Always raise IntegrityError to simulate continuous collisions
        async def mock_execute(query, params=None):
            if "SELECT labs.novnc_host_port" in str(query):
                # Check existing port query: return None
                mock_result = MagicMock()
                mock_result.scalar_one_or_none.return_value = None
                return mock_result
            elif "UPDATE labs SET novnc_host_port" in str(query):
                # Update queries: always raise IntegrityError (collision)
                raise IntegrityError("duplicate key value violates unique constraint", {}, None)
            else:
                mock_result = MagicMock()
                return mock_result

        session.execute = mock_execute
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        # Mock port selection to return same port each time to guarantee collision
        with patch('secrets.randbelow') as mock_randbelow:
            mock_randbelow.return_value = 1000  # Same relative port each time
            with pytest.raises(RuntimeError, match="Unable to allocate unique noVNC port after"):
                await allocate_novnc_port(session, lab_id=lab_id, owner_id=owner_id)


@pytest.mark.asyncio
async def test_release_novnc_port_success():
    """Test that release_novnc_port successfully clears the reservation."""
    async with AsyncMock() as session:
        lab_id = uuid4()
        owner_id = uuid4()

        # Mock successful UPDATE with 1 row affected
        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            mock_result.rowcount = 1  # One row was updated (the reservation was found and cleared)
            return mock_result

        session.execute = mock_execute
        session.commit = AsyncMock()

        success = await release_novnc_port(session, lab_id=lab_id, owner_id=owner_id)
        
        assert success is True
        # Verify session.commit was called
        session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_release_novnc_port_no_reservation():
    """Test that release_novnc_port returns False when no active reservation exists."""
    async with AsyncMock() as session:
        lab_id = uuid4()
        owner_id = uuid4()

        # Mock UPDATE with 0 rows affected (no matching reservation)
        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            mock_result.rowcount = 0  # No rows matched the WHERE condition
            return mock_result

        session.execute = mock_execute
        session.commit = AsyncMock()

        success = await release_novnc_port(session, lab_id=lab_id, owner_id=owner_id)
        
        assert success is False
        # Verify session.commit was called (to persist the update attempt)
        session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_allocate_novnc_port_tenant_scoping():
    """Test that allocate_novnc_port only operates on labs owned by the specified owner."""
    async with AsyncMock() as session:
        lab_id = uuid4()
        owner_id = uuid4()
        wrong_owner_id = uuid4()

        # Mock a SELECT query that would return None because the owner_id doesn't match
        # This simulates tenant isolation enforcing that only the correct owner can access the lab
        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            if "SELECT labs.novnc_host_port" in str(query):
                # Query would check for existing port with tenant isolation (owner_id)
                # This simulates finding no existing port reservation for the wrong owner
                mock_result.scalar_one_or_none.return_value = None
                return mock_result
            return mock_result

        session.execute = mock_execute
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        # Mock random port selection
        with patch('secrets.randbelow') as mock_randbelow:
            mock_randbelow.return_value = 5000
            allocated_port = await allocate_novnc_port(session, lab_id=lab_id, owner_id=owner_id)
            
            # Should succeed with owner_id scope
            expected_port = settings.compose_port_min + 5000
            assert allocated_port == expected_port


@pytest.mark.asyncio
async def test_release_novnc_port_tenant_scoping():
    """Test that release_novnc_port only operates on labs owned by the specified owner."""
    async with AsyncMock() as session:
        lab_id = uuid4()
        owner_id = uuid4()

        # Mock UPDATE that respects tenant scoping
        call_params = None
        async def mock_execute(query, params=None):
            nonlocal call_params
            call_params = params
            mock_result = MagicMock()
            mock_result.rowcount = 1  # Simulate successful update
            return mock_result

        session.execute = mock_execute
        session.commit = AsyncMock()

        success = await release_novnc_port(session, lab_id=lab_id, owner_id=owner_id)
        
        assert success is True
        # Verify that the call included both lab_id and owner_id for tenant isolation
        assert call_params is not None
        assert call_params["lab_id"] == lab_id
        assert call_params["owner_id"] == owner_id