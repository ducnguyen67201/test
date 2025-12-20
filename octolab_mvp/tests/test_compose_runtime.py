"""Unit tests for compose runtime port handling."""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from pathlib import Path
from uuid import uuid4

from app.runtime.compose_runtime import ComposeLabRuntime
from app.models.lab import Lab
from app.models.recipe import Recipe


@pytest.mark.asyncio
async def test_create_lab_with_db_session():
    """Test that create_lab uses the port allocator when db_session is provided."""
    # Mock the compose path to exist
    with patch('pathlib.Path.exists', return_value=True):
        runtime = ComposeLabRuntime(compose_path=Path("/tmp/fake/compose.yml"))

    lab = Lab(
        id=uuid4(),
        owner_id=uuid4(),
        recipe_id=uuid4(),
        status="provisioning"
    )
    recipe = Recipe(
        id=uuid4(),
        name="test",
        software="test"
    )

    # Create a mock session and configure it to mock the port reservation flow
    async def mock_session_execute(query, params=None):
        # This simulates the SELECT query checking for existing port (returns None)
        # and the UPDATE query (returns result with rowcount=1 for successful reservation)
        mock_result = MagicMock()
        if 'SELECT' in str(query):
            mock_result.scalar_one_or_none.return_value = None  # No existing port
        elif 'UPDATE' in str(query):
            mock_result.rowcount = 1  # Successful update
        return mock_result

    # Mock the session
    mock_session = AsyncMock()
    mock_session.execute.side_effect = mock_session_execute
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    # Mock random port generation
    with patch('random.randint', return_value=30001):
        with patch.object(runtime, '_run_compose', new_callable=AsyncMock) as mock_run:
            # Call with db session
            await runtime.create_lab(lab, recipe, db_session=mock_session)

            # Verify _run_compose was called with proper environment
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            env = call_args.kwargs.get('env', call_args[1].get('env', {}))

            assert env['LAB_ID'] == str(lab.id)
            assert env['NOVNC_HOST_PORT'] == '30001'
            assert env['NOVNC_BIND_ADDR'] == '127.0.0.1'  # Should use config default


@pytest.mark.asyncio
async def test_create_lab_without_db_session_fails():
    """Test that create_lab fails when no db_session is provided."""
    # Mock the compose path to exist
    with patch('pathlib.Path.exists', return_value=True):
        runtime = ComposeLabRuntime(compose_path=Path("/tmp/fake/compose.yml"))

    lab = Lab(
        id=uuid4(),
        owner_id=uuid4(),
        recipe_id=uuid4(),
        status="provisioning"
    )
    recipe = Recipe(
        id=uuid4(),
        name="test",
        software="test"
    )

    # Should raise RuntimeError when no db session is provided
    with pytest.raises(RuntimeError, match="Database session required for port allocation"):
        await runtime.create_lab(lab, recipe)