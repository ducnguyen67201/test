"""
Test to specifically verify that secrets never leak in exception messages
when subprocess calls fail with sensitive data.
"""

import pytest
from subprocess import CalledProcessError
from app.utils.redact import sanitize_subprocess_error, redact_argv


def test_secret_not_in_calledprocesserror():
    """Test that secrets don't leak when CalledProcessError occurs."""
    # Simulate a kubectl command that fails and contains a secret in the command or output
    cmd = [
        "kubectl", "create", "secret", "generic", "test-secret",
        "--from-literal=VNC_PASSWORD=super_secret_password_12345",
        "--dry-run=client", "-o", "yaml"
    ]

    stdout = "Some output that might contain sensitive data like super_secret_password_12345 in the response"
    stderr = "Error occurred: unauthorized access with password super_secret_password_12345"

    error = CalledProcessError(
        returncode=1,
        cmd=cmd,
        output=stdout,
        stderr=stderr
    )

    # Sanitize the error using our utility
    sanitized = sanitize_subprocess_error(error, secret_patterns=["super_secret_password_12345"])

    # Verify the original sensitive data is NOT in the sanitized error
    cmd_str = str(sanitized['cmd'])
    stdout_str = sanitized['stdout']
    stderr_str = sanitized['stderr']

    assert "super_secret_password_12345" not in cmd_str
    assert "super_secret_password_12345" not in stdout_str
    assert "super_secret_password_12345" not in stderr_str

    # Verify redactions occurred
    assert "***REDACTED***" in cmd_str
    assert "***REDACTED***" in stdout_str
    assert "***REDACTED***" in stderr_str

    print("SUCCESS: Sensitive data properly redacted from CalledProcessError")


def test_redact_argv_various_sensitive_patterns():
    """Test redaction of various sensitive patterns."""
    test_cases = [
        # Single arg pattern
        (["kubectl", "--from-literal=VNC_PASSWORD=secret123"], 
         ["kubectl", "--from-literal=VNC_PASSWORD=***REDACTED***"]),
        # Token patterns
        (["kubectl", "--token=abc123token"], 
         ["kubectl", "--token=***REDACTED***"]),
        (["kubectl", "--password=mypassword"], 
         ["kubectl", "--password=***REDACTED***"]),
        # Two-arg pattern
        (["kubectl", "--from-literal", "VNC_PASSWORD=secret123"], 
         ["kubectl", "--from-literal", "***REDACTED***"]),
    ]
    
    for input_cmd, expected in test_cases:
        result = redact_argv(input_cmd)
        assert result == expected, f"Failed for {input_cmd}: got {result}, expected {expected}"
    
    print("SUCCESS: All argv redaction patterns work correctly")


if __name__ == "__main__":
    test_secret_not_in_calledprocesserror()
    test_redact_argv_various_sensitive_patterns()
    print("All leak prevention tests passed!")