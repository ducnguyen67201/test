#!/usr/bin/env python3
"""
redact_stream.py - Redact sensitive values from stdin

Usage:
    some_command 2>&1 | python3 redact_stream.py

Redacts common secret patterns:
- ENV-style: SOME_PASSWORD=value, TOKEN=value, SECRET=value, KEY=value
- YAML/INI-style: password: value, password = value
- JSON-style: "password": "value"

SECURITY:
- NEVER shows partial secrets (e.g., "gu...in"). Always "****".
- Never throws on weird bytes; treats input as text with errors="replace".
- Always exits 0 to avoid breaking pipelines.
"""
import re
import sys


# Patterns to match sensitive environment variables or config values
# Pattern 1: ENV-style assignments like PASSWORD=value or GUAC_ADMIN_TOKEN=xyz
# Captures the key name, and replaces the value portion
ENV_PATTERN = re.compile(
    r'([A-Za-z_][A-Za-z0-9_]*(?:PASS|PASSWORD|SECRET|TOKEN|KEY)[A-Za-z0-9_]*)='
    r'("[^"]*"|\'[^\']*\'|[^\s]*)',
    re.IGNORECASE
)

# Pattern 2: YAML/INI-style like "password: value" or "password = value"
# Handles optional quotes around value
CONFIG_PATTERN = re.compile(
    r'(password|secret|token|api_key|apikey|auth_token|access_token|private_key|credentials?)'
    r'(\s*[:=]\s*)'
    r'("[^"]*"|\'[^\']*\'|[^\s]*)',
    re.IGNORECASE
)

# Pattern 3: JSON-style like "password": "value" or 'password': 'value'
JSON_PATTERN = re.compile(
    r'(["\'])(password|secret|token|api_key|apikey|auth_token|access_token|private_key|credentials?)(\1)'
    r'(\s*:\s*)'
    r'(["\'])([^"\']*)\5',
    re.IGNORECASE
)


def redact_text(text: str) -> str:
    """Redact sensitive values from text.

    SECURITY: Never shows partial secrets. Always replaces with "****".

    Args:
        text: Input text that may contain secrets

    Returns:
        Text with all secret values replaced with "****"
    """
    try:
        # Redact ENV-style patterns
        text = ENV_PATTERN.sub(r'\1=****', text)
        # Redact config-style patterns
        text = CONFIG_PATTERN.sub(r'\1\2****', text)
        # Redact JSON-style patterns
        text = JSON_PATTERN.sub(r'\1\2\3\4\5****\5', text)
        return text
    except Exception:
        # Never crash; return text as-is if regex somehow fails
        return text


def redact_line(line: str) -> str:
    """Redact sensitive values from a single line.

    Alias for redact_text for backwards compatibility.
    """
    return redact_text(line)


def main() -> int:
    """Read stdin, redact, write to stdout. Always exit 0."""
    try:
        # Use errors='replace' to handle any encoding issues gracefully
        # Configure stdin for text mode with error handling
        if hasattr(sys.stdin, 'reconfigure'):
            sys.stdin.reconfigure(errors='replace')

        for line in sys.stdin:
            try:
                redacted = redact_text(line)
                sys.stdout.write(redacted)
            except Exception:
                # On any error, try to pass through the line unchanged
                try:
                    sys.stdout.write(line)
                except Exception:
                    pass
        sys.stdout.flush()
    except Exception:
        # Never crash the pipeline
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
