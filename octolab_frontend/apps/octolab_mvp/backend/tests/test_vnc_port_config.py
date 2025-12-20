"""Tests for VNC port configuration consistency.

Verifies that:
1. OCTOBOX_VNC_PORT constant is 5900 (DISPLAY :0)
2. start-vnc-session.sh defaults to port 5900
3. docker-compose.yml healthcheck uses port 5900
4. VNC_LOCALHOST=0 is set in compose for network accessibility
"""

import re
from pathlib import Path

import pytest

# Path to the hackvm directory relative to backend tests
HACKVM_DIR = Path(__file__).parent.parent.parent / "octolab-hackvm"
IMAGES_DIR = Path(__file__).parent.parent.parent / "images" / "octobox-beta"

# Mark entire module as not requiring database
pytestmark = pytest.mark.no_db


class TestVncPortConstant:
    """Tests for VNC port constants across modules."""

    def test_vnc_internal_port_is_5900(self):
        """VNC_INTERNAL_PORT must be 5900 (single source of truth)."""
        from app.services.docker_net import VNC_INTERNAL_PORT

        assert VNC_INTERNAL_PORT == 5900, (
            f"VNC_INTERNAL_PORT is {VNC_INTERNAL_PORT}, expected 5900. "
            "VNC DISPLAY :0 maps to port 5900 (5900 + display number)."
        )

    def test_octobox_vnc_port_uses_internal_port(self):
        """OCTOBOX_VNC_PORT must reference VNC_INTERNAL_PORT."""
        from app.services.guacamole_provisioner import OCTOBOX_VNC_PORT
        from app.services.docker_net import VNC_INTERNAL_PORT

        assert OCTOBOX_VNC_PORT == VNC_INTERNAL_PORT, (
            f"OCTOBOX_VNC_PORT ({OCTOBOX_VNC_PORT}) must equal "
            f"VNC_INTERNAL_PORT ({VNC_INTERNAL_PORT}) for consistency."
        )

    def test_preflight_netcheck_default_port_is_5900(self):
        """preflight_netcheck must default to port 5900."""
        import inspect
        from app.services.docker_net import preflight_netcheck

        sig = inspect.signature(preflight_netcheck)
        vnc_port_default = sig.parameters["vnc_port"].default

        assert vnc_port_default == 5900, (
            f"preflight_netcheck vnc_port default is {vnc_port_default}, expected 5900."
        )


class TestStartVncSessionScript:
    """Tests for start-vnc-session.sh VNC configuration."""

    def test_vnc_rfbport_defaults_to_5900(self):
        """start-vnc-session.sh must default VNC_RFBPORT to 5900."""
        script_path = IMAGES_DIR / "rootfs" / "usr" / "local" / "bin" / "start-vnc-session.sh"
        if not script_path.exists():
            pytest.skip(f"start-vnc-session.sh not found at {script_path}")

        content = script_path.read_text()

        # Should have VNC_RFBPORT default to 5900
        assert 'VNC_RFBPORT="${VNC_RFBPORT:-5900}"' in content, (
            "start-vnc-session.sh should default VNC_RFBPORT to 5900"
        )

    def test_vnc_display_defaults_to_zero(self):
        """start-vnc-session.sh must default VNC_DISPLAY to :0."""
        script_path = IMAGES_DIR / "rootfs" / "usr" / "local" / "bin" / "start-vnc-session.sh"
        if not script_path.exists():
            pytest.skip(f"start-vnc-session.sh not found at {script_path}")

        content = script_path.read_text()

        # Should have VNC_DISPLAY default to :0
        assert 'VNC_DISPLAY="${VNC_DISPLAY:-:0}"' in content, (
            "start-vnc-session.sh should default VNC_DISPLAY to :0"
        )

    def test_vnc_port_export_is_5900(self):
        """start-vnc-session.sh must export VNC_PORT=5900."""
        script_path = IMAGES_DIR / "rootfs" / "usr" / "local" / "bin" / "start-vnc-session.sh"
        if not script_path.exists():
            pytest.skip(f"start-vnc-session.sh not found at {script_path}")

        content = script_path.read_text()

        # Should export VNC_PORT=5900
        assert "export VNC_PORT=5900" in content, (
            "start-vnc-session.sh should export VNC_PORT=5900"
        )


class TestComposeVncConfig:
    """Tests for docker-compose.yml VNC configuration."""

    def test_vnc_localhost_zero_for_network_access(self):
        """docker-compose.yml must set VNC_LOCALHOST=0 for guacd access."""
        compose_path = HACKVM_DIR / "docker-compose.yml"
        if not compose_path.exists():
            pytest.skip(f"docker-compose.yml not found at {compose_path}")

        content = compose_path.read_text()

        # VNC_LOCALHOST=0 enables binding to 0.0.0.0 for network access
        assert "VNC_LOCALHOST=0" in content, (
            "docker-compose.yml must set VNC_LOCALHOST=0 so guacd can reach VNC. "
            "VNC_LOCALHOST=1 would bind only to localhost, making guacd unable to connect."
        )

    def test_healthcheck_uses_port_5900(self):
        """Dockerfile healthcheck must check VNC port 5900."""
        # Healthcheck is defined in Dockerfile, not docker-compose.yml
        dockerfile_path = IMAGES_DIR / "Dockerfile"
        if not dockerfile_path.exists():
            pytest.skip(f"Dockerfile not found at {dockerfile_path}")

        content = dockerfile_path.read_text()

        # Dockerfile should have HEALTHCHECK
        assert "HEALTHCHECK" in content, "Dockerfile should have HEALTHCHECK"

        # Healthcheck script should use port 5900
        healthcheck_script = IMAGES_DIR / "rootfs" / "usr" / "local" / "bin" / "octobox-healthcheck"
        if healthcheck_script.exists():
            script_content = healthcheck_script.read_text()
            assert "5900" in script_content, "healthcheck script should default to port 5900"


class TestPortConsistency:
    """Cross-component port consistency tests."""

    def test_all_vnc_ports_are_5900(self):
        """All VNC port references must be 5900 for consistency."""
        from app.services.guacamole_provisioner import OCTOBOX_VNC_PORT

        # Guacamole provisioner constant
        assert OCTOBOX_VNC_PORT == 5900

        # start-vnc-session.sh default
        script_path = IMAGES_DIR / "rootfs" / "usr" / "local" / "bin" / "start-vnc-session.sh"
        if script_path.exists():
            content = script_path.read_text()
            assert "5900" in content

        # docker-compose.yml healthcheck
        compose_path = HACKVM_DIR / "docker-compose.yml"
        if compose_path.exists():
            content = compose_path.read_text()
            assert "5900" in content
