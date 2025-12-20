"""Unit tests for redaction utilities."""

import pytest
from app.utils.redact import redact_argv, redact_yaml, truncate_text, sanitize_subprocess_error
from subprocess import CalledProcessError


def test_redact_argv_from_literal_single_arg():
    """Test redacting --from-literal=sensitive_value format."""
    argv = [
        "kubectl", 
        "create", 
        "secret", 
        "generic", 
        "test-secret", 
        "--from-literal=VNC_PASSWORD=secret123",
        "--other-flag=value"
    ]
    
    redacted = redact_argv(argv)
    
    expected = [
        "kubectl", 
        "create", 
        "secret", 
        "generic", 
        "test-secret", 
        "--from-literal=VNC_PASSWORD=***REDACTED***",
        "--other-flag=value"
    ]
    
    assert redacted == expected


def test_redact_argv_from_literal_two_args():
    """Test redacting --from-literal VNC_PASSWORD=secret123 format."""
    argv = [
        "kubectl", 
        "create", 
        "secret", 
        "generic", 
        "test-secret", 
        "--from-literal",
        "VNC_PASSWORD=secret123",
        "--other-flag=value"
    ]
    
    redacted = redact_argv(argv)
    
    expected = [
        "kubectl", 
        "create", 
        "secret", 
        "generic", 
        "test-secret", 
        "--from-literal",
        "***REDACTED***",
        "--other-flag=value"
    ]
    
    assert redacted == expected


def test_redact_argv_various_sensitive_flags():
    """Test redacting various sensitive flags."""
    argv = [
        "kubectl",
        "--token=secret_token",
        "--password=secret_password", 
        "--client-key=secret_key",
        "--client-certificate=secret_cert",
        "--kubeconfig=secret_config",
        "get",
        "pods"
    ]
    
    redacted = redact_argv(argv)
    
    expected = [
        "kubectl",
        "--token=***REDACTED***",
        "--password=***REDACTED***", 
        "--client-key=***REDACTED***",
        "--client-certificate=***REDACTED***",
        "--kubeconfig=***REDACTED***",
        "get",
        "pods"
    ]
    
    assert redacted == expected


def test_redact_argv_sensitive_flags_two_arg_format():
    """Test redacting sensitive flags in two-arg format."""
    argv = [
        "kubectl",
        "--token", "secret_token",
        "--password", "secret_password", 
        "--client-key", "secret_key",
        "get",
        "pods"
    ]
    
    redacted = redact_argv(argv)
    
    expected = [
        "kubectl",
        "--token", "***REDACTED***",
        "--password", "***REDACTED***", 
        "--client-key", "***REDACTED***",
        "get",
        "pods"
    ]
    
    assert redacted == expected


def test_redact_yaml_secret_data():
    """Test redacting data in Secret YAML."""
    yaml_content = """apiVersion: v1
kind: Secret
metadata:
  name: test-secret
data:
  VNC_PASSWORD: c2VjcmV0MTIz
  other_field: dGVzdA==
stringData:
  ANOTHER_SECRET: secret_value
"""
    
    redacted = redact_yaml(yaml_content)
    
    # Check that secret data is redacted
    assert "***REDACTED***" in redacted
    assert "c2VjcmV0MTIz" not in redacted  # Original base64 not present
    assert "secret_value" not in redacted  # Original string not present
    assert "VNC_PASSWORD" in redacted  # Key names preserved
    assert "ANOTHER_SECRET" in redacted  # Key names preserved


def test_redact_yaml_non_secret_unchanged():
    """Test that non-Secret YAML content is preserved (no redaction)."""
    yaml_content = """apiVersion: v1
kind: ConfigMap
metadata:
  name: test-config
data:
  some_value: secret123
"""

    redacted = redact_yaml(yaml_content)

    # The content should not be redacted but format might change slightly due to YAML processing
    # Check that no redaction was performed
    assert "***REDACTED***" not in redacted  # No redaction should happen
    # Check that key elements are still present
    assert "apiVersion: v1" in redacted
    assert "kind: ConfigMap" in redacted
    assert "test-config" in redacted
    assert "some_value: secret123" in redacted  # The value should be preserved in non-Secret


def test_redact_yaml_multiple_documents():
    """Test redacting multiple YAML documents."""
    yaml_content = """apiVersion: v1
kind: Secret
metadata:
  name: secret1
data:
  password: c2VjcmV0

---
apiVersion: v1
kind: ConfigMap
metadata:
  name: config1
data:
  key: value

---
apiVersion: v1
kind: Secret
metadata:
  name: secret2
stringData:
  password: secret_value
"""
    
    redacted = redact_yaml(yaml_content)
    
    # Check that both secrets are redacted but ConfigMap is unchanged
    assert "***REDACTED***" in redacted
    assert "c2VjcmV0" not in redacted  # First secret redacted
    assert "secret_value" not in redacted  # Second secret redacted
    assert "key: value" in redacted  # ConfigMap unchanged


def test_truncate_text_within_limit():
    """Test that text within limit is unchanged."""
    text = "short text"
    result = truncate_text(text, 100)
    assert result == "short text"


def test_truncate_text_over_limit():
    """Test that text over limit is truncated."""
    text = "a" * 100  # 100 characters
    result = truncate_text(text, 50)
    # The result should be the first 50 chars + length of "... [TRUNCATED]"
    expected_max_length = 50 + len("... [TRUNCATED]")
    assert len(result) <= expected_max_length
    assert result.endswith("[TRUNCATED]")


def test_sanitize_subprocess_error():
    """Test sanitizing CalledProcessError."""
    error = CalledProcessError(
        returncode=1,
        cmd=["kubectl", "create", "secret", "generic", "--from-literal=VNC_PASSWORD=secret123"],
        output="secret in output",
        stderr="secret in stderr"
    )
    
    sanitized = sanitize_subprocess_error(error, secret_patterns=["secret123", "secret"])
    
    # Check command is redacted
    assert "***REDACTED***" in str(sanitized['cmd'])
    assert "secret123" not in str(sanitized['cmd'])
    
    # Check outputs are redacted
    assert "***REDACTED***" in sanitized['stdout']
    assert "secret" not in sanitized['stdout']
    assert "***REDACTED***" in sanitized['stderr']
    assert "secret" not in sanitized['stderr']


def test_redact_argv_preserves_non_sensitive():
    """Test that non-sensitive args are preserved."""
    argv = [
        "kubectl",
        "--namespace=default", 
        "get",
        "pods",
        "--output=json"
    ]
    
    redacted = redact_argv(argv)
    assert redacted == argv  # Should be unchanged


def test_redact_yaml_handles_invalid_yaml():
    """Test that redact_yaml handles invalid YAML gracefully."""
    invalid_yaml = "invalid: [yaml: without closing bracket"
    
    result = redact_yaml(invalid_yaml)  # Should not raise exception
    assert result == invalid_yaml  # Should return original text