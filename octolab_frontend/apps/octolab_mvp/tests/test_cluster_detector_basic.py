"""Unit tests for cluster detection logic."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from app.helpers.cluster_detector import detect_cluster_type, is_wsl_mount_issue_present, check_apiserver_readiness


def test_detect_cluster_type_unknown_when_no_context():
    """Test that detection returns unknown when kubectl config fails."""
    with patch("subprocess.run") as mock_run:
        # Mock current-context command to fail
        mock_context_result = MagicMock()
        mock_context_result.returncode = 1
        mock_context_result.stderr = "context not set"
        
        def side_effect_func(args, **kwargs):
            if "current-context" in args:
                return mock_context_result
            else:
                # For any other command, return a generic success
                mock_result = MagicMock()
                mock_result.returncode = 0
                mock_result.stdout = ""
                return mock_result
        
        mock_run.side_effect = side_effect_func
        
        context, server_url, cluster_type = detect_cluster_type()
        
        assert context == ""
        assert server_url == ""
        assert cluster_type == "unknown"


def test_is_wsl_mount_issue_present_false_when_no_proc_mounts():
    """Test that mount issue detection returns False when /proc/mounts doesn't exist."""
    with patch("os.path.exists", return_value=False):
        result = is_wsl_mount_issue_present()
        assert result is False


@patch("builtins.open", autospec=True)
def test_is_wsl_mount_issue_present_false_with_regular_mounts(mock_open_func):
    """Test that mount issue detection returns False with regular mounts."""
    mock_mounts_content = """proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0
    /dev/sda1 / ext4 rw,relatime 0 0
    tmpfs /tmp tmpfs rw 0 0
    """
    
    mock_file = MagicMock()
    mock_file.read.return_value = mock_mounts_content
    mock_open_func.return_value.__enter__.return_value = mock_file
    
    with patch("os.path.exists", return_value=True):
        result = is_wsl_mount_issue_present()
        assert result is False


def test_is_docker_available_when_docker_works():
    """Test that docker availability check works when docker is available."""
    from app.helpers.cluster_detector import is_docker_available
    
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Client: Docker Engine\n Server: Docker Engine"
        mock_run.return_value = mock_result
        
        result = is_docker_available()
        assert result is True


def test_is_docker_available_when_docker_fails():
    """Test that docker availability check returns False when docker fails."""
    from app.helpers.cluster_detector import is_docker_available
    
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_run.return_value = mock_result
        
        result = is_docker_available()
        assert result is False


if __name__ == "__main__":
    pytest.main([__file__])