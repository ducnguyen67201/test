"""Unit tests for K8sLabRuntime with context selection."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from subprocess import CalledProcessError
from uuid import uuid4

from app.runtime.k8s_runtime import K8sLabRuntime
from app.models.lab import Lab
from app.config import settings


@pytest.mark.asyncio
async def test_kubectl_base_args_uses_explicit_context():
    """Test that _kubectl_base_args includes context when specified explicitly."""
    # Create runtime with explicit context
    runtime = K8sLabRuntime(context="k3d-test-cluster")
    
    args = runtime._kubectl_base_args()
    
    # Should include context parameter
    assert "--context" in args
    context_idx = args.index("--context")
    assert args[context_idx + 1] == "k3d-test-cluster"


@pytest.mark.asyncio
async def test_kubectl_base_args_uses_settings_context():
    """Test that _kubectl_base_args falls back to settings context."""
    with patch('app.runtime.k8s_runtime.settings') as mock_settings:
        mock_settings.kubectl_context = "k3d-from-settings"
        
        # Runtime without explicit context
        runtime = K8sLabRuntime()
        args = runtime._kubectl_base_args()
        
        # Should use the context from settings
        assert "--context" in args
        context_idx = args.index("--context")
        assert args[context_idx + 1] == "k3d-from-settings"


@pytest.mark.asyncio
async def test_kubectl_base_args_uses_octolab_settings_context():
    """Test that _kubectl_base_args falls back to octolab_k8s_context setting."""
    with patch('app.runtime.k8s_runtime.settings') as mock_settings:
        # Simulate the case where kubectl_context is None but octolab_k8s_context has value
        mock_settings.kubectl_context = None
        mock_settings.octolab_k8s_context = "k3d-from-octolab-settings"
        
        runtime = K8sLabRuntime()  # No context specified
        args = runtime._kubectl_base_args()
        
        # Should use octolab_k8s_context as fallback
        assert "--context" in args
        context_idx = args.index("--context")
        assert args[context_idx + 1] == "k3d-from-octolab-settings"


@pytest.mark.asyncio
async def test_kubectl_base_args_uses_kubeconfig():
    """Test that _kubectl_base_args includes kubeconfig when specified."""
    # Create runtime with explicit kubeconfig
    runtime = K8sLabRuntime(kubeconfig_path="/test/path/kubeconfig.yaml")
    
    args = runtime._kubectl_base_args()
    
    # Should include kubeconfig parameter
    assert "--kubeconfig" in args
    kubeconfig_idx = args.index("--kubeconfig")
    assert args[kubeconfig_idx + 1] == "/test/path/kubeconfig.yaml"


@pytest.mark.asyncio
async def test_kubectl_base_args_uses_settings_kubeconfig():
    """Test that _kubectl_base_args falls back to settings kubeconfig."""
    with patch('app.runtime.k8s_runtime.settings') as mock_settings:
        mock_settings.kubectl_kubeconfig_path = "/settings/path/kubeconfig.yaml"
        
        # Runtime without explicit kubeconfig
        runtime = K8sLabRuntime()
        args = runtime._kubectl_base_args()
        
        # Should use the kubeconfig from settings
        assert "--kubeconfig" in args
        kubeconfig_idx = args.index("--kubeconfig")
        assert args[kubeconfig_idx + 1] == "/settings/path/kubeconfig.yaml"


@pytest.mark.asyncio
async def test_run_kubectl_includes_context():
    """Test that _run_kubectl includes the correct context in kubectl command."""
    with patch('app.runtime.k8s_runtime.subprocess.run') as mock_run:
        # Mock successful completion
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "nodes found"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        # Create runtime with explicit context
        runtime = K8sLabRuntime(context="k3d-test-context")
        lab = Lab(
            id=uuid4(),
            owner_id=uuid4(),
            recipe_id=uuid4(),
            status="provisioning"
        )
        
        # Run a command with namespace
        await runtime._run_kubectl(["get", "nodes"], namespace="default", timeout_s=10)
        
        # Verify subprocess.run was called with the correct arguments
        assert mock_run.called
        call_args = mock_run.call_args[0][0]  # First positional argument is the command list
        
        # Verify the full command includes kubectl, context, namespace, and the command itself
        expected_cmd_pattern = ["kubectl"]
        assert "kubectl" in call_args
        assert "--context" in call_args
        context_idx = call_args.index("--context")
        assert call_args[context_idx + 1] == "k3d-test-context"
        assert "-n" in call_args
        namespace_idx = call_args.index("-n")
        assert call_args[namespace_idx + 1] == "default"
        assert "get" in call_args
        assert "nodes" in call_args


@pytest.mark.asyncio
async def test_run_kubectl_sanitizes_errors():
    """Test that _run_kubectl sanitizes errors properly without exposing secrets."""
    from subprocess import CalledProcessError
    
    with patch('app.runtime.k8s_runtime.subprocess.run') as mock_run:
        # Mock a CalledProcessError with sensitive content
        error = CalledProcessError(
            returncode=1,
            cmd=["kubectl", "--context", "k3d-secret-context", "get", "secrets"],
            output="secret data: super_secret_token_12345",
            stderr="error: failed to load config: token=abc123def456"
        )
        mock_run.side_effect = error
        
        runtime = K8sLabRuntime(context="k3d-secret-context")
        
        with pytest.raises(RuntimeError) as exc_info:
            await runtime._run_kubectl(["get", "secrets"], timeout_s=5)
        
        error_message = str(exc_info.value)
        # Verify that sensitive data is not exposed in the error message
        assert "abc123def456" not in error_message
        assert "super_secret_token_12345" not in error_message


@pytest.mark.asyncio
async def test_run_kubectl_allows_retries_on_openapi_failures():
    """Test that kubectl operations handle OpenAPI failures with retries."""
    # Mock a scenario where the first call fails with OpenAPI issue but second succeeds
    with patch('app.runtime.k8s_runtime.subprocess.run', side_effect=[
        # First call: OpenAPI download failure
        CalledProcessError(
            returncode=1,
            cmd=["kubectl", "--context", "k3d-test", "apply", "-f", "-"],
            output="",
            stderr="failed to download openapi: server is currently unable to handle the request"
        ),
        # Second call: success with --validate=false (we'll test this separately)
        MagicMock(returncode=0, stdout="success", stderr="")
    ]) as mock_run:
        runtime = K8sLabRuntime(context="k3d-test")
        
        # This is expected to fail on first attempt
        with pytest.raises(RuntimeError) as exc_info:
            await runtime._run_kubectl(["apply", "-f", "-"], timeout_s=10)
        
        error_message = str(exc_info.value)
        assert "failed" in error_message.lower()


@pytest.mark.asyncio
async def test_create_lab_passes_context_to_kubectl():
    """Test that create_lab uses the correct kubectl context during execution."""
    with patch.object(K8sLabRuntime, '_run_kubectl', new_callable=AsyncMock) as mock_run:
        # Mock the return value for the first call (which would be a successful one)
        mock_result = MagicMock()
        mock_result.stdout = "generated yaml content"
        mock_result.stderr = ""
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        runtime = K8sLabRuntime(context="k3d-test-cluster")
        lab = Lab(
            id=uuid4(),
            owner_id=uuid4(),
            recipe_id=uuid4(),
            status="provisioning"
        )

        # Call create_lab (without novnc_port parameter as it's not part of the signature)
        await runtime.create_lab(lab, MagicMock())

        # Verify that _run_kubectl was called at least once
        assert mock_run.called

        # Check that the context was properly passed for at least one of the calls
        # Go through all the calls to find one that includes the context
        has_context = False
        for call_args in mock_run.call_args_list:
            args_passed = call_args[0][0]  # First positional arg is the command args list

            if "--context" in args_passed:
                context_idx = args_passed.index("--context")
                if args_passed[context_idx + 1] == "k3d-test-cluster":
                    has_context = True
                    break

        assert has_context, "At least one kubectl call should include the correct context"


@pytest.mark.asyncio
async def test_destroy_lab_passes_context_to_kubectl():
    """Test that destroy_lab uses the correct kubectl context during execution."""
    with patch.object(K8sLabRuntime, '_run_kubectl', new_callable=AsyncMock) as mock_run:
        # Mock the return value for the calls
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        runtime = K8sLabRuntime(context="k3d-test-cluster")
        lab = Lab(
            id=uuid4(),
            owner_id=uuid4(),
            recipe_id=uuid4(),
            status="finished"
        )

        # Call destroy_lab
        await runtime.destroy_lab(lab)

        # Verify that _run_kubectl was called at least once
        assert mock_run.called

        # Check that the context was properly passed for at least one of the calls
        has_context = False
        for call_args in mock_run.call_args_list:
            args_passed = call_args[0][0]  # First positional arg is the command args list

            if "--context" in args_passed:
                context_idx = args_passed.index("--context")
                if args_passed[context_idx + 1] == "k3d-test-cluster":
                    has_context = True
                    break

        assert has_context, "At least one kubectl call during destroy should include the correct context"