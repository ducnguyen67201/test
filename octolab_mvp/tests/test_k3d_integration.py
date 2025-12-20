"""Test to verify k3d integration functionality works properly."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4

from app.services.port_allocator import allocate_novnc_port, release_novnc_port
from app.config import settings


@pytest.mark.asyncio
async def test_port_allocation_functions_still_work():
    """Test that port allocation functions can be imported and basic logic works."""
    # Create a mock DB session that simulates the common path where a port already exists
    session = AsyncMock()

    # Mock the SELECT query to return an existing port (simulating idempotency)
    mock_select_result = MagicMock()
    mock_select_result.scalar_one_or_none.return_value = 35001  # Existing allocated port

    # Mock the execute to return the select result for the first call
    def mock_execute_fn(query, *args, **kwargs):
        mock_result = MagicMock()
        if hasattr(query, 'compile') or 'SELECT labs.novnc_host_port' in str(query):  # This is a SQLAlchemy select query
            mock_result.scalar_one_or_none.return_value = 35001
        else:  # This is an UPDATE query
            mock_result.rowcount = 1
        return mock_result

    session.execute = AsyncMock(side_effect=mock_execute_fn)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    lab_id = uuid4()
    owner_id = uuid4()

    # Test the idempotency path (when port already exists)
    result_port = await allocate_novnc_port(session, lab_id=lab_id, owner_id=owner_id)

    # Should return the existing port
    assert result_port == 35001

    print("✓ Port allocation functions work correctly")


def test_config_settings_updated():
    """Test that new config settings are available."""
    # Check that the port range settings are available
    assert hasattr(settings, 'compose_port_min')
    assert hasattr(settings, 'compose_port_max')
    assert hasattr(settings, 'compose_bind_host')

    # Check that the values are reasonable
    assert settings.compose_port_min == 30000
    assert settings.compose_port_max == 39999
    assert settings.compose_bind_host == "127.0.0.1"

    print("✓ Configuration settings updated correctly")


@pytest.mark.asyncio
async def test_port_release_function():
    """Test that port release works."""
    session = AsyncMock()

    # Mock a successful release result
    mock_update_result = MagicMock()
    mock_update_result.rowcount = 1  # Indicate one row was updated

    def mock_execute_fn(query, *args, **kwargs):
        return mock_update_result

    session.execute = AsyncMock(side_effect=mock_execute_fn)
    session.commit = AsyncMock()

    lab_id = uuid4()
    owner_id = uuid4()

    # Test release function
    success = await release_novnc_port(session, lab_id=lab_id, owner_id=owner_id)

    assert success is True

    print("✓ Port release function works correctly")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_port_allocation_functions_still_work())
    test_config_settings_updated()
    asyncio.run(test_port_release_function())
    print("All validation tests passed!")