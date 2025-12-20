"""Centralized redaction utilities for sensitive data.

This module provides comprehensive redaction for:
- Command line arguments (--password, --token, etc.)
- YAML/JSON secrets
- Free-form text (tokens, passwords, API keys, JWT, auth headers)
- Database URLs with credentials
- Subprocess error output

SECURITY: All redaction is applied before logging or external output.
"""

import re
import yaml
from subprocess import CalledProcessError
from typing import List, Dict, Any, Optional, Union


# =============================================================================
# Text Redaction Patterns (secrets in free-form text)
# =============================================================================

# Patterns for sensitive values to redact in text
# Each tuple: (pattern, replacement)
_SECRET_TEXT_PATTERNS: List[tuple] = [
    # Key=value patterns (env vars, config)
    (
        r"(PASS|PASSWORD|SECRET|TOKEN|KEY|CREDENTIAL|AUTH|ENC_KEY|COOKIE|API_KEY)"
        r"(\s*[:=]\s*)([^\s\n\"']+)",
        r"\1\2[REDACTED]",
    ),
    # JSON "password": "value" patterns
    (
        r'("(?:password|secret|token|auth_token|authToken|access_token|api_key|'
        r'refresh_token|client_secret|enc_key|private_key)")'
        r'(\s*:\s*)"[^"]*"',
        r'\1\2"[REDACTED]"',
    ),
    # Database URLs with passwords (postgresql, mysql, redis)
    (r"(postgresql://[^:]+:)([^@]+)(@)", r"\1[REDACTED]\3"),
    (r"(postgres://[^:]+:)([^@]+)(@)", r"\1[REDACTED]\3"),
    (r"(mysql://[^:]+:)([^@]+)(@)", r"\1[REDACTED]\3"),
    (r"(redis://[^:]+:)([^@]+)(@)", r"\1[REDACTED]\3"),
    # Bearer tokens
    (r"(Bearer\s+)([A-Za-z0-9\-._~+/]+=*)", r"\1[REDACTED]"),
    # Guacamole tokens in URLs
    (r"(token=)([A-Za-z0-9]+)", r"\1[REDACTED]"),
    # Authorization headers
    (r"(Authorization:\s*)(Bearer\s+)?([^\s\n]+)", r"\1[REDACTED]"),
    # Cookie values
    (r"(Cookie:\s*)([^\n]+)", r"\1[REDACTED]"),
    # Set-Cookie headers
    (r"(Set-Cookie:\s*)([^\n]+)", r"\1[REDACTED]"),
    # JWT patterns (eyJ... base64)
    (r"(eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)", r"[JWT_REDACTED]"),
    # Fernet tokens (gAAAAA...)
    (r"(gAAAAA[A-Za-z0-9_-]{40,})", r"[FERNET_REDACTED]"),
]


def redact_text(text: str) -> str:
    """Redact sensitive values from free-form text.

    Redacts:
    - password/secret/token/key patterns in KEY=VALUE format
    - JSON password fields ("password": "...")
    - Bearer tokens
    - Database URLs with passwords
    - Authorization/Cookie headers
    - JWT tokens
    - Fernet encrypted values

    Args:
        text: Text that may contain secrets

    Returns:
        Text with secrets redacted

    Example:
        >>> redact_text('PASSWORD=secret123')
        'PASSWORD=[REDACTED]'
        >>> redact_text('Bearer eyJhbG...')
        'Bearer [REDACTED]'
    """
    if not text:
        return text

    result = text
    for pattern, replacement in _SECRET_TEXT_PATTERNS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result


def redact_dict(obj: Any, max_depth: int = 10) -> Any:
    """Recursively redact sensitive values from dict/list structures.

    Walks through nested dicts and lists, applying redact_text to all
    string values.

    Args:
        obj: Dict, list, or primitive value to redact
        max_depth: Maximum recursion depth (prevents infinite loops)

    Returns:
        Redacted copy of the structure

    Example:
        >>> redact_dict({"password": "secret", "user": "admin"})
        {"password": "[REDACTED]", "user": "admin"}
    """
    if max_depth <= 0:
        return obj

    if isinstance(obj, dict):
        return {
            k: redact_dict(v, max_depth - 1) for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [redact_dict(item, max_depth - 1) for item in obj]
    elif isinstance(obj, str):
        return redact_text(obj)
    else:
        return obj


def redact_long_random(text: str, min_length: int = 32) -> str:
    """Redact long random-looking strings (potential tokens/keys).

    Useful for catching secrets that don't match specific patterns
    but look like random tokens (high entropy strings).

    Args:
        text: Text to process
        min_length: Minimum length to consider for redaction

    Returns:
        Text with long random strings partially redacted
    """
    if not text:
        return text

    # Pattern for long alphanumeric strings that look like tokens
    pattern = rf"[A-Za-z0-9\-._~+/]{{{min_length},}}"

    def replacer(match):
        value = match.group(0)
        # Keep first 8 chars for debugging
        return value[:8] + "...[REDACTED]"

    return re.sub(pattern, replacer, text)


# =============================================================================
# Command-line Argument Redaction
# =============================================================================


def redact_argv(argv: List[str]) -> List[str]:
    """
    Redact sensitive values from command line arguments.

    Masks values for: --from-literal, --token, --password, --client-key,
    --client-certificate, --kubeconfig, etc.
    Supports both "--flag=value" and "--flag", "value" patterns.
    For --from-literal, masks the portion after '=' (KEY=****) while preserving KEY name.
    """
    redacted = []
    i = 0
    while i < len(argv):
        arg = argv[i]

        # Check for flag=value pattern
        if '=' in arg:
            for sensitive_flag in ['--from-literal', '--token', '--password',
                                   '--client-key', '--client-certificate', '--kubeconfig']:
                if arg.startswith(f"{sensitive_flag}="):
                    # Extract the part after the flag= and before the first equals sign in that part
                    flag_part, remaining = arg.split('=', 1)
                    if sensitive_flag == '--from-literal':
                        # For --from-literal, preserve the KEY= part and only redact the value
                        # e.g. --from-literal=VNC_PASSWORD=secret123 -> --from-literal=VNC_PASSWORD=***REDACTED***
                        if '=' in remaining:
                            key_part, value_part = remaining.split('=', 1)
                            redacted.append(f"{flag_part}={key_part}=***REDACTED***")
                        else:
                            # If there's no second =, redact the entire value
                            redacted.append(f"{flag_part}=***REDACTED***")
                    else:
                        # For other flags, redact the entire value after the =
                        redacted.append(f"{flag_part}=***REDACTED***")
                    break
            else:
                # Not a sensitive flag, add as-is
                redacted.append(arg)
        # Check for flag followed by value pattern
        elif arg in ['--from-literal', '--token', '--password',
                     '--client-key', '--client-certificate', '--kubeconfig']:
            # Add the flag
            redacted.append(arg)
            # Next element is the sensitive value
            if i + 1 < len(argv):
                redacted.append("***REDACTED***")
                i += 2  # Skip both the flag and its value
                continue
        else:
            # Not a sensitive flag, add as-is
            redacted.append(arg)

        i += 1

    return redacted


def redact_yaml(text: str) -> str:
    """
    Redact sensitive data from YAML content.

    If YAML contains "kind: Secret" (or multiple docs), mask/remove data:/stringData: blocks.
    Keep structure but replace values with "***REDACTED***".
    """
    try:
        # Handle multiple YAML documents separated by ---
        documents = []
        doc_parts = text.split('---')

        for doc in doc_parts:
            doc = doc.strip()
            if not doc:
                continue

            # Load the YAML to check if it's a Secret
            try:
                parsed = yaml.safe_load(doc)
                if parsed and isinstance(parsed, dict) and parsed.get('kind') == 'Secret':
                    # Redact sensitive fields in Secrets
                    if 'data' in parsed:
                        parsed['data'] = {k: "***REDACTED***" for k in parsed['data'].keys()}
                    if 'stringData' in parsed:
                        parsed['stringData'] = {k: "***REDACTED***" for k in parsed['stringData'].keys()}

                    # Convert back to YAML, ensuring proper formatting
                    redacted_doc = yaml.dump(parsed, default_flow_style=False, indent=2)
                    documents.append(redacted_doc)
                else:
                    # Not a Secret, keep as-is
                    documents.append(doc)
            except yaml.YAMLError:
                # If we can't parse as YAML, return original text
                documents.append(doc)

        # Join with proper separator
        result = '---\n'.join(documents)
        return result
    except Exception:
        # If anything goes wrong, return original text
        return text


def truncate_text(text: str, limit: int = 16384) -> str:
    """Truncate text to a maximum length, keeping both head and tail.

    Args:
        text: Text to truncate
        limit: Maximum length (default 16KB)

    Returns:
        Original text if within limit, otherwise head + truncation notice + tail
    """
    if len(text) <= limit:
        return text

    # Keep head and tail (split evenly, minus space for notice)
    notice = "\n...<truncated>...\n"
    half = (limit - len(notice)) // 2
    head = text[:half]
    tail = text[-half:]
    return head + notice + tail


def redact_explicit_secrets(text: str, secrets: Optional[List[str]]) -> str:
    """Redact explicit secret values from text.

    Performs exact string replacement for each provided secret.

    Args:
        text: Text that may contain secrets
        secrets: List of exact secret values to redact (case-sensitive)

    Returns:
        Text with explicit secrets replaced with ***REDACTED***
    """
    if not text or not secrets:
        return text or ""

    result = text
    for secret in secrets:
        if secret:  # Skip empty strings
            result = result.replace(secret, "***REDACTED***")
    return result


def sanitize_output(
    text: Optional[str],
    secrets: Optional[List[str]] = None,
    limit: int = 16384
) -> str:
    """Sanitize output by redacting secrets and truncating.

    Combines explicit secret redaction, pattern-based redaction, and truncation.

    Args:
        text: Output text (may be None)
        secrets: List of explicit secrets to redact
        limit: Maximum output length

    Returns:
        Sanitized, truncated text safe for logging
    """
    if not text:
        return ""

    # First, redact explicit secrets (exact match)
    result = redact_explicit_secrets(text, secrets)

    # Then apply pattern-based redaction
    result = redact_text(result)

    # Finally truncate
    return truncate_text(result, limit)


def sanitize_subprocess_error(
    e: CalledProcessError,
    *,
    secret_patterns: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Sanitize a CalledProcessError for safe logging.

    Return safe dict with redacted cmd + redacted/truncated stdout/stderr.
    Never return raw cmd/outputs.
    """
    secret_patterns = secret_patterns or []

    # Redact the command
    redacted_cmd = redact_argv(e.cmd if isinstance(e.cmd, list) else [str(e.cmd)])

    # Sanitize stdout and stderr
    stdout = e.stdout or ""
    stderr = e.stderr or ""

    # Apply secret pattern redaction for specific known secrets
    for pattern in secret_patterns:
        if pattern:
            stdout = stdout.replace(pattern, "***REDACTED***")
            stderr = stderr.replace(pattern, "***REDACTED***")

    # Truncate outputs
    stdout = truncate_text(stdout)
    stderr = truncate_text(stderr)

    return {
        "returncode": e.returncode,
        "cmd": redacted_cmd,
        "stdout": stdout,
        "stderr": stderr
    }