"""Tests for evidence bundle permission handling.

Tests that evidence bundling works correctly with files that have
restrictive permissions (simulating container-produced files).

IMPORTANT: Some tests require non-root execution to test permission errors.
Tests are skipped if running as root.
"""

import io
import os
import tempfile
import zipfile
from pathlib import Path

import pytest

from app.utils.fs import (
    EvidenceTreeError,
    copy_file_to_zip_streaming,
    normalize_evidence_tree,
    rmtree_hardened,
    safe_mkdir,
)

# Mark all tests in this module as not requiring database
pytestmark = pytest.mark.no_db


def is_root() -> bool:
    """Check if running as root (UID 0)."""
    return os.geteuid() == 0


@pytest.fixture
def temp_dir():
    """Create a temp directory for test extraction."""
    tmpdir = Path(tempfile.mkdtemp(prefix="test-evidence-perms-"))
    yield tmpdir
    rmtree_hardened(tmpdir)


class TestNormalizeEvidenceTree:
    """Tests for normalize_evidence_tree function."""

    def test_normalizes_readable_files(self, temp_dir: Path):
        """Test that normalize works on normal files."""
        # Create evidence tree
        evidence_dir = temp_dir / "evidence"
        safe_mkdir(evidence_dir)
        (evidence_dir / "test.log").write_text("test content")

        # Normalize should succeed
        normalize_evidence_tree(temp_dir, lab_id="test-lab")

        # File should be readable
        assert (evidence_dir / "test.log").read_text() == "test content"

    def test_rejects_symlinks_in_files(self, temp_dir: Path):
        """Test that symlinks in files are rejected."""
        evidence_dir = temp_dir / "evidence"
        safe_mkdir(evidence_dir)
        (evidence_dir / "real.log").write_text("real content")

        # Create a symlink
        symlink_path = evidence_dir / "link.log"
        symlink_path.symlink_to(evidence_dir / "real.log")

        # Should raise EvidenceTreeError
        with pytest.raises(EvidenceTreeError, match="symlink"):
            normalize_evidence_tree(temp_dir, lab_id="test-lab")

    def test_rejects_symlink_directories(self, temp_dir: Path):
        """Test that symlink directories are rejected."""
        evidence_dir = temp_dir / "evidence"
        safe_mkdir(evidence_dir)
        (evidence_dir / "test.log").write_text("content")

        # Create another directory and symlink to it
        other_dir = temp_dir / "other"
        safe_mkdir(other_dir)
        symlink_dir = evidence_dir / "link_dir"
        symlink_dir.symlink_to(other_dir)

        # Should raise EvidenceTreeError
        with pytest.raises(EvidenceTreeError, match="symlink"):
            normalize_evidence_tree(temp_dir, lab_id="test-lab")

    def test_handles_nonexistent_directory(self, temp_dir: Path):
        """Test that nonexistent directory is handled gracefully."""
        nonexistent = temp_dir / "does_not_exist"

        # Should not raise
        normalize_evidence_tree(nonexistent, lab_id="test-lab")

    @pytest.mark.skipif(is_root(), reason="Test requires non-root user")
    def test_best_effort_chmod_on_unreadable_file(self, temp_dir: Path):
        """Test that chmod is best-effort (doesn't fail if cannot chmod)."""
        evidence_dir = temp_dir / "evidence"
        safe_mkdir(evidence_dir)
        test_file = evidence_dir / "test.log"
        test_file.write_text("test content")

        # Make file write-only (simulating container perms)
        os.chmod(test_file, 0o200)

        # normalize_evidence_tree should try to fix it
        normalize_evidence_tree(temp_dir, lab_id="test-lab")

        # After normalization, file should be readable (0o600)
        mode = test_file.stat().st_mode & 0o777
        assert mode == 0o600
        assert test_file.read_text() == "test content"

    def test_normalizes_nested_structure(self, temp_dir: Path):
        """Test normalization of nested directory structure."""
        # Create nested structure like real evidence
        evidence_dir = temp_dir / "evidence"
        pcap_dir = temp_dir / "pcap"
        tlog_dir = evidence_dir / "tlog" / "session-123"

        safe_mkdir(evidence_dir)
        safe_mkdir(pcap_dir)
        safe_mkdir(tlog_dir)

        (evidence_dir / "commands.log").write_text("command log")
        (tlog_dir / "session.jsonl").write_text('{"event": "test"}')
        (pcap_dir / "capture.pcap").write_bytes(b"pcap data")

        # Normalize
        normalize_evidence_tree(temp_dir, lab_id="test-lab")

        # All files should be readable
        assert (evidence_dir / "commands.log").read_text() == "command log"
        assert (tlog_dir / "session.jsonl").read_text() == '{"event": "test"}'
        assert (pcap_dir / "capture.pcap").read_bytes() == b"pcap data"


class TestCopyFileToZipStreaming:
    """Tests for copy_file_to_zip_streaming function."""

    def test_copies_normal_file(self, temp_dir: Path):
        """Test that normal file is copied to zip."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("test content")

        zip_path = temp_dir / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            copy_file_to_zip_streaming(zf, test_file, "test.txt")

        # Verify zip contents
        with zipfile.ZipFile(zip_path, "r") as zf:
            assert zf.read("test.txt") == b"test content"

    def test_rejects_symlink(self, temp_dir: Path):
        """Test that symlinks are rejected."""
        real_file = temp_dir / "real.txt"
        real_file.write_text("real content")

        symlink = temp_dir / "link.txt"
        symlink.symlink_to(real_file)

        zip_path = temp_dir / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            with pytest.raises(ValueError, match="symlink"):
                copy_file_to_zip_streaming(zf, symlink, "link.txt")

    def test_copies_large_file_streaming(self, temp_dir: Path):
        """Test that large files are copied in chunks (streaming)."""
        # Create a 5MB file
        test_file = temp_dir / "large.bin"
        test_file.write_bytes(b"x" * (5 * 1024 * 1024))

        zip_path = temp_dir / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            # Use smaller chunk size for test
            copy_file_to_zip_streaming(zf, test_file, "large.bin", chunk_size=1024 * 1024)

        # Verify zip contents
        with zipfile.ZipFile(zip_path, "r") as zf:
            data = zf.read("large.bin")
            assert len(data) == 5 * 1024 * 1024
            assert data == b"x" * (5 * 1024 * 1024)

    def test_preserves_path_in_zip(self, temp_dir: Path):
        """Test that nested paths are preserved in zip."""
        subdir = temp_dir / "pcap"
        safe_mkdir(subdir)
        test_file = subdir / "capture.pcap"
        test_file.write_bytes(b"pcap data")

        zip_path = temp_dir / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            copy_file_to_zip_streaming(zf, test_file, "pcap/capture.pcap")

        # Verify nested path
        with zipfile.ZipFile(zip_path, "r") as zf:
            assert "pcap/capture.pcap" in zf.namelist()
            assert zf.read("pcap/capture.pcap") == b"pcap data"


class TestZipWithRestrictivePermissions:
    """Tests for zipping files with restrictive permissions."""

    @pytest.mark.skipif(is_root(), reason="Test requires non-root user")
    def test_zip_after_normalize_succeeds(self, temp_dir: Path):
        """Test that zipping works after normalization fixes permissions."""
        # Create evidence tree with restrictive permissions
        evidence_dir = temp_dir / "evidence"
        pcap_dir = temp_dir / "pcap"
        safe_mkdir(evidence_dir)
        safe_mkdir(pcap_dir)

        # Create files
        log_file = evidence_dir / "commands.log"
        log_file.write_text("command log")

        pcap_file = pcap_dir / "capture.pcap"
        pcap_file.write_bytes(b"pcap data")

        # Make pcap file write-only (simulating container perms)
        os.chmod(pcap_file, 0o200)

        # Normalize should fix permissions
        normalize_evidence_tree(temp_dir, lab_id="test-lab")

        # Now zipping should work
        zip_path = temp_dir / "evidence.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            copy_file_to_zip_streaming(zf, log_file, "evidence/commands.log")
            copy_file_to_zip_streaming(zf, pcap_file, "pcap/capture.pcap")

        # Verify zip contents
        with zipfile.ZipFile(zip_path, "r") as zf:
            assert zf.read("evidence/commands.log") == b"command log"
            assert zf.read("pcap/capture.pcap") == b"pcap data"

    @pytest.mark.skipif(is_root(), reason="Test requires non-root user")
    def test_zip_readable_file_with_000_mode_after_normalize(self, temp_dir: Path):
        """Test that file with mode 000 becomes readable after normalize."""
        evidence_dir = temp_dir / "evidence"
        safe_mkdir(evidence_dir)

        test_file = evidence_dir / "test.log"
        test_file.write_text("test content")

        # Make file completely inaccessible
        os.chmod(test_file, 0o000)

        # Without normalization, file is not readable
        # (This is expected to fail)

        # Normalize should fix it
        normalize_evidence_tree(temp_dir, lab_id="test-lab")

        # Now file should be readable
        assert test_file.read_text() == "test content"

        # And zipping should work
        zip_path = temp_dir / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            copy_file_to_zip_streaming(zf, test_file, "evidence/test.log")

        with zipfile.ZipFile(zip_path, "r") as zf:
            assert zf.read("evidence/test.log") == b"test content"


class TestEvidenceTreeWithPcap:
    """Tests specifically for pcap file handling."""

    def test_pcap_directory_can_be_empty(self, temp_dir: Path):
        """Test that empty pcap directory doesn't cause issues."""
        evidence_dir = temp_dir / "evidence"
        pcap_dir = temp_dir / "pcap"
        safe_mkdir(evidence_dir)
        safe_mkdir(pcap_dir)  # Empty pcap dir

        (evidence_dir / "commands.log").write_text("log")

        # Normalize should succeed
        normalize_evidence_tree(temp_dir, lab_id="test-lab")

        # Should be able to zip without pcap files
        zip_path = temp_dir / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            copy_file_to_zip_streaming(
                zf,
                evidence_dir / "commands.log",
                "evidence/commands.log"
            )

    def test_multiple_pcap_files(self, temp_dir: Path):
        """Test handling multiple pcap files."""
        pcap_dir = temp_dir / "pcap"
        safe_mkdir(pcap_dir)

        # Create multiple pcap files
        (pcap_dir / "capture1.pcap").write_bytes(b"pcap1")
        (pcap_dir / "capture2.pcapng").write_bytes(b"pcap2")
        (pcap_dir / "other.log").write_text("not a pcap")

        normalize_evidence_tree(temp_dir, lab_id="test-lab")

        # All files should be readable
        assert (pcap_dir / "capture1.pcap").read_bytes() == b"pcap1"
        assert (pcap_dir / "capture2.pcapng").read_bytes() == b"pcap2"
        assert (pcap_dir / "other.log").read_text() == "not a pcap"
