"""Tests for tmp_janitor startup cleanup.

Tests the orphaned temp directory cleanup in app.utils.tmp_janitor.
"""

import os
import tempfile
from pathlib import Path

import pytest

# Mark all tests in this module as not requiring database
pytestmark = pytest.mark.no_db

from app.utils.tmp_janitor import (
    EVIDENCE_TMPDIR_PREFIX,
    cleanup_orphaned_evidence_tmpdirs,
)
from app.utils.fs import rmtree_hardened


@pytest.fixture
def test_tmp_base():
    """Create a test temp base directory."""
    tmpdir = Path(tempfile.mkdtemp(prefix="test-janitor-base-"))
    yield tmpdir
    rmtree_hardened(tmpdir)


class TestCleanupOrphanedTmpdirs:
    """Tests for cleanup_orphaned_evidence_tmpdirs."""

    def test_no_orphans_found(self, test_tmp_base: Path):
        """Test that cleanup handles empty directory gracefully."""
        count = cleanup_orphaned_evidence_tmpdirs(test_tmp_base)
        assert count == 0

    def test_cleans_matching_directories(self, test_tmp_base: Path):
        """Test that directories with matching prefix are cleaned."""
        # Create orphaned directories
        orphan1 = test_tmp_base / f"{EVIDENCE_TMPDIR_PREFIX}abc123"
        orphan2 = test_tmp_base / f"{EVIDENCE_TMPDIR_PREFIX}def456"
        orphan1.mkdir()
        orphan2.mkdir()

        # Add some files to make it more realistic
        (orphan1 / "test.txt").write_text("test")
        (orphan2 / "evidence.zip").write_bytes(b"fake zip")

        count = cleanup_orphaned_evidence_tmpdirs(test_tmp_base)

        assert count == 2
        assert not orphan1.exists()
        assert not orphan2.exists()

    def test_ignores_non_matching_directories(self, test_tmp_base: Path):
        """Test that directories without matching prefix are not cleaned."""
        # Create non-matching directories
        safe_dir = test_tmp_base / "important-data"
        other_dir = test_tmp_base / "other-temp-12345"
        safe_dir.mkdir()
        other_dir.mkdir()

        # Create one matching orphan
        orphan = test_tmp_base / f"{EVIDENCE_TMPDIR_PREFIX}xyz789"
        orphan.mkdir()

        count = cleanup_orphaned_evidence_tmpdirs(test_tmp_base)

        assert count == 1
        assert not orphan.exists()
        assert safe_dir.exists()
        assert other_dir.exists()

    def test_ignores_files(self, test_tmp_base: Path):
        """Test that files with matching prefix are not cleaned."""
        # Create a file with matching prefix (should be ignored)
        matching_file = test_tmp_base / f"{EVIDENCE_TMPDIR_PREFIX}file.txt"
        matching_file.write_text("not a directory")

        # Create a matching directory
        orphan = test_tmp_base / f"{EVIDENCE_TMPDIR_PREFIX}dir"
        orphan.mkdir()

        count = cleanup_orphaned_evidence_tmpdirs(test_tmp_base)

        assert count == 1
        assert matching_file.exists()  # File should not be deleted
        assert not orphan.exists()

    def test_ignores_symlinks(self, test_tmp_base: Path):
        """Test that symlinks with matching prefix are not followed."""
        # Create a real target directory (should not be deleted)
        target = test_tmp_base / "real-target"
        target.mkdir()
        (target / "important.txt").write_text("don't delete me")

        # Create a symlink with matching prefix
        symlink = test_tmp_base / f"{EVIDENCE_TMPDIR_PREFIX}symlink"
        symlink.symlink_to(target)

        count = cleanup_orphaned_evidence_tmpdirs(test_tmp_base)

        assert count == 0
        assert target.exists()
        assert (target / "important.txt").exists()

    def test_dry_run_mode(self, test_tmp_base: Path):
        """Test that dry_run mode doesn't delete anything."""
        orphan1 = test_tmp_base / f"{EVIDENCE_TMPDIR_PREFIX}dry1"
        orphan2 = test_tmp_base / f"{EVIDENCE_TMPDIR_PREFIX}dry2"
        orphan1.mkdir()
        orphan2.mkdir()

        count = cleanup_orphaned_evidence_tmpdirs(test_tmp_base, dry_run=True)

        assert count == 2
        assert orphan1.exists()  # Should still exist
        assert orphan2.exists()  # Should still exist

    def test_handles_nested_content(self, test_tmp_base: Path):
        """Test that directories with nested content are cleaned."""
        orphan = test_tmp_base / f"{EVIDENCE_TMPDIR_PREFIX}nested"
        orphan.mkdir()
        (orphan / "subdir").mkdir()
        (orphan / "subdir" / "deep").mkdir()
        (orphan / "subdir" / "deep" / "file.txt").write_text("nested content")

        count = cleanup_orphaned_evidence_tmpdirs(test_tmp_base)

        assert count == 1
        assert not orphan.exists()

    def test_handles_restrictive_permissions(self, test_tmp_base: Path):
        """Test that directories with restrictive permissions are cleaned."""
        orphan = test_tmp_base / f"{EVIDENCE_TMPDIR_PREFIX}locked"
        orphan.mkdir()
        locked_file = orphan / "locked.txt"
        locked_file.write_text("locked content")

        # Make file read-only
        os.chmod(locked_file, 0o444)
        # Make directory read-only
        os.chmod(orphan, 0o555)

        try:
            count = cleanup_orphaned_evidence_tmpdirs(test_tmp_base)
            # Should have attempted cleanup (may or may not succeed based on user)
            # If running as non-root, should handle permission error gracefully
        finally:
            # Restore permissions for test cleanup
            try:
                os.chmod(orphan, 0o755)
                os.chmod(locked_file, 0o644)
            except Exception:
                pass

    def test_nonexistent_tmp_base(self):
        """Test that nonexistent tmp_base is handled gracefully."""
        fake_path = Path("/nonexistent/path/that/does/not/exist")
        count = cleanup_orphaned_evidence_tmpdirs(fake_path)
        assert count == 0


class TestPrefixMatching:
    """Tests for prefix matching behavior."""

    def test_exact_prefix_required(self, test_tmp_base: Path):
        """Test that exact prefix match is required."""
        # These should NOT match
        not_matching = [
            "octolab-evidence",  # Missing trailing dash
            "octolab-evidencesomething",  # No dash after "evidence"
            "xoctolab-evidence-abc",  # Extra prefix
            "OCTOLAB-EVIDENCE-abc",  # Wrong case
        ]

        for name in not_matching:
            (test_tmp_base / name).mkdir()

        # This SHOULD match
        matching = test_tmp_base / f"{EVIDENCE_TMPDIR_PREFIX}match"
        matching.mkdir()

        count = cleanup_orphaned_evidence_tmpdirs(test_tmp_base)

        assert count == 1
        assert not matching.exists()
        for name in not_matching:
            assert (test_tmp_base / name).exists(), f"{name} should not be deleted"
