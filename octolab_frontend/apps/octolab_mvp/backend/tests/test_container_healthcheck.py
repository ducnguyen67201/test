"""Tests for Docker container healthcheck integration.

Verifies that:
1. Healthcheck format in docker-compose.yml is correct
2. Container naming convention is documented
3. Health status values are as expected

Note: Full runtime tests require app imports which need the database.
These tests focus on the file-based configuration validation.
"""

import pytest
from pathlib import Path
from uuid import uuid4


# Path references used by the tests
REPO_ROOT = Path(__file__).resolve().parents[2]
HACKVM_DIR = REPO_ROOT / "octolab-hackvm"
DOCKERFILE_PATH = REPO_ROOT / "images/octobox-beta" / "Dockerfile"
HEALTHCHECK_SCRIPT_PATH = REPO_ROOT / "images/octobox-beta/rootfs/usr/local/bin/octobox-healthcheck"


def test_dockerfile_healthcheck_block():
    """Ensure the Dockerfile defines the octobox-healthcheck script."""
    if not DOCKERFILE_PATH.exists():
        pytest.skip(f"Dockerfile not found at {DOCKERFILE_PATH}")

    content = DOCKERFILE_PATH.read_text()
    assert "HEALTHCHECK" in content
    assert "/usr/local/bin/octobox-healthcheck" in content
    assert "--interval=5s" in content
    assert "--timeout=2s" in content


def test_healthcheck_script_verifies_vnc_port():
    """Healthcheck script must verify VNC port and Xtigervnc process."""
    if not HEALTHCHECK_SCRIPT_PATH.exists():
        pytest.skip(f"Healthcheck script not found at {HEALTHCHECK_SCRIPT_PATH}")

    content = HEALTHCHECK_SCRIPT_PATH.read_text()
    assert "VNC_RFBPORT" in content
    assert "nc -z" in content or "socket" in content  # connectivity probe present
    assert "Xtigervnc" in content


def test_container_naming_convention():
    """Test that container name follows compose v2 convention."""
    lab_id = uuid4()
    project_name = f"octolab_{lab_id}"
    expected_container_name = f"{project_name}-octobox-1"

    # Verify format: <project>-<service>-<instance>
    # Project name: octolab_{uuid}
    # Container name: {project}-{service}-{instance}
    assert expected_container_name.startswith("octolab_")
    assert str(lab_id) in expected_container_name
    assert "-octobox-" in expected_container_name
    assert expected_container_name.endswith("-1")


def test_compose_sets_vnc_localhost_zero():
    """Compose template must bind VNC to 0.0.0.0 inside the lab network."""
    compose_path = HACKVM_DIR / "docker-compose.yml"
    if not compose_path.exists():
        pytest.skip(f"docker-compose.yml not found at {compose_path}")

    content = compose_path.read_text()
    assert "VNC_LOCALHOST=0" in content
    assert "${COMPOSE_BIND_HOST:-127.0.0.1}:${NOVNC_HOST_PORT" in content  # still host-only for noVNC


def test_health_status_values():
    """Document the expected Docker health status values."""
    # These are the possible values from docker inspect
    valid_health_statuses = ["starting", "healthy", "unhealthy", "none"]

    # "starting" = container is starting, healthcheck not yet passed
    assert "starting" in valid_health_statuses

    # "healthy" = healthcheck passed
    assert "healthy" in valid_health_statuses

    # "unhealthy" = healthcheck failed
    assert "unhealthy" in valid_health_statuses

    # "none" = no healthcheck defined
    assert "none" in valid_health_statuses
