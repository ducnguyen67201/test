"""Unit tests for kubectl context handling in K8s runtime."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.runtime.k8s_runtime import K8sLabRuntime
from app.models.lab import Lab
from app.models.recipe import Recipe


@pytest.mark.asyncio
async def test_kubectl_context_used_in_base_args():
    """Test that kubectl context from settings is included in kubectl commands."""
    # Mock settings to have a context
    with patch('app.runtime.k8s_runtime.settings') as mock_settings:
        mock_settings.kubectl_context = "k3d-test-cluster"
        mock_settings.kubectl_kubeconfig_path = None
        
        runtime = K8sLabRuntime()
        args = runtime._kubectl_base_args()
        
        assert "--context" in args
        context_idx = args.index("--context")
        assert args[context_idx + 1] == "k3d-test-cluster"


@pytest.mark.asyncio
async def test_kubectl_context_priority():
    """Test that runtime context takes priority over settings context."""
    with patch('app.runtime.k8s_runtime.settings') as mock_settings:
        mock_settings.kubectl_context = "settings-context"
        mock_settings.kubectl_kubeconfig_path = None
        
        runtime = K8sLabRuntime(context="runtime-context")
        args = runtime._kubectl_base_args()
        
        assert "--context" in args
        context_idx = args.index("--context")
        assert args[context_idx + 1] == "runtime-context"  # Runtime context should take priority


@pytest.mark.asyncio
async def test_run_kubectl_includes_context():
    """Test that _run_kubectl includes the configured context in the command."""
    with patch('app.runtime.k8s_runtime.subprocess.run') as mock_run:
        # Mock successful completion
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "nodes found"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        with patch('app.runtime.k8s_runtime.settings') as mock_settings:
            mock_settings.kubectl_context = "k3d-test-cluster"
            mock_settings.kubectl_request_timeout_seconds = 10
            
            runtime = K8sLabRuntime()
            await runtime._run_kubectl(["get", "nodes"], timeout_s=15)
        
        # Verify subprocess.run was called with correct arguments
        mock_run.assert_called_once()
        call_args, call_kwargs = mock_run.call_args
        
        # Check that the command includes the context
        cmd = call_args[0]  # First positional argument is the command list
        assert "--context" in cmd
        context_idx = cmd.index("--context")
        assert cmd[context_idx + 1] == "k3d-test-cluster"
        
        # Check timeout was passed correctly
        assert call_kwargs["timeout"] == 15  # The explicit timeout should override settings


@pytest.mark.asyncio
async def test_run_kubectl_uses_settings_timeout():
    """Test that _run_kubectl falls back to settings timeout when not provided."""
    with patch('app.runtime.k8s_runtime.subprocess.run') as mock_run:
        # Mock successful completion
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "success"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        with patch('app.runtime.k8s_runtime.settings') as mock_settings:
            mock_settings.kubectl_context = "k3d-test-cluster"
            mock_settings.kubectl_request_timeout_seconds = 8  # Settings default
            
            runtime = K8sLabRuntime()
            # Don't provide explicit timeout, should use settings
            await runtime._run_kubectl(["get", "pods"])
        
        # Verify subprocess.run was called with settings timeout
        mock_run.assert_called_once()
        _, call_kwargs = mock_run.call_args
        
        # Check timeout was set to the settings default
        assert call_kwargs["timeout"] == 8


@pytest.mark.asyncio
async def test_run_kubectl_sanitizes_errors_with_context():
    """Test that error messages from _run_kubectl are sanitized and don't leak secrets."""
    from subprocess import CalledProcessError
    
    with patch('app.runtime.k8s_runtime.subprocess.run') as mock_run:
        # Create a CalledProcessError with sensitive data in stderr
        error = CalledProcessError(
            returncode=1,
            cmd=["kubectl", "--context", "k3d-test-cluster", "--kubeconfig", "/secret/path/config", "get", "pods"],
            output="some output",
            stderr="Unauthorized: Bearer token=abc123def456ghi789"
        )
        mock_run.side_effect = error
        
        with patch('app.runtime.k8s_runtime.settings') as mock_settings:
            mock_settings.kubectl_context = "k3d-test-cluster"
            mock_settings.kubectl_request_timeout_seconds = 5
            
            runtime = K8sLabRuntime()
            
            with pytest.raises(RuntimeError) as exc_info:
                await runtime._run_kubectl(["get", "pods"])
        
        error_message = str(exc_info.value)
        
        # Verify sensitive data is not in the error message
        assert "abc123def456ghi789" not in error_message
        assert "/secret/path/config" not in error_message
        
        # Verify the command was redacted but still shows kubectl
        assert "kubectl" in error_message
        assert "failed" in error_message.lower()


def test_kubectl_base_args_with_kubeconfig():
    """Test that base args include kubeconfig when configured."""
    with patch('app.runtime.k8s_runtime.settings') as mock_settings:
        mock_settings.kubectl_kubeconfig_path = "/path/to/kubeconfig.yaml"
        mock_settings.kubectl_context = "k3d-test-context"
        
        runtime = K8sLabRuntime(kubeconfig_path="/runtime/kubeconfig.yaml")
        args = runtime._kubectl_base_args()
        
        # Runtime kubeconfig should take priority
        assert "--kubeconfig" in args
        kubeconfig_idx = args.index("--kubeconfig")
        assert args[kubeconfig_idx + 1] == "/runtime/kubeconfig.yaml"
        
        # Context should also be included
        assert "--context" in args
        context_idx = args.index("--context")
        assert args[context_idx + 1] == "k3d-test-context"


def test_kubectl_base_args_with_namespace():
    """Test that base args include namespace when provided."""
    with patch('app.runtime.k8s_runtime.settings') as mock_settings:
        mock_settings.kubectl_context = "k3d-test-cluster"
        mock_settings.kubectl_kubeconfig_path = None
        
        runtime = K8sLabRuntime()
        args = runtime._kubectl_base_args(namespace="test-namespace")
        
        assert "-n" in args
        namespace_idx = args.index("-n")
        assert args[namespace_idx + 1] == "test-namespace"
        
        assert "--context" in args
        context_idx = args.index("--context")
        assert args[context_idx + 1] == "k3d-test-cluster"


@pytest.mark.asyncio
async def test_preflight_check_uses_context():
    """Test that preflight checks use the configured context."""
    with patch('app.runtime.k8s_runtime.subprocess.run') as mock_run:
        # Mock successful version check
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        
        with patch('app.runtime.k8s_runtime.settings') as mock_settings:
            mock_settings.kubectl_context = "k3d-test-cluster"
            mock_settings.kubectl_request_timeout_seconds = 5
            
            runtime = K8sLabRuntime()
            try:
                await runtime._run_kubectl(["version", "--short"])
            except:
                pass  # Ignore return value, just test command construction
        
        mock_run.assert_called_once()
        call_args, _ = mock_run.call_args
        cmd = call_args[0]
        
        # Should include context in the version command
        assert "kubectl" in cmd
        assert "--context" in cmd
        context_idx = cmd.index("--context")
        assert cmd[context_idx + 1] == "k3d-test-cluster"