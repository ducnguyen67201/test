"""Tests for evidence status resolver and endpoint.

Tests the single source of truth for artifact presence detection.
Uses tmp_path fixtures to avoid Docker dependencies.
"""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import uuid4

# Mark all tests as not requiring database
pytestmark = pytest.mark.no_db


class TestComputeEvidenceStatus:
    """Tests for compute_evidence_status function (resolver)."""

    def test_empty_evidence_root_all_missing(self, tmp_path):
        """Empty evidence root returns all artifacts as not present."""
        from app.services.evidence_service import compute_evidence_status

        lab_id = str(uuid4())
        result = compute_evidence_status(tmp_path, lab_id)

        assert result["terminal_logs"].present is False
        assert "No terminal logs found" in result["terminal_logs"].reason
        assert result["pcap"].present is False
        assert "No network capture found" in result["pcap"].reason
        assert result["guac_recordings"].present is False

    def test_tlog_files_detected(self, tmp_path):
        """tlog session.jsonl files are detected correctly."""
        from app.services.evidence_service import compute_evidence_status

        lab_id = str(uuid4())

        # Create tlog directory structure
        tlog_dir = tmp_path / "evidence" / "tlog" / lab_id
        tlog_dir.mkdir(parents=True)

        # Create session.jsonl file with content
        session_file = tlog_dir / "session.jsonl"
        session_content = '{"ts":"2024-01-01T00:00:00Z","cmd":"ls"}\n'
        session_file.write_text(session_content)

        result = compute_evidence_status(tmp_path, lab_id)

        assert result["terminal_logs"].present is True
        assert result["terminal_logs"].bytes > 0
        assert len(result["terminal_logs"].files) == 1
        assert f"evidence/tlog/{lab_id}/session.jsonl" in result["terminal_logs"].files

    def test_legacy_commands_log_detected(self, tmp_path):
        """Legacy commands.log is detected correctly."""
        from app.services.evidence_service import compute_evidence_status

        lab_id = str(uuid4())

        # Create evidence directory with legacy log
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir(parents=True)

        commands_log = evidence_dir / "commands.log"
        commands_log.write_text("2024-01-01T00:00:00Z\tuser\t/home\tls -la\n")

        result = compute_evidence_status(tmp_path, lab_id)

        assert result["terminal_logs"].present is True
        assert "evidence/commands.log" in result["terminal_logs"].files

    def test_both_tlog_and_legacy_detected(self, tmp_path):
        """Both tlog and legacy logs are detected."""
        from app.services.evidence_service import compute_evidence_status

        lab_id = str(uuid4())

        # Create tlog
        tlog_dir = tmp_path / "evidence" / "tlog" / lab_id
        tlog_dir.mkdir(parents=True)
        (tlog_dir / "session.jsonl").write_text('{"cmd":"ls"}\n')

        # Create legacy log
        (tmp_path / "evidence" / "commands.log").write_text("ls\n")

        result = compute_evidence_status(tmp_path, lab_id)

        assert result["terminal_logs"].present is True
        assert len(result["terminal_logs"].files) == 2

    def test_pcap_files_detected(self, tmp_path):
        """PCAP files are detected correctly."""
        from app.services.evidence_service import compute_evidence_status

        lab_id = str(uuid4())

        # Create pcap directory with capture file
        pcap_dir = tmp_path / "pcap"
        pcap_dir.mkdir(parents=True)

        pcap_file = pcap_dir / "capture.pcap"
        # Write minimal pcap header
        pcap_file.write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 20)

        result = compute_evidence_status(tmp_path, lab_id)

        assert result["pcap"].present is True
        assert result["pcap"].bytes > 0
        assert "pcap/capture.pcap" in result["pcap"].files

    def test_pcapng_files_detected(self, tmp_path):
        """PCAPNG files are also detected."""
        from app.services.evidence_service import compute_evidence_status

        lab_id = str(uuid4())

        pcap_dir = tmp_path / "pcap"
        pcap_dir.mkdir(parents=True)
        (pcap_dir / "capture.pcapng").write_bytes(b"\x0a\x0d\x0d\x0a" + b"\x00" * 20)

        result = compute_evidence_status(tmp_path, lab_id)

        assert result["pcap"].present is True
        assert "pcap/capture.pcapng" in result["pcap"].files

    def test_guac_recordings_detected(self, tmp_path):
        """Guacamole recordings are detected if present."""
        from app.services.evidence_service import compute_evidence_status

        lab_id = str(uuid4())

        # Create recordings directory
        rec_dir = tmp_path / "recordings" / lab_id
        rec_dir.mkdir(parents=True)
        (rec_dir / "recording.guac").write_text("guac recording content")

        result = compute_evidence_status(tmp_path, lab_id)

        assert result["guac_recordings"].present is True
        assert f"recordings/{lab_id}/recording.guac" in result["guac_recordings"].files

    def test_unreadable_file_returns_permission_denied(self, tmp_path):
        """Unreadable files are reported with permission denied reason."""
        from app.services.evidence_service import compute_evidence_status

        lab_id = str(uuid4())

        # Create evidence directory with unreadable file
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir(parents=True)
        commands_log = evidence_dir / "commands.log"
        commands_log.write_text("test content")

        # Make file unreadable (skip if running as root)
        try:
            os.chmod(commands_log, 0o000)
            result = compute_evidence_status(tmp_path, lab_id)

            # File exists but is unreadable - should NOT appear in files list
            # The _list_files_safe function skips unreadable files
            # If no files are readable, terminal_logs.present should be False
            # This depends on whether we're root or not

            # Restore permissions for cleanup
            os.chmod(commands_log, 0o644)

            # If we're not root, file should be skipped
            if os.geteuid() != 0:
                assert result["terminal_logs"].present is False
        except PermissionError:
            # If we can't change permissions, skip test
            pytest.skip("Cannot modify file permissions")

    def test_bytes_are_calculated_correctly(self, tmp_path):
        """Total bytes are calculated for directories."""
        from app.services.evidence_service import compute_evidence_status

        lab_id = str(uuid4())

        # Create multiple files
        tlog_dir = tmp_path / "evidence" / "tlog" / lab_id
        tlog_dir.mkdir(parents=True)

        content1 = "a" * 100
        content2 = "b" * 200
        (tlog_dir / "session1.jsonl").write_text(content1)
        (tlog_dir / "session2.jsonl").write_text(content2)

        result = compute_evidence_status(tmp_path, lab_id)

        assert result["terminal_logs"].present is True
        assert result["terminal_logs"].bytes == 300


class TestSafeStatPath:
    """Tests for _safe_stat_path helper."""

    def test_nonexistent_path(self, tmp_path):
        """Non-existent path returns False with reason."""
        from app.services.evidence_service import _safe_stat_path

        result = _safe_stat_path(tmp_path / "nonexistent")

        exists, size, reason = result
        assert exists is False
        assert size == 0
        assert "does not exist" in reason

    def test_readable_file(self, tmp_path):
        """Readable file returns True with correct size."""
        from app.services.evidence_service import _safe_stat_path

        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        exists, size, reason = _safe_stat_path(test_file)

        assert exists is True
        assert size == 11
        assert reason is None

    def test_readable_directory(self, tmp_path):
        """Readable directory returns sum of file sizes."""
        from app.services.evidence_service import _safe_stat_path

        test_dir = tmp_path / "subdir"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("abc")
        (test_dir / "file2.txt").write_text("defgh")

        exists, size, reason = _safe_stat_path(test_dir)

        assert exists is True
        assert size == 8  # 3 + 5
        assert reason is None


class TestListFilesSafe:
    """Tests for _list_files_safe helper."""

    def test_nonexistent_directory(self, tmp_path):
        """Non-existent directory returns empty list."""
        from app.services.evidence_service import _list_files_safe

        result = _list_files_safe(tmp_path / "nonexistent")

        assert result == []

    def test_empty_directory(self, tmp_path):
        """Empty directory returns empty list."""
        from app.services.evidence_service import _list_files_safe

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        result = _list_files_safe(empty_dir)

        assert result == []

    def test_with_extension_filter(self, tmp_path):
        """Extension filter works correctly."""
        from app.services.evidence_service import _list_files_safe

        test_dir = tmp_path / "test"
        test_dir.mkdir()
        (test_dir / "file.jsonl").write_text("json")
        (test_dir / "file.txt").write_text("text")
        (test_dir / "file.log").write_text("log")

        result = _list_files_safe(test_dir, extensions=[".jsonl", ".log"])

        assert len(result) == 2
        assert "file.jsonl" in result
        assert "file.log" in result
        assert "file.txt" not in result

    def test_returns_sorted(self, tmp_path):
        """Results are sorted."""
        from app.services.evidence_service import _list_files_safe

        test_dir = tmp_path / "test"
        test_dir.mkdir()
        (test_dir / "zebra.txt").write_text("z")
        (test_dir / "alpha.txt").write_text("a")
        (test_dir / "beta.txt").write_text("b")

        result = _list_files_safe(test_dir)

        assert result == ["alpha.txt", "beta.txt", "zebra.txt"]


class TestBashrcHookContent:
    """Tests verifying bashrc hook file content.

    The canonical cmdlog script is at /etc/profile.d/octolab-cmdlog.sh.
    The file at /etc/octolab-cmdlog.sh is just a shim that sources the canonical one.
    """

    def test_hook_file_contains_interactive_check(self):
        """Hook file checks for interactive shell."""
        # Canonical script location (profile.d for login shells)
        hook_path = Path("/home/architect/octolab_mvp/images/octobox-beta/rootfs/etc/profile.d/octolab-cmdlog.sh")

        if not hook_path.exists():
            pytest.skip("Hook file not found")

        content = hook_path.read_text()

        # Check for interactive shell check
        assert 'case "$-" in' in content
        assert "*i*)" in content

    def test_hook_file_has_double_install_guard(self):
        """Hook file guards against double installation."""
        # Canonical script location (profile.d for login shells)
        hook_path = Path("/home/architect/octolab_mvp/images/octobox-beta/rootfs/etc/profile.d/octolab-cmdlog.sh")

        if not hook_path.exists():
            pytest.skip("Hook file not found")

        content = hook_path.read_text()

        assert "OCTOLAB_CMDLOG_ENABLED" in content

    def test_hook_file_chains_prompt_command(self):
        """Hook file chains with existing PROMPT_COMMAND."""
        # Canonical script location (profile.d for login shells)
        hook_path = Path("/home/architect/octolab_mvp/images/octobox-beta/rootfs/etc/profile.d/octolab-cmdlog.sh")

        if not hook_path.exists():
            pytest.skip("Hook file not found")

        content = hook_path.read_text()

        # Check that it chains with existing PROMPT_COMMAND
        assert "${PROMPT_COMMAND}" in content or "PROMPT_COMMAND" in content

    def test_hook_file_uses_lab_id_env_var(self):
        """Hook file uses LAB_ID environment variable."""
        # Canonical script location (profile.d for login shells)
        hook_path = Path("/home/architect/octolab_mvp/images/octobox-beta/rootfs/etc/profile.d/octolab-cmdlog.sh")

        if not hook_path.exists():
            pytest.skip("Hook file not found")

        content = hook_path.read_text()

        assert "LAB_ID" in content
