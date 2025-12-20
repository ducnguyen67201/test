"""HTTP utilities for E2E verification scripts.

Provides:
- URL normalization and joining
- Secret redaction
- HTTP request helpers with redirect handling

SECURITY: Never logs passwords, tokens, or secrets.
"""

import json
import re
import subprocess
from typing import Any


def normalize_base(url: str) -> str:
    """Normalize base URL by stripping trailing slash and whitespace.

    Args:
        url: Base URL to normalize

    Returns:
        Normalized URL without trailing slash

    Examples:
        >>> normalize_base("http://localhost:8000/")
        'http://localhost:8000'
        >>> normalize_base("  http://localhost:8000  ")
        'http://localhost:8000'
    """
    return url.strip().rstrip("/")


def join_url(base: str, path: str) -> str:
    """Join base URL and path with exactly one slash.

    Args:
        base: Base URL (may or may not have trailing slash)
        path: Path to append (may or may not have leading slash)

    Returns:
        Joined URL with exactly one slash between base and path

    Examples:
        >>> join_url("http://localhost:8000", "/auth/register")
        'http://localhost:8000/auth/register'
        >>> join_url("http://localhost:8000/", "auth/register")
        'http://localhost:8000/auth/register'
        >>> join_url("http://localhost:8000/", "/auth/register")
        'http://localhost:8000/auth/register'
    """
    base_normalized = normalize_base(base)
    path_normalized = path.lstrip("/")
    return f"{base_normalized}/{path_normalized}"


# Patterns for sensitive values to redact
_SECRET_PATTERNS = [
    # Key=value patterns (env vars, config)
    (
        r"(PASS|PASSWORD|SECRET|TOKEN|KEY|CREDENTIAL|AUTH|ENC_KEY|COOKIE)"
        r"(\s*[:=]\s*)([^\s\n\"']+)",
        r"\1\2[REDACTED]",
    ),
    # JSON "password": "value" patterns
    (
        r'("(?:password|secret|token|auth_token|authToken|access_token|api_key)")'
        r'(\s*:\s*)"[^"]*"',
        r'\1\2"[REDACTED]"',
    ),
    # Database URLs with passwords
    (r"(postgresql://[^:]+:)([^@]+)(@)", r"\1[REDACTED]\3"),
    (r"(postgres://[^:]+:)([^@]+)(@)", r"\1[REDACTED]\3"),
    # Bearer tokens
    (r"(Bearer\s+)([A-Za-z0-9\-._~+/]+=*)", r"\1[REDACTED]"),
    # Guacamole tokens in URLs
    (r"(token=)([A-Za-z0-9]+)", r"\1[REDACTED]"),
    # Authorization headers
    (r"(Authorization:\s*)(Bearer\s+)?([^\s\n]+)", r"\1[REDACTED]"),
    # Cookie values
    (r"(Cookie:\s*)([^\n]+)", r"\1[REDACTED]"),
]


def redact_secrets(text: str) -> str:
    """Redact sensitive values from text.

    Redacts:
    - password/secret/token/key patterns
    - Bearer tokens
    - Database URLs with passwords
    - Authorization/Cookie headers

    Args:
        text: Text that may contain secrets

    Returns:
        Text with secrets redacted

    Examples:
        >>> redact_secrets('PASSWORD=secret123')
        'PASSWORD=[REDACTED]'
        >>> redact_secrets('Bearer eyJhbGciOi...')
        'Bearer [REDACTED]'
    """
    if not text:
        return text

    result = text
    for pattern, replacement in _SECRET_PATTERNS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result


def redact_long_random(text: str, min_length: int = 32) -> str:
    """Redact long random-looking strings (potential tokens/keys).

    Args:
        text: Text to process
        min_length: Minimum length to consider for redaction

    Returns:
        Text with long random strings redacted
    """
    if not text:
        return text

    # Pattern for long alphanumeric strings that look like tokens
    pattern = rf"[A-Za-z0-9\-._~+/]{{{min_length},}}"

    def replacer(match):
        value = match.group(0)
        # Keep first 8 chars for debugging
        return value[:8] + "[REDACTED]"

    return re.sub(pattern, replacer, text)


def run_cmd(
    cmd: list[str],
    timeout: float = 30.0,
    cwd: str | None = None,
) -> dict[str, Any]:
    """Run command with shell=False for security.

    Args:
        cmd: Command as list of strings
        timeout: Timeout in seconds
        cwd: Working directory

    Returns:
        Dict with ok, returncode, stdout, stderr (all redacted)
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            shell=False,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": -1, "error": f"Timeout after {timeout}s"}
    except FileNotFoundError as e:
        return {"ok": False, "returncode": -2, "error": f"Command not found: {e}"}
    except Exception as e:
        return {"ok": False, "returncode": -3, "error": str(e)}


def http_request(
    method: str,
    url: str,
    data: dict | None = None,
    headers: dict | None = None,
    timeout: float = 10.0,
    follow_redirects: bool = True,
) -> dict[str, Any]:
    """Make HTTP request via curl.

    Args:
        method: HTTP method (GET, POST, OPTIONS, etc.)
        url: Full URL
        data: JSON body data (for POST/PUT)
        headers: Additional headers
        timeout: Request timeout in seconds
        follow_redirects: Whether to follow redirects

    Returns:
        Dict with:
        - ok: True if request succeeded
        - status_code: HTTP status code
        - body: Response body
        - headers_out: Response headers (redacted)
        - final_url: Final URL after redirects
        - num_redirects: Number of redirects followed
        - error: Error message if failed
    """
    cmd = [
        "curl",
        "-s",  # Silent
        "-X", method.upper(),
        "-o", "-",  # Output to stdout
        "-w", "\n---CURL_INFO---\nhttp_code:%{http_code}\nnum_redirects:%{num_redirects}\nurl_effective:%{url_effective}\n",
        "-D", "/dev/stderr",  # Headers to stderr
    ]

    if follow_redirects:
        cmd.append("-L")

    if data is not None:
        cmd.extend(["-H", "Content-Type: application/json"])
        cmd.extend(["-d", json.dumps(data)])

    if headers:
        for key, value in headers.items():
            cmd.extend(["-H", f"{key}: {value}"])

    cmd.append(url)

    result = run_cmd(cmd, timeout=timeout)

    if not result["ok"] and "error" in result:
        return {
            "ok": False,
            "error": result.get("error", "Request failed"),
            "status_code": 0,
        }

    # Parse output
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")

    # Split body and curl info
    body = ""
    status_code = 0
    num_redirects = 0
    final_url = url

    if "---CURL_INFO---" in stdout:
        parts = stdout.split("---CURL_INFO---")
        body = parts[0].rstrip("\n")

        # Parse curl info
        info_lines = parts[1].strip().split("\n") if len(parts) > 1 else []
        for line in info_lines:
            if line.startswith("http_code:"):
                try:
                    status_code = int(line.split(":", 1)[1])
                except ValueError:
                    pass
            elif line.startswith("num_redirects:"):
                try:
                    num_redirects = int(line.split(":", 1)[1])
                except ValueError:
                    pass
            elif line.startswith("url_effective:"):
                final_url = line.split(":", 1)[1].strip()
    else:
        # Fallback parsing
        lines = stdout.strip().split("\n")
        if lines and lines[-1].isdigit():
            status_code = int(lines[-1])
            body = "\n".join(lines[:-1])

    return {
        "ok": True,
        "status_code": status_code,
        "body": body,
        "headers_out": redact_secrets(stderr[:1000]) if stderr else "",
        "final_url": final_url,
        "num_redirects": num_redirects,
    }


def http_get(url: str, headers: dict | None = None, timeout: float = 10.0) -> dict[str, Any]:
    """HTTP GET request."""
    return http_request("GET", url, headers=headers, timeout=timeout)


def http_post_json(
    url: str,
    data: dict,
    headers: dict | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """HTTP POST request with JSON body."""
    return http_request("POST", url, data=data, headers=headers, timeout=timeout)


def http_options(
    url: str,
    origin: str,
    request_method: str = "POST",
    request_headers: str = "content-type",
    timeout: float = 5.0,
) -> dict[str, Any]:
    """HTTP OPTIONS request for CORS preflight check.

    Args:
        url: URL to check
        origin: Origin header value
        request_method: Access-Control-Request-Method value
        request_headers: Access-Control-Request-Headers value
        timeout: Request timeout

    Returns:
        Dict with status, allow_origin, allow_methods, allow_headers
    """
    headers = {
        "Origin": origin,
        "Access-Control-Request-Method": request_method,
        "Access-Control-Request-Headers": request_headers,
    }

    result = http_request("OPTIONS", url, headers=headers, timeout=timeout)

    # Parse CORS headers from response headers
    headers_out = result.get("headers_out", "")

    allow_origin = ""
    allow_methods = ""
    allow_headers = ""

    for line in headers_out.split("\n"):
        line_lower = line.lower()
        if line_lower.startswith("access-control-allow-origin:"):
            allow_origin = line.split(":", 1)[1].strip()
        elif line_lower.startswith("access-control-allow-methods:"):
            allow_methods = line.split(":", 1)[1].strip()
        elif line_lower.startswith("access-control-allow-headers:"):
            allow_headers = line.split(":", 1)[1].strip()

    result["allow_origin"] = allow_origin
    result["allow_methods"] = allow_methods
    result["allow_headers"] = allow_headers

    return result


def parse_json_safe(text: str) -> dict | list | None:
    """Safely parse JSON, returning None on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
