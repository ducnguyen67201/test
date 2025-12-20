"""Tests for cmdlog cache-busting mechanism.

This test verifies that the CMDLOG_BUST build-arg properly invalidates
Docker cache for cmdlog layers, allowing script changes to be picked up
without rebuilding the entire image.

To run manually:
    pytest backend/tests/test_cmdlog_cache_bust.py -v

Requirements:
    - Docker must be available and running
    - Tests will build/run containers (may take 30-60s per test)

The test builds the octobox-beta image twice with different CMDLOG_BUST values
and verifies that /etc/octolab-cmdlog.build-id contains the expected value.
"""

import subprocess
import shutil
from pathlib import Path

import pytest


# Skip all tests in this module if docker is not available
pytestmark = pytest.mark.no_db


def docker_available() -> bool:
    """Check if docker CLI is available and daemon is running."""
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
            shell=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


# Path to octobox-beta image directory
OCTOBOX_DIR = Path(__file__).parent.parent.parent / "images" / "octobox-beta"

# Test image name (unique to avoid conflicts)
TEST_IMAGE_NAME = "octobox-beta-cmdlog-test"

# Timeouts
BUILD_TIMEOUT = 300  # 5 minutes for initial build
RUN_TIMEOUT = 30  # 30 seconds to start container and read file


def build_image_with_bust(bust_value: str, image_tag: str) -> None:
    """Build octobox-beta image with specific CMDLOG_BUST value.

    Args:
        bust_value: Value for CMDLOG_BUST build-arg
        image_tag: Full image tag (name:tag)

    Raises:
        subprocess.CalledProcessError: If build fails
        subprocess.TimeoutExpired: If build exceeds timeout
    """
    cmd = [
        "docker", "build",
        "--build-arg", f"CMDLOG_BUST={bust_value}",
        "-t", image_tag,
        str(OCTOBOX_DIR),
    ]
    subprocess.run(
        cmd,
        check=True,
        shell=False,
        timeout=BUILD_TIMEOUT,
        capture_output=True,
    )


def get_build_id_from_image(image_tag: str) -> str:
    """Run container and read /etc/octolab-cmdlog.build-id.

    Args:
        image_tag: Image to run

    Returns:
        Contents of /etc/octolab-cmdlog.build-id (stripped)

    Raises:
        subprocess.CalledProcessError: If container fails to run
        subprocess.TimeoutExpired: If read exceeds timeout
    """
    # Run container, cat the file, exit
    # Use --rm to auto-cleanup, --entrypoint to override default
    cmd = [
        "docker", "run",
        "--rm",
        "--entrypoint", "cat",
        image_tag,
        "/etc/octolab-cmdlog.build-id",
    ]
    result = subprocess.run(
        cmd,
        check=True,
        shell=False,
        timeout=RUN_TIMEOUT,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def cleanup_test_images() -> None:
    """Remove test images to avoid clutter."""
    for tag in [f"{TEST_IMAGE_NAME}:111", f"{TEST_IMAGE_NAME}:222"]:
        try:
            subprocess.run(
                ["docker", "rmi", "-f", tag],
                shell=False,
                timeout=30,
                capture_output=True,
            )
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
            pass  # Ignore cleanup failures


@pytest.fixture(scope="module", autouse=True)
def cleanup_after_tests():
    """Cleanup test images after all tests in this module."""
    yield
    cleanup_test_images()


@pytest.mark.skipif(not docker_available(), reason="Docker not available")
@pytest.mark.skipif(not OCTOBOX_DIR.exists(), reason="octobox-beta directory not found")
class TestCmdlogCacheBust:
    """Test suite for cmdlog cache-busting verification."""

    def test_build_with_bust_111_contains_111(self):
        """Build with CMDLOG_BUST=111 should create build-id containing 111."""
        image_tag = f"{TEST_IMAGE_NAME}:111"

        # Build image with CMDLOG_BUST=111
        build_image_with_bust("111", image_tag)

        # Read build-id from container
        build_id = get_build_id_from_image(image_tag)

        # Verify
        assert "111" in build_id, f"Expected '111' in build-id, got: {build_id}"
        assert build_id == "cmdlog-bust=111", f"Unexpected build-id format: {build_id}"

    def test_build_with_bust_222_contains_222(self):
        """Build with CMDLOG_BUST=222 should create build-id containing 222."""
        image_tag = f"{TEST_IMAGE_NAME}:222"

        # Build image with CMDLOG_BUST=222
        build_image_with_bust("222", image_tag)

        # Read build-id from container
        build_id = get_build_id_from_image(image_tag)

        # Verify
        assert "222" in build_id, f"Expected '222' in build-id, got: {build_id}"
        assert build_id == "cmdlog-bust=222", f"Unexpected build-id format: {build_id}"

    def test_different_bust_values_produce_different_images(self):
        """Two builds with different CMDLOG_BUST values should have different build-ids."""
        # This test relies on the previous two tests having run
        # Build both if not already built
        tag_111 = f"{TEST_IMAGE_NAME}:111"
        tag_222 = f"{TEST_IMAGE_NAME}:222"

        # Ensure both images exist
        try:
            build_id_111 = get_build_id_from_image(tag_111)
        except subprocess.CalledProcessError:
            build_image_with_bust("111", tag_111)
            build_id_111 = get_build_id_from_image(tag_111)

        try:
            build_id_222 = get_build_id_from_image(tag_222)
        except subprocess.CalledProcessError:
            build_image_with_bust("222", tag_222)
            build_id_222 = get_build_id_from_image(tag_222)

        # Verify they're different
        assert build_id_111 != build_id_222, (
            f"Build IDs should differ: {build_id_111} vs {build_id_222}"
        )


# =============================================================================
# Manual Verification Instructions
# =============================================================================
"""
## How to Verify Manually

1. Build with a specific CMDLOG_BUST value:
   ```bash
   cd images/octobox-beta
   docker build --build-arg CMDLOG_BUST=test123 -t octobox-beta:test .
   ```

2. Verify the build-id in the container:
   ```bash
   docker run --rm --entrypoint cat octobox-beta:test /etc/octolab-cmdlog.build-id
   # Should output: cmdlog-bust=test123
   ```

3. Make a change to rootfs/etc/profile.d/octolab-cmdlog.sh

4. Rebuild with a NEW CMDLOG_BUST value:
   ```bash
   docker build --build-arg CMDLOG_BUST=test456 -t octobox-beta:test .
   ```

5. Verify the script change is now in the image:
   ```bash
   docker run --rm --entrypoint cat octobox-beta:test /etc/octolab-cmdlog.build-id
   # Should output: cmdlog-bust=test456
   ```

## Using DEV_FORCE_CMDLOG_REBUILD in Development

Add to your backend/.env.local:
   DEV_FORCE_CMDLOG_REBUILD=true

This will automatically rebuild cmdlog layers on every lab creation,
using a timestamp-based cache bust value.
"""
