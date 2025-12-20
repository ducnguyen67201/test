"""Tests for evidence bundle v3 (discovery-based bundling).

Verifies:
1. _norm_rel path normalization and traversal detection
2. _safe_resolve safe path resolution
3. preview_bundle file discovery
4. build_evidence_zip discovery-based ZIP building
5. Manifest truthfulness (claims match actual ZIP contents)

SECURITY TESTS:
- Path traversal prevention (../, symlinks, absolute paths)
- Zip-slip prevention
- Symlink escape detection
"""

import json
import os
import pytest
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

from app.services.evidence_service import (
    _norm_rel,
    _safe_resolve,
    PathTraversalError,
    preview_bundle,
    build_evidence_zip,
)

# Mark all tests in this file as not requiring database
pytestmark = pytest.mark.no_db


class TestNormRel:
    """Tests for _norm_rel path normalization."""

    def test_norm_rel_simple_path(self):
        """Test that simple paths pass through."""
        assert _norm_rel("foo/bar.txt") == "foo/bar.txt"
        assert _norm_rel("evidence/tlog/session.jsonl") == "evidence/tlog/session.jsonl"

    def test_norm_rel_removes_redundant_slashes(self):
        """Test that redundant slashes are normalized."""
        assert _norm_rel("foo//bar.txt") == "foo/bar.txt"
        assert _norm_rel("a///b///c.txt") == "a/b/c.txt"

    def test_norm_rel_removes_dot_segments(self):
        """Test that . segments are removed."""
        assert _norm_rel("./foo/bar.txt") == "foo/bar.txt"
        assert _norm_rel("foo/./bar.txt") == "foo/bar.txt"

    def test_norm_rel_converts_backslashes(self):
        """Test that Windows-style backslashes are converted."""
        assert _norm_rel("foo\\bar.txt") == "foo/bar.txt"
        assert _norm_rel("evidence\\tlog\\session.jsonl") == "evidence/tlog/session.jsonl"

    def test_norm_rel_rejects_absolute_paths(self):
        """Test that absolute paths are rejected."""
        with pytest.raises(PathTraversalError):
            _norm_rel("/etc/passwd")

        with pytest.raises(PathTraversalError):
            _norm_rel("/foo/bar.txt")

    def test_norm_rel_rejects_parent_traversal(self):
        """Test that parent directory traversal is rejected."""
        with pytest.raises(PathTraversalError):
            _norm_rel("../etc/passwd")

        with pytest.raises(PathTraversalError):
            _norm_rel("foo/../../../etc/passwd")

        with pytest.raises(PathTraversalError):
            _norm_rel("..")

    def test_norm_rel_safe_relative_traversal(self):
        """Test that traversal that stays inside is OK."""
        # foo/../bar normalizes to bar, which is safe
        assert _norm_rel("foo/../bar.txt") == "bar.txt"

    def test_norm_rel_rejects_hidden_traversal(self):
        """Test that hidden traversal attempts are rejected."""
        # These should be caught after normalization
        with pytest.raises(PathTraversalError):
            _norm_rel("foo/bar/../../..")


class TestSafeResolve:
    """Tests for _safe_resolve path resolution."""

    def test_safe_resolve_valid_file(self, tmp_path):
        """Test that valid files are resolved correctly."""
        # Create test file
        test_file = tmp_path / "evidence" / "test.txt"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("test content")

        result = _safe_resolve(tmp_path, "evidence/test.txt")
        assert result is not None
        assert result == test_file.resolve()

    def test_safe_resolve_nonexistent_file(self, tmp_path):
        """Test that nonexistent files return None."""
        result = _safe_resolve(tmp_path, "nonexistent.txt")
        assert result is None

    def test_safe_resolve_directory_returns_none(self, tmp_path):
        """Test that directories return None (not a regular file)."""
        test_dir = tmp_path / "evidence"
        test_dir.mkdir()

        result = _safe_resolve(tmp_path, "evidence")
        assert result is None

    def test_safe_resolve_symlink_returns_none(self, tmp_path):
        """Test that symlinks return None (security)."""
        # Create real file and symlink
        real_file = tmp_path / "real.txt"
        real_file.write_text("real content")
        symlink = tmp_path / "link.txt"
        symlink.symlink_to(real_file)

        # Symlink should be rejected
        result = _safe_resolve(tmp_path, "link.txt")
        assert result is None

        # Real file should work
        result = _safe_resolve(tmp_path, "real.txt")
        assert result is not None

    def test_safe_resolve_traversal_returns_none(self, tmp_path):
        """Test that path traversal attempts return None."""
        # Create a file outside the root
        outside = tmp_path.parent / "outside.txt"
        outside.write_text("outside content")

        result = _safe_resolve(tmp_path, "../outside.txt")
        assert result is None

    def test_safe_resolve_symlink_escape_returns_none(self, tmp_path):
        """Test that symlinks escaping the root return None."""
        # Create file outside and symlink inside pointing out
        outside = tmp_path.parent / "escape_target.txt"
        outside.write_text("escaped!")

        escape_link = tmp_path / "escape.txt"
        escape_link.symlink_to(outside)

        result = _safe_resolve(tmp_path, "escape.txt")
        assert result is None

    def test_safe_resolve_with_traversal_in_path(self, tmp_path):
        """Test that absolute paths are rejected via _norm_rel."""
        result = _safe_resolve(tmp_path, "/etc/passwd")
        assert result is None


class TestPreviewBundle:
    """Tests for preview_bundle file discovery."""

    def test_preview_bundle_empty_root(self, tmp_path):
        """Test preview with empty evidence root."""
        lab_id = uuid4()
        result = preview_bundle(lab_id, tmp_path)

        assert result["found"] == []
        assert result["total_bytes"] == 0
        assert result["arcnames"] == []
        assert result["artifact_counts"]["terminal_logs"] == 0
        assert result["artifact_counts"]["pcap"] == 0
        assert result["artifact_counts"]["guac_recordings"] == 0

    def test_preview_bundle_finds_tlog_files(self, tmp_path):
        """Test that tlog files are discovered."""
        lab_id = uuid4()

        # Create tlog structure
        tlog_dir = tmp_path / "evidence" / "tlog" / str(lab_id)
        tlog_dir.mkdir(parents=True)

        session_file = tlog_dir / "session.jsonl"
        session_file.write_text('{"ver":"2.3"}\n')

        commands_file = tlog_dir / "commands.tsv"
        commands_file.write_text("timestamp\tcommand\n")

        result = preview_bundle(lab_id, tmp_path)

        assert len(result["found"]) == 2
        assert result["artifact_counts"]["terminal_logs"] == 2
        arcnames = result["arcnames"]
        assert f"evidence/tlog/{lab_id}/session.jsonl" in arcnames
        assert f"evidence/tlog/{lab_id}/commands.tsv" in arcnames

    def test_preview_bundle_finds_pcap_files(self, tmp_path):
        """Test that pcap files are discovered."""
        lab_id = uuid4()

        # Create pcap directory
        pcap_dir = tmp_path / "pcap"
        pcap_dir.mkdir()

        pcap_file = pcap_dir / "capture.pcap"
        pcap_file.write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 20)

        result = preview_bundle(lab_id, tmp_path)

        assert result["artifact_counts"]["pcap"] == 1
        assert "pcap/capture.pcap" in result["arcnames"]

    def test_preview_bundle_calculates_total_bytes(self, tmp_path):
        """Test that total bytes is calculated correctly."""
        lab_id = uuid4()

        # Create files with known sizes
        tlog_dir = tmp_path / "evidence" / "tlog" / str(lab_id)
        tlog_dir.mkdir(parents=True)

        file1 = tlog_dir / "session.jsonl"
        file1.write_text("x" * 100)  # 100 bytes

        file2 = tlog_dir / "commands.tsv"
        file2.write_text("y" * 50)  # 50 bytes

        result = preview_bundle(lab_id, tmp_path)

        assert result["total_bytes"] == 150

    def test_preview_bundle_skips_symlinks(self, tmp_path):
        """Test that symlinks are skipped."""
        lab_id = uuid4()

        # Create real file
        tlog_dir = tmp_path / "evidence" / "tlog" / str(lab_id)
        tlog_dir.mkdir(parents=True)

        real_file = tlog_dir / "real.jsonl"
        real_file.write_text('{"ver":"2.3"}\n')

        # Create symlink
        link_file = tlog_dir / "link.jsonl"
        link_file.symlink_to(real_file)

        result = preview_bundle(lab_id, tmp_path, debug=True)

        # Only real file should be found
        assert len(result["found"]) == 1
        assert result["arcnames"][0].endswith("real.jsonl")

        # Symlink should be in skipped (when debug=True)
        assert "skipped" in result
        skipped_rels = [s["rel"] for s in result["skipped"]]
        assert any("link.jsonl" in rel for rel in skipped_rels)

    def test_preview_bundle_debug_mode(self, tmp_path):
        """Test that debug mode includes skipped info."""
        lab_id = uuid4()

        result_no_debug = preview_bundle(lab_id, tmp_path, debug=False)
        result_debug = preview_bundle(lab_id, tmp_path, debug=True)

        assert "skipped" not in result_no_debug
        assert "skipped" in result_debug


class TestBuildEvidenceZip:
    """Tests for build_evidence_zip ZIP creation."""

    def test_build_evidence_zip_creates_zip(self, tmp_path):
        """Test that ZIP file is created."""
        lab_id = uuid4()
        out_path = tmp_path / "output.zip"

        # Create some evidence
        tlog_dir = tmp_path / "evidence" / "tlog" / str(lab_id)
        tlog_dir.mkdir(parents=True)
        (tlog_dir / "session.jsonl").write_text('{"ver":"2.3"}\n')

        result = build_evidence_zip(lab_id, tmp_path, out_path)

        assert out_path.exists()
        assert result["zip_path"] == str(out_path)

    def test_build_evidence_zip_includes_files(self, tmp_path):
        """Test that files are included in ZIP."""
        lab_id = uuid4()
        out_path = tmp_path / "output.zip"

        # Create evidence
        tlog_dir = tmp_path / "evidence" / "tlog" / str(lab_id)
        tlog_dir.mkdir(parents=True)
        (tlog_dir / "session.jsonl").write_text('{"ver":"2.3"}\n')

        build_evidence_zip(lab_id, tmp_path, out_path)

        # Verify ZIP contents
        with zipfile.ZipFile(out_path, "r") as zf:
            names = zf.namelist()
            assert f"evidence/tlog/{lab_id}/session.jsonl" in names
            assert "manifest.json" in names

    def test_build_evidence_zip_manifest_is_truthful(self, tmp_path):
        """Test that manifest reflects actual ZIP contents."""
        lab_id = uuid4()
        out_path = tmp_path / "output.zip"

        # Create evidence
        tlog_dir = tmp_path / "evidence" / "tlog" / str(lab_id)
        tlog_dir.mkdir(parents=True)
        (tlog_dir / "session.jsonl").write_text('{"ver":"2.3"}\n')

        pcap_dir = tmp_path / "pcap"
        pcap_dir.mkdir()
        (pcap_dir / "capture.pcap").write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 20)

        build_evidence_zip(lab_id, tmp_path, out_path)

        # Verify manifest matches actual contents
        with zipfile.ZipFile(out_path, "r") as zf:
            manifest_data = zf.read("manifest.json")
            manifest = json.loads(manifest_data)

            # Get actual files (excluding manifest)
            actual_files = [n for n in zf.namelist() if n != "manifest.json"]

            # Manifest included_files should match actual
            assert set(manifest["included_files"]) == set(actual_files)

            # Artifacts should reflect truth
            assert manifest["artifacts"]["terminal_logs"]["present"] is True
            assert manifest["artifacts"]["pcap"]["present"] is True

    def test_build_evidence_zip_empty_evidence(self, tmp_path):
        """Test that empty evidence still creates valid ZIP with manifest."""
        lab_id = uuid4()
        out_path = tmp_path / "output.zip"

        result = build_evidence_zip(lab_id, tmp_path, out_path)

        assert out_path.exists()

        # Verify manifest shows no files
        with zipfile.ZipFile(out_path, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["included_files"] == []
            assert manifest["artifacts"]["terminal_logs"]["present"] is False
            assert manifest["artifacts"]["pcap"]["present"] is False

    def test_build_evidence_zip_no_fake_claims(self, tmp_path):
        """Test that manifest never claims files that aren't in ZIP."""
        lab_id = uuid4()
        out_path = tmp_path / "output.zip"

        # Create only pcap (no terminal logs)
        pcap_dir = tmp_path / "pcap"
        pcap_dir.mkdir()
        (pcap_dir / "capture.pcap").write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 20)

        build_evidence_zip(lab_id, tmp_path, out_path)

        with zipfile.ZipFile(out_path, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))

            # Terminal logs should be marked as NOT present
            assert manifest["artifacts"]["terminal_logs"]["present"] is False
            assert "files" not in manifest["artifacts"]["terminal_logs"] or \
                   manifest["artifacts"]["terminal_logs"].get("files") is None

            # PCAP should be marked as present with file
            assert manifest["artifacts"]["pcap"]["present"] is True
            assert "pcap/capture.pcap" in manifest["artifacts"]["pcap"]["files"]

    def test_build_evidence_zip_skips_symlinks(self, tmp_path):
        """Test that symlinks are not included in ZIP."""
        lab_id = uuid4()
        out_path = tmp_path / "output.zip"

        # Create real file
        tlog_dir = tmp_path / "evidence" / "tlog" / str(lab_id)
        tlog_dir.mkdir(parents=True)
        real_file = tlog_dir / "real.jsonl"
        real_file.write_text('{"ver":"2.3"}\n')

        # Create symlink
        link_file = tlog_dir / "link.jsonl"
        link_file.symlink_to(real_file)

        build_evidence_zip(lab_id, tmp_path, out_path)

        with zipfile.ZipFile(out_path, "r") as zf:
            names = zf.namelist()
            # Real file should be included
            assert any("real.jsonl" in n for n in names)
            # Symlink should NOT be included
            assert not any("link.jsonl" in n for n in names)

    def test_build_evidence_zip_secure_permissions(self, tmp_path):
        """Test that output ZIP has secure permissions (0o600)."""
        lab_id = uuid4()
        out_path = tmp_path / "output.zip"

        build_evidence_zip(lab_id, tmp_path, out_path)

        mode = out_path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_build_evidence_zip_result_format(self, tmp_path):
        """Test that result dict has expected format."""
        lab_id = uuid4()
        out_path = tmp_path / "output.zip"

        # Create some evidence
        tlog_dir = tmp_path / "evidence" / "tlog" / str(lab_id)
        tlog_dir.mkdir(parents=True)
        (tlog_dir / "session.jsonl").write_text('{"ver":"2.3"}\n')

        result = build_evidence_zip(lab_id, tmp_path, out_path)

        # Check result format
        assert result["lab_id"] == str(lab_id)
        assert result["zip_path"] == str(out_path)
        assert isinstance(result["files_included"], list)
        assert isinstance(result["total_bytes"], int)
        assert "artifact_counts" in result
        assert "manifest" in result

    def test_build_evidence_zip_debug_mode(self, tmp_path):
        """Test that debug mode includes extra info."""
        lab_id = uuid4()
        out_path = tmp_path / "output.zip"

        result = build_evidence_zip(lab_id, tmp_path, out_path, debug=True)

        assert "debug" in result
        assert "preview_found_count" in result["debug"]
        assert "evidence_root" in result["debug"]


class TestManifestTruthfulness:
    """Tests focused on manifest truthfulness guarantee."""

    def test_manifest_included_files_matches_zip_contents(self, tmp_path):
        """Critical: included_files MUST exactly match ZIP contents."""
        lab_id = uuid4()
        out_path = tmp_path / "output.zip"

        # Create diverse evidence
        tlog_dir = tmp_path / "evidence" / "tlog" / str(lab_id)
        tlog_dir.mkdir(parents=True)
        (tlog_dir / "session.jsonl").write_text('{"ver":"2.3"}\n')
        (tlog_dir / "commands.tsv").write_text("ts\tcmd\n")

        pcap_dir = tmp_path / "pcap"
        pcap_dir.mkdir()
        (pcap_dir / "capture.pcap").write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 20)

        build_evidence_zip(lab_id, tmp_path, out_path)

        with zipfile.ZipFile(out_path, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))

            # Get actual files (excluding manifest itself)
            actual_files = sorted([n for n in zf.namelist() if n != "manifest.json"])
            manifest_files = sorted(manifest["included_files"])

            assert actual_files == manifest_files, \
                f"Manifest claims {manifest_files} but ZIP contains {actual_files}"

    def test_artifact_present_only_if_files_actually_present(self, tmp_path):
        """Critical: artifacts.*.present MUST be True only if files exist."""
        lab_id = uuid4()
        out_path = tmp_path / "output.zip"

        # Create ONLY pcap
        pcap_dir = tmp_path / "pcap"
        pcap_dir.mkdir()
        (pcap_dir / "capture.pcap").write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 20)

        build_evidence_zip(lab_id, tmp_path, out_path)

        with zipfile.ZipFile(out_path, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))
            actual_files = [n for n in zf.namelist() if n != "manifest.json"]

            # Terminal logs should be False (no tlog files)
            has_tlog_files = any("tlog" in f for f in actual_files)
            assert manifest["artifacts"]["terminal_logs"]["present"] == has_tlog_files

            # PCAP should be True
            has_pcap_files = any(f.endswith(".pcap") for f in actual_files)
            assert manifest["artifacts"]["pcap"]["present"] == has_pcap_files

    def test_artifact_files_list_matches_zip(self, tmp_path):
        """Critical: artifacts.*.files MUST list only files actually in ZIP."""
        lab_id = uuid4()
        out_path = tmp_path / "output.zip"

        # Create tlog files
        tlog_dir = tmp_path / "evidence" / "tlog" / str(lab_id)
        tlog_dir.mkdir(parents=True)
        (tlog_dir / "session.jsonl").write_text('{"ver":"2.3"}\n')

        build_evidence_zip(lab_id, tmp_path, out_path)

        with zipfile.ZipFile(out_path, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))

            terminal_artifact = manifest["artifacts"]["terminal_logs"]
            if terminal_artifact["present"]:
                # Every file listed must actually be in ZIP
                for claimed_file in terminal_artifact["files"]:
                    assert claimed_file in zf.namelist(), \
                        f"Manifest claims {claimed_file} present but not in ZIP"
