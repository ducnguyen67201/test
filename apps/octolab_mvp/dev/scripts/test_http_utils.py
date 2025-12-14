#!/usr/bin/env python3
"""Tests for _http_utils module.

Run with:
    python3 -m pytest dev/scripts/test_http_utils.py -v
"""

import pytest
from _http_utils import normalize_base, join_url, redact_secrets


class TestNormalizeBase:
    """Tests for normalize_base function."""

    def test_strips_trailing_slash(self):
        assert normalize_base("http://localhost:8000/") == "http://localhost:8000"

    def test_strips_multiple_trailing_slashes(self):
        assert normalize_base("http://localhost:8000///") == "http://localhost:8000"

    def test_strips_whitespace(self):
        assert normalize_base("  http://localhost:8000  ") == "http://localhost:8000"

    def test_strips_both(self):
        assert normalize_base("  http://localhost:8000/  ") == "http://localhost:8000"

    def test_handles_no_trailing_slash(self):
        assert normalize_base("http://localhost:8000") == "http://localhost:8000"

    def test_handles_path(self):
        assert normalize_base("http://localhost:8000/api/") == "http://localhost:8000/api"


class TestJoinUrl:
    """Tests for join_url function."""

    def test_basic_join(self):
        assert join_url("http://localhost:8000", "/auth/register") == "http://localhost:8000/auth/register"

    def test_base_with_trailing_slash(self):
        assert join_url("http://localhost:8000/", "/auth/register") == "http://localhost:8000/auth/register"

    def test_path_without_leading_slash(self):
        assert join_url("http://localhost:8000", "auth/register") == "http://localhost:8000/auth/register"

    def test_both_slashes(self):
        assert join_url("http://localhost:8000/", "auth/register") == "http://localhost:8000/auth/register"

    def test_double_slash_handling(self):
        # Both have slashes at the junction
        assert join_url("http://localhost:8000/", "/auth/register") == "http://localhost:8000/auth/register"

    def test_empty_path(self):
        assert join_url("http://localhost:8000", "") == "http://localhost:8000/"

    def test_root_path(self):
        assert join_url("http://localhost:8000", "/") == "http://localhost:8000/"


class TestRedactSecrets:
    """Tests for redact_secrets function."""

    def test_redacts_password_env_var(self):
        assert "[REDACTED]" in redact_secrets("PASSWORD=secret123")
        assert "secret123" not in redact_secrets("PASSWORD=secret123")

    def test_redacts_bearer_token(self):
        assert "[REDACTED]" in redact_secrets("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9")
        assert "eyJhbGciOi" not in redact_secrets("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9")

    def test_redacts_json_password(self):
        text = '{"password": "mysecret", "email": "test@example.com"}'
        result = redact_secrets(text)
        assert "mysecret" not in result
        assert "test@example.com" in result

    def test_redacts_db_url_password(self):
        url = "postgresql://user:mysecretpass@localhost:5432/db"
        result = redact_secrets(url)
        assert "mysecretpass" not in result
        assert "user" in result
        assert "localhost" in result

    def test_empty_input(self):
        assert redact_secrets("") == ""
        assert redact_secrets(None) is None

    def test_no_secrets(self):
        text = "Hello world, no secrets here"
        assert redact_secrets(text) == text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
