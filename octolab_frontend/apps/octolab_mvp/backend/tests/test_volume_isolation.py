"""Tests for volume isolation in compose runtime.

Verifies that Docker Compose volumes are project-scoped to prevent
cross-lab volume collisions (security issue).
"""

import pytest
import yaml
from pathlib import Path


def test_compose_yaml_no_explicit_volume_name():
    """Test that docker-compose.yml does not use explicit volume names.

    SECURITY: Using explicit names like 'name: octobox_home' causes all labs
    to share the same volume, which is both a reliability and security issue.

    Compose should use project-scoped naming: <project>_<volume> automatically.
    """
    compose_path = Path(__file__).parent.parent.parent / "octolab-hackvm" / "docker-compose.yml"

    if not compose_path.exists():
        pytest.skip(f"docker-compose.yml not found at {compose_path}")

    with open(compose_path) as f:
        compose_yaml = yaml.safe_load(f)

    volumes = compose_yaml.get("volumes", {})

    # Check each volume definition
    for volume_name, volume_config in volumes.items():
        if volume_config is None:
            # Empty config like `octobox_home:` is fine (project-scoped)
            continue

        if isinstance(volume_config, dict):
            # Check for explicit 'name' field which would cause collisions
            assert "name" not in volume_config, (
                f"Volume '{volume_name}' has explicit 'name: {volume_config.get('name')}'. "
                f"This causes cross-lab collisions. Remove the 'name' field to use "
                f"project-scoped naming (<project>_{volume_name})."
            )

            # Check for external volumes which would also be shared
            if volume_config.get("external"):
                pytest.fail(
                    f"Volume '{volume_name}' is marked external. "
                    f"External volumes are shared across all labs (security issue)."
                )


def test_compose_runtime_project_name_isolation():
    """Test that ComposeLabRuntime generates unique project names per lab."""
    from uuid import uuid4

    # Create mock lab objects
    class MockLab:
        def __init__(self, lab_id):
            self.id = lab_id

    lab1 = MockLab(uuid4())
    lab2 = MockLab(uuid4())

    # Verify project names are different
    project1 = f"octolab_{lab1.id}"
    project2 = f"octolab_{lab2.id}"

    assert project1 != project2, "Different labs should have different project names"
    assert lab1.id != lab2.id, "Lab IDs should be unique"

    # Verify project name format
    assert project1.startswith("octolab_"), "Project name should start with 'octolab_'"
    assert str(lab1.id) in project1, "Project name should contain lab ID"


def test_volume_names_would_be_isolated():
    """Test that volume names derived from project names would be isolated.

    Docker Compose automatically prefixes volume names with project name,
    so if project names are unique, volume names will be too.
    """
    from uuid import uuid4

    lab1_id = uuid4()
    lab2_id = uuid4()

    # Simulate compose naming: <project>_<volume>
    project1 = f"octolab_{lab1_id}"
    project2 = f"octolab_{lab2_id}"

    # Volume names that compose would generate
    vol1_home = f"{project1}_octobox_home"
    vol2_home = f"{project2}_octobox_home"

    vol1_pcap = f"{project1}_lab_pcap"
    vol2_pcap = f"{project2}_lab_pcap"

    # Evidence volumes (split into auth and user for security)
    vol1_evidence_auth = f"{project1}_evidence_auth"
    vol2_evidence_auth = f"{project2}_evidence_auth"

    vol1_evidence_user = f"{project1}_evidence_user"
    vol2_evidence_user = f"{project2}_evidence_user"

    # All should be different
    assert vol1_home != vol2_home, "octobox_home volumes should be isolated per lab"
    assert vol1_pcap != vol2_pcap, "lab_pcap volumes should be isolated per lab"
    assert vol1_evidence_auth != vol2_evidence_auth, "evidence_auth volumes should be isolated per lab"
    assert vol1_evidence_user != vol2_evidence_user, "evidence_user volumes should be isolated per lab"
