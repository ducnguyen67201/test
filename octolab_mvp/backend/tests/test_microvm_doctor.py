"""Tests for standalone microvm_doctor module.

This module tests the microVM doctor health checks, ensuring they work
without requiring app.config/Settings (database_url, secret_key, etc.).

IMPORTANT: These tests should NOT import app.config or Settings.
"""

import os
import stat
import tempfile
from pathlib import Path
from unittest import mock

import pytest


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_kvm_available():
    """Mock /dev/kvm being available and writable."""
    with mock.patch("pathlib.Path.exists") as mock_exists:
        # Only mock /dev/kvm, let other paths through
        original_exists = Path.exists

        def exists_side_effect(self):
            if str(self) == "/dev/kvm":
                return True
            return original_exists(self)

        mock_exists.side_effect = exists_side_effect

        with mock.patch("builtins.open", mock.mock_open()) as mock_file:
            yield mock_file


@pytest.fixture
def valid_elf64_header():
    """Return a valid ELF64 header for use in tests."""
    # ELF magic: \x7fELF, then ELFCLASS64=2, ELFDATA2LSB=1, EV_CURRENT=1
    return b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8  # 16 bytes


@pytest.fixture
def minimal_env(temp_dir, valid_elf64_header):
    """Create a minimal environment with required paths."""
    kernel_path = temp_dir / "vmlinux"
    kernel_path.write_bytes(valid_elf64_header)  # Use valid ELF header

    rootfs_path = temp_dir / "rootfs.ext4"
    rootfs_path.write_bytes(b"fake rootfs")

    state_dir = temp_dir / "microvm"
    state_dir.mkdir()

    return {
        "MICROVM_KERNEL_PATH": str(kernel_path),
        "MICROVM_ROOTFS_BASE_PATH": str(rootfs_path),
        "MICROVM_STATE_DIR": str(state_dir),
    }


# =============================================================================
# Test: Module imports without app.config
# =============================================================================


@pytest.mark.no_db
def test_import_without_app_config():
    """Verify microvm_doctor can be imported without app.config."""
    # This should NOT raise ImportError or require database_url/secret_key
    from app.services.microvm_doctor import run_checks, get_fatal_summary

    # Basic sanity check
    assert callable(run_checks)
    assert callable(get_fatal_summary)


# =============================================================================
# Test: Missing environment variables
# =============================================================================


@pytest.mark.no_db
def test_missing_kernel_path_is_fatal():
    """Missing MICROVM_KERNEL_PATH should be fatal."""
    from app.services.microvm_doctor import run_checks

    # Empty env = no kernel path set
    result = run_checks(env={})

    kernel_check = next(
        (c for c in result["checks"] if c["name"] == "kernel"), None
    )
    assert kernel_check is not None
    assert kernel_check["status"] == "FAIL"
    assert kernel_check["severity"] == "fatal"
    assert "not set" in kernel_check["message"].lower()


@pytest.mark.no_db
def test_missing_rootfs_path_is_fatal():
    """Missing MICROVM_ROOTFS_BASE_PATH should be fatal."""
    from app.services.microvm_doctor import run_checks

    result = run_checks(env={})

    rootfs_check = next(
        (c for c in result["checks"] if c["name"] == "rootfs"), None
    )
    assert rootfs_check is not None
    assert rootfs_check["status"] == "FAIL"
    assert rootfs_check["severity"] == "fatal"
    assert "not set" in rootfs_check["message"].lower()


@pytest.mark.no_db
def test_missing_state_dir_is_fatal():
    """Missing/non-existent state_dir should be fatal."""
    from app.services.microvm_doctor import run_checks

    # Use a non-existent directory
    env = {"MICROVM_STATE_DIR": "/nonexistent/path/to/microvm"}
    result = run_checks(env=env)

    state_check = next(
        (c for c in result["checks"] if c["name"] == "state_dir"), None
    )
    assert state_check is not None
    assert state_check["status"] == "FAIL"
    assert state_check["severity"] == "fatal"


# =============================================================================
# Test: Environment variable fallbacks
# =============================================================================


@pytest.mark.no_db
def test_env_var_fallback_kernel(temp_dir, valid_elf64_header):
    """Test fallback from OCTOLAB_MICROVM_KERNEL_PATH to MICROVM_KERNEL_PATH."""
    from app.services.microvm_doctor import run_checks

    kernel_path = temp_dir / "vmlinux"
    kernel_path.write_bytes(valid_elf64_header)  # Use valid ELF header

    # Use the non-prefixed version
    env = {"MICROVM_KERNEL_PATH": str(kernel_path)}
    result = run_checks(env=env)

    kernel_check = next(
        (c for c in result["checks"] if c["name"] == "kernel"), None
    )
    assert kernel_check is not None
    assert kernel_check["status"] == "OK"


@pytest.mark.no_db
def test_env_var_primary_takes_precedence(temp_dir, valid_elf64_header):
    """OCTOLAB_MICROVM_KERNEL_PATH takes precedence over MICROVM_KERNEL_PATH."""
    from app.services.microvm_doctor import run_checks

    kernel_path1 = temp_dir / "vmlinux1"
    kernel_path1.write_bytes(valid_elf64_header)  # Use valid ELF header
    kernel_path2 = temp_dir / "vmlinux2"
    kernel_path2.write_bytes(valid_elf64_header)  # Use valid ELF header

    # Primary should take precedence
    env = {
        "OCTOLAB_MICROVM_KERNEL_PATH": str(kernel_path1),
        "MICROVM_KERNEL_PATH": str(kernel_path2),
    }
    result = run_checks(env=env, debug=True)

    kernel_check = next(
        (c for c in result["checks"] if c["name"] == "kernel"), None
    )
    assert kernel_check is not None
    assert kernel_check["status"] == "OK"
    # In debug mode, full path is shown
    assert "vmlinux1" in kernel_check["message"]


# =============================================================================
# Test: File existence and permissions
# =============================================================================


@pytest.mark.no_db
def test_kernel_file_not_found_is_fatal(temp_dir):
    """Kernel file that doesn't exist should be fatal."""
    from app.services.microvm_doctor import run_checks

    env = {"MICROVM_KERNEL_PATH": str(temp_dir / "nonexistent_kernel")}
    result = run_checks(env=env)

    kernel_check = next(
        (c for c in result["checks"] if c["name"] == "kernel"), None
    )
    assert kernel_check is not None
    assert kernel_check["status"] == "FAIL"
    assert kernel_check["severity"] == "fatal"
    assert "not found" in kernel_check["message"].lower()


@pytest.mark.no_db
def test_kernel_is_directory_is_fatal(temp_dir):
    """Kernel path that is a directory should be fatal."""
    from app.services.microvm_doctor import run_checks

    kernel_dir = temp_dir / "kernel_dir"
    kernel_dir.mkdir()

    env = {"MICROVM_KERNEL_PATH": str(kernel_dir)}
    result = run_checks(env=env)

    kernel_check = next(
        (c for c in result["checks"] if c["name"] == "kernel"), None
    )
    assert kernel_check is not None
    assert kernel_check["status"] == "FAIL"
    assert kernel_check["severity"] == "fatal"
    assert "not a file" in kernel_check["message"].lower()


@pytest.mark.no_db
def test_state_dir_not_writable_is_fatal(temp_dir):
    """State dir that's not writable should be fatal."""
    from app.services.microvm_doctor import run_checks

    state_dir = temp_dir / "readonly_state"
    state_dir.mkdir()
    # Make read-only
    state_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)

    try:
        env = {"MICROVM_STATE_DIR": str(state_dir)}
        result = run_checks(env=env)

        state_check = next(
            (c for c in result["checks"] if c["name"] == "state_dir"), None
        )
        assert state_check is not None
        assert state_check["status"] == "FAIL"
        assert state_check["severity"] == "fatal"
        assert "not writable" in state_check["message"].lower()
    finally:
        # Restore permissions for cleanup
        state_dir.chmod(stat.S_IRWXU)


@pytest.mark.no_db
def test_state_dir_world_writable_is_warn(temp_dir):
    """State dir that's world-writable should be a warning."""
    from app.services.microvm_doctor import run_checks

    state_dir = temp_dir / "world_writable"
    state_dir.mkdir()
    state_dir.chmod(stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)

    try:
        env = {"MICROVM_STATE_DIR": str(state_dir)}
        result = run_checks(env=env)

        state_check = next(
            (c for c in result["checks"] if c["name"] == "state_dir"), None
        )
        assert state_check is not None
        assert state_check["status"] == "WARN"
        assert state_check["severity"] == "warn"
        assert "world-writable" in state_check["message"].lower()
    finally:
        state_dir.chmod(stat.S_IRWXU)


# =============================================================================
# Test: Firecracker binary check
# =============================================================================


@pytest.mark.no_db
def test_firecracker_binary_not_found_is_fatal():
    """Missing firecracker binary should be fatal."""
    from app.services.microvm_doctor import run_checks

    # Use a non-existent path
    env = {"OCTOLAB_MICROVM_FIRECRACKER_BIN": "/nonexistent/firecracker"}
    result = run_checks(env=env)

    fc_check = next(
        (c for c in result["checks"] if c["name"] == "firecracker"), None
    )
    assert fc_check is not None
    assert fc_check["status"] == "FAIL"
    assert fc_check["severity"] == "fatal"


@pytest.mark.no_db
def test_firecracker_binary_success(temp_dir):
    """Firecracker binary that works should pass."""
    from app.services.microvm_doctor import _check_firecracker_binary

    # Create a fake firecracker binary that outputs a version
    fc_bin = temp_dir / "firecracker"
    fc_bin.write_text("#!/bin/bash\necho 'Firecracker v1.7.0'\n")
    fc_bin.chmod(stat.S_IRWXU)

    env = {"OCTOLAB_MICROVM_FIRECRACKER_BIN": str(fc_bin)}

    with mock.patch(
        "app.services.microvm_doctor._run_cmd_safe",
        return_value=(0, "Firecracker v1.7.0", ""),
    ):
        result = _check_firecracker_binary(env)

    assert result["status"] == "OK"
    # Version is parsed from first word of output
    assert "Firecracker" in result["message"] or "firecracker" in result["message"]


@pytest.mark.no_db
def test_firecracker_version_fails_is_fatal(temp_dir):
    """Firecracker binary that fails --version should be fatal."""
    from app.services.microvm_doctor import _check_firecracker_binary

    # Create a binary that exists but fails
    fc_bin = temp_dir / "firecracker"
    fc_bin.write_bytes(b"not a real binary")
    fc_bin.chmod(stat.S_IRWXU)

    env = {"OCTOLAB_MICROVM_FIRECRACKER_BIN": str(fc_bin)}

    with mock.patch(
        "app.services.microvm_doctor._run_cmd_safe",
        return_value=(1, "", "error"),
    ):
        result = _check_firecracker_binary(env)

    assert result["status"] == "FAIL"
    assert result["severity"] == "fatal"


# =============================================================================
# Test: Jailer check (WARN not FATAL)
# =============================================================================


@pytest.mark.no_db
def test_jailer_missing_is_warn():
    """Missing jailer should be WARN, not FATAL."""
    from app.services.microvm_doctor import _check_jailer_binary

    env = {"OCTOLAB_MICROVM_JAILER_BIN": "/nonexistent/jailer"}
    result = _check_jailer_binary(env)

    assert result["status"] == "WARN"
    assert result["severity"] == "warn"


@pytest.mark.no_db
def test_jailer_missing_with_dev_override_is_warn():
    """Missing jailer with DEV_UNSAFE_ALLOW_NO_JAILER should be WARN."""
    from app.services.microvm_doctor import _check_jailer_binary

    env = {
        "OCTOLAB_MICROVM_JAILER_BIN": "/nonexistent/jailer",
        "DEV_UNSAFE_ALLOW_NO_JAILER": "true",
    }
    # Need to mock is_wsl to return False so dev override is used
    with mock.patch("app.services.microvm_doctor._is_wsl", return_value=False):
        result = _check_jailer_binary(env)

    assert result["status"] == "WARN"
    assert "UNSAFE" in result["message"] or "DEV" in result["message"]


# =============================================================================
# Test: Summary and is_ok
# =============================================================================


@pytest.mark.no_db
def test_summary_counts(temp_dir, minimal_env):
    """Summary should count OK/WARN/FAIL correctly."""
    from app.services.microvm_doctor import run_checks

    # With minimal_env, kernel/rootfs/state_dir should pass
    # But kvm/firecracker will likely fail (unless mocked)
    result = run_checks(env=minimal_env)

    summary = result["summary"]
    total = summary["ok"] + summary["warn"] + summary["fail"]
    assert total == len(result["checks"])


@pytest.mark.no_db
def test_is_ok_false_with_fatal():
    """is_ok should be False when there are fatal failures."""
    from app.services.microvm_doctor import run_checks

    # Empty env = missing kernel/rootfs/etc = fatal
    result = run_checks(env={})

    assert result["is_ok"] is False
    assert result["summary"]["fatal"] > 0


@pytest.mark.no_db
def test_is_ok_true_with_only_warnings(temp_dir, valid_elf64_header):
    """is_ok should be True when there are only warnings (no fatal)."""
    from app.services.microvm_doctor import run_checks

    # Create all required files
    kernel_path = temp_dir / "vmlinux"
    kernel_path.write_bytes(valid_elf64_header)  # Use valid ELF header
    rootfs_path = temp_dir / "rootfs.ext4"
    rootfs_path.write_bytes(b"rootfs")
    state_dir = temp_dir / "microvm"
    state_dir.mkdir()

    # Create fake firecracker binary
    fc_bin = temp_dir / "firecracker"
    fc_bin.write_text("#!/bin/bash\necho 'Firecracker v1.7.0'\n")
    fc_bin.chmod(stat.S_IRWXU)

    env = {
        "MICROVM_KERNEL_PATH": str(kernel_path),
        "MICROVM_ROOTFS_BASE_PATH": str(rootfs_path),
        "MICROVM_STATE_DIR": str(state_dir),
        "OCTOLAB_MICROVM_FIRECRACKER_BIN": str(fc_bin),
    }

    # Mock the checks that would fail in test environment
    with mock.patch(
        "app.services.microvm_doctor._check_kvm",
        return_value={
            "name": "kvm",
            "status": "OK",
            "severity": "info",
            "message": "/dev/kvm accessible",
            "hint": None,
        },
    ), mock.patch(
        "app.services.microvm_doctor._run_cmd_safe",
        return_value=(0, "Firecracker v1.7.0", ""),
    ), mock.patch(
        "app.services.microvm_doctor._check_netd",
        return_value={
            "name": "netd",
            "status": "OK",
            "severity": "info",
            "message": "netd running",
            "hint": None,
        },
    ):
        result = run_checks(env=env)

    # Should have no fatal failures
    assert result["summary"]["fatal"] == 0
    assert result["is_ok"] is True


# =============================================================================
# Test: get_fatal_summary
# =============================================================================


@pytest.mark.no_db
def test_get_fatal_summary_empty():
    """get_fatal_summary should return 'no fatal issues' when none."""
    from app.services.microvm_doctor import get_fatal_summary

    result = {
        "checks": [
            {"name": "test", "status": "OK", "severity": "info", "message": "ok", "hint": None},
        ],
        "summary": {"ok": 1, "warn": 0, "fail": 0, "fatal": 0},
        "is_ok": True,
        "generated_at": "2024-01-01T00:00:00Z",
    }

    summary = get_fatal_summary(result)
    assert summary == "no fatal issues"


@pytest.mark.no_db
def test_get_fatal_summary_with_failures():
    """get_fatal_summary should list fatal check names and hints."""
    from app.services.microvm_doctor import get_fatal_summary

    result = {
        "checks": [
            {
                "name": "kernel",
                "status": "FAIL",
                "severity": "fatal",
                "message": "kernel not found",
                "hint": "Set MICROVM_KERNEL_PATH",
            },
            {
                "name": "rootfs",
                "status": "FAIL",
                "severity": "fatal",
                "message": "rootfs not found",
                "hint": "Set MICROVM_ROOTFS_BASE_PATH",
            },
        ],
        "summary": {"ok": 0, "warn": 0, "fail": 2, "fatal": 2},
        "is_ok": False,
        "generated_at": "2024-01-01T00:00:00Z",
    }

    summary = get_fatal_summary(result)
    assert "kernel" in summary
    assert "rootfs" in summary


# =============================================================================
# Test: Path redaction
# =============================================================================


@pytest.mark.no_db
def test_path_redaction_default(temp_dir, valid_elf64_header):
    """By default, paths should be redacted (only basename shown)."""
    from app.services.microvm_doctor import run_checks

    kernel_path = temp_dir / "my_kernel_file"
    kernel_path.write_bytes(valid_elf64_header)  # Use valid ELF header

    env = {"MICROVM_KERNEL_PATH": str(kernel_path)}
    result = run_checks(env=env, debug=False)

    kernel_check = next(
        (c for c in result["checks"] if c["name"] == "kernel"), None
    )
    assert kernel_check is not None
    # Should NOT contain the full temp_dir path
    assert str(temp_dir) not in kernel_check["message"]
    # Should contain the basename
    assert "my_kernel_file" in kernel_check["message"]


@pytest.mark.no_db
def test_path_not_redacted_in_debug(temp_dir, valid_elf64_header):
    """In debug mode, full paths should be shown."""
    from app.services.microvm_doctor import run_checks

    kernel_path = temp_dir / "my_kernel_file"
    kernel_path.write_bytes(valid_elf64_header)  # Use valid ELF header

    env = {"MICROVM_KERNEL_PATH": str(kernel_path)}
    result = run_checks(env=env, debug=True)

    kernel_check = next(
        (c for c in result["checks"] if c["name"] == "kernel"), None
    )
    assert kernel_check is not None
    # In debug mode, full path is shown
    assert str(kernel_path) in kernel_check["message"]


# =============================================================================
# Test: CLI main function
# =============================================================================


@pytest.mark.no_db
def test_cli_exit_code_success():
    """CLI should exit 0 when all critical checks pass."""
    from app.services.microvm_doctor import main

    # Mock run_checks to return success
    with mock.patch(
        "app.services.microvm_doctor.run_checks",
        return_value={
            "checks": [],
            "summary": {"ok": 7, "warn": 0, "fail": 0, "fatal": 0},
            "is_ok": True,
            "generated_at": "2024-01-01T00:00:00Z",
        },
    ), mock.patch("sys.argv", ["microvm_doctor", "--json"]):
        exit_code = main()

    assert exit_code == 0


@pytest.mark.no_db
def test_cli_exit_code_fatal():
    """CLI should exit 2 when there are fatal failures."""
    from app.services.microvm_doctor import main

    # Mock run_checks to return fatal failure
    with mock.patch(
        "app.services.microvm_doctor.run_checks",
        return_value={
            "checks": [
                {"name": "kvm", "status": "FAIL", "severity": "fatal", "message": "missing", "hint": None},
            ],
            "summary": {"ok": 0, "warn": 0, "fail": 1, "fatal": 1},
            "is_ok": False,
            "generated_at": "2024-01-01T00:00:00Z",
        },
    ), mock.patch("sys.argv", ["microvm_doctor", "--json"]):
        exit_code = main()

    assert exit_code == 2


# =============================================================================
# Test: vsock check (WARN only)
# =============================================================================


@pytest.mark.no_db
def test_vsock_missing_is_warn():
    """Missing vsock should be WARN, not FATAL."""
    from app.services.microvm_doctor import _check_vsock

    with mock.patch("pathlib.Path.exists", return_value=False), mock.patch(
        "app.services.microvm_doctor._run_cmd_safe",
        return_value=(0, "", ""),  # No vhost_vsock in lsmod
    ):
        result = _check_vsock({})

    assert result["status"] == "WARN"
    assert result["severity"] == "warn"


@pytest.mark.no_db
def test_vsock_present_is_ok():
    """Present /dev/vsock should be OK."""
    from app.services.microvm_doctor import _check_vsock

    with mock.patch("pathlib.Path.exists", return_value=True):
        result = _check_vsock({})

    assert result["status"] == "OK"


# =============================================================================
# Test: Kernel ELF Magic Check (Slice: smoke truth + self-heal)
# =============================================================================


@pytest.mark.no_db
def test_kernel_elf_magic_valid(temp_dir):
    """Valid ELF64 kernel should pass."""
    from app.services.microvm_doctor import _check_kernel_path

    # Create a fake ELF64 kernel (valid header)
    # ELF magic: \x7fELF, then ELFCLASS64=2, ELFDATA2LSB=1, EV_CURRENT=1
    kernel_path = temp_dir / "vmlinux"
    elf_header = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8  # 16 bytes ELF header
    kernel_path.write_bytes(elf_header)

    env = {"MICROVM_KERNEL_PATH": str(kernel_path)}
    result = _check_kernel_path(env)

    assert result["status"] == "OK"
    assert "valid ELF64" in result["message"].lower() or "elf64" in result["message"].lower()


@pytest.mark.no_db
def test_kernel_elf_magic_invalid_magic(temp_dir):
    """Non-ELF file should fail."""
    from app.services.microvm_doctor import _check_kernel_path

    # Create a file with wrong magic
    kernel_path = temp_dir / "vmlinux"
    kernel_path.write_bytes(b"MZ" + b"\x00" * 14)  # DOS/PE header

    env = {"MICROVM_KERNEL_PATH": str(kernel_path)}
    result = _check_kernel_path(env)

    assert result["status"] == "FAIL"
    assert result["severity"] == "fatal"
    assert "not elf" in result["message"].lower() or "elf format" in result["message"].lower()


@pytest.mark.no_db
def test_kernel_elf_magic_bzimage(temp_dir):
    """Compressed bzImage should fail (not uncompressed vmlinux)."""
    from app.services.microvm_doctor import _check_kernel_path

    # bzImage typically starts with different bytes
    kernel_path = temp_dir / "bzImage"
    kernel_path.write_bytes(b"\x1f\x8b\x08\x00" + b"\x00" * 12)  # gzip header

    env = {"MICROVM_KERNEL_PATH": str(kernel_path)}
    result = _check_kernel_path(env)

    assert result["status"] == "FAIL"
    assert result["severity"] == "fatal"
    # Hint should mention vmlinux
    assert "hint" in result and result["hint"] is not None
    assert "vmlinux" in result["hint"].lower() or "bzimage" in result["hint"].lower()


@pytest.mark.no_db
def test_kernel_elf_magic_32bit_fails(temp_dir):
    """32-bit ELF should fail (Firecracker needs 64-bit)."""
    from app.services.microvm_doctor import _check_kernel_path

    # Create a 32-bit ELF (ELFCLASS32 = 1)
    kernel_path = temp_dir / "vmlinux"
    elf_header = b"\x7fELF\x01\x01\x01\x00" + b"\x00" * 8  # ELFCLASS32 = 1
    kernel_path.write_bytes(elf_header)

    env = {"MICROVM_KERNEL_PATH": str(kernel_path)}
    result = _check_kernel_path(env)

    assert result["status"] == "FAIL"
    assert result["severity"] == "fatal"
    assert "32-bit" in result["message"].lower() or "64-bit" in result["message"].lower()


@pytest.mark.no_db
def test_kernel_elf_magic_truncated(temp_dir):
    """Truncated file should fail."""
    from app.services.microvm_doctor import _check_kernel_path

    # Create a file too small to be a valid ELF
    kernel_path = temp_dir / "vmlinux"
    kernel_path.write_bytes(b"\x7fELF")  # Only 4 bytes

    env = {"MICROVM_KERNEL_PATH": str(kernel_path)}
    result = _check_kernel_path(env)

    assert result["status"] == "FAIL"
    assert result["severity"] == "fatal"
    assert "small" in result["message"].lower() or "truncated" in result["hint"].lower()


@pytest.mark.no_db
def test_kernel_elf_magic_in_full_check(temp_dir):
    """Integration test: run_checks should verify ELF format."""
    from app.services.microvm_doctor import run_checks

    # Create files
    kernel_path = temp_dir / "vmlinux"
    kernel_path.write_bytes(b"not elf content but some padding" * 10)  # Not ELF

    rootfs_path = temp_dir / "rootfs.ext4"
    rootfs_path.write_bytes(b"fake rootfs")

    state_dir = temp_dir / "microvm"
    state_dir.mkdir()

    env = {
        "MICROVM_KERNEL_PATH": str(kernel_path),
        "MICROVM_ROOTFS_BASE_PATH": str(rootfs_path),
        "MICROVM_STATE_DIR": str(state_dir),
    }

    result = run_checks(env=env)

    kernel_check = next(
        (c for c in result["checks"] if c["name"] == "kernel"), None
    )
    assert kernel_check is not None
    assert kernel_check["status"] == "FAIL"
    assert "not elf" in kernel_check["message"].lower() or "elf format" in kernel_check["message"].lower()
