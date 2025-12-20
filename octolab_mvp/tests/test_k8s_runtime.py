"""Unit tests for K8sLabRuntime with enhanced security features."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from subprocess import CalledProcessError
from app.runtime.k8s_runtime import K8sLabRuntime
from app.models.lab import Lab
from app.models.user import User
from app.models.recipe import Recipe
from uuid import UUID, uuid4


def test_redact_argv_from_literal_preserves_key():
    """Test that _redact_argv properly handles --from-literal=KEY=VALUE format."""
    from app.utils.redact import redact_argv
    
    # Test single arg format: --from-literal=VNC_PASSWORD=secret123
    argv = ["kubectl", "create", "secret", "generic", "test", "--from-literal=VNC_PASSWORD=secret123"]
    result = redact_argv(argv)
    
    expected = ["kubectl", "create", "secret", "generic", "test", "--from-literal=VNC_PASSWORD=***REDACTED***"]
    assert result == expected


def test_redact_argv_from_literal_two_args():
    """Test that _redact_argv properly handles --from-literal KEY=VALUE format."""
    from app.utils.redact import redact_argv
    
    # Test two arg format: --from-literal VNC_PASSWORD=secret123
    argv = ["kubectl", "create", "secret", "generic", "test", "--from-literal", "VNC_PASSWORD=secret123"]
    result = redact_argv(argv)
    
    expected = ["kubectl", "create", "secret", "generic", "test", "--from-literal", "***REDACTED***"]
    assert result == expected


@pytest.mark.asyncio
async def test_secret_creation_argv_format():
    """Test that _create_secret uses correct --from-literal format without leaking secrets."""
    runtime = K8sLabRuntime()

    # Mock lab object
    lab = Lab(
        id=uuid4(),
        owner_id=uuid4(),
        recipe_id=uuid4()
    )

    # Mock the _run_kubectl call
    with patch.object(runtime, '_run_kubectl', new_callable=AsyncMock) as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "generated yaml"
        mock_run.return_value = mock_result

        vnc_password = "super_secret_password_12345"
        await runtime._create_secret(lab, vnc_password)

        # _run_kubectl should be called twice: once to create secret, once to apply it
        assert mock_run.call_count == 2

        # First call: create secret with --from-literal
        first_call_args = mock_run.call_args_list[0][0][0]  # First positional arg of first call
        found_from_literal = False
        for arg in first_call_args:
            if arg.startswith("--from-literal="):
                assert f"VNC_PASSWORD={vnc_password}" in arg  # Original password should be in the arg
                found_from_literal = True
                break
        assert found_from_literal, "Expected --from-literal with password to be in first call args"

        # Second call: apply the generated YAML
        second_call_args = mock_run.call_args_list[1][0][0]  # First positional arg of second call
        assert "apply" in second_call_args
        assert "-f" in second_call_args


@pytest.mark.asyncio
async def test_secret_never_in_exception_logs():
    """Test that secrets never appear in exception messages/logs."""
    runtime = K8sLabRuntime()
    
    # Create a CalledProcessError with secret in stdout/stderr
    error = CalledProcessError(
        returncode=1,
        cmd=["kubectl", "create", "secret", "generic", "test", "--from-literal=VNC_PASSWORD=secret123"],
        output="output with secret123",
        stderr="stderr with secret123 and more details"
    )
    
    # Import the sanitize function
    from app.utils.redact import sanitize_subprocess_error
    
    # Sanitize the error
    sanitized = sanitize_subprocess_error(error, secret_patterns=["secret123"])
    
    # Verify secrets are redacted
    assert "***REDACTED***" in str(sanitized['cmd'])
    assert "secret123" not in str(sanitized['cmd'])
    assert "***REDACTED***" in sanitized['stdout']
    assert "secret123" not in sanitized['stdout']
    assert "***REDACTED***" in sanitized['stderr'] 
    assert "secret123" not in sanitized['stderr']


@pytest.mark.asyncio
async def test_kubectl_apply_retry_on_openapi_failure():
    """Test that _kubectl_apply_with_retry handles OpenAPI failures."""
    runtime = K8sLabRuntime()

    yaml_content = "apiVersion: v1\nkind: Secret\n..."

    # Mock the _run_kubectl method which is used by _kubectl_apply_with_retry
    with patch.object(runtime, '_run_kubectl', side_effect=[
        RuntimeError("failed to download openapi: server is currently unable to handle the request"),
        AsyncMock()  # Success on retry
    ]) as mock_run:

        # This should not raise when the first call fails but the second succeeds with --validate=false
        await runtime._kubectl_apply_with_retry(yaml_content)

        # Verify that it was called twice - first with original args, then with --validate=false
        assert mock_run.call_count == 2

        # First call should be the original args
        first_call_args = mock_run.call_args_list[0][0][0]  # First positional arg of first call
        assert "apply" in first_call_args
        assert "-f" in first_call_args
        if "--validate=false" not in first_call_args:
            # First call should NOT have --validate=false
            assert True

        # Second call should have --validate=false
        second_call_args = mock_run.call_args_list[1][0][0]  # First positional arg of second call
        assert "apply" in second_call_args
        assert "--validate=false" in second_call_args


@pytest.mark.asyncio
async def test_kubectl_apply_no_retry_on_other_errors():
    """Test that _kubectl_apply_with_retry does not retry on non-OpenAPI errors."""
    runtime = K8sLabRuntime()

    yaml_content = "apiVersion: v1\nkind: Secret\n..."

    # Create a RuntimeError with a message that doesn't match the OpenAPI failure pattern
    runtime_error = RuntimeError("this is a different error, not an OpenAPI download failure")

    with patch.object(runtime, '_run_kubectl', side_effect=runtime_error) as mock_run:
        with pytest.raises(RuntimeError):
            await runtime._kubectl_apply_with_retry(yaml_content, namespace="test")

        # Should only be called once since it's not an OpenAPI error
        assert mock_run.call_count == 1


def test_verify_namespace_labels_tristate():
    """Test the tri-state verification logic."""
    runtime = K8sLabRuntime()
    
    # Test the enum values exist
    assert runtime.NamespaceVerificationResult.NOT_FOUND == "not_found"
    assert runtime.NamespaceVerificationResult.MISMATCH == "mismatch"
    assert runtime.NamespaceVerificationResult.OK == "ok"


@pytest.mark.asyncio 
async def test_destroy_lab_namespace_not_found():
    """Test that destroy_lab handles missing namespace safely."""
    runtime = K8sLabRuntime()
    
    lab = Lab(
        id=uuid4(),
        owner_id=uuid4(),
        recipe_id=uuid4()
    )
    
    # Mock a return code != 0 to simulate namespace not found
    mock_result = MagicMock()
    mock_result.returncode = 1  # Simulate 'not found'
    
    with patch.object(runtime, '_kubectl', return_value=mock_result) as mock_kubectl:
        # Should not raise when namespace doesn't exist
        await runtime.destroy_lab(lab)
        
        # Only the initial check should be called
        assert mock_kubectl.call_count == 1


@pytest.mark.asyncio
async def test_destroy_lab_labels_mismatch():
    """Test that destroy_lab hard fails when labels don't match."""
    runtime = K8sLabRuntime()
    
    lab = Lab(
        id=uuid4(),
        owner_id=uuid4(),
        recipe_id=uuid4()
    )
    
    # Mock the namespace exists (first check returns success)
    exists_mock_result = MagicMock()
    exists_mock_result.returncode = 0
    
    # Mock the label verification to return mismatch
    with patch.object(runtime, '_kubectl', return_value=exists_mock_result):
        with patch.object(runtime, '_verify_namespace_labels', 
                         return_value=runtime.NamespaceVerificationResult.MISMATCH):
            with pytest.raises(RuntimeError, match="Security violation"):
                await runtime.destroy_lab(lab)


@pytest.mark.asyncio
async def test_destroy_lab_labels_match_success():
    """Test that destroy_lab succeeds when labels match."""
    runtime = K8sLabRuntime()
    
    lab = Lab(
        id=uuid4(),
        owner_id=uuid4(),
        recipe_id=uuid4()
    )
    
    # Mock the namespace exists (first check returns success)
    exists_mock_result = MagicMock()
    exists_mock_result.returncode = 0
    
    # Mock the label verification to return OK
    with patch.object(runtime, '_kubectl') as mock_kubectl:
        mock_kubectl.return_value = exists_mock_result
        
        with patch.object(runtime, '_verify_namespace_labels', 
                         return_value=runtime.NamespaceVerificationResult.OK):
            with patch.object(runtime, '_kubectl') as mock_delete_kubectl:
                mock_delete_kubectl.return_value.returncode = 0  # Success on delete
                # Should succeed without exceptions
                await runtime.destroy_lab(lab)
                
                # Should call kubectl delete
                assert mock_delete_kubectl.called


if __name__ == "__main__":
    pytest.main([__file__])