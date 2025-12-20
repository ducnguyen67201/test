"""Tests for octolabctl infrastructure management.

Tests for:
- octolabctl script existence and permissions
- Path validation in smoke test
- netd service file validity
- Environment file generation

SECURITY:
- Tests path containment validation
- Tests no ../ usage in paths
- Tests group/permission setup
"""

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Mark tests that don't need database
pytestmark = pytest.mark.no_db


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def project_root():
    """Get project root directory."""
    # Navigate from backend/tests to project root
    return Path(__file__).parent.parent.parent


@pytest.fixture
def octolabctl_path(project_root):
    """Get path to octolabctl script."""
    return project_root / "infra" / "octolabctl" / "octolabctl.sh"


@pytest.fixture
def netd_service_path(project_root):
    """Get path to netd service file."""
    return project_root / "infra" / "microvm" / "netd" / "microvm-netd.service"


# =============================================================================
# Tests: octolabctl Script
# =============================================================================


class TestOctolabctlScript:
    """Tests for octolabctl.sh script."""

    def test_octolabctl_exists(self, octolabctl_path):
        """Verify octolabctl.sh exists."""
        assert octolabctl_path.exists(), f"octolabctl not found at {octolabctl_path}"

    def test_octolabctl_executable(self, octolabctl_path):
        """Verify octolabctl.sh is executable."""
        assert os.access(octolabctl_path, os.X_OK), "octolabctl is not executable"

    def test_octolabctl_has_shebang(self, octolabctl_path):
        """Verify octolabctl.sh has proper shebang."""
        content = octolabctl_path.read_text()
        assert content.startswith("#!/"), "Missing shebang"
        assert "bash" in content.split("\n")[0], "Not a bash script"

    def test_octolabctl_strict_mode(self, octolabctl_path):
        """Verify octolabctl.sh uses strict mode."""
        content = octolabctl_path.read_text()
        assert "set -euo pipefail" in content, "Missing strict mode"

    def test_octolabctl_help_works(self, octolabctl_path):
        """Verify octolabctl --help runs without error."""
        result = subprocess.run(
            [str(octolabctl_path), "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0, f"Help failed: {result.stderr}"
        assert "octolabctl" in result.stdout.lower()
        assert "doctor" in result.stdout.lower()
        assert "install" in result.stdout.lower()

    def test_octolabctl_has_subcommands(self, octolabctl_path):
        """Verify octolabctl has expected subcommands."""
        content = octolabctl_path.read_text()

        expected_commands = ["doctor", "install", "netd", "smoke", "enable-runtime"]
        for cmd in expected_commands:
            assert cmd in content, f"Missing subcommand: {cmd}"

    def test_octolabctl_no_backticks(self, octolabctl_path):
        """Verify octolabctl doesn't use legacy backtick syntax."""
        content = octolabctl_path.read_text()
        # Allow backticks only in comments
        for i, line in enumerate(content.split("\n"), 1):
            if line.strip().startswith("#"):
                continue
            if "`" in line and "$(" not in line:
                # Check if it's a legitimate use (like in heredoc)
                if "EOF" not in line and "END" not in line:
                    pytest.fail(f"Line {i}: Uses backticks instead of $()")


class TestOctolabctlPathSecurity:
    """Tests for path security in octolabctl."""

    def test_no_dotdot_paths_in_runtime(self, octolabctl_path):
        """Verify octolabctl doesn't use ../ in runtime operations.

        Note: Using ../ in script initialization (finding PROJECT_ROOT) is acceptable
        since it's for bootstrapping the script's own location, not runtime paths.
        """
        content = octolabctl_path.read_text()

        # Skip initial script setup (first 50 lines typically)
        lines = content.split("\n")
        for i, line in enumerate(lines[50:], 51):
            if line.strip().startswith("#"):
                continue
            # Check for runtime path construction with ../
            if "../" in line:
                # These are problematic runtime uses
                if any(x in line for x in ["temp_dir", "state_dir", "smoke_dir", "mkdir", "rm -rf"]):
                    pytest.fail(f"Line {i}: Uses ../ in runtime path: {line.strip()[:60]}")

    def test_uses_realpath(self, octolabctl_path):
        """Verify octolabctl uses realpath or similar for path resolution."""
        content = octolabctl_path.read_text()

        # Should use $() for command substitution with dirname/realpath/pwd
        assert "$(cd" in content or "$(dirname" in content, \
            "Should use safe path resolution"


# =============================================================================
# Tests: netd Service File
# =============================================================================


class TestNetdServiceFile:
    """Tests for microvm-netd.service file."""

    def test_service_file_exists(self, netd_service_path):
        """Verify service file exists."""
        assert netd_service_path.exists()

    def test_service_file_valid_syntax(self, netd_service_path):
        """Verify service file has valid systemd syntax."""
        content = netd_service_path.read_text()

        # Must have Unit, Service, Install sections
        assert "[Unit]" in content
        assert "[Service]" in content
        assert "[Install]" in content

    def test_service_runs_as_root(self, netd_service_path):
        """Verify service runs as root (required for network ops)."""
        content = netd_service_path.read_text()

        # Should have User=root or no User (defaults to root)
        if "User=" in content:
            assert "User=root" in content, "Service must run as root"

    def test_service_has_security_hardening(self, netd_service_path):
        """Verify service has security hardening options."""
        content = netd_service_path.read_text()

        # Should have some security options
        security_options = [
            "ProtectSystem",
            "ProtectHome",
            "PrivateTmp",
            "NoNewPrivileges",
        ]

        found = [opt for opt in security_options if opt in content]
        assert len(found) >= 2, f"Missing security hardening. Found: {found}"

    def test_service_has_restart_policy(self, netd_service_path):
        """Verify service has restart policy."""
        content = netd_service_path.read_text()
        assert "Restart=" in content


# =============================================================================
# Tests: Path Containment
# =============================================================================


class TestPathContainment:
    """Tests for path containment security."""

    def test_resolve_under_base_prevents_traversal(self):
        """Test that resolve_under_base prevents path traversal."""
        from app.services.microvm_paths import (
            PathContainmentError,
            PathTraversalError,
            resolve_under_base,
        )

        base_dir = Path("/var/lib/octolab/microvm")

        # Valid paths should work
        result = resolve_under_base(base_dir, "lab123")
        assert str(result).startswith(str(base_dir))

        # Traversal should fail with PathTraversalError
        with pytest.raises(PathTraversalError):
            resolve_under_base(base_dir, "../etc/passwd")

        with pytest.raises(PathTraversalError):
            resolve_under_base(base_dir, "lab/../../../etc")

    def test_validate_lab_id_returns_string(self):
        """Test that validate_lab_id returns string for valid UUIDs."""
        from app.services.firecracker_paths import validate_lab_id

        # Valid UUIDs should return string
        result = validate_lab_id("12345678-1234-1234-1234-123456789abc")
        assert isinstance(result, str)
        assert result == "12345678-1234-1234-1234-123456789abc"

    def test_validate_lab_id_raises_on_invalid(self):
        """Test that validate_lab_id raises on invalid input."""
        from app.services.firecracker_paths import validate_lab_id, InvalidLabIdError

        # Invalid should raise InvalidLabIdError (subclass of ValueError)
        with pytest.raises(InvalidLabIdError):
            validate_lab_id("../etc/passwd")

        with pytest.raises(InvalidLabIdError):
            validate_lab_id("not-a-uuid")

        with pytest.raises(InvalidLabIdError):
            validate_lab_id("path/traversal/../../../etc")


# =============================================================================
# Tests: Smoke Test Path Security
# =============================================================================


class TestSmokeTestSecurity:
    """Tests for smoke test path security."""

    def test_smoke_id_pattern(self):
        """Test smoke ID pattern validation."""
        from app.services.microvm_smoke import validate_smoke_id

        # Valid patterns
        assert validate_smoke_id("smoke_1234567890123_abcd1234")
        assert validate_smoke_id("smoke_9999999999999_00000000")

        # Invalid patterns
        assert not validate_smoke_id("smoke_123_abc")  # Too short
        assert not validate_smoke_id("../smoke_1234567890123_abcd1234")
        assert not validate_smoke_id("smoke_1234567890123_abcd1234/../..")
        assert not validate_smoke_id("")
        assert not validate_smoke_id(None)

    def test_get_smoke_dir_validates(self):
        """Test that get_smoke_dir validates inputs."""
        from app.services.microvm_smoke import get_smoke_dir

        state_dir = Path("/var/lib/octolab/microvm")

        # Valid smoke_id should return path
        result = get_smoke_dir(state_dir, "smoke_1234567890123_abcd1234")
        assert result is not None
        assert str(result).startswith(str(state_dir))

        # Invalid smoke_id should return None
        assert get_smoke_dir(state_dir, "../etc") is None
        assert get_smoke_dir(state_dir, "not_valid") is None
        assert get_smoke_dir(state_dir, "") is None


# =============================================================================
# Tests: Environment File Generation
# =============================================================================


class TestEnvFileGeneration:
    """Tests for environment file generation."""

    def test_env_markers_used(self, octolabctl_path):
        """Verify octolabctl uses BEGIN/END markers for env blocks."""
        content = octolabctl_path.read_text()

        assert "BEGIN OCTOLAB_MICROVM" in content
        assert "END OCTOLAB_MICROVM" in content

    def test_env_preserves_existing(self, octolabctl_path):
        """Verify octolabctl preserves existing env vars."""
        content = octolabctl_path.read_text()

        # Should remove old block before adding new one
        assert "sed" in content or "grep" in content


# =============================================================================
# Tests: Documentation
# =============================================================================


class TestDocumentation:
    """Tests for documentation completeness."""

    def test_docs_readme_exists(self, project_root):
        """Verify docs/README.md exists."""
        readme = project_root / "docs" / "README.md"
        assert readme.exists()

    def test_docs_quickstart_exists(self, project_root):
        """Verify docs/dev/quickstart.md exists."""
        quickstart = project_root / "docs" / "dev" / "quickstart.md"
        assert quickstart.exists()

    def test_docs_hetzner_exists(self, project_root):
        """Verify docs/ops/hetzner.md exists."""
        hetzner = project_root / "docs" / "ops" / "hetzner.md"
        assert hetzner.exists()

    def test_docs_architecture_exists(self, project_root):
        """Verify docs/architecture/microvm.md exists."""
        arch = project_root / "docs" / "architecture" / "microvm.md"
        assert arch.exists()

    def test_docs_troubleshooting_exists(self, project_root):
        """Verify docs/troubleshooting.md exists."""
        trouble = project_root / "docs" / "troubleshooting.md"
        assert trouble.exists()
