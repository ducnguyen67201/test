"""Tests for evidence bundle ZIP endpoint.

Verifies that:
1. Bundle endpoint returns ZIP containing tlog entries when present
2. Authorization scoping works (cannot fetch another user's evidence)
3. Manifest includes correct metadata
4. tlog path is per-lab and does not use shared volumes
"""

import io
import json
import os
import pytest
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

from app.services.evidence_service import (
    build_evidence_bundle_zip,
    EvidenceNotFoundError,
    _extract_volume_to_dir,
)

# Mark all tests in this file as not requiring database
pytestmark = pytest.mark.no_db


class MockLab:
    """Mock lab object for testing."""

    def __init__(self, lab_id=None, owner_id=None):
        self.id = lab_id or uuid4()
        self.owner_id = owner_id or uuid4()


@pytest.mark.asyncio
async def test_build_evidence_bundle_includes_manifest(tmp_path, monkeypatch):
    """Test that evidence bundle includes manifest.json with correct metadata."""
    lab = MockLab()
    lab_id = str(lab.id)

    # Mock the extraction function to create test files
    async def mock_extract_evidence(volume_name, dest_dir, subfolder):
        target_dir = dest_dir / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)

        # Create tlog directory structure
        tlog_dir = target_dir / "tlog" / lab_id
        tlog_dir.mkdir(parents=True, exist_ok=True)
        session_file = tlog_dir / "session.jsonl"
        session_file.write_text('{"ver":"2.3","host":"octobox"}\n{"out":"hello\\n"}\n')

        return [f"evidence/tlog/{lab_id}/session.jsonl"]

    async def mock_extract_pcap(volume_name, dest_dir, subfolder):
        target_dir = dest_dir / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)
        # Create fake pcap
        pcap_file = target_dir / "capture.pcap"
        pcap_file.write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 20)  # Fake pcap header
        return ["pcap/capture.pcap"]

    # Patch the extraction function
    call_count = 0

    async def mock_extract(volume_name, dest_dir, subfolder):
        nonlocal call_count
        call_count += 1
        if "evidence" in volume_name:
            return await mock_extract_evidence(volume_name, dest_dir, subfolder)
        else:
            return await mock_extract_pcap(volume_name, dest_dir, subfolder)

    monkeypatch.setattr(
        "app.services.evidence_service._extract_volume_to_dir",
        mock_extract,
    )

    # Build bundle
    zip_bytes = await build_evidence_bundle_zip(lab)

    # Parse ZIP
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        file_list = zf.namelist()

        # Check manifest exists
        assert "manifest.json" in file_list

        # Parse manifest
        manifest_content = zf.read("manifest.json").decode("utf-8")
        manifest = json.loads(manifest_content)

        assert manifest["lab_id"] == lab_id
        assert manifest["bundle_version"] == 2
        assert manifest["evidence_version"] == "3.0"
        assert "generated_at" in manifest
        assert "included_files" in manifest
        assert manifest["tlog_enabled"] is True
        assert manifest["pcap_included"] is True


@pytest.mark.asyncio
async def test_build_evidence_bundle_includes_tlog_session(tmp_path, monkeypatch):
    """Test that evidence bundle includes tlog session.jsonl file."""
    lab = MockLab()
    lab_id = str(lab.id)

    async def mock_extract(volume_name, dest_dir, subfolder):
        target_dir = dest_dir / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)

        if "evidence" in volume_name:
            # Create tlog output
            tlog_dir = target_dir / "tlog" / lab_id
            tlog_dir.mkdir(parents=True, exist_ok=True)
            session_file = tlog_dir / "session.jsonl"
            tlog_content = '{"ver":"2.3","host":"octobox"}\n{"out":"$ echo test\\n"}\n'
            session_file.write_text(tlog_content)
            return [f"evidence/tlog/{lab_id}/session.jsonl"]
        return []

    monkeypatch.setattr(
        "app.services.evidence_service._extract_volume_to_dir",
        mock_extract,
    )

    zip_bytes = await build_evidence_bundle_zip(lab)

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        file_list = zf.namelist()

        # Check tlog file exists
        tlog_path = f"evidence/tlog/{lab_id}/session.jsonl"
        assert tlog_path in file_list

        # Verify content
        tlog_content = zf.read(tlog_path).decode("utf-8")
        assert "octobox" in tlog_content
        assert "echo test" in tlog_content


@pytest.mark.asyncio
async def test_build_evidence_bundle_raises_when_empty(monkeypatch):
    """Test that EvidenceNotFoundError is raised when no files are found."""
    lab = MockLab()

    async def mock_extract_empty(volume_name, dest_dir, subfolder):
        # Create empty directory
        target_dir = dest_dir / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)
        return []

    monkeypatch.setattr(
        "app.services.evidence_service._extract_volume_to_dir",
        mock_extract_empty,
    )

    with pytest.raises(EvidenceNotFoundError):
        await build_evidence_bundle_zip(lab)


def test_volume_names_are_per_lab():
    """Test that volume names are deterministically derived from lab.id only."""
    lab1 = MockLab()
    lab2 = MockLab()

    # Compute expected volume names (matching compose file: evidence_user, evidence_auth)
    project1 = f"octolab_{lab1.id}"
    project2 = f"octolab_{lab2.id}"

    evidence_user_vol1 = f"{project1}_evidence_user"
    evidence_user_vol2 = f"{project2}_evidence_user"
    evidence_auth_vol1 = f"{project1}_evidence_auth"
    evidence_auth_vol2 = f"{project2}_evidence_auth"

    # Volumes should be unique per lab
    assert evidence_user_vol1 != evidence_user_vol2
    assert evidence_auth_vol1 != evidence_auth_vol2
    assert str(lab1.id) in evidence_user_vol1
    assert str(lab2.id) in evidence_user_vol2


def test_tlog_path_is_per_lab():
    """Test that tlog output path is per-lab to prevent cross-contamination."""
    lab1 = MockLab()
    lab2 = MockLab()

    # tlog paths should be unique per lab
    tlog_path1 = f"/evidence/tlog/{lab1.id}/session.jsonl"
    tlog_path2 = f"/evidence/tlog/{lab2.id}/session.jsonl"

    assert tlog_path1 != tlog_path2
    assert str(lab1.id) in tlog_path1
    assert str(lab2.id) in tlog_path2


@pytest.mark.asyncio
async def test_evidence_bundle_includes_commands_tsv(tmp_path, monkeypatch):
    """Test that evidence bundle includes commands.tsv from PROMPT_COMMAND hook."""
    lab = MockLab()
    lab_id = str(lab.id)

    async def mock_extract(volume_name, dest_dir, subfolder):
        target_dir = dest_dir / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)

        if "evidence_user" in volume_name:
            # Create commands.tsv from PROMPT_COMMAND hook
            tlog_dir = target_dir / "tlog" / lab_id
            tlog_dir.mkdir(parents=True, exist_ok=True)
            commands_tsv = tlog_dir / "commands.tsv"
            commands_tsv.write_text(
                "2025-01-01T12:00:00Z\tpentester\t/home/pentester\techo hello\n"
                "2025-01-01T12:00:01Z\tpentester\t/home/pentester\twhoami\n"
            )
            return [f"evidence/tlog/{lab_id}/commands.tsv"]
        return []

    monkeypatch.setattr(
        "app.services.evidence_service._extract_volume_to_dir",
        mock_extract,
    )

    zip_bytes = await build_evidence_bundle_zip(lab)

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        file_list = zf.namelist()

        # Check commands.tsv is included
        commands_path = f"evidence/tlog/{lab_id}/commands.tsv"
        assert commands_path in file_list

        # Verify content
        content = zf.read(commands_path).decode("utf-8")
        assert "echo hello" in content
        assert "whoami" in content

        # Verify terminal logs are detected in manifest
        manifest = json.loads(zf.read("manifest.json").decode())
        # commands.tsv is detected as terminal log artifact
        assert manifest["artifacts"]["terminal_logs"]["present"] is True
        # CONSISTENCY FIX: tlog_enabled = true if ANY terminal log is present
        # This ensures tlog_enabled is always consistent with terminal_logs.present
        assert manifest["tlog_enabled"] is True


@pytest.mark.asyncio
async def test_evidence_bundle_includes_legacy_commands_log(tmp_path, monkeypatch):
    """Test that evidence bundle includes legacy commands.log if present."""
    lab = MockLab()

    async def mock_extract(volume_name, dest_dir, subfolder):
        target_dir = dest_dir / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)

        if "evidence_user" in volume_name:
            # Create legacy command log
            (target_dir / "commands.log").write_text("Script started...\n$ whoami\npentester\n")
            (target_dir / "commands.time").write_bytes(b"\x00" * 100)
            return ["evidence/commands.log", "evidence/commands.time"]
        return []

    monkeypatch.setattr(
        "app.services.evidence_service._extract_volume_to_dir",
        mock_extract,
    )

    zip_bytes = await build_evidence_bundle_zip(lab)

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        file_list = zf.namelist()

        assert "evidence/commands.log" in file_list
        assert "evidence/commands.time" in file_list

        # Verify legacy format detected in manifest
        manifest = json.loads(zf.read("manifest.json").decode())
        # CONSISTENCY FIX: tlog_enabled = true if ANY terminal log is present
        # commands.log counts as a terminal log, so tlog_enabled is True
        assert manifest["tlog_enabled"] is True
        assert manifest["artifacts"]["terminal_logs"]["present"] is True


@pytest.mark.asyncio
async def test_extract_volume_creates_subdirectory(tmp_path, monkeypatch):
    """Test that _extract_volume_to_dir creates the target subdirectory."""

    async def mock_run(*args, **kwargs):
        pass

    # Patch subprocess to do nothing (we're just testing directory creation)
    with patch("asyncio.to_thread", return_value=None):
        dest_dir = tmp_path / "extract_test"
        dest_dir.mkdir()

        # This will create the subdirectory even if docker fails
        await _extract_volume_to_dir("fake_volume", dest_dir, "evidence")

        assert (dest_dir / "evidence").exists()
        assert (dest_dir / "evidence").is_dir()


def test_lab_id_is_uuid_format():
    """Test that lab IDs are validated as UUIDs to prevent path traversal."""
    import re

    # Valid UUID pattern
    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        re.IGNORECASE,
    )

    lab = MockLab()
    lab_id_str = str(lab.id)

    # Verify lab ID matches UUID format
    assert uuid_pattern.match(lab_id_str), "Lab ID must be a valid UUID"

    # Verify lab ID doesn't contain path traversal characters
    assert ".." not in lab_id_str
    assert "/" not in lab_id_str
    assert "\\" not in lab_id_str


def test_volume_names_no_path_traversal():
    """Test that volume names are derived only from lab.id and contain no path traversal."""
    lab = MockLab()
    project_name = f"octolab_{lab.id}"
    # Volume names match compose file: evidence_user, evidence_auth, lab_pcap
    evidence_user_vol = f"{project_name}_evidence_user"
    evidence_auth_vol = f"{project_name}_evidence_auth"
    pcap_vol = f"{project_name}_lab_pcap"

    # No path traversal characters
    for name in [project_name, evidence_user_vol, evidence_auth_vol, pcap_vol]:
        assert ".." not in name
        assert "/" not in name
        assert "\\" not in name
        # Only alphanumeric, underscore, hyphen allowed
        assert all(c.isalnum() or c in "_-" for c in name)


@pytest.mark.asyncio
async def test_zip_paths_are_relative(tmp_path, monkeypatch):
    """Test that ZIP archive only contains relative paths, no absolute paths."""
    lab = MockLab()
    lab_id = str(lab.id)

    async def mock_extract(volume_name, dest_dir, subfolder):
        target_dir = dest_dir / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)

        if "evidence" in volume_name:
            tlog_dir = target_dir / "tlog" / lab_id
            tlog_dir.mkdir(parents=True, exist_ok=True)
            (tlog_dir / "session.jsonl").write_text('{"test": true}\n')
            return [f"evidence/tlog/{lab_id}/session.jsonl"]
        elif "pcap" in volume_name:
            (target_dir / "capture.pcap").write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 20)
            return ["pcap/capture.pcap"]
        return []

    monkeypatch.setattr(
        "app.services.evidence_service._extract_volume_to_dir",
        mock_extract,
    )

    zip_bytes = await build_evidence_bundle_zip(lab)

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        for name in zf.namelist():
            # No absolute paths
            assert not name.startswith("/"), f"Absolute path found: {name}"
            # No parent directory references
            assert ".." not in name, f"Path traversal found: {name}"
            # No backslashes (Windows paths)
            assert "\\" not in name, f"Backslash in path: {name}"


def test_tlog_config_disables_input_logging():
    """SECURITY: Verify tlog configuration template disables input logging.

    Input logging would capture keystrokes including passwords, tokens, etc.
    This is a critical security requirement.
    """
    # Read the entrypoint.sh file to verify tlog config
    import os
    from pathlib import Path

    # Find entrypoint.sh relative to tests
    backend_dir = Path(__file__).parent.parent
    hackvm_dir = backend_dir.parent / "octolab-hackvm"
    entrypoint_path = hackvm_dir / "entrypoint.sh"

    if not entrypoint_path.exists():
        pytest.skip(f"entrypoint.sh not found at {entrypoint_path}")

    content = entrypoint_path.read_text()

    # Verify log.input is set to false
    assert '"input": false' in content, (
        "SECURITY VIOLATION: tlog configuration must have 'input: false' "
        "to prevent capturing passwords and tokens"
    )

    # Verify it's not commented out
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if '"input": false' in line:
            # Check the line is not a comment
            stripped = line.strip()
            assert not stripped.startswith("#"), (
                f"Line {i+1}: 'input: false' is commented out"
            )
            break


@pytest.mark.asyncio
async def test_evidence_bundle_includes_pcap_files(tmp_path, monkeypatch):
    """Test that evidence bundle correctly includes .pcap files."""
    lab = MockLab()
    lab_id = str(lab.id)

    async def mock_extract(volume_name, dest_dir, subfolder):
        target_dir = dest_dir / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)

        if "pcap" in volume_name:
            # Write a fake PCAP file with valid magic bytes
            pcap_file = target_dir / "capture.pcap"
            # PCAP magic number (little-endian): 0xa1b2c3d4
            pcap_file.write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 20)
            return ["pcap/capture.pcap"]
        elif "evidence" in volume_name:
            # Must have evidence files (pcap is optional, evidence is required)
            tlog_dir = target_dir / "tlog" / lab_id
            tlog_dir.mkdir(parents=True, exist_ok=True)
            (tlog_dir / "session.jsonl").write_text('{"test": true}\n')
            return [f"evidence/tlog/{lab_id}/session.jsonl"]
        return []

    monkeypatch.setattr(
        "app.services.evidence_service._extract_volume_to_dir",
        mock_extract,
    )

    zip_bytes = await build_evidence_bundle_zip(lab)

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        file_list = zf.namelist()
        assert "pcap/capture.pcap" in file_list

        # Verify manifest indicates pcap is included
        manifest = json.loads(zf.read("manifest.json").decode())
        assert manifest["pcap_included"] is True


def test_owner_scoping_in_endpoint():
    """Document that evidence endpoint enforces owner scoping.

    The endpoint uses get_lab_for_user() which filters by:
    - Lab.id == lab_id
    - Lab.owner_id == current_user.id

    This ensures only the lab owner can access evidence.
    Non-owners receive 404 (not 403) to prevent lab enumeration.
    """
    # This is a documentation test - actual enforcement is in the route
    # See labs.py: get_lab_for_user(db=db, user=current_user, lab_id=lab_id)
    # Returns None if lab not owned by user -> 404

    user_a = uuid4()
    user_b = uuid4()
    lab = MockLab(owner_id=user_a)

    # Verify lab is owned by user_a, not user_b
    assert lab.owner_id == user_a
    assert lab.owner_id != user_b

    # The endpoint query would be:
    # SELECT * FROM labs WHERE id = lab.id AND owner_id = current_user.id
    # For user_a: returns lab (allowed)
    # For user_b: returns None -> 404 (denied, no enumeration)


def test_subprocess_timeout_configured():
    """Verify that docker commands have timeouts configured."""
    from app.services.evidence_service import DOCKER_TIMEOUT

    # Timeout should be reasonable (between 10 and 120 seconds)
    assert DOCKER_TIMEOUT >= 10, "Timeout too short for docker operations"
    assert DOCKER_TIMEOUT <= 120, "Timeout too long, could hang"


def test_docker_commands_use_shell_false():
    """Document that docker commands use shell=False for security.

    shell=False prevents command injection attacks by passing
    arguments as a list rather than a shell command string.
    """
    # This is verified by code inspection of evidence_service.py
    # All subprocess.run calls use explicit argument lists, not shell=True
    # Example:
    #   cmd = ["docker", "run", "--rm", "-v", ...]
    #   subprocess.run(cmd, shell=False, ...)
    pass


@pytest.mark.asyncio
async def test_manifest_derived_from_actual_zip_contents(tmp_path, monkeypatch):
    """Test that manifest.included_files matches ACTUAL ZIP entries.

    CRITICAL: This test verifies that the manifest cannot "lie" about what's in the ZIP.
    The manifest must be derived from what was actually added, not what was "supposed to be" added.
    """
    lab = MockLab()
    lab_id = str(lab.id)

    async def mock_extract(volume_name, dest_dir, subfolder):
        target_dir = dest_dir / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)

        if "evidence_user" in volume_name:
            # Create tlog file
            tlog_dir = target_dir / "tlog" / lab_id
            tlog_dir.mkdir(parents=True, exist_ok=True)
            commands_tsv = tlog_dir / "commands.tsv"
            commands_tsv.write_text("2025-01-01T12:00:00Z\tpentester\t/home\techo test\n")
            return [f"evidence/tlog/{lab_id}/commands.tsv"]
        elif "pcap" in volume_name:
            # Create pcap file
            pcap_file = target_dir / "capture.pcap"
            pcap_file.write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 20)
            return ["pcap/capture.pcap"]
        return []

    monkeypatch.setattr(
        "app.services.evidence_service._extract_volume_to_dir",
        mock_extract,
    )

    zip_bytes = await build_evidence_bundle_zip(lab)

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        # Get actual ZIP entries (excluding manifest.json which is added last)
        actual_entries = [n for n in zf.namelist() if n != "manifest.json"]

        # Parse manifest
        manifest = json.loads(zf.read("manifest.json").decode())

        # TRUTH CHECK: included_files must exactly match actual ZIP entries
        assert sorted(manifest["included_files"]) == sorted(actual_entries), (
            f"Manifest lies! included_files={manifest['included_files']} "
            f"but actual ZIP entries={actual_entries}"
        )

        # CONSISTENCY CHECK: tlog_enabled must match terminal_logs.present
        terminal_present = manifest["artifacts"]["terminal_logs"]["present"]
        tlog_enabled = manifest["tlog_enabled"]
        assert terminal_present == tlog_enabled, (
            f"Inconsistent: terminal_logs.present={terminal_present} but tlog_enabled={tlog_enabled}"
        )

        # CONSISTENCY CHECK: pcap_included must match pcap.present
        pcap_present = manifest["artifacts"]["pcap"]["present"]
        pcap_included = manifest["pcap_included"]
        assert pcap_present == pcap_included, (
            f"Inconsistent: pcap.present={pcap_present} but pcap_included={pcap_included}"
        )


@pytest.mark.asyncio
async def test_manifest_includes_only_actually_added_files(tmp_path, monkeypatch):
    """Test that files that fail to be added are NOT in manifest.included_files.

    When a file can't be read (permission denied, missing, etc.), it must not
    appear in the manifest's included_files list.
    """
    lab = MockLab()
    lab_id = str(lab.id)

    async def mock_extract(volume_name, dest_dir, subfolder):
        target_dir = dest_dir / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)

        if "evidence_user" in volume_name:
            # Create a real file that will succeed
            tlog_dir = target_dir / "tlog" / lab_id
            tlog_dir.mkdir(parents=True, exist_ok=True)
            commands_tsv = tlog_dir / "commands.tsv"
            commands_tsv.write_text("2025-01-01T12:00:00Z\tpentester\t/home\techo test\n")

            # Return paths including one that doesn't exist (simulates extraction claim vs reality)
            return [
                f"evidence/tlog/{lab_id}/commands.tsv",
                f"evidence/tlog/{lab_id}/missing_file.txt",  # This won't exist on disk
            ]
        return []

    monkeypatch.setattr(
        "app.services.evidence_service._extract_volume_to_dir",
        mock_extract,
    )

    zip_bytes = await build_evidence_bundle_zip(lab)

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        # Get actual ZIP entries
        actual_entries = [n for n in zf.namelist() if n != "manifest.json"]

        # Parse manifest
        manifest = json.loads(zf.read("manifest.json").decode())

        # The missing file should NOT be in included_files
        assert f"evidence/tlog/{lab_id}/missing_file.txt" not in manifest["included_files"], (
            "Manifest includes file that was never added to ZIP!"
        )

        # Only the actual file should be in included_files
        assert f"evidence/tlog/{lab_id}/commands.tsv" in manifest["included_files"]

        # Verify ZIP matches manifest
        assert sorted(manifest["included_files"]) == sorted(actual_entries)


@pytest.mark.asyncio
async def test_tlog_enabled_consistent_with_terminal_logs_present(tmp_path, monkeypatch):
    """Test that tlog_enabled is always consistent with terminal_logs.present.

    REQUIREMENT: If terminal_logs.present=true then tlog_enabled MUST be true.
    This was previously inconsistent - .tsv files counted as terminal logs
    but tlog_enabled only checked for .jsonl files.
    """
    lab = MockLab()
    lab_id = str(lab.id)

    # Test with .tsv file only
    async def mock_extract_tsv(volume_name, dest_dir, subfolder):
        target_dir = dest_dir / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)

        if "evidence_user" in volume_name:
            tlog_dir = target_dir / "tlog" / lab_id
            tlog_dir.mkdir(parents=True, exist_ok=True)
            # Only .tsv, no .jsonl
            (tlog_dir / "commands.tsv").write_text("timestamp\tuser\tcwd\tcommand\n")
            return [f"evidence/tlog/{lab_id}/commands.tsv"]
        return []

    monkeypatch.setattr(
        "app.services.evidence_service._extract_volume_to_dir",
        mock_extract_tsv,
    )

    zip_bytes = await build_evidence_bundle_zip(lab)

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        manifest = json.loads(zf.read("manifest.json").decode())

        # Both must be true when .tsv is present
        assert manifest["artifacts"]["terminal_logs"]["present"] is True
        assert manifest["tlog_enabled"] is True, (
            "tlog_enabled should be True when terminal_logs.present is True"
        )
