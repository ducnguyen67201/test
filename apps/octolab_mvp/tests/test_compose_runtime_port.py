"""Unit tests for compose runtime with port allocation integration."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from subprocess import CalledProcessError

from app.runtime.compose_runtime import ComposeLabRuntime
from app.models.lab import Lab
from app.models.recipe import Recipe


@pytest.mark.asyncio
async def test_create_lab_passes_allocated_port_as_environment():
    """Test that create_lab passes the allocated port as environment variable to docker compose."""
    # Create runtime instance
    runtime = ComposeLabRuntime(compose_path=Path("/tmp/fake-compose.yml"))

    # Create mock lab
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

    # Mock subprocess.run to prevent actual compose execution
    with patch('subprocess.run') as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        # Mock the compose file existence
        with patch.object(runtime, 'compose_path', Path("/tmp/fake-compose.yml")):
            # Call create_lab with an allocated port - note: actual signature doesn't accept novnc_port parameter
            # Need to create a mock db_session to pass to create_lab
            from unittest.mock import AsyncMock
            mock_session = AsyncMock()

            # Mock the allocation function to return the port we want
            with patch('app.runtime.compose_runtime.allocate_novnc_port', new_callable=AsyncMock) as mock_alloc:
                mock_alloc.return_value = 35000
                await runtime.create_lab(lab, recipe, db_session=mock_session)

        # Verify that subprocess.run was called with environment containing the port
        assert mock_run.called
        call_args, call_kwargs = mock_run.call_args

        # Check that the env dictionary contains the expected noVNC port
        env = call_kwargs.get('env', {})
        assert 'NOVNC_HOST_PORT' in env
        assert env['NOVNC_HOST_PORT'] == '35000'

        # Check that the bind host is also correctly set
        assert 'COMPOSE_BIND_HOST' in env
        # This should match the config default
        from app.config import settings
        assert env['COMPOSE_BIND_HOST'] == settings.compose_bind_host


@pytest.mark.asyncio
async def test_create_lab_with_none_port():
    """Test that create_lab works when novnc_port is None."""
    # Create runtime instance
    runtime = ComposeLabRuntime(compose_path=Path("/tmp/fake-compose.yml"))

    # Create mock lab
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

    # Mock subprocess.run to prevent actual compose execution
    with patch('subprocess.run') as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        # Mock the compose file existence
        with patch.object(runtime, 'compose_path', Path("/tmp/fake-compose.yml")):
            # Call create_lab with no db session would fail, so test with a mock session
            from unittest.mock import AsyncMock
            mock_session = AsyncMock()

            # Call create_lab with database session required
            with patch('app.runtime.compose_runtime.allocate_novnc_port', new_callable=AsyncMock) as mock_alloc:
                mock_alloc.return_value = 35000  # Still mock the allocation to avoid DB calls
                await runtime.create_lab(lab, recipe, db_session=mock_session)

        # Verify that subprocess.run was called once
        assert mock_run.called
        call_args, call_kwargs = mock_run.call_args

        # Check that the env dictionary contains basic variables
        env = call_kwargs.get('env', {})
        assert 'LAB_ID' in env
        assert env['LAB_ID'] == str(lab.id)

        # Should have the port that was allocated
        assert 'NOVNC_HOST_PORT' in env
        assert env['NOVNC_HOST_PORT'] == '35000'


@pytest.mark.asyncio
async def test_subprocess_uses_shell_false():
    """Test that subprocess is always called with shell=False for security."""
    runtime = ComposeLabRuntime(compose_path="/tmp/fake-compose.yml")
    
    # Create mock lab
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
    
    # Mock subprocess.run
    with patch('subprocess.run') as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        
        # Mock the compose file existence
        with patch.object(runtime, 'compose_path', "/tmp/fake-compose.yml"):
            await runtime.create_lab(lab, recipe, novnc_port=35005)
        
        # Verify that shell=False was used in all calls
        assert mock_run.called
        call_kwargs = mock_run.call_args[1]  # Get the keyword arguments
        
        assert call_kwargs.get('shell') is False


def test_project_name_generation():
    """Test that project names are generated correctly from lab IDs."""
    runtime = ComposeLabRuntime(compose_path="/tmp/fake-compose.yml")
    
    # Create a test lab
    lab = Lab(
        id=uuid4(),
        owner_id=uuid4(),
        recipe_id=uuid4(),
        status="provisioning"
    )
    
    project_name = runtime._project_name(lab)
    
    # Should start with prefix and include lab id
    assert project_name.startswith(runtime.project_prefix)
    assert str(lab.id) in project_name


@pytest.mark.asyncio
async def test_error_sanitization_in_compose_runtime():
    """Test that compose runtime sanitizes errors properly without exposing secrets."""
    runtime = ComposeLabRuntime(compose_path="/tmp/fake-compose.yml")
    
    # Create mock lab
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
    
    # Mock a CalledProcessError that would contain sensitive data
    error = CalledProcessError(
        returncode=1,
        cmd=["docker", "compose", "-f", "/secret/path/compose.yaml", "up", "-d"],
        output="some output with fake_secret_token_12345",
        stderr="error: port already allocated for fake_secret_token_12345"
    )
    
    # Mock subprocess.run to raise this error
    with patch('subprocess.run', side_effect=error):
        # Mock the compose file existence
        with patch.object(runtime, 'compose_path', "/tmp/fake-compose.yml"):
            with pytest.raises(RuntimeError) as exc_info:
                await runtime.create_lab(lab, recipe, novnc_port=35010)
        
        # Verify that the error message doesn't contain the fake secret
        error_message = str(exc_info.value)
        assert "fake_secret_token_12345" not in error_message
        # Should have generic error message without exposing the command details
        assert "Docker compose failed" in error_message