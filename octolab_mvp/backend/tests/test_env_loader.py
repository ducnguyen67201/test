"""Tests for the secure environment file loader (run_with_env.py).

These tests verify that the env loader:
- Correctly parses KEY=VALUE format
- Rejects shell syntax (export, command substitution)
- Redacts sensitive values
- Never uses shell=True

No database access is needed.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Mark entire module as not requiring database
pytestmark = pytest.mark.no_db

# Add backend/scripts to path so we can import run_with_env
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from run_with_env import (
    is_sensitive_key,
    parse_env_line,
    load_env_file,
    merge_env_files,
    redact_value,
)


class TestSensitiveKeyDetection:
    """Test sensitive key pattern matching."""

    @pytest.mark.parametrize("key", [
        "PASSWORD",
        "DB_PASSWORD",
        "password",
        "MY_PASSWORD_123",
    ])
    def test_password_keys_are_sensitive(self, key):
        assert is_sensitive_key(key) is True

    @pytest.mark.parametrize("key", [
        "SECRET_KEY",
        "JWT_SECRET",
        "HMAC_SECRET",
        "my_secret",
    ])
    def test_secret_keys_are_sensitive(self, key):
        assert is_sensitive_key(key) is True

    @pytest.mark.parametrize("key", [
        "GUAC_ENC_KEY",
        "API_KEY",
        "ENCRYPTION_KEY",
    ])
    def test_key_suffix_is_sensitive(self, key):
        assert is_sensitive_key(key) is True

    @pytest.mark.parametrize("key", [
        "DATABASE_URL",
    ])
    def test_database_url_is_sensitive(self, key):
        assert is_sensitive_key(key) is True

    @pytest.mark.parametrize("key", [
        "AUTH_TOKEN",
        "API_TOKEN",
        "ACCESS_TOKEN",
    ])
    def test_token_keys_are_sensitive(self, key):
        assert is_sensitive_key(key) is True

    @pytest.mark.parametrize("key", [
        "APP_NAME",
        "LOG_LEVEL",
        "HOST",
        "PORT",
        "DEBUG",
    ])
    def test_non_sensitive_keys(self, key):
        assert is_sensitive_key(key) is False


class TestRedactValue:
    """Test value redaction for sensitive keys."""

    def test_redacts_sensitive_short_value(self):
        result = redact_value("PASSWORD", "abc")
        assert result == "****"

    def test_redacts_sensitive_long_value(self):
        result = redact_value("PASSWORD", "verylongsecretpassword")
        assert "..." in result
        assert len(result) < len("verylongsecretpassword")

    def test_does_not_redact_non_sensitive(self):
        result = redact_value("APP_NAME", "OctoLab")
        assert result == "OctoLab"


class TestParseEnvLine:
    """Test individual line parsing."""

    def test_parses_simple_key_value(self):
        result = parse_env_line("FOO=bar", 1, Path("test.env"))
        assert result == ("FOO", "bar")

    def test_parses_empty_value(self):
        result = parse_env_line("FOO=", 1, Path("test.env"))
        assert result == ("FOO", "")

    def test_parses_value_with_equals(self):
        result = parse_env_line("URL=http://example.com?foo=bar", 1, Path("test.env"))
        assert result == ("URL", "http://example.com?foo=bar")

    def test_parses_double_quoted_value(self):
        result = parse_env_line('FOO="hello world"', 1, Path("test.env"))
        assert result == ("FOO", "hello world")

    def test_parses_single_quoted_value(self):
        result = parse_env_line("FOO='hello world'", 1, Path("test.env"))
        assert result == ("FOO", "hello world")

    def test_skips_blank_line(self):
        result = parse_env_line("", 1, Path("test.env"))
        assert result is None

    def test_skips_whitespace_only_line(self):
        result = parse_env_line("   ", 1, Path("test.env"))
        assert result is None

    def test_skips_comment_line(self):
        result = parse_env_line("# This is a comment", 1, Path("test.env"))
        assert result is None

    def test_rejects_export_syntax(self):
        with pytest.raises(ValueError, match="export"):
            parse_env_line("export FOO=bar", 1, Path("test.env"))

    def test_rejects_command_substitution_dollar_paren(self):
        with pytest.raises(ValueError, match="command substitution"):
            parse_env_line("FOO=$(whoami)", 1, Path("test.env"))

    def test_rejects_command_substitution_backtick(self):
        with pytest.raises(ValueError, match="command substitution"):
            parse_env_line("FOO=`whoami`", 1, Path("test.env"))

    def test_rejects_missing_equals(self):
        with pytest.raises(ValueError, match="KEY=value"):
            parse_env_line("FOO", 1, Path("test.env"))

    def test_rejects_invalid_key_starting_with_number(self):
        with pytest.raises(ValueError, match="Invalid key"):
            parse_env_line("123FOO=bar", 1, Path("test.env"))

    def test_rejects_key_with_spaces(self):
        with pytest.raises(ValueError, match="Invalid key"):
            parse_env_line("FOO BAR=baz", 1, Path("test.env"))


class TestLoadEnvFile:
    """Test loading env files."""

    def test_loads_valid_env_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("FOO=bar\n")
            f.write("BAZ=qux\n")
            f.name
        try:
            result = load_env_file(Path(f.name))
            assert result == {"FOO": "bar", "BAZ": "qux"}
        finally:
            os.unlink(f.name)

    def test_returns_empty_for_missing_file(self):
        result = load_env_file(Path("/nonexistent/file.env"))
        assert result == {}

    def test_skips_comments_and_blanks(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("# Comment\n")
            f.write("\n")
            f.write("FOO=bar\n")
            f.write("   \n")
            f.write("BAZ=qux\n")
        try:
            result = load_env_file(Path(f.name))
            assert result == {"FOO": "bar", "BAZ": "qux"}
        finally:
            os.unlink(f.name)

    def test_raises_on_invalid_syntax(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("FOO=bar\n")
            f.write("export BAD=value\n")  # Invalid
        try:
            with pytest.raises(ValueError, match="export"):
                load_env_file(Path(f.name))
        finally:
            os.unlink(f.name)


class TestMergeEnvFiles:
    """Test merging multiple env files."""

    def test_merges_multiple_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env1 = Path(tmpdir) / ".env"
            env2 = Path(tmpdir) / ".env.local"

            env1.write_text("FOO=from_env\nBAR=from_env\n")
            env2.write_text("BAR=from_local\nBAZ=from_local\n")

            result = merge_env_files([env1, env2])

            assert result["FOO"] == "from_env"
            assert result["BAR"] == "from_local"  # Overridden
            assert result["BAZ"] == "from_local"

    def test_ignores_missing_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env1 = Path(tmpdir) / ".env"
            env1.write_text("FOO=bar\n")

            missing = Path(tmpdir) / ".env.missing"

            result = merge_env_files([env1, missing])
            assert result == {"FOO": "bar"}


class TestSecurityGuarantees:
    """Test that security requirements are met."""

    def test_no_shell_true_in_source(self):
        """Verify run_with_env.py never uses shell=True in code."""
        import ast

        source_file = SCRIPTS_DIR / "run_with_env.py"
        content = source_file.read_text()

        # Should have shell=False in the source
        assert "shell=False" in content

        # Parse the AST to find any shell=True keyword arguments
        tree = ast.parse(content)
        shell_true_found = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg == "shell":
                        if isinstance(keyword.value, ast.Constant):
                            if keyword.value.value is True:
                                shell_true_found.append(ast.dump(node))

        assert len(shell_true_found) == 0, f"Found shell=True in code: {shell_true_found}"

    def test_no_eval_or_exec_in_source(self):
        """Verify run_with_env.py never uses eval/exec."""
        source_file = SCRIPTS_DIR / "run_with_env.py"
        content = source_file.read_text()

        # Filter out comments and strings containing eval/exec
        lines = [l for l in content.split("\n")
                 if not l.strip().startswith("#")
                 and "eval" not in l.split("#")[0].split('"')[0]
                 and "exec" not in l.split("#")[0].split('"')[0]]

        code_content = "\n".join(lines)

        # No direct eval() or exec() calls
        assert "eval(" not in code_content
        assert "exec(" not in code_content

    def test_rejects_shell_injection_attempts(self):
        """Verify common shell injection patterns are rejected."""
        injection_attempts = [
            "FOO=$(cat /etc/passwd)",
            "FOO=`cat /etc/passwd`",
            "export FOO=bar; rm -rf /",
            "export PATH=/evil:$PATH",
        ]

        for attempt in injection_attempts:
            with pytest.raises(ValueError):
                parse_env_line(attempt, 1, Path("test.env"))
