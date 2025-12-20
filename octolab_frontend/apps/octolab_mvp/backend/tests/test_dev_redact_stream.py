"""Tests for dev/scripts/redact_stream.py

These tests verify the redaction script works correctly.
No database access is needed.
"""
import subprocess
import sys
from pathlib import Path

import pytest

# Mark entire module as not requiring database
pytestmark = pytest.mark.no_db

# Path to the redaction script
REPO_ROOT = Path(__file__).parent.parent.parent
REDACT_SCRIPT = REPO_ROOT / "dev" / "scripts" / "redact_stream.py"


def run_redact(input_text: str) -> str:
    """Run redact_stream.py with the given input and return output."""
    result = subprocess.run(
        [sys.executable, str(REDACT_SCRIPT)],
        input=input_text,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout


class TestRedactStream:
    """Test cases for the redact_stream.py script."""

    def test_env_style_password(self):
        """PASSWORD=value should be redacted."""
        assert run_redact("PASSWORD=supersecret\n") == "PASSWORD=****\n"

    def test_env_style_guac_admin_password(self):
        """GUAC_ADMIN_PASSWORD=value should be redacted."""
        assert run_redact("GUAC_ADMIN_PASSWORD=abc\n") == "GUAC_ADMIN_PASSWORD=****\n"

    def test_env_style_token(self):
        """TOKEN-style env vars should be redacted."""
        assert run_redact("API_TOKEN=xyz123\n") == "API_TOKEN=****\n"

    def test_env_style_secret(self):
        """SECRET-style env vars should be redacted."""
        assert run_redact("MY_SECRET=hidden\n") == "MY_SECRET=****\n"

    def test_env_style_key(self):
        """KEY-style env vars should be redacted."""
        assert run_redact("ENCRYPTION_KEY=aes256key\n") == "ENCRYPTION_KEY=****\n"

    def test_yaml_style_password_colon(self):
        """password: value should be redacted."""
        assert run_redact("password: hunter2\n") == "password: ****\n"

    def test_yaml_style_password_equals(self):
        """password = value should be redacted."""
        assert run_redact("password = hunter2\n") == "password = ****\n"

    def test_yaml_style_secret_colon(self):
        """secret: value should be redacted."""
        assert run_redact("secret: my-secret\n") == "secret: ****\n"

    def test_yaml_style_token_colon(self):
        """token: value should be redacted."""
        assert run_redact("token: abcd1234\n") == "token: ****\n"

    def test_non_secret_line_unchanged(self):
        """Lines without secrets should pass through unchanged."""
        line = "Creating network default...\n"
        assert run_redact(line) == line

    def test_multiple_lines(self):
        """Multiple lines should all be processed."""
        input_text = "line1\nPASSWORD=secret\nline3\n"
        expected = "line1\nPASSWORD=****\nline3\n"
        assert run_redact(input_text) == expected

    def test_quoted_value_redacted(self):
        """Quoted values should be redacted."""
        assert run_redact('PASSWORD="my secret"\n') == "PASSWORD=****\n"
        assert run_redact("PASSWORD='mysecret'\n") == "PASSWORD=****\n"

    def test_multiple_secrets_same_line(self):
        """Multiple secrets on same line should all be redacted."""
        input_text = "PASSWORD=abc TOKEN=xyz\n"
        output = run_redact(input_text)
        assert "PASSWORD=****" in output
        assert "TOKEN=****" in output

    def test_case_insensitive_password(self):
        """password matching should be case-insensitive."""
        assert run_redact("db_password=secret\n") == "db_password=****\n"
        assert run_redact("DB_PASSWORD=secret\n") == "DB_PASSWORD=****\n"

    def test_script_exits_zero(self):
        """Script should always exit 0."""
        result = subprocess.run(
            [sys.executable, str(REDACT_SCRIPT)],
            input="test\n",
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0

    def test_empty_input(self):
        """Empty input should produce empty output."""
        assert run_redact("") == ""

    def test_line_without_newline(self):
        """Line without trailing newline should still work."""
        output = run_redact("PASSWORD=secret")
        assert "****" in output
