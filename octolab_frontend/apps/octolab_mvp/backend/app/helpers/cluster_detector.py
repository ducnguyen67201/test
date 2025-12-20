"""Helper functions for detecting cluster type and kubectl context."""

import subprocess
import logging
import re
from pathlib import Path
from typing import Optional, Tuple
import os

logger = logging.getLogger(__name__)


def detect_cluster_type() -> Tuple[str, str, str]:
    """
    Detect the current kubectl cluster type.
    
    Returns a tuple of (context, server_url, cluster_type) where:
    - context: current kubectl context name
    - server_url: server URL from current context
    - cluster_type: one of 'k3d', 'k3s-local', or 'unknown'
    """
    try:
        # Get current context
        result = subprocess.run(
            ["kubectl", "config", "current-context"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning(f"Could not get current kubectl context: {result.stderr}")
            return "", "", "unknown"
        
        context = result.stdout.strip()
        
        # Get server URL for current context
        result = subprocess.run(
            ["kubectl", "config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning(f"Could not get server URL for context {context}: {result.stderr}")
            return context, "", "unknown"
        
        server_url = result.stdout.strip()
        
        # Determine cluster type heuristically
        cluster_type = "unknown"
        
        # Check for k3d patterns in context or server
        if context.startswith("k3d-") or "host.k3d.internal" in server_url or "0.0.0.0:" in server_url:
            cluster_type = "k3d"
        # Check for k3s local patterns
        elif server_url == "https://127.0.0.1:6443" and Path("/etc/rancher/k3s/k3s.yaml").exists():
            cluster_type = "k3s-local"
        
        return context, server_url, cluster_type
        
    except subprocess.TimeoutExpired:
        logger.warning("kubectl command timed out")
        return "", "", "unknown"
    except Exception as e:
        logger.warning(f"Error detecting cluster type: {e}")
        return "", "", "unknown"


def is_wsl_mount_issue_present() -> bool:
    """
    Check if current system has the problematic Docker Desktop WSL mount that can cause k3s/kubelet to crash.

    Reads /proc/mounts and looks for specific patterns indicating Docker Desktop WSL integration
    that can interfere with k3s/kubelet operations.
    """
    if not os.path.exists("/proc/mounts"):
        return False

    try:
        with open("/proc/mounts", "r") as f:
            mounts_content = f.read()

        # Look for Docker Desktop mount lines that indicate the problematic setup
        for line in mounts_content.splitlines():
            # Check if the line contains typical Docker Desktop patterns that can interfere with k3s
            if "C:\\\\Program Files\\\\Docker\\\\Docker\\\\resources\\\\ext\\\\" in line:
                # This indicates Docker Desktop mounting Windows paths that can interfere with k3s
                return True

        # Check for other common Docker Desktop WSL mount patterns that might interfere
        for line in mounts_content.splitlines():
            if "overlay" in line and "/mnt/wsl" in line:
                # Docker Desktop WSL integration creates overlay mounts that can conflict
                # with k3s's overlayfs usage, leading to kubelet crashes
                parts = line.split()
                # Check if this is a Docker Desktop related overlay mount
                if len(parts) > 3 and parts[2] == "overlay":
                    # Get the mount options to check for conflict indicators
                    if len(parts) > 3:
                        options = parts[3]
                        if "upperdir=" in options and "workdir=" in options and "lowerdir=" in options:
                            # This is a layered overlay mount that can conflict with k3s/kubelet
                            return True

        return False
    except Exception as e:
        logger.warning(f"Error checking WSL mount issue: {e}")
        return False


def is_docker_available() -> bool:
    """Check if Docker is available."""
    try:
        result = subprocess.run(
            ["docker", "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def check_apiserver_readiness() -> Tuple[bool, str]:
    """
    Check if apiserver is ready by calling /readyz endpoint.
    Returns (is_ready, message) with actionable information.
    """
    try:
        # Get cluster info first
        context, server_url, cluster_type = detect_cluster_type()
        
        result = subprocess.run(
            ["kubectl", "get", "--raw", "/readyz"],
            capture_output=True,
            text=True,
            timeout=5,  # Tight timeout for readiness check
        )
        
        is_ready = result.returncode == 0
        message = f"API server not ready (detected: {cluster_type}"
        if context:
            message += f", context: {context}"
        message += ")."
        
        if result.returncode == 0:
            message = f"API server ready (detected: {cluster_type})"
        
        return is_ready, message
        
    except subprocess.TimeoutExpired:
        context, server_url, cluster_type = detect_cluster_type()
        return False, f"API server check timed out (detected: {cluster_type})."
    except Exception as e:
        context, server_url, cluster_type = detect_cluster_type()
        return False, f"API server unreachable (detected: {cluster_type}): {type(e).__name__}"