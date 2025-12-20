"""Tests for safe tar extraction utilities.

Tests the security-critical extraction functions in app.utils.safe_extract:
- Path traversal rejection
- Symlink/hardlink/device rejection
- Size limit enforcement
- Permission stripping
- Ownership ignoring (files owned by current user, not tar uid/gid)
"""

import io
import os
import tarfile
import tempfile
from pathlib import Path

import pytest


def is_root() -> bool:
    """Check if running as root (UID 0)."""
    return os.geteuid() == 0

# Mark all tests in this module as not requiring database
pytestmark = pytest.mark.no_db

from app.utils.safe_extract import (
    ArchiveSizeLimitError,
    UnsafeArchiveError,
    safe_extract_tarfile_from_fileobj,
    safe_extract_tarfile_from_path,
)
from app.utils.fs import rmtree_hardened


@pytest.fixture
def temp_dir():
    """Create a temp directory for test extraction."""
    tmpdir = Path(tempfile.mkdtemp(prefix="test-safe-extract-"))
    yield tmpdir
    rmtree_hardened(tmpdir)


def create_tar_in_memory(members: list[tuple[str, bytes]]) -> io.BytesIO:
    """Create a tar archive in memory with given members."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, content in members:
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    buf.seek(0)
    return buf


def create_tar_with_symlink(target: str, link_name: str) -> io.BytesIO:
    """Create a tar archive containing a symlink."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo(name=link_name)
        info.type = tarfile.SYMTYPE
        info.linkname = target
        tf.addfile(info)
    buf.seek(0)
    return buf


def create_tar_with_hardlink(target: str, link_name: str) -> io.BytesIO:
    """Create a tar archive containing a hardlink."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        # First add a regular file as the target
        info = tarfile.TarInfo(name=target)
        info.size = 5
        tf.addfile(info, io.BytesIO(b"hello"))

        # Then add a hardlink to it
        info = tarfile.TarInfo(name=link_name)
        info.type = tarfile.LNKTYPE
        info.linkname = target
        tf.addfile(info)
    buf.seek(0)
    return buf


class TestSafeExtraction:
    """Tests for safe tar extraction."""

    def test_extract_normal_files(self, temp_dir: Path):
        """Test extraction of normal files works."""
        tar_buf = create_tar_in_memory([
            ("file1.txt", b"content1"),
            ("subdir/file2.txt", b"content2"),
        ])

        extracted = safe_extract_tarfile_from_fileobj(tar_buf, temp_dir, mode="r")

        assert "file1.txt" in extracted
        assert "subdir/file2.txt" in extracted
        assert (temp_dir / "file1.txt").read_bytes() == b"content1"
        assert (temp_dir / "subdir/file2.txt").read_bytes() == b"content2"

    def test_permissions_stripped(self, temp_dir: Path):
        """Test that files are extracted with secure permissions."""
        tar_buf = create_tar_in_memory([
            ("secret.txt", b"sensitive"),
        ])

        safe_extract_tarfile_from_fileobj(tar_buf, temp_dir, mode="r")

        file_path = temp_dir / "secret.txt"
        assert file_path.exists()
        # Should be 0o600 (owner read/write only)
        assert (file_path.stat().st_mode & 0o777) == 0o600


class TestPathTraversalRejection:
    """Tests for path traversal attack prevention."""

    def test_reject_absolute_path(self, temp_dir: Path):
        """Test that absolute paths are rejected."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo(name="/etc/passwd")
            info.size = 4
            tf.addfile(info, io.BytesIO(b"test"))
        buf.seek(0)

        with pytest.raises(UnsafeArchiveError, match="unsafe path"):
            safe_extract_tarfile_from_fileobj(buf, temp_dir, mode="r")

    def test_reject_dotdot_traversal(self, temp_dir: Path):
        """Test that ../ traversal is rejected."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo(name="../../../etc/passwd")
            info.size = 4
            tf.addfile(info, io.BytesIO(b"test"))
        buf.seek(0)

        with pytest.raises(UnsafeArchiveError, match="unsafe path"):
            safe_extract_tarfile_from_fileobj(buf, temp_dir, mode="r")

    def test_reject_embedded_dotdot(self, temp_dir: Path):
        """Test that embedded ../ is rejected."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo(name="foo/../../../etc/passwd")
            info.size = 4
            tf.addfile(info, io.BytesIO(b"test"))
        buf.seek(0)

        with pytest.raises(UnsafeArchiveError, match="unsafe path"):
            safe_extract_tarfile_from_fileobj(buf, temp_dir, mode="r")


class TestLinkRejection:
    """Tests for symlink and hardlink rejection."""

    def test_reject_symlink(self, temp_dir: Path):
        """Test that symlinks are rejected."""
        tar_buf = create_tar_with_symlink("/etc/passwd", "passwd_link")

        with pytest.raises(UnsafeArchiveError, match="symlink"):
            safe_extract_tarfile_from_fileobj(tar_buf, temp_dir, mode="r")

    def test_reject_hardlink(self, temp_dir: Path):
        """Test that hardlinks are rejected."""
        tar_buf = create_tar_with_hardlink("target.txt", "link.txt")

        with pytest.raises(UnsafeArchiveError, match="hardlink"):
            safe_extract_tarfile_from_fileobj(tar_buf, temp_dir, mode="r")

    def test_reject_device_file(self, temp_dir: Path):
        """Test that device files are rejected."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo(name="dev_null")
            info.type = tarfile.CHRTYPE
            info.devmajor = 1
            info.devminor = 3
            tf.addfile(info)
        buf.seek(0)

        with pytest.raises(UnsafeArchiveError, match="device"):
            safe_extract_tarfile_from_fileobj(buf, temp_dir, mode="r")

    def test_reject_fifo(self, temp_dir: Path):
        """Test that FIFOs are rejected."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo(name="my_fifo")
            info.type = tarfile.FIFOTYPE
            tf.addfile(info)
        buf.seek(0)

        with pytest.raises(UnsafeArchiveError, match="FIFO|device"):
            safe_extract_tarfile_from_fileobj(buf, temp_dir, mode="r")


class TestSizeLimits:
    """Tests for archive size limit enforcement."""

    def test_reject_oversized_member(self, temp_dir: Path):
        """Test that oversized individual files are rejected."""
        # Create a file larger than default max_member_bytes
        large_content = b"x" * (51 * 1024 * 1024)  # 51 MB
        tar_buf = create_tar_in_memory([("large.bin", large_content)])

        with pytest.raises(ArchiveSizeLimitError, match="exceeds size limit"):
            safe_extract_tarfile_from_fileobj(tar_buf, temp_dir, mode="r")

    def test_reject_oversized_total(self, temp_dir: Path):
        """Test that total archive size is limited."""
        # Create multiple files that together exceed the limit
        small_files = [
            (f"file{i}.bin", b"x" * (10 * 1024 * 1024))  # 10 MB each
            for i in range(30)  # 300 MB total
        ]
        tar_buf = create_tar_in_memory(small_files)

        with pytest.raises(ArchiveSizeLimitError, match="exceed.*limit"):
            safe_extract_tarfile_from_fileobj(tar_buf, temp_dir, mode="r")

    def test_custom_size_limits(self, temp_dir: Path):
        """Test that custom size limits are enforced."""
        content = b"x" * 1000  # 1 KB
        tar_buf = create_tar_in_memory([("file.bin", content)])

        # Should fail with 500 byte limit
        tar_buf.seek(0)
        with pytest.raises(ArchiveSizeLimitError):
            safe_extract_tarfile_from_fileobj(
                tar_buf, temp_dir, mode="r",
                max_member_bytes=500,
            )

        # Should succeed with 2000 byte limit
        tar_buf.seek(0)
        extracted = safe_extract_tarfile_from_fileobj(
            tar_buf, temp_dir, mode="r",
            max_member_bytes=2000,
        )
        assert "file.bin" in extracted


class TestFromPath:
    """Tests for extraction from file path."""

    def test_extract_from_path(self, temp_dir: Path):
        """Test extraction from a file path works."""
        # Create a tar file on disk
        tar_path = temp_dir / "test.tar"
        with tarfile.open(tar_path, "w") as tf:
            info = tarfile.TarInfo(name="test.txt")
            content = b"test content"
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))

        # Create extraction directory
        extract_dir = temp_dir / "extracted"
        extract_dir.mkdir()

        extracted = safe_extract_tarfile_from_path(tar_path, extract_dir)

        assert "test.txt" in extracted
        assert (extract_dir / "test.txt").read_bytes() == b"test content"

    def test_extract_gzip_tar(self, temp_dir: Path):
        """Test extraction of gzipped tar works."""
        tar_path = temp_dir / "test.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tf:
            info = tarfile.TarInfo(name="compressed.txt")
            content = b"compressed content"
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))

        extract_dir = temp_dir / "extracted"
        extract_dir.mkdir()

        extracted = safe_extract_tarfile_from_path(tar_path, extract_dir)

        assert "compressed.txt" in extracted


class TestOwnershipAndModeIgnored:
    """Tests for ignoring tar uid/gid/mode (files owned by current user)."""

    @pytest.mark.skipif(is_root(), reason="Test requires non-root user")
    def test_extracted_files_owned_by_current_user(self, temp_dir: Path):
        """Test that extracted files are owned by the current uid (not tar uid)."""
        # Create tar with root uid/gid
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo(name="root_owned.txt")
            info.size = 4
            info.uid = 0  # root
            info.gid = 0  # root
            tf.addfile(info, io.BytesIO(b"test"))
        buf.seek(0)

        safe_extract_tarfile_from_fileobj(buf, temp_dir, mode="r")

        file_path = temp_dir / "root_owned.txt"
        assert file_path.exists()

        # File should be owned by current user, not root
        stat_info = file_path.stat()
        assert stat_info.st_uid == os.geteuid(), "File should be owned by current user"
        assert stat_info.st_gid == os.getegid(), "File should belong to current group"

    def test_restrictive_tar_mode_ignored(self, temp_dir: Path):
        """Test that tar member mode 000 is ignored (file is readable due to 0o600)."""
        # Create tar with mode 000
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo(name="mode000.txt")
            info.size = 11
            info.mode = 0o000  # No permissions in tar
            tf.addfile(info, io.BytesIO(b"should read"))
        buf.seek(0)

        safe_extract_tarfile_from_fileobj(buf, temp_dir, mode="r")

        file_path = temp_dir / "mode000.txt"
        assert file_path.exists()

        # File should have 0o600, not 0o000 from tar
        mode = file_path.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got 0o{mode:03o}"

        # File should be readable
        content = file_path.read_text()
        assert content == "should read"

    def test_setuid_mode_stripped(self, temp_dir: Path):
        """Test that setuid/setgid bits from tar are stripped."""
        # Create tar with setuid bit
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo(name="setuid.txt")
            info.size = 4
            info.mode = 0o4755  # setuid
            tf.addfile(info, io.BytesIO(b"test"))
        buf.seek(0)

        safe_extract_tarfile_from_fileobj(buf, temp_dir, mode="r")

        file_path = temp_dir / "setuid.txt"
        assert file_path.exists()

        # File should have 0o600, setuid bit should be stripped
        mode = file_path.stat().st_mode & 0o7777
        assert mode == 0o600, f"Expected 0o600, got 0o{mode:04o}"

    @pytest.mark.skipif(is_root(), reason="Test requires non-root user")
    def test_directory_owned_by_current_user(self, temp_dir: Path):
        """Test that created directories are owned by current user."""
        # Create tar with directory and file
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            # Directory entry with root ownership
            dir_info = tarfile.TarInfo(name="subdir/")
            dir_info.type = tarfile.DIRTYPE
            dir_info.uid = 0
            dir_info.gid = 0
            tf.addfile(dir_info)

            # File in directory with root ownership
            info = tarfile.TarInfo(name="subdir/file.txt")
            info.size = 4
            info.uid = 0
            info.gid = 0
            tf.addfile(info, io.BytesIO(b"test"))
        buf.seek(0)

        safe_extract_tarfile_from_fileobj(buf, temp_dir, mode="r")

        dir_path = temp_dir / "subdir"
        file_path = temp_dir / "subdir" / "file.txt"

        assert dir_path.exists()
        assert file_path.exists()

        # Directory should be owned by current user
        dir_stat = dir_path.stat()
        assert dir_stat.st_uid == os.geteuid(), "Directory should be owned by current user"
        assert (dir_stat.st_mode & 0o777) == 0o700, "Directory should have mode 0o700"

        # File should be owned by current user
        file_stat = file_path.stat()
        assert file_stat.st_uid == os.geteuid(), "File should be owned by current user"


class TestDockerVolumeExtraction:
    """Integration tests for Docker volume extraction.

    These tests require Docker and will be skipped if Docker is not available.
    """

    @pytest.fixture
    def docker_available(self):
        """Check if Docker is available."""
        import subprocess
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
                shell=False,
            )
            return result.returncode == 0
        except Exception:
            return False

    @pytest.mark.skipif(
        not os.path.exists("/var/run/docker.sock"),
        reason="Docker socket not available"
    )
    def test_extract_volume_uses_hardened_container(self, temp_dir: Path, docker_available):
        """Test that volume extraction uses security-hardened container options."""
        if not docker_available:
            pytest.skip("Docker not available")

        import subprocess

        # Create a test volume
        volume_name = f"test_extract_{os.getpid()}"
        try:
            # Create volume
            subprocess.run(
                ["docker", "volume", "create", volume_name],
                capture_output=True,
                check=True,
                shell=False,
            )

            # Write test content via hardened container
            subprocess.run(
                [
                    "docker", "run", "--rm",
                    "--network", "none",
                    "--cap-drop", "ALL",
                    "--security-opt", "no-new-privileges",
                    "-v", f"{volume_name}:/dest",
                    "alpine:3.20",
                    "sh", "-c", "mkdir -p /dest/tlog/test-lab && echo 'test content' > /dest/tlog/test-lab/commands.tsv",
                ],
                capture_output=True,
                check=True,
                shell=False,
            )

            # Extract via tar stream (same method as evidence_service)
            # Note: BusyBox tar doesn't support --null, so we use xargs with -0
            result = subprocess.run(
                [
                    "docker", "run", "--rm",
                    "--network", "none",
                    "--cap-drop", "ALL",
                    "--security-opt", "no-new-privileges",
                    "-v", f"{volume_name}:/src:ro",
                    "alpine:3.20",
                    "sh", "-c", "cd /src && tar -cf - $(find . -type f)",
                ],
                capture_output=True,
                shell=False,
            )

            assert result.returncode == 0, f"Extraction failed: {result.stderr.decode()}"
            assert len(result.stdout) > 0, "No tar data returned"

            # Verify tar contains expected content
            tar_buf = io.BytesIO(result.stdout)
            with tarfile.open(fileobj=tar_buf, mode="r") as tf:
                members = tf.getnames()
                assert any("commands.tsv" in m for m in members), f"commands.tsv not in tar: {members}"

        finally:
            # Cleanup
            subprocess.run(
                ["docker", "volume", "rm", "-f", volume_name],
                capture_output=True,
                shell=False,
            )

    @pytest.mark.skipif(
        not os.path.exists("/var/run/docker.sock"),
        reason="Docker socket not available"
    )
    def test_extract_0700_dir_with_uid_1000(self, temp_dir: Path, docker_available):
        """Test that 0700 directories owned by UID 1000 can be read with --user 1000:1000.

        This is the critical test for the evidence bundler fix:
        - OctoBox creates /evidence/tlog/<lab_id>/ with mode 0700 owned by UID 1000
        - With --cap-drop ALL, root cannot bypass these permissions
        - We must run as --user 1000:1000 to read the files

        This test reproduces the exact issue reported by the user.
        """
        if not docker_available:
            pytest.skip("Docker not available")

        import subprocess

        volume_name = f"test_0700_perms_{os.getpid()}"
        lab_id = "test-lab-uuid"

        try:
            # Create volume
            subprocess.run(
                ["docker", "volume", "create", volume_name],
                capture_output=True,
                check=True,
                shell=False,
            )

            # Create tlog directory structure with 0700 permissions as UID 1000
            # This mimics what OctoBox does via the cmdlog hook
            # First create as root, then chown to 1000:1000, then write as 1000:1000
            subprocess.run(
                [
                    "docker", "run", "--rm",
                    "-v", f"{volume_name}:/evidence",
                    "alpine:3.20",
                    "sh", "-c",
                    f"mkdir -p /evidence/tlog/{lab_id} && "
                    f"chown -R 1000:1000 /evidence/tlog && "
                    f"chmod 0700 /evidence/tlog/{lab_id}",
                ],
                capture_output=True,
                check=True,
                shell=False,
            )
            # Now write files as UID 1000 (the file owner)
            subprocess.run(
                [
                    "docker", "run", "--rm",
                    "--user", "1000:1000",
                    "-v", f"{volume_name}:/evidence",
                    "alpine:3.20",
                    "sh", "-c",
                    f"echo '2025-01-01T12:00:00Z\\tpentester\\t/home\\techo hello' > /evidence/tlog/{lab_id}/commands.tsv && "
                    f"chmod 0600 /evidence/tlog/{lab_id}/commands.tsv",
                ],
                capture_output=True,
                check=True,
                shell=False,
            )

            # Verify: Running as non-matching UID (65532) should NOT be able to read
            # (This demonstrates the original bug with --cap-drop ALL)
            result_wrong_uid = subprocess.run(
                [
                    "docker", "run", "--rm",
                    "--network", "none",
                    "--cap-drop", "ALL",
                    "--security-opt", "no-new-privileges",
                    "--user", "65532:65532",  # Wrong UID - can't read
                    "-v", f"{volume_name}:/src:ro",
                    "alpine:3.20",
                    "sh", "-c",
                    f"cat /src/tlog/{lab_id}/commands.tsv 2>&1 || echo 'PERMISSION_DENIED'",
                ],
                capture_output=True,
                shell=False,
            )
            stdout_wrong = result_wrong_uid.stdout.decode()
            # Should fail with permission denied
            assert "PERMISSION_DENIED" in stdout_wrong or "Permission denied" in stdout_wrong, \
                f"Expected permission denied with wrong UID, got: {stdout_wrong}"

            # Verify: Running as UID 1000:1000 (file owner) SHOULD be able to read
            result_correct_uid = subprocess.run(
                [
                    "docker", "run", "--rm",
                    "--network", "none",
                    "--cap-drop", "ALL",
                    "--security-opt", "no-new-privileges",
                    "--pids-limit", "64",
                    "--memory", "128m",
                    "--user", "1000:1000",  # Correct UID - can read
                    "-v", f"{volume_name}:/src:ro",
                    "alpine:3.20",
                    "sh", "-c",
                    f"cd /src && tar -cf - $(find . -type f 2>/dev/null) 2>/dev/null",
                ],
                capture_output=True,
                shell=False,
            )

            assert result_correct_uid.returncode == 0, \
                f"Extraction with correct UID failed: {result_correct_uid.stderr.decode()}"
            assert len(result_correct_uid.stdout) > 0, "No tar data returned with correct UID"

            # Verify tar contains the commands.tsv file
            tar_buf = io.BytesIO(result_correct_uid.stdout)
            with tarfile.open(fileobj=tar_buf, mode="r") as tf:
                members = tf.getnames()
                assert any("commands.tsv" in m for m in members), \
                    f"commands.tsv not found in tar members: {members}"

                # Verify content is readable
                for member in tf.getmembers():
                    if "commands.tsv" in member.name:
                        f = tf.extractfile(member)
                        assert f is not None
                        content = f.read().decode()
                        assert "echo hello" in content, f"Expected content not found: {content}"

        finally:
            # Cleanup
            subprocess.run(
                ["docker", "volume", "rm", "-f", volume_name],
                capture_output=True,
                shell=False,
            )
