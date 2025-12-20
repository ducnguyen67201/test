"""Unit tests for cluster detection logic."""

import pytest
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path

from app.helpers.cluster_detector import detect_cluster_type, is_wsl_mount_issue_present, check_apiserver_readiness


def test_detect_cluster_type_k3d():
    """Test detection of k3d cluster type."""
    with patch("subprocess.run") as mock_run:
        # Mock successful kubectl config current-context response
        mock_context_result = MagicMock()
        mock_context_result.returncode = 0
        mock_context_result.stdout = "k3d-myserver\n"

        # Mock successful kubectl config view response with jsonpath
        mock_view_result = MagicMock()
        mock_view_result.returncode = 0
        mock_view_result.stdout = "https://host.k3d.internal:6443"

        def side_effect(command, **kwargs):
            # command is a list, so check for specific elements
            if "current-context" in command:
                return mock_context_result
            elif "--minify" in command and any("jsonpath" in element for element in command):
                return mock_view_result
            else:
                # Default return
                result = MagicMock()
                result.returncode = 0
                return result

        mock_run.side_effect = side_effect

        context, server_url, cluster_type = detect_cluster_type()

        assert context == "k3d-myserver"
        assert server_url == "https://host.k3d.internal:6443"
        assert cluster_type == "k3d"


def test_detect_cluster_type_k3s_local():
    """Test detection of k3s local cluster type."""
    with patch("subprocess.run") as mock_run, \
         patch("pathlib.Path.exists") as mock_exists:
        # Mock successful kubectl config current-context response
        mock_context_result = MagicMock()
        mock_context_result.returncode = 0
        mock_context_result.stdout = "default\n"
        
        # Mock successful kubectl config view response
        mock_view_result = MagicMock()
        mock_view_result.returncode = 0
        mock_view_result.stdout = "https://127.0.0.1:6443"
        
        def side_effect(args, **kwargs):
            if "current-context" in args:
                return mock_context_result
            elif "jsonpath" in args:
                return mock_view_result
            else:
                # Default return
                result = MagicMock()
                result.returncode = 0
                return result
        
        mock_run.side_effect = side_effect
        mock_exists.return_value = True  # /etc/rancher/k3s/k3s.yaml exists
        
        context, server_url, cluster_type = detect_cluster_type()
        
        assert context == "default"
        assert server_url == "https://127.0.0.1:6443"
        assert cluster_type == "k3s-local"


def test_detect_cluster_type_unknown():
    """Test detection of unknown cluster type."""
    with patch("subprocess.run") as mock_run:
        # Mock unsuccessful kubectl config current-context response
        mock_context_result = MagicMock()
        mock_context_result.returncode = 1
        mock_context_result.stderr = "error: current-context is not set"
        
        # Also mock the second call to trigger the error path
        def side_effect(args, **kwargs):
            return mock_context_result
        
        mock_run.side_effect = side_effect
        
        context, server_url, cluster_type = detect_cluster_type()
        
        assert context == ""
        assert server_url == ""
        assert cluster_type == "unknown"


def test_is_wsl_mount_issue_present_true():
    """Test detection of WSL mount issue when present."""
    # Create a mock mount file content that includes the problematic pattern
    mock_mounts_content = """
/dev/sda1 / ext4 rw,relatime 0 0
C:\\\\\\\\Program Files\\\\\\\\Docker\\\\\\\\Docker\\\\\\\\resources\\\\\\\\ext\\\\\\\\ /mnt/wsl/docker-desktop/ext4 upperdir=/dev/sda1,workdir=/dev/sda2 overlay rw 0 0
tmpfs /tmp tmpfs rw 0 0
"""
    
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=mock_mounts_content)):
        result = is_wsl_mount_issue_present()
        assert result is True


def test_is_wsl_mount_issue_present_overlay():
    """Test detection of WSL mount issue based on overlay pattern."""
    # Create a mock mount file content that includes the overlay pattern
    mock_mounts_content = """
/dev/sda1 / ext4 rw,relatime 0 0
overlay /mnt/wsl/distro /dev/sda2 ext4 rw,upperdir=/path/to/upper,workdir=/path/to/work lowerdir=/path/to/lower overlay rw 0 0
tmpfs /tmp tmpfs rw 0 0
"""
    
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=mock_mounts_content)):
        result = is_wsl_mount_issue_present()
        assert result is True


def test_is_wsl_mount_issue_present_false():
    """Test that WSL mount issue detection returns False when not present."""
    mock_mounts_content = """
/dev/sda1 / ext4 rw,relatime 0 0
tmpfs /tmp tmpfs rw 0 0
"""
    
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=mock_mounts_content)):
        result = is_wsl_mount_issue_present()
        assert result is False


def test_check_apiserver_readiness():
    """Test API server readiness check."""
    with patch("subprocess.run") as mock_run:
        # Mock successful kubectl get --raw /readyz response
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ok"
        
        def side_effect(args, **kwargs):
            if "get" in args and "readyz" in args:
                return mock_result
            else:
                # Mock kubectl config commands
                mock_config = MagicMock()
                mock_config.returncode = 0
                if "current-context" in args:
                    mock_config.stdout = "default\n"
                elif "jsonpath" in args:
                    mock_config.stdout = "https://127.0.0.1:6443"
                return mock_config
        
        mock_run.side_effect = side_effect
        
        is_ready, message = check_apiserver_readiness()
        
        assert is_ready is True
        assert "API server ready" in message
        assert "k3s-local" in message


def test_check_apiserver_readiness_fails():
    """Test API server readiness check when it fails."""
    with patch("subprocess.run") as mock_run:
        # Mock unsuccessful kubectl get --raw /readyz response
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "connection refused"
        
        def side_effect(args, **kwargs):
            if "get" in args and "readyz" in args:
                return mock_result
            else:
                # Mock kubectl config commands
                mock_config = MagicMock()
                mock_config.returncode = 0
                if "current-context" in args:
                    mock_config.stdout = "default\n"
                elif "jsonpath" in args:
                    mock_config.stdout = "https://127.0.0.1:6443"
                return mock_config
        
        mock_run.side_effect = side_effect
        
        is_ready, message = check_apiserver_readiness()
        
        assert is_ready is False
        assert "API server not ready" in message
        assert "k3s-local" in message


if __name__ == "__main__":
    pytest.main([__file__])