"""Tests for XFCE VNC startup configuration.

Verifies that:
1. xstartup.template calls octobox-xstartup launcher
2. octobox-xstartup includes proper environment setup
3. DBus session bus is started for XFCE
4. XDG_RUNTIME_DIR is created
5. Fallback behavior is defined
"""

import os
import pytest
from pathlib import Path


# Path to the hackvm directory relative to backend tests
HACKVM_DIR = Path(__file__).parent.parent.parent / "octolab-hackvm"


def test_dockerfile_creates_xfce_launcher():
    """Test that Dockerfile creates /usr/local/bin/octobox-xstartup."""
    dockerfile_path = HACKVM_DIR / "Dockerfile"
    if not dockerfile_path.exists():
        pytest.skip(f"Dockerfile not found at {dockerfile_path}")

    content = dockerfile_path.read_text()

    # Verify octobox-xstartup is created
    assert "octobox-xstartup" in content
    assert "/usr/local/bin/octobox-xstartup" in content

    # Verify it includes required components
    assert "xfce4-session" in content or "startxfce4" in content
    assert "dbus-launch" in content
    assert "XDG_RUNTIME_DIR" in content


def test_dockerfile_creates_xstartup_template():
    """Test that Dockerfile creates xstartup.template that calls octobox-xstartup."""
    dockerfile_path = HACKVM_DIR / "Dockerfile"
    if not dockerfile_path.exists():
        pytest.skip(f"Dockerfile not found at {dockerfile_path}")

    content = dockerfile_path.read_text()

    # Verify xstartup.template is created
    assert "/etc/octobox/xstartup.template" in content

    # Verify template calls the launcher
    assert "exec /usr/local/bin/octobox-xstartup" in content


def test_startup_sh_verifies_xstartup():
    """Test that startup.sh verifies xstartup contains octobox-xstartup."""
    startup_path = HACKVM_DIR / "startup.sh"
    if not startup_path.exists():
        pytest.skip(f"startup.sh not found at {startup_path}")

    content = startup_path.read_text()

    # Verify startup.sh checks for octobox-xstartup in xstartup
    assert 'grep -q "octobox-xstartup"' in content


def test_startup_sh_has_diagnostic_dump():
    """Test that startup.sh includes diagnostic dump function."""
    startup_path = HACKVM_DIR / "startup.sh"
    if not startup_path.exists():
        pytest.skip(f"startup.sh not found at {startup_path}")

    content = startup_path.read_text()

    # Verify diagnostic dump function exists
    assert "dump_diagnostics()" in content or "dump_diagnostics" in content

    # Verify it captures VNC logs
    assert ".vnc/" in content and "log" in content.lower()


def test_startup_sh_detects_early_exit():
    """Test that startup.sh detects 'xstartup exited too early' error."""
    startup_path = HACKVM_DIR / "startup.sh"
    if not startup_path.exists():
        pytest.skip(f"startup.sh not found at {startup_path}")

    content = startup_path.read_text()

    # Verify early exit detection
    assert "exited too early" in content


def test_compose_healthcheck_defers_to_dockerfile():
    """Test that docker-compose.yml defers to Dockerfile healthcheck."""
    compose_path = HACKVM_DIR / "docker-compose.yml"
    if not compose_path.exists():
        pytest.skip(f"docker-compose.yml not found at {compose_path}")

    content = compose_path.read_text()

    # Verify compose does NOT override Dockerfile healthcheck
    # The Dockerfile has the correct healthcheck (checks VNC 5900)
    assert "healthcheck:" not in content or "# Note: Healthcheck is defined in Dockerfile" in content
    # Verify VNC_LOCALHOST=0 is set for network accessibility
    assert "VNC_LOCALHOST=0" in content


def test_dockerfile_has_required_xfce_packages():
    """Test that Dockerfile installs required XFCE packages."""
    dockerfile_path = HACKVM_DIR / "Dockerfile"
    if not dockerfile_path.exists():
        pytest.skip(f"Dockerfile not found at {dockerfile_path}")

    content = dockerfile_path.read_text()

    # Required packages for stable XFCE session
    required_packages = [
        "xfce4",
        "xfce4-session",
        "xfce4-terminal",
        "dbus-x11",
        "policykit-1",
    ]

    for package in required_packages:
        assert package in content, f"Missing required package: {package}"


def test_dockerfile_has_build_time_checks():
    """Test that Dockerfile has build-time sanity checks for XFCE."""
    dockerfile_path = HACKVM_DIR / "Dockerfile"
    if not dockerfile_path.exists():
        pytest.skip(f"Dockerfile not found at {dockerfile_path}")

    content = dockerfile_path.read_text()

    # Verify build-time checks for critical commands
    assert "command -v" in content
    assert "startxfce4" in content or "xfce4-session" in content
    assert "dbus-launch" in content


def test_xfce_launcher_sets_xdg_runtime_dir():
    """Test that octobox-xstartup creates XDG_RUNTIME_DIR."""
    dockerfile_path = HACKVM_DIR / "Dockerfile"
    if not dockerfile_path.exists():
        pytest.skip(f"Dockerfile not found at {dockerfile_path}")

    content = dockerfile_path.read_text()

    # Verify XDG_RUNTIME_DIR is set and created
    assert 'XDG_RUNTIME_DIR="/tmp/xdg-' in content
    assert "mkdir -p" in content and "XDG_RUNTIME_DIR" in content
    assert "chmod 700" in content


def test_xfce_launcher_unsets_session_manager():
    """Test that octobox-xstartup unsets SESSION_MANAGER to prevent conflicts."""
    dockerfile_path = HACKVM_DIR / "Dockerfile"
    if not dockerfile_path.exists():
        pytest.skip(f"Dockerfile not found at {dockerfile_path}")

    content = dockerfile_path.read_text()

    # Verify SESSION_MANAGER is unset
    assert "unset SESSION_MANAGER" in content


def test_xfce_launcher_starts_dbus():
    """Test that octobox-xstartup starts DBus session bus."""
    dockerfile_path = HACKVM_DIR / "Dockerfile"
    if not dockerfile_path.exists():
        pytest.skip(f"Dockerfile not found at {dockerfile_path}")

    content = dockerfile_path.read_text()

    # Verify DBus is started
    assert "dbus-launch" in content
    assert "DBUS_SESSION_BUS_ADDRESS" in content


def test_xfce_launcher_execs_session():
    """Test that octobox-xstartup uses exec for xfce4-session."""
    dockerfile_path = HACKVM_DIR / "Dockerfile"
    if not dockerfile_path.exists():
        pytest.skip(f"Dockerfile not found at {dockerfile_path}")

    content = dockerfile_path.read_text()

    # Verify exec is used (keeps session as PID 1 for proper signal handling)
    assert "exec xfce4-session" in content
